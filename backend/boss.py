"""Boss agent (Career Scout): owns the chat with the student and delegates to specialist agents.

Specialists: Report Analyst (PDF -> employers), Geo Verifier (does a company hire in the country?),
Program Scout (top MBA programs via QS rankings), MBA Employment Report Finder (finds + downloads report PDFs),
Report Summarizer (groups employers into industries, max 100), Company Researcher (salary, roles,
locations, visa, recruiting; ranks by salary or fit). Students keep a tracker of 5-15 companies;
Job Posting Scout checks their careers pages for intern / MBA / early-career postings in the city.. Conversation state lives per session in memory.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelRequest, ModelResponse, TextPart, UserPromptPart

from backend import db
from backend.geo_verifier import verify
from backend.models import ReportLinks
from backend.llm import responses_model, run_logged
from backend.program_scout import find_programs
from backend.employment_report_finder import check_pdf, download_pdf, file_name, find_report_links
from backend.report_analyst import analyze_report
from backend.report_summarizer import norm, summarize
from backend.company_researcher import MAX_PER_RUN as MAX_RESEARCH, apply_report_salary, fit_scores, rank_by_salary, report_salary, research_many
from backend.salary_extractor import scan_reports
from backend.job_scout import scan_many
from backend.models import CompanyResearch

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "data" / "reports"
MAX_VERIFY = 50
HISTORY_TURNS = 10  # only the last N user turns are sent to the model (full history stays saved)


@dataclass
class Session:
    id: str = ""
    country: str | None = None
    city: str | None = None
    report_source: Literal["upload", "auto"] | None = None
    history: list[ModelMessage] = field(default_factory=list)
    pending_downloads: list[tuple[str, str]] = field(default_factory=list)  # (url, file name) awaiting OK
    research: dict[str, CompanyResearch] = field(default_factory=dict)  # last researched companies
    target_roles: list[str] = field(default_factory=list)  # e.g. ["strategy", "product", "finance"]
    stage: int = 0  # last completed step of the guided path (see STEPS)


SESSIONS: dict[str, Session] = {}

STEPS = ["Where to work", "Employment reports", "Employers by industry", "Research companies", "Tracker", "Job postings"]


def _done(s: Session, step: int) -> None:
    """Mark a guided-path step complete (set by the tools, not by the model)."""
    s.stage = max(s.stage, step)

boss = Agent(deps_type=Session, output_type=str, instructions=(Path(__file__).parent / "prompts" / "boss.md").read_text())


@boss.instructions
def _state(ctx: RunContext[Session]) -> str:
    s = ctx.deps
    tracked = [r[0] for r in db.tracker_rows(db.connect(), s.id)]
    done = ", ".join(f"{i}. {n}" for i, n in enumerate(STEPS[: s.stage], 1)) or "none"
    nxt = f"step {s.stage + 1}: {STEPS[s.stage]}" if s.stage < len(STEPS) else "all done (offer a new posting check)"
    return (f"Guided path: completed steps: {done}. Next: {nxt}.\n"
            f"Saved tracker: {', '.join(tracked) or 'empty'}.\n"
            f"Current state: country={s.country or 'not set'}, city={s.city or 'any'}, "
            f"report_source={s.report_source or 'not chosen'}, target_roles={', '.join(s.target_roles) or 'not set'}.")


@boss.tool
def set_country(ctx: RunContext[Session], country: str, city: str | None = None) -> str:
    """Save the country (and optional city) the student wants to work in, e.g. "Canada", "Toronto"."""
    new_country, new_city = country.strip().title(), (city.strip().title() if city else None)
    if (new_country, new_city) != (ctx.deps.country, ctx.deps.city):
        ctx.deps.stage = 0  # new place: reports and employers need redoing for it
    ctx.deps.country, ctx.deps.city = new_country, new_city
    _done(ctx.deps, 1)
    return f"Location set to {ctx.deps.city + ', ' if ctx.deps.city else ''}{ctx.deps.country}."


@boss.tool
def set_report_source(ctx: RunContext[Session], source: Literal["upload", "auto"]) -> str:
    """Save how reports will be gathered: "upload" (student uploads PDFs) or "auto" (agents find them)."""
    ctx.deps.report_source = source
    return f"Report source set to {source}."


@boss.tool_plain
def list_uploaded_reports() -> str:
    """List employment report PDFs uploaded so far and whether each has been analyzed."""
    pdfs = sorted(REPORTS.glob("*.pdf"))
    if not pdfs:
        return "No PDFs uploaded yet."
    conn = db.connect()
    return "\n".join(f"- {p.name} ({'analyzed' if db.is_analyzed(conn, p.name) else 'not analyzed'})" for p in pdfs)


@boss.tool
async def analyze_reports(ctx: RunContext[Session]) -> str:
    """Delegate to the Report Analyst: extract employers from every uploaded PDF not analyzed yet."""
    conn = db.connect()
    lines = []
    for pdf in sorted(REPORTS.glob("*.pdf")):
        if db.is_analyzed(conn, pdf.name):
            continue
        try:
            extraction, rejected = await analyze_report(pdf)
        except Exception as e:
            lines.append(f"- {pdf.name}: failed ({e})")
            continue
        db.save_report(conn, pdf.name, extraction)
        lines.append(f"- {pdf.name} ({extraction.school or 'school unknown'}): {len(extraction.employers)} employers"
                     + (f", {len(rejected)} dropped (not found on cited page)" if rejected else ""))
    lines += await scan_reports(conn)  # salary-by-industry/function tables
    total = conn.execute("SELECT COUNT(DISTINCT company) FROM employers").fetchone()[0]
    if total:
        _done(ctx.deps, 2)
    return ("\n".join(lines) or "No new PDFs to analyze.") + f"\nDatabase now has {total} distinct employers."


@boss.tool
async def research_programs(ctx: RunContext[Session], top_n: int = 10) -> str:
    """Delegate to the Program Scout: find the top MBA programs in the session's country/city (QS MBA rankings),
    with links to their employment reports where found. Cached for 30 days."""
    s = ctx.deps
    if not s.country:
        return "No country set yet."
    conn = db.connect()
    programs = db.cached_programs(conn, s.country, s.city)
    note = " (cached)"
    if programs is None:
        programs = await find_programs(s.country, s.city, min(top_n, 15))
        db.save_programs(conn, s.country, s.city, programs)
        note = ""
    if not programs.programs:
        return "Program Scout found no programs."
    lines = [f"- {p.school} ({p.city or '?'}) QS rank: {p.qs_rank or 'n/a'} | report: {p.employment_report_url or 'not found'}"
             for p in programs.programs]
    return f"Top MBA programs{note}:\n" + "\n".join(lines)


@boss.tool
async def find_reports(ctx: RunContext[Session], n: int = 3) -> str:
    """Delegate to the MBA Employment Report Finder: find the latest employment report PDFs for the top n MBA programs in the
    session's city (from research_programs). Does NOT download; returns links with file sizes for the student
    to approve, then call download_reports."""
    s = ctx.deps
    if not s.country:
        return "No country set yet."
    conn = db.connect()
    schools = db.top_programs_in_city(conn, s.country, s.city, min(n, 5))
    if not schools:
        return "No programs researched yet. Call research_programs first."
    s.pending_downloads = []
    lines = []
    # Free first: links Program Scout already found, checked in code (no model call)
    to_search = []
    for school in schools:
        url = db.known_report_url(conn, school)
        ok, size, _ = await check_pdf(url) if url else (False, None, "")
        if ok:
            name = file_name(school, url)
            s.pending_downloads.append((url, name))
            lines.append(f"- {school}: {name}, {f'{size:.1f} MB' if size else 'size unknown'} from {url}")
        else:
            to_search.append(school)
    links = await find_report_links(to_search) if to_search else ReportLinks(reports=[])
    for link in links.reports:
        if link.pdf_url:
            ok, size, note = await check_pdf(link.pdf_url)
            if ok:
                name = file_name(link.school, link.report_year)
                s.pending_downloads.append((link.pdf_url, name))
                lines.append(f"- {link.school} ({link.report_year or 'year?'}): {name}, "
                             f"{f'{size:.1f} MB' if size else 'size unknown'} from {link.pdf_url}")
                continue
            lines.append(f"- {link.school}: PDF link failed check ({note}): {link.pdf_url}")
        else:
            lines.append(f"- {link.school}: no direct PDF; report page: {link.page_url or 'not found'}")
    return "\n".join(lines) + (f"\n{len(s.pending_downloads)} PDF(s) ready. Ask the student to confirm before "
                               "calling download_reports." if s.pending_downloads else "")


@boss.tool
async def download_reports(ctx: RunContext[Session]) -> str:
    """Download the PDFs found by find_reports into data/reports/. Only call after the student said yes."""
    s = ctx.deps
    if not s.pending_downloads:
        return "Nothing to download. Call find_reports first."
    lines = []
    for url, name in s.pending_downloads:
        try:
            await download_pdf(url, name)
            lines.append(f"- saved {name}")
        except Exception as e:
            lines.append(f"- {name} failed: {e}")
    s.pending_downloads = []
    return "\n".join(lines) + "\nNext: analyze_reports to extract employers."


@boss.tool
async def verify_employers(ctx: RunContext[Session], limit: int = 10) -> str:
    """Delegate to the Geo Verifier: check whether extracted employers hire in the session's country.
    Uses web search (~19k tokens per company); cached for 7 days; max 50 per run."""
    if not ctx.deps.country:
        return "No country set yet."
    conn = db.connect()
    todo, cached = db.companies_to_verify(conn, ctx.deps.country, None, min(limit, MAX_VERIFY))
    counts = {"yes": 0, "no": 0, "unsure": 0}
    for company in todo:
        try:
            check = await verify(company, ctx.deps.country)
        except Exception:
            continue
        db.save_geo_check(conn, company, ctx.deps.country, check)
        counts[check.hires_in_country] += 1
    yes = [r[0] for r in db.geo_results(conn, ctx.deps.country, None) if r[1] == "yes"]
    return (f"Checked {len(todo)} companies ({cached} cached): {counts}. "
            f"Companies confirmed hiring in {ctx.deps.country}: {', '.join(yes) or 'none yet'}.")


def _load_session(user_id: int) -> Session:
    """Chat state per user, loaded from the database on first use: country, city, roles and chat history."""
    key = f"user:{user_id}"
    if key not in SESSIONS:
        conn = db.connect()
        country, city, roles, stage = db.get_prefs(conn, user_id)
        saved = db.get_chat_history(conn, user_id)
        history = ModelMessagesTypeAdapter.validate_json(saved) if saved else []
        SESSIONS[key] = Session(id=key, country=country, city=city, target_roles=roles, stage=stage, history=history)
    return SESSIONS[key]


def _is_user_turn(m: ModelMessage) -> bool:
    return isinstance(m, ModelRequest) and any(isinstance(p, UserPromptPart) for p in m.parts)


def recent_history(messages: list[ModelMessage], turns: int = HISTORY_TURNS) -> list[ModelMessage]:
    """Last `turns` user turns, cut at a user message so tool calls and their results stay together."""
    starts = [i for i, m in enumerate(messages) if _is_user_turn(m)]
    return messages[starts[-turns]:] if len(starts) > turns else messages


async def chat(user_id: int, message: str) -> tuple[Session, str]:
    session = _load_session(user_id)
    context = recent_history(session.history)
    result = await run_logged(
        boss, message, "boss", model=responses_model(), deps=session, message_history=context
    )
    session.history = session.history[: len(session.history) - len(context)] + result.all_messages()
    conn = db.connect()
    db.save_prefs(conn, user_id, session.country, session.city, session.target_roles, session.stage)
    db.save_chat_history(conn, user_id, ModelMessagesTypeAdapter.dump_json(session.history).decode())
    return session, result.output


def chat_transcript(user_id: int) -> list[dict]:
    """User messages and assistant replies (no tool calls) for showing the conversation in the UI."""
    out = []
    for m in _load_session(user_id).history:
        if isinstance(m, ModelRequest):
            out += [{"role": "user", "text": p.content} for p in m.parts
                    if isinstance(p, UserPromptPart) and isinstance(p.content, str)]
        elif isinstance(m, ModelResponse):
            text = "".join(p.content for p in m.parts if isinstance(p, TextPart)).strip()
            if text:
                out.append({"role": "assistant", "text": text})
    return out


def new_chat(user_id: int) -> None:
    """Start a fresh conversation. Saved prefs, tracker and postings stay."""
    db.clear_chat_history(db.connect(), user_id)
    SESSIONS.pop(f"user:{user_id}", None)


def reset_chat(user_id: int) -> None:
    """Drop the in-memory copy (on logout); the saved history stays in the database."""
    SESSIONS.pop(f"user:{user_id}", None)


@boss.tool
async def summarize_employers(ctx: RunContext[Session]) -> str:
    """Delegate to the Report Summarizer: group employers from the analyzed reports of the top 3 MBA programs in
    the session's city into industries (max 100 companies). Call after analyze_reports."""
    s = ctx.deps
    conn = db.connect()
    schools = db.top_programs_in_city(conn, s.country, s.city, 3) if s.country else []
    files = db.reports_for_schools(conn, schools) if schools else []
    if not files:  # e.g. student uploaded reports without running research_programs
        files = [r[0] for r in conn.execute("SELECT file FROM reports")]
    if not files:
        return "No analyzed reports yet."
    summary, cands = await summarize(conn, files, s.city or s.country or "the target location")
    _done(s, 3)
    total = sum(len(g.companies) for g in summary.industries)
    lines = [f"Reports used: {', '.join(files)}. {len(cands)} unique employers found; showing {total}.",
             f"Overview: {summary.overview}"]
    for g in summary.industries:
        tagged = [f"{c}{' *' if len(cands[norm(c)]['schools']) > 1 else ''}" for c in g.companies]
        lines.append(f"\n{g.industry} ({len(g.companies)}): " + ", ".join(tagged))
    lines.append("\n(* = listed by more than one school)")
    return "\n".join(lines)


