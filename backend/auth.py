"""Basic email + password accounts. Passwords: scrypt with a per-user salt. Login tokens: random, stored hashed,
valid 30 days."""
import hashlib
import hmac
import re
import secrets
import sqlite3

TOKEN_DAYS = 30
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
