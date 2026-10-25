"""FastAPI app: chat with the boss agent and upload employment report PDFs."""
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend import auth, boss, db

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
        auth.sign_up(conn, body.email, body.password)
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


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    country, city, roles = db.get_prefs(db.connect(), user.id)
    return {"email": user.email, "country": country, "city": city, "target_roles": roles}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, user: User = Depends(current_user)):
    session, answer = await boss.chat(user.id, body.message)
    return ChatResponse(answer=answer, country=session.country, report_source=session.report_source)


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


@app.get("/api/postings")
def postings(user: User = Depends(current_user)):
    """Active postings for the user's tracked companies in their saved city/country."""
    country, city, _ = db.get_prefs(db.connect(), user.id)
    location = f"{city + ', ' if city else ''}{country}"
    cols = ("company", "title", "location", "level", "url", "first_seen", "location_flexible")
    return [dict(zip(cols, r)) for r in db.postings_for_student(db.connect(), f"user:{user.id}", location)]
