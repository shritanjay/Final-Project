"""SQLite storage for extracted employers (data/employers.db)."""
import sqlite3
from pathlib import Path

from backend.models import GeoCheck, MBAProgram, ProgramList, ReportExtraction

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "employers.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    file TEXT UNIQUE NOT NULL,
    school TEXT,
    analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS employers (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    company TEXT NOT NULL,
    role_type TEXT NOT NULL,
    function TEXT NOT NULL,
    location TEXT,
    page INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS geo_checks (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    country TEXT NOT NULL,
    careers_url TEXT,
    hires_in_country TEXT NOT NULL CHECK (hires_in_country IN ('yes', 'no', 'unsure')),
    evidence_url TEXT,
    evidence_text TEXT,
    checked_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (company, country)
);
CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY,
    country TEXT NOT NULL,
    city TEXT NOT NULL DEFAULT '',
    school TEXT NOT NULL,
    program_city TEXT,
    qs_rank TEXT,
    source_url TEXT NOT NULL,
    employment_report_url TEXT,
    checked_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

PROGRAM_CACHE_DAYS = 30  # rankings change yearly

CACHE_DAYS = 7


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def is_analyzed(conn: sqlite3.Connection, file: str) -> bool:
    return conn.execute("SELECT 1 FROM reports WHERE file = ?", (file,)).fetchone() is not None


def save_report(conn: sqlite3.Connection, file: str, extraction: ReportExtraction) -> None:
    """Replaces any previous results for this file."""
    with conn:
        conn.execute("DELETE FROM reports WHERE file = ?", (file,))
        report_id = conn.execute(
            "INSERT INTO reports (file, school) VALUES (?, ?)", (file, extraction.school)
        ).lastrowid
        conn.executemany(
            "INSERT INTO employers (report_id, company, role_type, function, location, page) VALUES (?, ?, ?, ?, ?, ?)",
            [(report_id, e.company, e.role_type, e.function, e.location, e.page) for e in extraction.employers],
        )


def all_employers(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        """SELECT r.file, e.company, e.role_type, e.function, COALESCE(e.location, '-'), e.page
           FROM employers e JOIN reports r ON r.id = e.report_id
           ORDER BY r.file, e.company COLLATE NOCASE"""
    ).fetchall()


def companies_to_verify(conn: sqlite3.Connection, country: str, school: str | None, limit: int) -> tuple[list[str], int]:
    """Distinct companies (optionally from one school's reports) with no geo check in the last CACHE_DAYS.
    Returns (up to `limit` companies, number skipped because they're cached)."""
    params: list = []
    where = ""
    if school:
        where = "WHERE (r.school LIKE ? OR r.file LIKE ?)"
        params += [f"%{school}%", f"%{school}%"]
    companies = [row[0] for row in conn.execute(
        f"SELECT DISTINCT e.company FROM employers e JOIN reports r ON r.id = e.report_id {where} ORDER BY e.company COLLATE NOCASE",
        params,
    )]
    fresh = {row[0] for row in conn.execute(
        "SELECT company FROM geo_checks WHERE country = ? AND checked_at >= datetime('now', ?)",
        (country, f"-{CACHE_DAYS} days"),
    )}
    todo = [c for c in companies if c not in fresh]
    return todo[:limit], len(companies) - len(todo)


def save_geo_check(conn: sqlite3.Connection, company: str, country: str, check: GeoCheck) -> None:
    with conn:
        conn.execute(
            """INSERT INTO geo_checks (company, country, careers_url, hires_in_country, evidence_url, evidence_text, checked_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT (company, country) DO UPDATE SET careers_url = excluded.careers_url,
                 hires_in_country = excluded.hires_in_country, evidence_url = excluded.evidence_url,
                 evidence_text = excluded.evidence_text, checked_at = excluded.checked_at""",
            (company, country, check.careers_url, check.hires_in_country, check.evidence_url, check.evidence_text),
        )


def geo_results(conn: sqlite3.Connection, country: str, school: str | None) -> list[tuple]:
    params: list = [country]
    where = ""
    if school:
        where = "AND (r.school LIKE ? OR r.file LIKE ?)"
        params += [f"%{school}%", f"%{school}%"]
    return conn.execute(
        f"""SELECT DISTINCT g.company, g.hires_in_country, COALESCE(g.careers_url, '-'),
                  COALESCE(g.evidence_url, '-'), date(g.checked_at)
           FROM geo_checks g JOIN employers e ON e.company = g.company JOIN reports r ON r.id = e.report_id
           WHERE g.country = ? {where} ORDER BY g.company COLLATE NOCASE""",
        params,
    ).fetchall()


def cached_programs(conn: sqlite3.Connection, country: str, city: str | None) -> ProgramList | None:
    rows = conn.execute(
        """SELECT school, program_city, qs_rank, source_url, employment_report_url FROM programs
           WHERE country = ? AND city = ? AND checked_at >= datetime('now', ?) ORDER BY id""",
        (country, city or "", f"-{PROGRAM_CACHE_DAYS} days"),
    ).fetchall()
    if not rows:
        return None
    return ProgramList(programs=[
        MBAProgram(school=r[0], city=r[1], qs_rank=r[2], source_url=r[3], employment_report_url=r[4]) for r in rows
    ])


def save_programs(conn: sqlite3.Connection, country: str, city: str | None, programs: ProgramList) -> None:
    with conn:
        conn.execute("DELETE FROM programs WHERE country = ? AND city = ?", (country, city or ""))
        conn.executemany(
            """INSERT INTO programs (country, city, school, program_city, qs_rank, source_url, employment_report_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(country, city or "", p.school, p.city, p.qs_rank, p.source_url, p.employment_report_url)
             for p in programs.programs],
        )


def top_programs_in_city(conn: sqlite3.Connection, country: str, city: str | None, n: int) -> list[str]:
    """Best-ranked cached programs for the location: ones in the city first (Program Scout order), then the rest."""
    rows = conn.execute(
        "SELECT school, COALESCE(program_city, '') FROM programs WHERE country = ? AND city = ? ORDER BY id",
        (country, city or ""),
    ).fetchall()
    in_city = [r[0] for r in rows if city and city.lower() in r[1].lower()]
    rest = [r[0] for r in rows if r[0] not in in_city]
    return (in_city + rest)[:n]


def known_report_url(conn: sqlite3.Connection, school: str) -> str | None:
    row = conn.execute(
        "SELECT employment_report_url FROM programs WHERE school = ? AND employment_report_url IS NOT NULL ORDER BY id DESC",
        (school,),
    ).fetchone()
    return row[0] if row else None


def reports_for_schools(conn: sqlite3.Connection, schools: list[str]) -> list[str]:
    """Analyzed report files matching the given schools (by the school's distinctive first word in file/school name)."""
    files = []
    for school in schools:
        key = school.split(",")[0].split()[0].lower()  # "Rotman School of Management, ..." -> "rotman"
        row = conn.execute(
            "SELECT file FROM reports WHERE lower(file) LIKE ? OR lower(COALESCE(school, '')) LIKE ? ORDER BY analyzed_at DESC",
            (f"%{key}%", f"%{key}%"),
        ).fetchone()
        if row and row[0] not in files:
            files.append(row[0])
    return files
