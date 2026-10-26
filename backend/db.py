"""SQLite storage (data/employers.db): reports, employers, research, users, trackers, postings."""
import json
import sqlite3
from pathlib import Path

from backend.models import CompanyResearch, GeoCheck, PostingScan, SalaryTable, MBAProgram, ProgramList, ReportExtraction

DATA = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA / "employers.db"   # working database (created on first run, not in git)
DEMO_DB = DATA / "demo.db"        # small test dataset in the repo: Toronto reports already analyzed, no user data

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
CREATE TABLE IF NOT EXISTS company_research (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    country TEXT NOT NULL,
    question TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL,  -- CompanyResearch JSON
    checked_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (company, country, question)
);
CREATE TABLE IF NOT EXISTS report_salaries (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    hire_type TEXT NOT NULL,
    basis TEXT NOT NULL,
    label TEXT NOT NULL,
    category TEXT NOT NULL,
    average INTEGER,
    median INTEGER,
    low INTEGER,
    high INTEGER,
    range_type TEXT,
    period TEXT NOT NULL,
    currency TEXT,
    page INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS salary_scans (
    report_id INTEGER PRIMARY KEY REFERENCES reports(id) ON DELETE CASCADE,
    scanned_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS job_postings (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    location_key TEXT NOT NULL,  -- "city, country" searched
    title TEXT NOT NULL,
    location TEXT,
    level TEXT NOT NULL,
    url TEXT NOT NULL,
    posted TEXT,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (company, location_key, url)
);
CREATE TABLE IF NOT EXISTS posting_scans (
    company TEXT NOT NULL,
    location_key TEXT NOT NULL,
    careers_url TEXT,
    note TEXT,
    scanned_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (company, location_key)
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash TEXT PRIMARY KEY,  -- sha256 of the token; the raw token is never stored
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS email_tokens (
    token_hash TEXT PRIMARY KEY,  -- sha256; raw token only goes out in the email
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('verify', 'reset')),
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    country TEXT,
    city TEXT,
    target_roles TEXT NOT NULL DEFAULT '[]',  -- JSON list
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS chat_history (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    messages TEXT NOT NULL,  -- PydanticAI message list as JSON
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS employer_views (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    location TEXT NOT NULL,
    overview TEXT,
    files TEXT NOT NULL,  -- JSON list of report files used
    rows TEXT NOT NULL,   -- JSON list of employer rows for the UI table
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS searches (  -- one saved search per location; a user can have several
    id INTEGER PRIMARY KEY AUTOINCREMENT,  -- AUTOINCREMENT: ids are never reused
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    country TEXT,
    city TEXT,
    stage INTEGER NOT NULL DEFAULT 0,      -- bitmask of completed guided-path steps
    messages TEXT,                         -- PydanticAI chat history JSON
    actions TEXT NOT NULL DEFAULT '{}',    -- {transcript index: [action buttons]} for assistant messages
    emp_overview TEXT,
    emp_files TEXT,
    emp_rows TEXT,                         -- employer table rows JSON
    emp_created_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tracker (
    id INTEGER PRIMARY KEY,
    student TEXT NOT NULL,
    company TEXT NOT NULL,
    careers_url TEXT,
    status TEXT NOT NULL DEFAULT 'interested',
    notes TEXT,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student, company)
);
"""

PROGRAM_CACHE_DAYS = 30  # rankings change yearly
RESEARCH_CACHE_DAYS = 30
TRACKER_MAX = 15
POSTING_CACHE_HOURS = 24
TRACKER_STATUSES = ("interested", "applied", "interviewing", "offer", "rejected")

CACHE_DAYS = 7


MIGRATIONS = [  # columns added after tables were first created
    "ALTER TABLE job_postings ADD COLUMN location_flexible INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE posting_scans ADD COLUMN roles TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE user_prefs ADD COLUMN stage INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE employers ADD COLUMN evidence TEXT NOT NULL DEFAULT 'hired'",
    "ALTER TABLE user_prefs ADD COLUMN active_search INTEGER",
    "ALTER TABLE job_postings ADD COLUMN manual INTEGER NOT NULL DEFAULT 0",
]


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists() and DEMO_DB.exists():
        import shutil
        shutil.copy(DEMO_DB, DB_PATH)  # first run from a fresh clone: start from the demo data
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # already applied
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
            """INSERT INTO employers (report_id, company, role_type, function, location, page, evidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(report_id, e.company, e.role_type, e.function, e.location, e.page, e.evidence) for e in extraction.employers],
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


def program_city(conn: sqlite3.Connection, school: str) -> str | None:
    row = conn.execute("SELECT program_city FROM programs WHERE school = ? ORDER BY id DESC", (school,)).fetchone()
    return row[0] if row else None


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


def cached_research(conn: sqlite3.Connection, company: str, country: str, question: str | None) -> CompanyResearch | None:
    row = conn.execute(
        "SELECT data FROM company_research WHERE company = ? AND country = ? AND question = ? AND checked_at >= datetime('now', ?)",
        (company, country, question or "", f"-{RESEARCH_CACHE_DAYS} days"),
    ).fetchone()
    return CompanyResearch.model_validate_json(row[0]) if row else None


def save_research(conn: sqlite3.Connection, country: str, question: str | None, r: CompanyResearch) -> None:
    with conn:
        conn.execute(
            """INSERT INTO company_research (company, country, question, data, checked_at) VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT (company, country, question) DO UPDATE SET data = excluded.data, checked_at = excluded.checked_at""",
            (r.company, country, question or "", r.model_dump_json()),
        )


def tracker_rows(conn: sqlite3.Connection, student: str) -> list[tuple]:
    return conn.execute(
        "SELECT company, status, COALESCE(careers_url, '-'), COALESCE(notes, ''), date(updated_at) FROM tracker WHERE student = ? ORDER BY id",
        (student,),
    ).fetchall()


def tracker_add(conn: sqlite3.Connection, student: str, company: str, careers_url: str | None) -> bool:
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO tracker (student, company, careers_url) VALUES (?, ?, ?)", (student, company, careers_url)
        )
    return cur.rowcount == 1


def tracker_update(conn: sqlite3.Connection, student: str, company: str, status: str | None, notes: str | None) -> bool:
    with conn:
        cur = conn.execute(
            """UPDATE tracker SET status = COALESCE(?, status), notes = COALESCE(?, notes), updated_at = datetime('now')
               WHERE student = ? AND lower(company) = lower(?)""",
            (status, notes, student, company),
        )
    return cur.rowcount == 1


def tracker_remove(conn: sqlite3.Connection, student: str, company: str) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM tracker WHERE student = ? AND lower(company) = lower(?)", (student, company))
    return cur.rowcount == 1


def unscanned_salary_reports(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return conn.execute(
        "SELECT id, file FROM reports WHERE id NOT IN (SELECT report_id FROM salary_scans)"
    ).fetchall()


def save_salaries(conn: sqlite3.Connection, report_id: int, table: SalaryTable) -> None:
    with conn:
        conn.execute("DELETE FROM report_salaries WHERE report_id = ?", (report_id,))
        conn.executemany(
            """INSERT INTO report_salaries (report_id, hire_type, basis, label, category, average, median, low, high,
               range_type, period, currency, page) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(report_id, r.hire_type, r.basis, r.label, r.category, r.average, r.median, r.low, r.high,
              r.range_type, r.period, r.currency, r.page) for r in table.rows],
        )
        conn.execute("INSERT OR REPLACE INTO salary_scans (report_id) VALUES (?)", (report_id,))


def company_category(conn: sqlite3.Connection, company: str) -> str | None:
    """Most common function tag the Report Analyst gave this company."""
    row = conn.execute(
        "SELECT function, COUNT(*) n FROM employers WHERE lower(company) = lower(?) GROUP BY function ORDER BY n DESC",
        (company,),
    ).fetchone()
    return row[0] if row else None


def report_salaries_for(conn: sqlite3.Connection, category: str) -> list[tuple]:
    """Full-time annual salary rows for a category, one per report: by-industry rows preferred over by-function."""
    rows = conn.execute(
        """SELECT COALESCE(r.school, r.file), s.label, s.average, s.median, s.low, s.high, s.range_type, s.currency,
                  s.page, s.basis, r.file
           FROM report_salaries s JOIN reports r ON r.id = s.report_id
           WHERE s.category = ? AND s.hire_type = 'full-time' AND s.period = 'annual'
           ORDER BY r.file, CASE s.basis WHEN 'industry' THEN 0 ELSE 1 END""",
        (category,),
    ).fetchall()
    best = {}
    for row in rows:
        best.setdefault(row[10], row)  # first (industry-based) row per report
    return list(best.values())


def recently_scanned(conn: sqlite3.Connection, company: str, location_key: str, roles: str) -> bool:
    """Scanned in the last POSTING_CACHE_HOURS for the same target roles."""
    return conn.execute(
        """SELECT 1 FROM posting_scans WHERE company = ? AND location_key = ? AND roles = ?
           AND scanned_at >= datetime('now', ?)""",
        (company, location_key, roles, f"-{POSTING_CACHE_HOURS} hours"),
    ).fetchone() is not None


def save_posting_scan(conn: sqlite3.Connection, company: str, location_key: str, scan: PostingScan, roles: str) -> int:
    """Upsert postings; mark ones not seen this time inactive. Returns number of NEW postings."""
    with conn:
        before = {r[0] for r in conn.execute(
            "SELECT url FROM job_postings WHERE company = ? AND location_key = ?", (company, location_key))}
        conn.execute("UPDATE job_postings SET active = 0 WHERE company = ? AND location_key = ? AND manual = 0",
                     (company, location_key))  # postings the student added by hand stay
        for p in scan.postings:
            conn.execute(
                """INSERT INTO job_postings (company, location_key, title, location, level, url, posted, location_flexible)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (company, location_key, url) DO UPDATE SET title = excluded.title,
                     location = excluded.location, level = excluded.level, posted = excluded.posted,
                     location_flexible = excluded.location_flexible, last_seen = datetime('now'), active = 1""",
                (company, location_key, p.title, p.location, p.level, p.url, p.posted, int(p.location_flexible)),
            )
        conn.execute(
            """INSERT INTO posting_scans (company, location_key, careers_url, note, roles, scanned_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT (company, location_key) DO UPDATE SET careers_url = excluded.careers_url,
                 note = excluded.note, roles = excluded.roles, scanned_at = excluded.scanned_at""",
            (company, location_key, scan.careers_url, scan.note, roles),
        )
    return len({p.url for p in scan.postings} - before)


def set_tracker_careers_url(conn: sqlite3.Connection, student: str, company: str, url: str) -> None:
    with conn:
        conn.execute("UPDATE tracker SET careers_url = ? WHERE student = ? AND company = ?", (url, student, company))


def postings_for_student(conn: sqlite3.Connection, student: str, location_key: str) -> list[tuple]:
    """Active postings for the student's tracked companies: company, title, location, level, url, first_seen, flexible."""
    return conn.execute(
        """SELECT p.company, p.title, COALESCE(p.location, ''), p.level, p.url, date(p.first_seen), p.location_flexible
           FROM job_postings p JOIN tracker t ON t.company = p.company AND t.student = ?
           WHERE p.location_key = ? AND p.active = 1 ORDER BY t.id, p.level, p.title""",
        (student, location_key),
    ).fetchall()


def scan_notes(conn: sqlite3.Connection, student: str, location_key: str) -> list[tuple]:
    return conn.execute(
        """SELECT s.company, s.careers_url, s.note, s.scanned_at FROM posting_scans s
           JOIN tracker t ON t.company = s.company AND t.student = ? WHERE s.location_key = ? ORDER BY t.id""",
        (student, location_key),
    ).fetchall()


def get_prefs(conn: sqlite3.Connection, user_id: int) -> tuple[str | None, str | None, list[str], int]:
    """(country, city, target roles, guided-path stage)."""
    row = conn.execute("SELECT country, city, target_roles, stage FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return (row[0], row[1], json.loads(row[2]), row[3]) if row else (None, None, [], 0)


def save_prefs(conn: sqlite3.Connection, user_id: int, country: str | None, city: str | None, roles: list[str],
               stage: int = 0) -> None:
    with conn:
        conn.execute(
            """INSERT INTO user_prefs (user_id, country, city, target_roles, stage, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT (user_id) DO UPDATE SET country = excluded.country, city = excluded.city,
                 target_roles = excluded.target_roles, stage = excluded.stage, updated_at = excluded.updated_at""",
            (user_id, country, city, json.dumps(roles), stage),
        )


def get_chat_history(conn: sqlite3.Connection, user_id: int) -> str | None:
    row = conn.execute("SELECT messages FROM chat_history WHERE user_id = ?", (user_id,)).fetchone()
    return row[0] if row else None


def save_chat_history(conn: sqlite3.Connection, user_id: int, messages_json: str) -> None:
    with conn:
        conn.execute(
            """INSERT INTO chat_history (user_id, messages, updated_at) VALUES (?, ?, datetime('now'))
               ON CONFLICT (user_id) DO UPDATE SET messages = excluded.messages, updated_at = excluded.updated_at""",
            (user_id, messages_json),
        )


def clear_chat_history(conn: sqlite3.Connection, user_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))


def save_employer_view(conn: sqlite3.Connection, user_id: int, location: str, overview: str, files: list[str],
                       rows: list[dict]) -> None:
    with conn:
        conn.execute(
            """INSERT INTO employer_views (user_id, location, overview, files, rows, created_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT (user_id) DO UPDATE SET location = excluded.location, overview = excluded.overview,
                 files = excluded.files, rows = excluded.rows, created_at = excluded.created_at""",
            (user_id, location, overview, json.dumps(files), json.dumps(rows)),
        )


def get_employer_view(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT location, overview, files, rows, created_at FROM employer_views WHERE user_id = ?",
                       (user_id,)).fetchone()
    if not row:
        return None
    return {"location": row[0], "overview": row[1], "files": json.loads(row[2]), "rows": json.loads(row[3]),
            "created_at": row[4]}


def report_school_counts(conn: sqlite3.Connection, files: list[str]) -> list[tuple[str, int, int]]:
    """(school, employers listed, of which confirmed hires) per report."""
    marks = ",".join("?" * len(files))
    return conn.execute(
        f"""SELECT COALESCE(r.school, r.file), COUNT(*), SUM(e.evidence = 'hired')
            FROM employers e JOIN reports r ON r.id = e.report_id
            WHERE r.file IN ({marks}) GROUP BY r.id ORDER BY 2 DESC""",
        files,
    ).fetchall()


def clear_employer_view(conn: sqlite3.Connection, user_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM employer_views WHERE user_id = ?", (user_id,))


def tracker_clear(conn: sqlite3.Connection, student: str) -> None:
    with conn:
        conn.execute("DELETE FROM tracker WHERE student = ?", (student,))


def user_stamp(conn: sqlite3.Connection, user_id: int) -> str | None:
    """Identifies one specific account even if SQLite later reuses its id."""
    row = conn.execute("SELECT created_at, email FROM users WHERE id = ?", (user_id,)).fetchone()
    return f"{user_id}:{row[0]}:{row[1]}" if row else None



# ---------- saved searches ----------
# Everything a student builds for one location lives in a search: location, progress, chat, employer table.
# The tracker is keyed by scope(search id). user_prefs.active_search remembers which one is open.

def scope(search_id: int) -> str:
    """Tracker key for a search."""
    return f"search:{search_id}"


def _search_label(country: str | None, city: str | None) -> str:
    return f"{city + ', ' if city else ''}{country}" if country else "New search"


def create_search(conn: sqlite3.Connection, user_id: int, country: str | None = None, city: str | None = None,
                  stage: int = 0) -> int:
    with conn:
        sid = conn.execute("INSERT INTO searches (user_id, country, city, stage) VALUES (?, ?, ?, ?)",
                           (user_id, country, city, stage)).lastrowid
        conn.execute("INSERT INTO user_prefs (user_id, active_search) VALUES (?, ?) "
                     "ON CONFLICT (user_id) DO UPDATE SET active_search = excluded.active_search", (user_id, sid))
    return sid


def _migrate_legacy(conn: sqlite3.Connection, user_id: int) -> int:
    """First load after saved searches were added: move the user's single search into a saved search."""
    country, city, _, stage = get_prefs(conn, user_id)
    sid = create_search(conn, user_id, country, city, stage)
    with conn:
        row = conn.execute("SELECT messages FROM chat_history WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            conn.execute("UPDATE searches SET messages = ? WHERE id = ?", (row[0], sid))
        view = conn.execute("SELECT location, overview, files, rows, created_at FROM employer_views WHERE user_id = ?",
                            (user_id,)).fetchone()
        if view:
            conn.execute("UPDATE searches SET emp_overview = ?, emp_files = ?, emp_rows = ?, emp_created_at = ? WHERE id = ?",
                         (view[1], view[2], view[3], view[4], sid))
        conn.execute("UPDATE tracker SET student = ? WHERE student = ?", (scope(sid), f"user:{user_id}"))
    return sid


def active_search_id(conn: sqlite3.Connection, user_id: int) -> int:
    """The search the user has open (creating or migrating one if needed)."""
    row = conn.execute(
        """SELECT s.id FROM user_prefs p JOIN searches s ON s.id = p.active_search AND s.user_id = p.user_id
           WHERE p.user_id = ?""", (user_id,)).fetchone()
    if row:
        return row[0]
    latest = conn.execute("SELECT id FROM searches WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
                          (user_id,)).fetchone()
    if latest:
        set_active_search(conn, user_id, latest[0])
        return latest[0]
    return _migrate_legacy(conn, user_id)


def set_active_search(conn: sqlite3.Connection, user_id: int, search_id: int) -> bool:
    if not conn.execute("SELECT 1 FROM searches WHERE id = ? AND user_id = ?", (search_id, user_id)).fetchone():
        return False
    with conn:
        conn.execute("INSERT INTO user_prefs (user_id, active_search) VALUES (?, ?) "
                     "ON CONFLICT (user_id) DO UPDATE SET active_search = excluded.active_search", (user_id, search_id))
    return True


def get_search(conn: sqlite3.Connection, search_id: int) -> dict:
    r = conn.execute("SELECT id, country, city, stage, messages, actions FROM searches WHERE id = ?", (search_id,)).fetchone()
    return {"id": r[0], "country": r[1], "city": r[2], "stage": r[3], "messages": r[4], "actions": json.loads(r[5] or "{}")}


def list_searches(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT s.id, s.country, s.city, s.stage, s.updated_at,
                  (SELECT COUNT(*) FROM tracker t WHERE t.student = 'search:' || s.id)
           FROM searches s WHERE s.user_id = ? ORDER BY s.updated_at DESC, s.id DESC""", (user_id,)).fetchall()
    return [{"id": r[0], "country": r[1], "city": r[2], "label": _search_label(r[1], r[2]), "stage": r[3],
             "updated_at": r[4], "tracked": r[5]} for r in rows]


def update_search(conn: sqlite3.Connection, search_id: int, country: str | None, city: str | None, stage: int) -> None:
    with conn:
        conn.execute("UPDATE searches SET country = ?, city = ?, stage = ?, updated_at = datetime('now') WHERE id = ?",
                     (country, city, stage, search_id))


def save_search_chat(conn: sqlite3.Connection, search_id: int, messages_json: str | None, actions: dict) -> None:
    with conn:
        conn.execute("UPDATE searches SET messages = ?, actions = ?, updated_at = datetime('now') WHERE id = ?",
                     (messages_json, json.dumps(actions), search_id))


def save_search_employers(conn: sqlite3.Connection, search_id: int, overview: str, files: list[str], rows: list[dict]) -> None:
    with conn:
        conn.execute("""UPDATE searches SET emp_overview = ?, emp_files = ?, emp_rows = ?, emp_created_at = datetime('now'),
                        updated_at = datetime('now') WHERE id = ?""", (overview, json.dumps(files), json.dumps(rows), search_id))


def get_search_employers(conn: sqlite3.Connection, search_id: int) -> dict | None:
    r = conn.execute("SELECT country, city, emp_overview, emp_files, emp_rows, emp_created_at FROM searches WHERE id = ?",
                     (search_id,)).fetchone()
    if not r or not r[4]:
        return None
    return {"location": r[1] or r[0], "overview": r[2], "files": json.loads(r[3]), "rows": json.loads(r[4]), "created_at": r[5]}


def delete_search(conn: sqlite3.Connection, user_id: int, search_id: int) -> bool:
    with conn:
        n = conn.execute("DELETE FROM searches WHERE id = ? AND user_id = ?", (search_id, user_id)).rowcount
        conn.execute("DELETE FROM tracker WHERE student = ?", (scope(search_id),))
    return bool(n)


def latest_research(conn: sqlite3.Connection, company: str, country: str) -> CompanyResearch | None:
    row = conn.execute("SELECT data FROM company_research WHERE lower(company) = lower(?) AND country = ? "
                       "ORDER BY checked_at DESC", (company, country)).fetchone()
    return CompanyResearch.model_validate_json(row[0]) if row else None


def postings_by_company(conn: sqlite3.Connection, company: str, location_key: str) -> list[dict]:
    cols = ("title", "location", "level", "url", "first_seen", "location_flexible", "manual")
    return [dict(zip(cols, r)) for r in conn.execute(
        """SELECT title, COALESCE(location, ''), level, url, date(first_seen), location_flexible, manual FROM job_postings
           WHERE company = ? AND location_key = ? AND active = 1
           ORDER BY CASE level WHEN 'mba' THEN 0 WHEN 'internship' THEN 1 ELSE 2 END, title""",
        (company, location_key))]


def last_scan(conn: sqlite3.Connection, company: str, location_key: str) -> tuple[str | None, str | None]:
    """(note, scanned_at) of the latest job-posting check for a company in a location."""
    row = conn.execute("SELECT note, scanned_at FROM posting_scans WHERE company = ? AND location_key = ?",
                       (company, location_key)).fetchone()
    return (row[0], row[1]) if row else (None, None)


def add_manual_posting(conn: sqlite3.Connection, company: str, location_key: str, title: str, url: str, level: str) -> None:
    """A job link the student found themselves; never hidden by later automatic checks."""
    with conn:
        conn.execute(
            """INSERT INTO job_postings (company, location_key, title, location, level, url, manual)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT (company, location_key, url) DO UPDATE SET title = excluded.title, level = excluded.level,
                 active = 1, manual = 1, last_seen = datetime('now')""",
            (company, location_key, title, location_key, level, url),
        )
