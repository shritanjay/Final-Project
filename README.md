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

## MBA Employment Report Finder
Finds the latest full-time MBA employment report PDF for the top 3 programs in the student's city
(order from Program Scout; schools in the city first).
- First tries report links Program Scout already found (checked in code, no model call), then web-searches the rest.
- Every link is checked in code: HTTPS, HTTP 200, file really starts with `%PDF`, under 25 MB.
- **Nothing is downloaded until the student confirms** in chat (`find_reports` → student says yes → `download_reports`).
  Files are saved to `data/reports/` as `<school>_<year>.pdf`, then `analyze_reports` extracts employers.

## Report Summarizer
Groups employers from the analyzed reports of the city's top 3 MBA programs into industries and presents
**at most 100 companies** to the student (boss tool `summarize_employers`).
- Code picks the reports (matched to Program Scout's top 3; falls back to all analyzed reports), merges duplicate
  names across schools ("Inc.", "LLP", "(CPPIB)" etc. ignored), and counts how many schools list each company.
- The model groups them into 6–12 industries and picks the most useful (companies listed by more schools first).
- Code then drops any name not in the reports and enforces the 100 cap. `*` = listed by more than one school.
- One run for Rotman + Schulich (787 unique employers in) ≈ 9k input / 2.6k output tokens.

## Company Researcher + Tracker
- `research_companies`: per company (web search, max 20 per run, 4 at a time, cached 30 days): careers URL,
  post-MBA base salary range (+ source), MBA roles, office cities in the country, visa sponsorship (yes/no/unsure),
  recruiting programs/timeline, and an optional custom question from the student. Salaries with no source are dropped.
  ≈ 17k input / 1.1k output tokens per company.
- `rank_companies`: by salary (code) or by fit to the student's priorities (one small model call, no web search).
- Tracker (`tracker` table, per session): student picks 10–15 companies (max 15); status
  interested/applied/interviewing/offer/rejected + notes. `add_to_tracker`, `view_tracker`, `update_tracker`;
  `GET /api/tracker/{session_id}` for the frontend.

## Salaries from employment reports
- **Salary Extractor** (`backend/salary_extractor.py`): after reports are analyzed, sends only the pages that look
  like salary tables to the model and extracts salary-by-industry and salary-by-function rows (full-time annual and
  internship monthly; average, median, range and what the range means, currency only if written, page).
  Code keeps a row only if its number really appears on the cited page. Stored in `report_salaries`
  (each report scanned once; ≈ 1–2k input / 1–2k output tokens per report).
- **Company Researcher** uses these as the primary salary source: company → its industry tag from the Report Analyst →
  full-time annual rows (by-industry preferred) from each school's report. The note cites school, row label and page,
  and says it's an industry average, not company-specific. Web search is skipped for salary when a report figure exists
  and used only as a fallback (e.g. companies tagged "other", like law firms).

## Job Posting Scout
For every company on the student's tracker (10–15), finds the careers page and current **internship / MBA /
early-career** postings in the city (or country) — boss tools `check_job_postings` and `view_job_postings`.
- The boss first asks for the student's **target role types** (e.g. strategy, product, finance; `set_target_roles`);
  postings outside those types are skipped. Changing roles triggers a fresh scan (cache key includes roles).
- Country-wide MBA / rotational programs whose city is decided after hire (e.g. Amazon Pathways) are included and
  marked **"location matched after hire"** (`location_flexible`).
- Web search per company (≈ 15–20k input tokens, 4 at a time). Companies checked in the last 24h are skipped
  unless `force=True`.
- Code keeps only postings with a link that resolves (free HTTP check; 403/429 from bot-blocking job sites count as live).
- Postings are stored in `job_postings` with first/last seen; postings missing from a new scan are marked inactive, and
  each check reports how many are **new**. Careers URLs found are saved to the tracker.
- `GET /api/postings/{session_id}?location=Toronto, Canada` for the frontend.
