"""Boss agent (Career Scout): owns the chat with the student and delegates to specialist agents.

Specialists: Report Analyst (PDF -> employers), Geo Verifier (does a company hire in the country?),
Program Scout (top MBA programs via QS rankings), MBA Employment Report Finder (finds + downloads report PDFs),
Report Summarizer (groups employers into industries, max 100). Conversation state lives per session in memory.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage

from backend import db
from backend.geo_verifier import verify
from backend.models import ReportLinks
from backend.llm import responses_model, run_logged
from backend.program_scout import find_programs
from backend.employment_report_finder import check_pdf, download_pdf, file_name, find_report_links
from backend.report_analyst import analyze_report
from backend.report_summarizer import norm, summarize

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "data" / "reports"
MAX_VERIFY = 50


@dataclass
class Session:
    country: str | None = None
    city: str | None = None
    report_source: Literal["upload", "auto"] | None = None
    history: list[ModelMessage] = field(default_factory=list)
    pending_downloads: list[tuple[str, str]] = field(default_factory=list)  # (url, file name) awaiting OK


SESSIONS: dict[str, Session] = {}

boss = Agent(deps_type=Session, output_type=str, instructions=(Path(__file__).parent / "prompts" / "boss.md").read_text())


@boss.instructions
def _state(ctx: RunContext[Session]) -> str:
    s = ctx.deps
    return f"Current state: country={s.country or 'not set'}, city={s.city or 'any'}, report_source={s.report_source or 'not chosen'}."


@boss.tool
def set_country(ctx: RunContext[Session], country: str, city: str | None = None) -> str:
    """Save the country (and optional city) the student wants to work in, e.g. "Canada", "Toronto"."""
    ctx.deps.country = country.strip().title()
    ctx.deps.city = city.strip().title() if city else None
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


@boss.tool_plain
async def analyze_reports() -> str:
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
    total = conn.execute("SELECT COUNT(DISTINCT company) FROM employers").fetchone()[0]
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


async def chat(session_id: str, message: str) -> tuple[Session, str]:
    session = SESSIONS.setdefault(session_id, Session())
    result = await run_logged(
        boss, message, "boss", model=responses_model(), deps=session, message_history=session.history
    )
    session.history = result.all_messages()
    return session, result.output


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
    total = sum(len(g.companies) for g in summary.industries)
    lines = [f"Reports used: {', '.join(files)}. {len(cands)} unique employers found; showing {total}.",
             f"Overview: {summary.overview}"]
    for g in summary.industries:
        tagged = [f"{c}{' *' if len(cands[norm(c)]['schools']) > 1 else ''}" for c in g.companies]
        lines.append(f"\n{g.industry} ({len(g.companies)}): " + ", ".join(tagged))
    lines.append("\n(* = listed by more than one school)")
    return "\n".join(lines)
