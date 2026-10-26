"""Boss agent (Career Scout): owns the chat with the student and delegates to specialist agents.

Specialists: Report Analyst (PDF -> employers), Geo Verifier (does a company hire in the country?),
Program Scout (top MBA programs via QS rankings), MBA Employment Report Finder (finds + downloads report PDFs),
Report Summarizer (groups employers into industries, max 100), Company Researcher (salary, roles,
locations, visa, recruiting; ranks by salary or fit). Students keep a tracker of 5-15 companies;
Job Posting Scout checks their careers pages for intern / MBA / early-career postings in the city.
Each saved search (one per location) has its own chat, progress, employer table and tracker.
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
    id: str = ""  # tracker scope key of the open search ("search:<id>")
    owner: str | None = None  # account stamp + search id this in-memory state belongs to
    user_id: int = 0
    search_id: int = 0
    country: str | None = None
    city: str | None = None
    report_source: Literal["upload", "auto"] | None = None
    history: list[ModelMessage] = field(default_factory=list)
    pending_downloads: list[tuple[str, str]] = field(default_factory=list)  # (url, file name) awaiting OK
    research: dict[str, CompanyResearch] = field(default_factory=dict)  # last researched companies
    stage: int = 0  # bitmask of completed guided-path steps: bit (n-1) set = step n done (see STEPS)
    actions: dict[str, list[dict]] = field(default_factory=dict)  # transcript index -> buttons under that reply
    turn_actions: list[dict] = field(default_factory=list)  # buttons collected by tools during this turn
    switch_to: tuple[str, str | None] | None = None  # set_country asked for a different place -> new saved search


def _action(s: "Session", action: dict) -> None:
    """Add a button under this turn's reply (deduplicated)."""
    if action not in s.turn_actions:
        s.turn_actions.append(action)


SESSIONS: dict[str, Session] = {}

STEPS = ["Where to work", "Employment reports", "Employers by industry", "Research companies", "Tracker", "Job postings"]


def _done(s: Session, step: int) -> None:
    """Mark a guided-path step complete (set by the tools, not by the model)."""
    s.stage |= 1 << (step - 1)


def steps_done(stage: int) -> list[int]:
    return [i for i in range(1, len(STEPS) + 1) if stage & (1 << (i - 1))]


def next_step(stage: int) -> int | None:
    """First step not done yet (1-based), or None when all are done."""
    return next((i for i in range(1, len(STEPS) + 1) if not stage & (1 << (i - 1))), None)

boss = Agent(deps_type=Session, output_type=str, instructions=(Path(__file__).parent / "prompts" / "boss.md").read_text())


@boss.instructions
def _state(ctx: RunContext[Session]) -> str:
    s = ctx.deps
    tracked = [r[0] for r in db.tracker_rows(db.connect(), s.id)]
    done = ", ".join(f"{i}. {STEPS[i - 1]}" for i in steps_done(s.stage)) or "none"
    n = next_step(s.stage)
    nxt = f"step {n}: {STEPS[n - 1]}" if n else "all done (offer a new posting check)"
    return (f"Guided path: completed steps: {done}. Next: {nxt}.\n"
            f"Saved tracker: {', '.join(tracked) or 'empty'}.\n"
            f"Current state: country={s.country or 'not set'}, city={s.city or 'any'}, "
            f"report_source={s.report_source or 'not chosen'}.")


@boss.tool
def set_country(ctx: RunContext[Session], country: str, city: str | None = None) -> str:
    """Save the country (and optional city) the student wants to work in, e.g. "Canada", "Toronto"."""
    s = ctx.deps
    new_country, new_city = country.strip().title(), (city.strip().title() if city else None)
    label = f"{new_city + ', ' if new_city else ''}{new_country}"
    if s.country and (new_country, new_city) != (s.country, s.city):
        # A different place becomes its own saved search; the current one is kept as it is.
        old = f"{s.city + ', ' if s.city else ''}{s.country}"
        s.switch_to = (new_country, new_city)
        s.country, s.city, s.stage = new_country, new_city, 0
        _done(s, 1)
        return (f"Started a new saved search for {label}. The {old} search is kept: the student can switch back "
                f"any time from the search menu at the top.")
    s.country, s.city = new_country, new_city
    _done(s, 1)
    return f"Location set to {label}."


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


REPORTS_PER_CITY = 3


def _city_reports(conn, s: Session) -> list[str]:
    """Analyzed report files for the location: best-ranked programs first (city first), up to REPORTS_PER_CITY."""
    ranked = db.top_programs_in_city(conn, s.country, s.city, 10) if s.country else []
    return db.reports_for_schools(conn, ranked)[:REPORTS_PER_CITY]


