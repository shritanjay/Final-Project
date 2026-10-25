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

## Boss agent (Career Scout)
Multi-agent pattern from Lecture 10: a boss agent talks to the student and delegates to specialists via tools.
- Flow: asks for the target country (and optional city) → asks whether to **upload** report PDFs or have agents **find** them →
  delegates to the Report Analyst (`analyze_reports`), Program Scout (`research_programs`), and
  Geo Verifier (`verify_employers`, confirms with the student first since it uses web search).
- Code: `backend/boss.py`, prompt in `backend/prompts/boss.md`. Runs on the Responses API (needed for function tools).
- API (`uvicorn backend.main:app --reload`):
  - `POST /api/chat` `{session_id, message}` → `{answer, country, report_source}` (history kept per session in memory)
  - `POST /api/upload` (multipart PDF, max 25 MB) → saved to `data/reports/`

## Program Scout
Finds the top full-time MBA programs in the country/city using the QS MBA rankings
(https://www.topuniversities.com/mba-rankings) via web search, plus links to each school's employment report.
- Saved to the `programs` table; cached 30 days per country/city (one run ≈ 20k input tokens, 4 searches).
- QS ranks are often null: the QS site renders ranks with JavaScript and blocks direct fetches, so the model
  only records a rank if it actually sees one.
- Downloading the report PDFs isn't automated yet; the boss asks the student to download and upload them.
