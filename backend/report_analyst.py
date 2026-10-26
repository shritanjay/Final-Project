"""Report Analyst agent: one employment report PDF -> ReportExtraction (employers with page numbers)."""
import re
from pathlib import Path

from pydantic_ai import Agent, NativeOutput

from backend.llm import model, run_logged
from backend.models import Employer, ReportExtraction
from backend.pdf_reader import read_pages

INSTRUCTIONS = """You are a Report Analyst. You read MBA employment reports and list the employers in them.

Rules:
- Include every company named in the report's employer lists: "hiring organizations", "employers",
  "companies recruiting at <school>", "where our graduates work", internship employer lists, and companies named in
  quotes or profiles. Long alphabetical lists spanning several pages must be listed in full.
- Only list companies that are actually named in the report text. Never add companies from your own knowledge.
- Every employer needs the page number from the === PAGE n === marker above the text where it appears.
  If a company appears on several pages, use the first page.
- role_type: "internship" if listed only under summer/internship hiring, "full-time" if only under
  full-time/graduate hiring, "both" if under both. If the report doesn't separate them, use "full-time".
- function: use the function the report lists the company under. If the report doesn't say (e.g. a plain
  alphabetical list), pick the category that best fits what the company mainly does (McKinsey -> consulting,
  RBC -> finance, Microsoft -> tech, Loblaw -> operations, hospitals -> healthcare). Use "other" only if unclear.
- evidence: "hired" if the report says the company hired graduates (e.g. "employers hiring our graduates", or a
  symbol the report's legend defines as "hired"); "recruiting" if it is only listed as recruiting at the school,
  engaging with students, networking or posting jobs. Read list headings and legends carefully.
- Keep footnote symbols (*, †) at the end of names exactly as printed; code removes them.
- location: only if the report states it for that company (e.g. under a region heading). Otherwise null.
- List each company once. Skip schools, generic phrases like "various startups", and section headings.
"""

# NativeOutput = JSON-schema response format; gpt-6-luna on Portkey rejects tool-call output with reasoning on
agent = Agent(output_type=NativeOutput(ReportExtraction), instructions=INSTRUCTIONS)


_ABBREV = re.compile(r"\b(inc|ltd|co|corp|jr|sr|bros|ltée|ltee|s\.a|l\.p|n\.a|u\.s|p\.c)\.$", re.I)


def clean_name(name: str) -> str:
    """Strip footnote markers and stray trailing periods: 'Deloitte.*' -> 'Deloitte', keeps 'Acme Inc.'."""
    name = re.sub(r"[\s*†‡]+$", "", name.strip())
    if name.endswith(".") and not _ABBREV.search(name):
        name = name[:-1].rstrip()
    return name


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def on_page(employer: Employer, pages: list[str]) -> bool:
    """Grounding check: the company name must really appear on the cited page."""
    if not 1 <= employer.page <= len(pages):
        return False
    page = _norm(pages[employer.page - 1])
    if _norm(employer.company) in page:
        return True
    words = [_norm(w) for w in employer.company.split() if len(_norm(w)) > 2]
    return bool(words) and all(w in page for w in words)


async def analyze_report(path: Path) -> tuple[ReportExtraction, list[Employer]]:
    """Returns (grounded extraction, rejected employers that failed the page check)."""
    pages = read_pages(path)
    if not any(p.strip() for p in pages):
        raise ValueError(f"{path.name}: no extractable text (scanned PDF?)")
    text = "\n\n".join(f"=== PAGE {i} ===\n{p}" for i, p in enumerate(pages, 1))
    result = await run_logged(agent, text, f"report_analyst:{path.name}", model=model())
    out = result.output
    kept = [e for e in out.employers if on_page(e, pages)]
    rejected = [e for e in out.employers if e not in kept]
    for e in kept:
        e.company = clean_name(e.company)
    return ReportExtraction(school=out.school, employers=kept), rejected