@boss.tool
async def find_reports(ctx: RunContext[Session]) -> str:
    """Delegate to the MBA Employment Report Finder: get employment reports for 3 MBA programs in the session's
    city (best-ranked first; if a school has no report, moves on to the next-ranked program, city first, then
    nearby). Reports already analyzed count. Does NOT download; returns links with sizes for the student to
    approve, then call download_reports."""
    s = ctx.deps
    if not s.country:
        return "No country set yet."
    conn = db.connect()
    ranked = db.top_programs_in_city(conn, s.country, s.city, 10)
    if not ranked:
        return "No programs researched yet. Call research_programs first."
    s.pending_downloads = []
    picked, notes, idx, searches = [], [], 0, 0
    def _offer_download():
        if s.pending_downloads:
            _action(s, {"type": "say", "text": "Yes, download them and pull out the employers.",
                        "label": "Yes, download and extract employers"})

    def where(school: str) -> str:
        pc = db.program_city(conn, school)
        return f" [{pc}, outside {s.city}]" if s.city and pc and s.city.lower() not in pc.lower() else ""

    while len(picked) < REPORTS_PER_CITY and idx < len(ranked):
        batch = ranked[idx: idx + REPORTS_PER_CITY - len(picked)]
        idx += len(batch)
        to_search = []
        for school in batch:
            if db.reports_for_schools(conn, [school]):  # already analyzed: no download needed
                picked.append(f"- {school}{where(school)}: report already analyzed")
                continue
            url = db.known_report_url(conn, school)
            ok, size, _ = await check_pdf(url) if url else (False, None, "")
            if ok:
                name = file_name(school, url)
                s.pending_downloads.append((url, name))
                picked.append(f"- {school}{where(school)}: {name}, {f'{size:.1f} MB' if size else 'size unknown'} from {url}")
            else:
                to_search.append(school)
        if not to_search:
            continue
        if searches >= 2:  # cap web searches per request
            notes += [f"- {school}: not searched (search limit reached)" for school in to_search]
            continue
        searches += 1
        found = {l.school: l for l in (await find_report_links(to_search)).reports}
        for school in to_search:
            link = found.get(school) or next((l for k, l in found.items() if k.split(",")[0] in school), None)
            if link and link.pdf_url:
                ok, size, note = await check_pdf(link.pdf_url)
                if ok:
                    name = file_name(school, link.report_year)
                    s.pending_downloads.append((link.pdf_url, name))
                    picked.append(f"- {school}{where(school)} ({link.report_year or 'year?'}): {name}, "
                                  f"{f'{size:.1f} MB' if size else 'size unknown'} from {link.pdf_url}")
                    continue
                notes.append(f"- {school}: PDF link failed check ({note}); skipped, trying the next school")
            else:
                page = link.page_url if link else None
                notes.append(f"- {school}: no PDF found{f' (report page: {page})' if page else ''}; trying the next school")
    _offer_download()
    out = [f"Reports for {len(picked)} of {REPORTS_PER_CITY} programs:"] + picked
    if notes:
        out += ["Skipped:"] + notes
    if s.pending_downloads:
        out.append(f"{len(s.pending_downloads)} PDF(s) to download. Ask the student to confirm before calling download_reports.")
    elif picked:
        out.append("Nothing to download: all are already analyzed. Call analyze_reports (fast) then summarize_employers.")
    return "\n".join(out)


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
    """State of the user's open search. The database is the source of truth for location and progress (re-read every
    call). The in-memory part (history, pending downloads, research) is tied to the exact account and search, so a
    reused id or a switched search never inherits someone else's conversation."""
    conn = db.connect()
    sid = db.active_search_id(conn, user_id)
    key = db.scope(sid)
    owner = f"{db.user_stamp(conn, user_id)}|{sid}"
    row = db.get_search(conn, sid)
    session = SESSIONS.get(key)
    if session is None or session.owner != owner:
        history = ModelMessagesTypeAdapter.validate_json(row["messages"]) if row["messages"] else []
        session = SESSIONS[key] = Session(id=key, owner=owner, user_id=user_id, search_id=sid, history=history,
                                          actions=row["actions"])
    session.country, session.city, session.stage = row["country"], row["city"], row["stage"]
    session.switch_to = None
    return session


def _is_user_turn(m: ModelMessage) -> bool:
    return isinstance(m, ModelRequest) and any(isinstance(p, UserPromptPart) for p in m.parts)


