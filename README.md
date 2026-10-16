# MBA Employer Finder (MGT 409 Final Project)

Helps MBA students targeting Canada (other countries later) decide which companies to apply to:
reads MBA employment reports, extracts employers, ranks them, and tracks their career pages.

## Stack
- Backend: Python, FastAPI, PydanticAI
- Model: `gpt-6-luna` via Portkey (only model used)
- Frontend: React (coming later)

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add PORTKEY_API_KEY
```
The key is loaded from `.env` in this folder first, then from the folder one level up.

## Run
```bash
python test_call.py                 # smoke test model call
uvicorn backend.main:app --reload   # API at http://localhost:8000/health
```

## Token usage
Every model call made through `backend.llm.run_logged()` appends input, cached input, and
output token counts (from the API response) to `logs/usage_log.json`.