def _fmt_research(r: CompanyResearch) -> str:
    sal = (f"{r.salary_base_low or '?'}-{r.salary_base_high or '?'} {r.salary_currency or ''}".strip()
           if r.salary_base_low or r.salary_base_high else "salary n/a")
    parts = [f"**{r.company}**: {sal}" + (f" ({r.salary_note})" if r.salary_note else ""),
             f"roles: {', '.join(r.mba_roles) or 'n/a'}", f"locations: {', '.join(r.locations) or 'n/a'}",
             f"visa: {r.visa_sponsorship}"]
    if r.recruiting_notes:
        parts.append(f"recruiting: {r.recruiting_notes}")
    if r.custom_answer:
        parts.append(f"answer: {r.custom_answer}")
    parts.append(f"careers: {r.careers_url or 'n/a'}")
    return " | ".join(parts)


@boss.tool
async def research_companies(ctx: RunContext[Session], companies: list[str], question: str | None = None) -> str:
    """Delegate to the Company Researcher: post-MBA salary, MBA roles, office locations, visa sponsorship and
    recruiting timeline for each company (max 20 per run; web search ~20k tokens per company, cached 30 days).
    `question` = an extra thing the student wants to know about every company (optional).
    Confirm the list with the student first if it's more than 5 new companies."""
    s = ctx.deps
    if not s.country:
        return "No country set yet."
    conn = db.connect()
    companies = list(dict.fromkeys(companies))[:MAX_RESEARCH]
    todo = []
    for c in companies:
        if (hit := db.cached_research(conn, c, s.country, question)):
            s.research[c] = hit
        else:
            todo.append(c)
    await scan_reports(conn)  # make sure report salary tables are loaded
    known = {c for c in todo if report_salary(conn, c)}  # salary from reports -> skip web salary search
    results, errors = await research_many(todo, s.country, s.city, question, known)
    for r in results:
        db.save_research(conn, s.country, question, r)
        s.research[r.company] = r
    for c in companies:  # reports are the primary salary source (also for cached research)
        if c in s.research:
            apply_report_salary(conn, s.research[c])
    if any(c in s.research for c in companies):
        _done(s, 4)
    lines = [_fmt_research(s.research[c]) for c in companies if c in s.research]
    head = f"Researched {len(results)} new, {len(companies) - len(todo)} cached."
    return head + "\n" + "\n".join(lines) + (f"\nFailed: {', '.join(errors)}" if errors else "")