def recent_history(messages: list[ModelMessage], turns: int = HISTORY_TURNS) -> list[ModelMessage]:
    """Last `turns` user turns, cut at a user message so tool calls and their results stay together."""
    starts = [i for i, m in enumerate(messages) if _is_user_turn(m)]
    return messages[starts[-turns]:] if len(starts) > turns else messages


def _transcript(history: list[ModelMessage]) -> list[dict]:
    """User messages and assistant replies (no tool calls) for showing the conversation in the UI."""
    out = []
    for m in history:
        if isinstance(m, ModelRequest):
            out += [{"role": "user", "text": p.content} for p in m.parts
                    if isinstance(p, UserPromptPart) and isinstance(p.content, str)]
        elif isinstance(m, ModelResponse):
            text = "".join(p.content for p in m.parts if isinstance(p, TextPart)).strip()
            if text:
                out.append({"role": "assistant", "text": text})
    return out


def _attach(actions: dict, history: list[ModelMessage], turn_actions: list[dict]) -> dict:
    """Pin this turn's buttons to the last assistant message of the transcript."""
    if turn_actions:
        actions = {**actions, str(len(_transcript(history)) - 1): turn_actions}
    return actions


def _dump(history: list[ModelMessage]) -> str:
    return ModelMessagesTypeAdapter.dump_json(history).decode()


async def chat(user_id: int, message: str) -> tuple[Session, str, list[dict]]:
    session = _load_session(user_id)
    before = (session.country, session.city, session.stage)
    session.turn_actions = []
    context = recent_history(session.history)
    result = await run_logged(
        boss, message, "boss", model=responses_model(), deps=session, message_history=context
    )
    conn = db.connect()
    full = session.history[: len(session.history) - len(context)] + result.all_messages()
    if session.switch_to:
        # Keep the old search as it was (with this exchange), then open the new place as its own search.
        db.update_search(conn, session.search_id, *before)
        db.save_search_chat(conn, session.search_id, _dump(full), session.actions)
        country, city = session.switch_to
        new_sid = db.create_search(conn, user_id, country, city, session.stage)
        new_history = result.new_messages()
        new_actions = _attach({}, new_history, session.turn_actions)
        db.save_search_chat(conn, new_sid, _dump(new_history), new_actions)
        SESSIONS.pop(session.id, None)
        return _load_session(user_id), result.output, session.turn_actions
    session.history = full
    session.actions = _attach(session.actions, full, session.turn_actions)
    db.update_search(conn, session.search_id, session.country, session.city, session.stage)
    db.save_search_chat(conn, session.search_id, _dump(full), session.actions)
    return session, result.output, session.turn_actions


def chat_transcript(user_id: int) -> list[dict]:
    session = _load_session(user_id)
    out = _transcript(session.history)
    for i, m in enumerate(out):
        if str(i) in session.actions:
            m["actions"] = session.actions[str(i)]
    return out


def new_chat(user_id: int, new_search: bool = False) -> None:
    """new_search=False: clear the open search's conversation (location, progress, table and tracker stay).
    new_search=True: open a brand-new empty search; the current one is kept and can be switched back to."""
    conn = db.connect()
    session = _load_session(user_id)
    if new_search:
        db.create_search(conn, user_id)
    else:
        db.save_search_chat(conn, session.search_id, None, {})
    SESSIONS.pop(session.id, None)


def switch_search(user_id: int, search_id: int) -> bool:
    return db.set_active_search(db.connect(), user_id, search_id)


def delete_search(user_id: int, search_id: int) -> bool:
    ok = db.delete_search(db.connect(), user_id, search_id)
    SESSIONS.pop(db.scope(search_id), None)
    return ok


def reset_chat(user_id: int) -> None:
    """Drop this user's in-memory state (on logout); everything saved stays in the database."""
    for key in [k for k, v in SESSIONS.items() if v.user_id == user_id]:
        SESSIONS.pop(key, None)


FUNCTION_INDUSTRY = {  # fallback industry for employers outside the curated top picks
    "consulting": "Consulting", "finance": "Finance", "tech": "Technology", "marketing": "Consumer & Marketing",
    "operations": "Operations & Industrial", "healthcare": "Healthcare & Life Sciences", "energy": "Energy & Resources",
    "general management": "General Management", "other": "Other",
}


def short_school(name: str) -> str:
    """'Rotman School of Management, University of Toronto' -> 'Rotman'."""
    words = [w for w in name.split(",")[0].split() if w.lower() not in ("the",)]
    return words[0] if words else name


