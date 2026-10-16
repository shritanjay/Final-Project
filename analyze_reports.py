"""Run the Report Analyst on every PDF in data/reports/ and print the results.

    python analyze_reports.py           # skips PDFs already in the database (saves tokens)
    python analyze_reports.py --force   # re-analyze everything
"""
import asyncio
import sys
from pathlib import Path

from backend import db
from backend.report_analyst import analyze_report

REPORTS = Path(__file__).resolve().parent / "data" / "reports"


def print_table(rows: list[tuple], headers=("Report", "Company", "Type", "Function", "Location", "Page")) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = lambda r: "  ".join(str(x).ljust(w) for x, w in zip(r, widths))
    print(line(headers))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))
    print(f"\n{len(rows)} rows")


async def main(force: bool) -> None:
    pdfs = sorted(REPORTS.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {REPORTS}")
        return
    conn = db.connect()
    for pdf in pdfs:
        if not force and db.is_analyzed(conn, pdf.name):
            print(f"skip   {pdf.name} (already analyzed; --force to redo)")
            continue
        try:
            extraction, rejected = await analyze_report(pdf)
        except Exception as e:
            print(f"error  {pdf.name}: {e}")
            continue
        db.save_report(conn, pdf.name, extraction)
        print(f"done   {pdf.name}: {len(extraction.employers)} employers", end="")
        print(f", dropped {len(rejected)} not found on cited page: {[e.company for e in rejected]}" if rejected else "")
    print()
    print_table(db.all_employers(conn))


if __name__ == "__main__":
    asyncio.run(main("--force" in sys.argv))
