"""SQLite storage for extracted employers (data/employers.db)."""
import sqlite3
from pathlib import Path

from backend.models import ReportExtraction

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
"""


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
