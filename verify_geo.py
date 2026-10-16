"""Run the Geo Verifier on companies in the database and print the results.

    python verify_geo.py --school Rotman                 # Canada by default
    python verify_geo.py --country "United States" --limit 20
Companies checked for the same country in the last 7 days are skipped (cached). Max 50 per run.
"""
import argparse
import asyncio

from analyze_reports import print_table
from backend import db
from backend.geo_verifier import verify

MAX_PER_RUN = 50


async def main(country: str, school: str | None, limit: int) -> None:
    conn = db.connect()
    todo, cached = db.companies_to_verify(conn, country, school, min(limit, MAX_PER_RUN))
    print(f"{len(todo)} to check, {cached} cached (checked in last {db.CACHE_DAYS} days)\n")
    for company in todo:
        try:
            check = await verify(company, country)
        except Exception as e:
            print(f"error  {company}: {e}")
            continue
        db.save_geo_check(conn, company, country, check)
        print(f"{check.hires_in_country:<6} {company}")
    print()
    print_table(db.geo_results(conn, country, school), ("Company", f"Hires in {country}", "Careers URL", "Evidence", "Checked"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="Canada")
    ap.add_argument("--school", help="only companies from reports whose school or filename matches")
    ap.add_argument("--limit", type=int, default=MAX_PER_RUN)
    a = ap.parse_args()
    asyncio.run(main(a.country, a.school, a.limit))