@boss.tool
async def summarize_employers(ctx: RunContext[Session]) -> str:
    """Delegate to the Report Summarizer: group employers from the analyzed reports of the city's 3 MBA programs
    into industries (top picks, max 100). Saves ALL employers to the student's interactive Employers table in the
    app (filter by industry/school, select to research or track). Call after analyze_reports."""
    s = ctx.deps
    conn = db.connect()
    files = _city_reports(conn, s)
    if not files:  # e.g. student uploaded reports without running research_programs
        files = [r[0] for r in conn.execute("SELECT file FROM reports")][:REPORTS_PER_CITY]
    if not files:
        return "No analyzed reports yet."
    location = s.city or s.country or "the target location"
    summary, cands = await summarize(conn, files, location)
    _done(s, 3)
    picks = {norm(c): g.industry for g in summary.industries for c in g.companies}
    rows = [{
        "company": c["company"],
        "industry": picks.get(k) or FUNCTION_INDUSTRY.get(c["function"], "Other"),
        "function": c["function"],
        "schools": sorted(({"school": short_school(x), "hired": x in c["hired_by"]} for x in c["schools"]),
                          key=lambda d: (not d["hired"], d["school"])),
        "hired": bool(c["hired_by"]),
        "top_pick": k in picks,
    } for k, c in cands.items()]
    rows.sort(key=lambda r: (not r["top_pick"], -sum(x["hired"] for x in r["schools"]), -len(r["schools"]),
                             r["company"].lower()))
    if s.search_id:
        db.save_search_employers(conn, s.search_id, summary.overview, files, rows)
    _action(s, {"type": "open_tab", "tab": "employers", "label": "Open the employer table →"})
    per_school = ", ".join(f"{short_school(n)}: {k} ({h} hired, {k - h} recruiting only)"
                           for n, k, h in db.report_school_counts(conn, files))
    per_industry = ", ".join(f"{g.industry} {len(g.companies)}" for g in summary.industries)
    multi = sum(1 for r in rows if len(r["schools"]) > 1)
    hired = sum(1 for r in rows if r["hired"])
    return (f"Saved to the student's Employers table (a button under your reply opens it). Reports used: {len(files)} "
            f"({per_school}).\n"
            f"Some reports list companies that only recruit/network at the school, not confirmed hires.\n"
            f"{len(rows)} unique employers; {hired} confirmed to have hired grads; {len(picks)} top picks; "
            f"{multi} listed by more than one school.\n"
            f"Top picks by industry: {per_industry}.\nOverview: {summary.overview}")


def mark_step(user_id: int, step: int) -> None:
    """For actions taken in the UI (e.g. + Track in the Employers table)."""
    session = _load_session(user_id)
    _done(session, step)
    db.update_search(db.connect(), session.search_id, session.country, session.city, session.stage)


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
    tracked = {r[0].lower() for r in db.tracker_rows(conn, s.id)}
    untracked = [c for c in companies if c in s.research and c.lower() not in tracked]
    if untracked:
        _action(s, {"type": "track", "companies": untracked,
                    "label": f"Add {'these ' + str(len(untracked)) if len(untracked) > 1 else untracked[0]} to my tracker"})
    else:
        _action(s, {"type": "open_tab", "tab": "tracker", "label": "Open my tracker →"})
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
        _action(s, {"type": "open_tab", "tab": "tracker", "label": "Open my tracker →"})
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
async def check_job_postings(ctx: RunContext[Session], force: bool = False) -> str:
    """Delegate to the Job Posting Scout: for every company on the student's tracker, find the careers page and
    ALL current intern / MBA / early-career postings (any function) in the session's city (or country), plus
    country-wide MBA programs whose city is matched after hire. No need to ask about role types. Web search ~17k tokens per
    company; companies checked in the last 24h are skipped unless force=True. Saves careers URLs to the tracker."""
    s = ctx.deps
    if not s.country:
        return "No country set yet."
    conn = db.connect()
    tracked = db.tracker_rows(conn, s.id)
    if not tracked:
        return "Tracker is empty. Ask the student to pick 5-15 companies first."
    key = _location_key(s)
    roles = "all early-career"  # cache key: scans cover every early-career role
    todo = [(c, None if url == "-" else url) for c, _, url, _, _ in tracked
            if force or not db.recently_scanned(conn, c, key, roles)]
    scans, errors = await scan_many(todo, s.country, s.city)
    new_total = 0
    for company, scan in scans.items():
        new_total += db.save_posting_scan(conn, company, key, scan, roles)
        if scan.careers_url:
            db.set_tracker_careers_url(conn, s.id, company, scan.careers_url)
    if scans or len(todo) < len(tracked):
        _done(s, 6)
        _action(s, {"type": "open_tab", "tab": "tracker", "label": "See jobs in my tracker →"})
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
