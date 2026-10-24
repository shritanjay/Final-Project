"""FastAPI app: chat with the boss agent and upload employment report PDFs."""
from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel

from backend import boss

app = FastAPI(title="MBA Employer Finder")
MAX_UPLOAD_MB = 25


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    answer: str
    country: str | None
    report_source: str | None


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    session, answer = await boss.chat(body.session_id, body.message)
    return ChatResponse(answer=answer, country=session.country, report_source=session.report_source)


@app.post("/api/upload")
async def upload(file: UploadFile):
    data = await file.read()
    if not (file.filename or "").lower().endswith(".pdf") or not data.startswith(b"%PDF"):
        raise HTTPException(400, "Please upload a PDF.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"Max {MAX_UPLOAD_MB} MB.")
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in file.filename)
    boss.REPORTS.mkdir(parents=True, exist_ok=True)
    (boss.REPORTS / name).write_bytes(data)
    return {"saved": name}
