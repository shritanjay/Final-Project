"""FastAPI app: chat with the boss agent and upload employment report PDFs."""
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend import auth, boss, db, emailer

app = FastAPI(title="MBA Employer Finder")
MAX_UPLOAD_MB = 25


bearer = HTTPBearer(auto_error=False)


class User(BaseModel):
    id: int
    email: str


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    row = auth.user_for_token(db.connect(), creds.credentials) if creds else None
    if not row:
        raise HTTPException(401, "Please log in.")
    return User(id=row[0], email=row[1])


class Credentials(BaseModel):
    email: str
    password: str


class EmailBody(BaseModel):
    email: str


class ResetBody(BaseModel):
    token: str
    password: str


class TokenBody(BaseModel):
    token: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str
    country: str | None
    report_source: str | None


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/signup")
def signup(body: Credentials):
    conn = db.connect()
    try:
        user_id = auth.sign_up(conn, body.email, body.password)
        emailer.send_verification(body.email.strip().lower(), auth.make_email_token(conn, user_id, "verify"))
        return {"token": auth.log_in(conn, body.email, body.password)}
    except auth.AuthError as e:
        raise HTTPException(400, str(e))


@app.post("/api/login")
def login(body: Credentials):
    try:
        return {"token": auth.log_in(db.connect(), body.email, body.password)}
    except auth.AuthError as e:
        raise HTTPException(401, str(e))


@app.post("/api/logout")
def logout(creds: HTTPAuthorizationCredentials | None = Depends(bearer), user: User = Depends(current_user)):
    auth.log_out(db.connect(), creds.credentials)
    boss.reset_chat(user.id)
    return {"ok": True}


@app.post("/api/verify-email")
def verify_email(body: TokenBody):
    try:
        auth.verify_email(db.connect(), body.token)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/verify-email/resend")
def resend_verification(user: User = Depends(current_user)):
    conn = db.connect()
    if not auth.is_verified(conn, user.id):
        emailer.send_verification(user.email, auth.make_email_token(conn, user.id, "verify"))
    return {"ok": True}


@app.post("/api/password/forgot")
def forgot_password(body: EmailBody):
    """Always returns ok, so the response doesn't reveal which emails have accounts."""
    conn = db.connect()
    user_id = auth.user_id_for_email(conn, body.email)
    if user_id:
        emailer.send_password_reset(body.email.strip().lower(), auth.make_email_token(conn, user_id, "reset"))
    return {"ok": True}


@app.post("/api/password/reset")
def reset_password(body: ResetBody):
    try:
        auth.reset_password(db.connect(), body.token, body.password)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    conn = db.connect()
    country, city, roles = db.get_prefs(conn, user.id)
    return {"email": user.email, "email_verified": auth.is_verified(conn, user.id),
            "country": country, "city": city, "target_roles": roles}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, user: User = Depends(current_user)):
    session, answer = await boss.chat(user.id, body.message)
    return ChatResponse(answer=answer, country=session.country, report_source=session.report_source)


@app.get("/api/chat/history")
def chat_history(user: User = Depends(current_user)):
    return boss.chat_transcript(user.id)


@app.post("/api/chat/new")
def chat_new(user: User = Depends(current_user)):
    boss.new_chat(user.id)
    return {"ok": True}


@app.post("/api/upload")
async def upload(file: UploadFile, user: User = Depends(current_user)):
    data = await file.read()
    if not (file.filename or "").lower().endswith(".pdf") or not data.startswith(b"%PDF"):
        raise HTTPException(400, "Please upload a PDF.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"Max {MAX_UPLOAD_MB} MB.")
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in file.filename)
    boss.REPORTS.mkdir(parents=True, exist_ok=True)
    (boss.REPORTS / name).write_bytes(data)
    return {"saved": name}


@app.get("/api/tracker")
def tracker(user: User = Depends(current_user)):
    cols = ("company", "status", "careers_url", "notes", "updated")
    return [dict(zip(cols, r)) for r in db.tracker_rows(db.connect(), f"user:{user.id}")]


class TrackerUpdate(BaseModel):
    company: str
    status: Literal["interested", "applied", "interviewing", "offer", "rejected"] | None = None
    notes: str | None = None


@app.patch("/api/tracker")
def tracker_update(body: TrackerUpdate, user: User = Depends(current_user)):
    if not db.tracker_update(db.connect(), f"user:{user.id}", body.company, body.status, body.notes):
        raise HTTPException(404, "Not in your tracker.")
    return {"ok": True}


@app.delete("/api/tracker/{company}")
def tracker_delete(company: str, user: User = Depends(current_user)):
    if not db.tracker_remove(db.connect(), f"user:{user.id}", company):
        raise HTTPException(404, "Not in your tracker.")
    return {"ok": True}


@app.get("/api/postings")
def postings(user: User = Depends(current_user)):
    """Active postings for the user's tracked companies in their saved city/country."""
    country, city, _ = db.get_prefs(db.connect(), user.id)
    location = f"{city + ', ' if city else ''}{country}"
    cols = ("company", "title", "location", "level", "url", "first_seen", "location_flexible")
    return [dict(zip(cols, r)) for r in db.postings_for_student(db.connect(), f"user:{user.id}", location)]


# Serve the built React app (npm run build -> frontend/dist) from the same server, if present.
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
