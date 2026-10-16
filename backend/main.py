"""FastAPI app entry point."""
from fastapi import FastAPI

app = FastAPI(title="MBA Employer Finder")


@app.get("/health")
def health():
    return {"ok": True}