@boss.tool
async def rank_companies(ctx: RunContext[Session], by: Literal["salary", "fit"] = "fit", priorities: str | None = None) -> str:
    """Rank the companies researched in this session. by="salary" (highest base midpoint first) or
    by="fit" (needs `priorities`, e.g. "consulting roles, Toronto, visa sponsorship, high pay")."""
    rows = list(ctx.deps.research.values())
    if not rows:
        return "Nothing researched yet. Call research_companies first."
    if by == "salary":
        return "\n".join(f"{i}. {_fmt_research(r)}" for i, r in enumerate(rank_by_salary(rows), 1))
    if not priorities:
        return "Ask the student what matters most to them (roles, pay, location, visa, etc.) first."
    scores = await fit_scores(rows, priorities)
    ranked = sorted(rows, key=lambda r: -scores.get(r.company, (0, ""))[0])
    return "\n".join(f"{i}. {r.company}: {scores.get(r.company, (0, 'not scored'))[0]}/10, "
                     f"{scores.get(r.company, (0, 'not scored'))[1]}" for i, r in enumerate(ranked, 1))


@boss.tool
def add_to_tracker(ctx: RunContext[Session], companies: list[str]) -> str:
    """Add companies the student picked to their application tracker (5-15 companies recommended, max 15)."""
    s = ctx.deps
    conn = db.connect()
    have = len(db.tracker_rows(conn, s.id))
    added, skipped = [], []
    for c in companies:
        if have >= db.TRACKER_MAX:
            skipped.append(c)
            continue
        url = s.research[c].careers_url if c in s.research else None
        if db.tracker_add(conn, s.id, c, url):
            added.append(c)
            have += 1
    if have:
        _done(s, 5)
    msg = f"Added {len(added)}: {', '.join(added) or 'none'}. Tracker has {have}/{db.TRACKER_MAX}."
    if skipped:
        msg += f" Not added (tracker full): {', '.join(skipped)}."
    if have < 5:
        msg += f" Suggest picking {5 - have} more (5-15 recommended)."
    return msg


