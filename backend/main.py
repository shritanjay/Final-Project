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


def open_search(user: User) -> tuple[int, str, dict]:
    """(search id, tracker scope key, search row) of the user's open search."""
    conn = db.connect()
    sid = db.active_search_id(conn, user.id)
    return sid, db.scope(sid), db.get_search(conn, sid)


def location_key(search: dict) -> str:
    return f"{search['city'] + ', ' if search['city'] else ''}{search['country']}"


class ChatResponse(BaseModel):
    answer: str
    country: str | None
    actions: list[dict] = []  # buttons to show under the reply


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
    sid, _, search = open_search(user)
    return {"email": user.email, "email_verified": auth.is_verified(conn, user.id), "search_id": sid,
            "country": search["country"], "city": search["city"], "steps": boss.STEPS,
            "steps_done": boss.steps_done(search["stage"]), "next_step": boss.next_step(search["stage"])}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, user: User = Depends(current_user)):
    session, answer, actions = await boss.chat(user.id, body.message)
    return ChatResponse(answer=answer, country=session.country, actions=actions)


@app.get("/api/chat/history")
def chat_history(user: User = Depends(current_user)):
    return boss.chat_transcript(user.id)


class NewChat(BaseModel):
    new_search: bool = False  # open a brand-new saved search (the current one is kept)


@app.post("/api/chat/new")
def chat_new(body: NewChat | None = None, user: User = Depends(current_user)):
    boss.new_chat(user.id, (body or NewChat()).new_search)
    return {"ok": True}


@app.get("/api/searches")
def searches(user: User = Depends(current_user)):
    conn = db.connect()
    active = db.active_search_id(conn, user.id)
    return [{**x, "active": x["id"] == active, "steps_done": len(boss.steps_done(x["stage"]))}
            for x in db.list_searches(conn, user.id)]


@app.post("/api/searches")
def search_new(user: User = Depends(current_user)):
    boss.new_chat(user.id, new_search=True)
    return {"ok": True}


@app.post("/api/searches/{search_id}/activate")
def search_activate(search_id: int, user: User = Depends(current_user)):
    if not boss.switch_search(user.id, search_id):
        raise HTTPException(404, "Search not found.")
    return {"ok": True}


@app.delete("/api/searches/{search_id}")
def search_delete(search_id: int, user: User = Depends(current_user)):
    if not boss.delete_search(user.id, search_id):
        raise HTTPException(404, "Search not found.")
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
    return [dict(zip(cols, r)) for r in db.tracker_rows(db.connect(), open_search(user)[1])]


@app.get("/api/employers")
def employers(user: User = Depends(current_user)):
    """The open search's employer table (saved by the Report Summarizer), or null if not built yet."""
    return db.get_search_employers(db.connect(), open_search(user)[0])


class TrackerAdd(BaseModel):
    companies: list[str]


@app.post("/api/tracker")
def tracker_add(body: TrackerAdd, user: User = Depends(current_user)):
    conn, student = db.connect(), open_search(user)[1]
    have = len(db.tracker_rows(conn, student))
    added, full = [], []
    for c in body.companies:
        if have >= db.TRACKER_MAX:
            full.append(c)
        elif db.tracker_add(conn, student, c, None):
            added.append(c)
            have += 1
    if have:
        boss.mark_step(user.id, 5)
    return {"added": added, "full": full, "count": have, "max": db.TRACKER_MAX}


class TrackerUpdate(BaseModel):
    company: str
    status: Literal["interested", "applied", "interviewing", "offer", "rejected"] | None = None
    notes: str | None = None


@app.patch("/api/tracker")
def tracker_update(body: TrackerUpdate, user: User = Depends(current_user)):
    if not db.tracker_update(db.connect(), open_search(user)[1], body.company, body.status, body.notes):
        raise HTTPException(404, "Not in your tracker.")
    return {"ok": True}


@app.delete("/api/tracker/{company}")
def tracker_delete(company: str, user: User = Depends(current_user)):
    if not db.tracker_remove(db.connect(), open_search(user)[1], company):
        raise HTTPException(404, "Not in your tracker.")
    return {"ok": True}


@app.get("/api/postings")
def postings(user: User = Depends(current_user)):
    """Active postings for the open search's tracked companies in its location."""
    _, key, search = open_search(user)
    cols = ("company", "title", "location", "level", "url", "first_seen", "location_flexible")
    return [dict(zip(cols, r)) for r in db.postings_for_student(db.connect(), key, location_key(search))]


@app.get("/api/tracker/details")
def tracker_details(user: User = Depends(current_user)):
    """Tracker table: each tracked company with status, careers page, research summary and its open jobs."""
    from backend.company_researcher import apply_report_salary
    conn = db.connect()
    _, key, search = open_search(user)
    loc = location_key(search)
    out = []
    for company, status, careers, notes, updated in db.tracker_rows(conn, key):
        research = db.latest_research(conn, company, search["country"]) if search["country"] else None
        summary = None
        if research:
            apply_report_salary(conn, research)
            summary = {
                "salary_low": research.salary_base_low, "salary_high": research.salary_base_high,
                "currency": research.salary_currency, "salary_note": research.salary_note,
                "visa": research.visa_sponsorship, "roles": research.mba_roles[:4], "locations": research.locations[:4],
                "recruiting": research.recruiting_notes,
            }
            careers = careers if careers != "-" else (research.careers_url or "-")
        note, scanned = db.last_scan(conn, company, loc)
        out.append({"company": company, "status": status, "careers_url": careers, "notes": notes, "updated": updated,
                    "research": summary, "jobs": db.postings_by_company(conn, company, loc),
                    "jobs_checked": scanned, "jobs_note": note})
    return {"location": loc if search["country"] else None, "rows": out}


# Serve the built React app (npm run build -> frontend/dist) from the same server, if present.
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
