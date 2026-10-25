"""Report Summarizer agent: groups employers from the city's top 3 MBA reports into industries (max 100 companies).

Code picks the reports, merges duplicate company names, and counts how many schools list each one.
The model groups them into industries and picks the most relevant. Code then drops any name that wasn't
in the input and enforces the 100-company cap.
"""
import re
import sqlite3

from pydantic_ai import Agent, NativeOutput

from backend.llm import model, run_logged
from backend.models import EmployerSummary

MAX_COMPANIES = 100

INSTRUCTIONS = f"""You are the Report Summarizer. You get employers taken from MBA employment reports of the top
MBA programs in one city, each with the schools that list it and a function tag.

- Pick at most {MAX_COMPANIES} companies most useful for an MBA student targeting jobs there. Prefer companies listed
  by more schools and well-known MBA employers (consulting, banking, tech, consumer goods, etc.). Drop placeholders
  like "Stealth" or "Confidential", individuals, and very small unknown firms when you need to cut.
- Group them into 6-12 clear industries (e.g. Consulting; Banking & Investment Management; Insurance;
  Technology; Consumer Goods & Retail; Healthcare & Life Sciences; Energy & Resources; Legal & Professional
  Services; Public Sector & Non-profit; Real Estate & Infrastructure). Sort companies within each industry by
  how many schools list them.
- Copy company names EXACTLY as given. Never add companies that aren't in the list.
- overview: 2-4 sentences on the hiring pattern (which industries dominate, notable employers).
"""

agent = Agent(output_type=NativeOutput(EmployerSummary), instructions=INSTRUCTIONS)

_SUFFIX = re.compile(r"\b(inc|ltd|llp|llc|limited|corp|corporation|co|company|group|plc|lp)\b")


def norm(name: str) -> str:
    name = re.sub(r"\(.*?\)", "", name.lower()).replace("&", " and ")
    name = _SUFFIX.sub("", re.sub(r"[^a-z0-9& ]", " ", name))
    return " ".join(name.split())


def candidates(conn: sqlite3.Connection, files: list[str]) -> dict[str, dict]:
    """norm name -> {company, function, schools} merged across the given report files."""
    marks = ",".join("?" * len(files))
    out: dict[str, dict] = {}
    for company, function, school, file in conn.execute(
        f"""SELECT e.company, e.function, COALESCE(r.school, r.file), r.file
            FROM employers e JOIN reports r ON r.id = e.report_id WHERE r.file IN ({marks})""",
        files,
    ):
        c = out.setdefault(norm(company), {"company": company, "function": function, "schools": set()})
        c["schools"].add(school)
    return out


async def summarize(conn: sqlite3.Connection, files: list[str], city: str) -> tuple[EmployerSummary, dict[str, dict]]:
    cands = candidates(conn, files)
    ranked = sorted(cands.values(), key=lambda c: (-len(c["schools"]), c["company"].lower()))
    listing = "\n".join(f"{c['company']} | {c['function']} | {len(c['schools'])} school(s)" for c in ranked)
    result = await run_logged(
        agent, f"City: {city}\nEmployers ({len(ranked)}):\n{listing}", f"report_summarizer:{city}", model=model()
    )
    summary = result.output
    seen: set[str] = set()
    for group in summary.industries:  # grounding + dedupe + cap, in code
        kept = []
        for name in group.companies:
            k = norm(name)
            if k in cands and k not in seen and len(seen) < MAX_COMPANIES:
                seen.add(k)
                kept.append(cands[k]["company"])
        group.companies = kept
    summary.industries = [g for g in summary.industries if g.companies]
    return summary, cands
