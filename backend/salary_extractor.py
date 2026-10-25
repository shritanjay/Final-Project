"""Salary Extractor: pulls salary-by-industry and salary-by-function tables out of analyzed employment reports.

Only pages that look like salary tables are sent to the model. Code then keeps a row only if its
average (or median) really appears on the cited page.
"""
import re
import sqlite3
from pathlib import Path

from pydantic_ai import Agent, NativeOutput

from backend import db
from backend.llm import model, run_logged
from backend.models import SalaryTable
from backend.pdf_reader import read_pages

INSTRUCTIONS = """You extract salary tables from an MBA employment report.

- Extract every row of tables that break salary down by INDUSTRY or by FUNCTION, for full-time hires and for
  internships. Skip overall/total figures, signing bonuses, and rows with no numbers.
- Copy numbers exactly as whole numbers (no $ or commas). Map each row to the closest category:
  consulting, finance (financial services, banking, accounting), tech, marketing (marketing/sales, CPG, retail,
  consumer goods), operations (operations/logistics, transportation, manufacturing), healthcare, energy,
  general management (incl. strategy), other (legal, government, real estate, media, other).
- period: "monthly" for monthly internship pay, else "annual". currency ONLY if the report writes it (e.g. "(CAD)");
  a bare "$" is not a currency, so leave it null.
- page = the === PAGE n === marker above the table. Never invent numbers.
"""

agent = Agent(output_type=NativeOutput(SalaryTable), instructions=INSTRUCTIONS)

_LOOKS_LIKE_TABLE = re.compile(r"salar|compensation", re.I)
_MONEY = re.compile(r"\d{1,3}, ?\d{3}")


def _numbers(text: str) -> set[str]:
    """All numbers on a page, with thousands separators removed ("123,922" and "86, 108" -> "123922", "86108")."""
    return set(re.findall(r"\d+", re.sub(r"(\d), ?(?=\d{3}\b)", r"\1", text)))


def salary_pages(pages: list[str]) -> list[int]:
    return [i for i, p in enumerate(pages, 1) if _LOOKS_LIKE_TABLE.search(p) and len(_MONEY.findall(p)) >= 6]


async def extract_salaries(path: Path) -> SalaryTable:
    pages = read_pages(path)
    keep = salary_pages(pages)
    if not keep:
        return SalaryTable(rows=[])
    text = "\n\n".join(f"=== PAGE {i} ===\n{pages[i - 1]}" for i in keep)
    result = await run_logged(agent, text, f"salary_extractor:{path.name}", model=model())
    rows = []
    for r in result.output.rows:  # grounding: the number must be on the cited page
        if r.page not in keep:
            continue
        value = r.average or r.median
        if value and str(value) in _numbers(pages[r.page - 1]):
            rows.append(r)
    return SalaryTable(rows=rows)


REPORTS = Path(__file__).resolve().parent.parent / "data" / "reports"


async def scan_reports(conn: sqlite3.Connection) -> list[str]:
    """Extract salary tables from every analyzed report not scanned yet. Returns one line per report."""
    lines = []
    for report_id, file in db.unscanned_salary_reports(conn):
        path = REPORTS / file
        if not path.exists():
            continue
        try:
            table = await extract_salaries(path)
        except Exception as e:
            lines.append(f"{file}: salary scan failed ({type(e).__name__})")
            continue
        db.save_salaries(conn, report_id, table)
        lines.append(f"{file}: {len(table.rows)} salary rows")
    return lines
