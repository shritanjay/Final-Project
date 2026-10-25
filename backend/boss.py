"""Boss agent (Career Scout): owns the chat with the student and delegates to specialist agents.

Specialists: Report Analyst (PDF -> employers), Geo Verifier (does a company hire in the country?),
Program Scout (top MBA programs via QS rankings). Conversation state lives per session in memory.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage

from backend import db
from backend.geo_verifier import verify
from backend.llm import responses_model, run_logged
from backend.program_scout import find_programs
from backend.report_analyst import analyze_report

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "data" / "reports"
MAX_VERIFY = 50


@dataclass
class Session:
    country: str | None = None
    city: str | None = None
    report_source: Literal["upload", "auto"] | None = None
    history: list[ModelMessage] = field(default_factory=list)


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
    return f"Top MBA programs{note}:\n" + "\n".join(lines) + "\n(Downloading the reports isn't automated yet.)"


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
