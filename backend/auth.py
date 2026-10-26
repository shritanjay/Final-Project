"""Email + password accounts, email verification, and password reset. Passwords: scrypt with a per-user salt. Login tokens: random, stored hashed,
valid 30 days."""
import hashlib
import hmac
import re
import secrets
import sqlite3

TOKEN_DAYS = 30
EMAIL_TOKEN_HOURS = {"verify": 48, "reset": 1}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    pass


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign_up(conn: sqlite3.Connection, email: str, password: str) -> int:
    email = email.strip().lower()
    if not _EMAIL.match(email):
        raise AuthError("Enter a valid email.")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    salt = secrets.token_bytes(16)
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, f"{salt.hex()}${_hash_password(password, salt)}"),
            )
    except sqlite3.IntegrityError:
        raise AuthError("An account with that email already exists.")
    with conn:  # SQLite can reuse ids of deleted accounts: drop anything left keyed to this id
        conn.execute("DELETE FROM tracker WHERE student = ?", (f"user:{cur.lastrowid}",))
    return cur.lastrowid


def log_in(conn: sqlite3.Connection, email: str, password: str) -> str:
    """Returns a new login token."""
    row = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    if row:
        salt, stored = row[1].split("$")
        ok = hmac.compare_digest(_hash_password(password, bytes.fromhex(salt)), stored)
    else:
        _hash_password(password, b"0" * 16)  # same work either way, so timing doesn't reveal which emails exist
        ok = False
    if not ok:
        raise AuthError("Wrong email or password.")
    token = secrets.token_urlsafe(32)
    with conn:
        conn.execute("DELETE FROM auth_tokens WHERE expires_at < datetime('now')")
        conn.execute(
            "INSERT INTO auth_tokens (token_hash, user_id, expires_at) VALUES (?, ?, datetime('now', ?))",
            (_token_hash(token), row[0], f"+{TOKEN_DAYS} days"),
        )
    return token


def user_for_token(conn: sqlite3.Connection, token: str) -> tuple[int, str] | None:
    """(user_id, email) if the token is valid and not expired."""
    return conn.execute(
        """SELECT u.id, u.email FROM auth_tokens t JOIN users u ON u.id = t.user_id
           WHERE t.token_hash = ? AND t.expires_at > datetime('now')""",
        (_token_hash(token),),
    ).fetchone()


def log_out(conn: sqlite3.Connection, token: str) -> None:
    with conn:
        conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (_token_hash(token),))


def make_email_token(conn: sqlite3.Connection, user_id: int, purpose: str) -> str:
    """One-time token for an email link. Older tokens of the same purpose for this user are cancelled."""
    token = secrets.token_urlsafe(32)
    with conn:
        conn.execute("DELETE FROM email_tokens WHERE (user_id = ? AND purpose = ?) OR expires_at < datetime('now')",
                     (user_id, purpose))
        conn.execute(
            "INSERT INTO email_tokens (token_hash, user_id, purpose, expires_at) VALUES (?, ?, ?, datetime('now', ?))",
            (_token_hash(token), user_id, purpose, f"+{EMAIL_TOKEN_HOURS[purpose]} hours"),
        )
    return token


def _use_email_token(conn: sqlite3.Connection, token: str, purpose: str) -> int:
    row = conn.execute(
        "SELECT user_id FROM email_tokens WHERE token_hash = ? AND purpose = ? AND expires_at > datetime('now')",
        (_token_hash(token), purpose),
    ).fetchone()
    if not row:
        raise AuthError("This link is invalid or has expired.")
    conn.execute("DELETE FROM email_tokens WHERE token_hash = ?", (_token_hash(token),))
    return row[0]


def verify_email(conn: sqlite3.Connection, token: str) -> None:
    with conn:
        user_id = _use_email_token(conn, token, "verify")
        conn.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))


def user_id_for_email(conn: sqlite3.Connection, email: str) -> int | None:
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    return row[0] if row else None


def is_verified(conn: sqlite3.Connection, user_id: int) -> bool:
    return bool(conn.execute("SELECT email_verified FROM users WHERE id = ?", (user_id,)).fetchone()[0])


def reset_password(conn: sqlite3.Connection, token: str, new_password: str) -> None:
    """Sets the new password and logs the user out everywhere. Reset links also prove the email, so mark it verified."""
    if len(new_password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    salt = secrets.token_bytes(16)
    with conn:
        user_id = _use_email_token(conn, token, "reset")
        conn.execute("UPDATE users SET password_hash = ?, email_verified = 1 WHERE id = ?",
                     (f"{salt.hex()}${_hash_password(new_password, salt)}", user_id))
        conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