@boss.tool
def view_tracker(ctx: RunContext[Session]) -> str:
    """Show the student's tracker: company, status, careers URL, notes, last updated."""
    rows = db.tracker_rows(db.connect(), ctx.deps.id)
    return "\n".join(f"- {c} [{st}] {url} {n} (updated {d})" for c, st, url, n, d in rows) or "Tracker is empty."


@boss.tool
def update_tracker(ctx: RunContext[Session], company: str,
                   status: Literal["interested", "applied", "interviewing", "offer", "rejected"] | None = None,
                   notes: str | None = None, remove: bool = False) -> str:
    """Update a tracked company's status and/or notes, or remove it (remove=True)."""
    conn = db.connect()
    if remove:
        return "Removed." if db.tracker_remove(conn, ctx.deps.id, company) else f"{company} isn't in the tracker."
    return "Updated." if db.tracker_update(conn, ctx.deps.id, company, status, notes) else f"{company} isn't in the tracker."


def _location_key(s: Session) -> str:
    return f"{s.city + ', ' if s.city else ''}{s.country}"


@boss.tool
def set_target_roles(ctx: RunContext[Session], roles: list[str]) -> str:
    """Save the role types the student wants, e.g. ["strategy", "product management", "finance"]."""
    ctx.deps.target_roles = [r.strip().lower() for r in roles if r.strip()]
    return f"Target roles: {', '.join(ctx.deps.target_roles)}."


