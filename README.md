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
python analyze_reports.py           # Report Analyst on every PDF in data/reports/
uvicorn backend.main:app --reload   # API at http://localhost:8000/health
```

## Token usage
Every model call made through `backend.llm.run_logged()` appends input, cached input, and
output token counts (from the API response) to `logs/usage_log.json`.

## Report Analyst
Drop employment report PDFs in `data/reports/` and run `python analyze_reports.py`.
- Reads each PDF page by page (pypdf), tags pages with `=== PAGE n ===`, and asks `gpt-6-luna` for a
  `ReportExtraction` (see `backend/models.py`): company, internship/full-time/both, function, location, page.
- **No invented companies:** after the model answers, each company is checked against the text of the page it
  cited. If the name isn't on that page, it's dropped and listed in the output.
- Results go to SQLite at `data/employers.db` (`reports` and `employers` tables).
- PDFs already in the database are skipped to save tokens; `--force` re-analyzes them.
- Scanned (image-only) PDFs have no text and are reported as errors.

## Geo Verifier
`python verify_geo.py --school Rotman` (default country Canada; `--country`, `--limit` options).
- For each company in the database, `gpt-6-luna` uses OpenAI's built-in web search (through Portkey; no extra
  API key) to find the careers page and check for offices/job postings in the country.
- Saves careers URL, hires_in_country (yes/no/unsure), evidence URL + text, and date to the `geo_checks` table.
- Web content is treated as untrusted data: the prompt says so, and code double-checks the answer
  (URLs must be real URLs; yes/no needs an evidence URL; "yes" evidence must mention the country, else "unsure").
- Cached: a company checked for the same country in the last 7 days is skipped. Max 50 companies per run.
- Cost: ~19k input tokens and a few web searches per company (logged in `logs/usage_log.json`).
