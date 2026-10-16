"""SQLite storage for extracted employers (data/employers.db)."""
import sqlite3
from pathlib import Path

from backend.models import GeoCheck, ReportExtraction

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
"""

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