@boss.tool
async def check_job_postings(ctx: RunContext[Session], force: bool = False) -> str:
    """Delegate to the Job Posting Scout: for every company on the student's tracker, find the careers page and
    current intern / MBA / early-career postings in the session's city (or country) for the student's target roles,
    plus country-wide MBA programs whose city is matched after hire. Set target roles first. Web search ~17k tokens per
    company; companies checked in the last 24h are skipped unless force=True. Saves careers URLs to the tracker."""
    s = ctx.deps
    if not s.country:
        return "No country set yet."
    conn = db.connect()
    tracked = db.tracker_rows(conn, s.id)
    if not tracked:
        return "Tracker is empty. Ask the student to pick 5-15 companies first."
    if not s.target_roles:
        return "Ask the student which role types they want (e.g. strategy, product, finance) and call set_target_roles first."
    key = _location_key(s)
    roles = ", ".join(sorted(s.target_roles))
    todo = [(c, None if url == "-" else url) for c, _, url, _, _ in tracked
            if force or not db.recently_scanned(conn, c, key, roles)]
    scans, errors = await scan_many(todo, s.country, s.city, s.target_roles)
    new_total = 0
    for company, scan in scans.items():
        new_total += db.save_posting_scan(conn, company, key, scan, roles)
        if scan.careers_url:
            db.set_tracker_careers_url(conn, s.id, company, scan.careers_url)
    if scans or len(todo) < len(tracked):
        _done(s, 6)
    return (f"Checked {len(scans)} companies ({len(tracked) - len(todo)} checked in last 24h, skipped); "
            f"{new_total} new postings.\n" + _postings_report(conn, s) + (f"\nFailed: {', '.join(errors)}" if errors else ""))


def _postings_report(conn, s: Session) -> str:
    key = _location_key(s)
    postings = db.postings_for_student(conn, s.id, key)
    by_company: dict[str, list] = {}
    for company, title, loc, level, url, first, flexible in postings:
        where = f"{loc}; location matched after hire" if flexible else loc
        by_company.setdefault(company, []).append(f"  - [{level}] {title} ({where}) {url} (first seen {first})")
    lines = []
    for company, careers, note, scanned in db.scan_notes(conn, s.id, key):
        lines.append(f"**{company}**: careers page {careers or 'not found'}")
        lines += by_company.get(company, [f"  - no matching postings. {note or ''}".rstrip()])
    return "\n".join(lines) or "No companies checked yet."


@boss.tool
def view_job_postings(ctx: RunContext[Session]) -> str:
    """Show saved careers pages and active postings for the tracked companies (no new search)."""
    return _postings_report(db.connect(), ctx.deps)
