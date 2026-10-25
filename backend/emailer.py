"""Email sending over SMTP (any provider: Gmail app password, Outlook, SendGrid/Mailgun SMTP, ...).

Configure in .env: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, EMAIL_FROM.
If SMTP_HOST isn't set, emails are written to logs/outbox/ instead (dev mode), so sign-up and reset still work locally.
"""
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

OUTBOX = Path(__file__).resolve().parent.parent / "logs" / "outbox"


def frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")


def send_email(to: str, subject: str, body: str) -> str:
    """Returns "smtp" or the outbox file path (dev mode)."""
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("EMAIL_FROM") or os.getenv("SMTP_USER") or "no-reply@localhost"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg.set_content(body)
    if not host:
        OUTBOX.mkdir(parents=True, exist_ok=True)
        path = OUTBOX / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{to.replace('@', '_at_')}.eml"
        path.write_text(msg.as_string())
        return str(path)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=20) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if os.getenv("SMTP_USER"):
            smtp.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(msg)
    return "smtp"


def send_verification(to: str, token: str) -> str:
    link = f"{frontend_url()}/#/verify?token={token}"
    return send_email(to, "Verify your email: MBA Career Scout",
                      f"Welcome to MBA Career Scout!\n\nConfirm your email by opening this link (valid 48 hours):\n{link}\n\n"
                      "If you didn't sign up, you can ignore this email.")


def send_password_reset(to: str, token: str) -> str:
    link = f"{frontend_url()}/#/reset?token={token}"
    return send_email(to, "Reset your password: MBA Career Scout",
                      f"Someone asked to reset the password for this account.\n\nSet a new password here (valid 1 hour):\n{link}\n\n"
                      "If it wasn't you, ignore this email; your password won't change.")
