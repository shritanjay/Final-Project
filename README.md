# Career Scout

**For MBA students who want to work somewhere new:** tell it a city, and it reads the employment reports of that
city's top MBA programs, shows you every company that hires their graduates, researches the ones you pick (salary,
MBA roles, visa sponsorship, recruiting timeline), and tracks their careers pages for internship and MBA openings.

MGT 409 final project · Shritanjay Bhatia · model: `gpt-6-luna` via Portkey (course key only)

---

## Quick start (about 3 minutes)

You need **Python 3.11+**. No Node, no database server.

1. **Key:** put a `.env` file containing `PORTKEY_API_KEY=...` in this folder **or one folder above it**
   (the app checks this folder first, then the parent). See `.env.example`.
2. **Run:**
   - macOS / Linux: `./run.sh`
   - Windows: double-click `run.bat` (or run it in a terminal)

   The script creates `.venv`, installs pinned packages, and starts the app.
3. **Open http://localhost:8000**, click **Create an account** (any email + 8-character password), and type
   **`Toronto, Canada`**. Then say **"find them for me"**.

Manual alternative to the script:
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn backend.main:app --port 8000
```

### Test data vs. full data
- The repo ships a small **demo database** (`data/demo.db`, 250 KB, no user data): Toronto's three employment
  reports (Rotman, Schulich, Ivey) already analyzed: 1,448 employer listings, salary tables, cached research and job
  postings. On first run it is copied to `data/employers.db` (the working database, not in git).
  **Toronto, Canada is the fast, cheap demo path** (few model calls, because the reports are already analyzed).
- **Full data:** any other city works too. The agents find the schools and reports online, download the PDFs to
  `data/reports/` (after you confirm), and analyze them. That uses more tokens (~15-30k per report).
- **Switching / reset:** delete `data/employers.db` to go back to the demo data; it's recreated from `demo.db`
  on the next start. Your accounts and trackers live in `employers.db`.

---

## What it does (the guided path)

The chat walks the student through six steps; a progress bar and **Next step** button show where they are.

1. **Where to work:** city + country. Each location is a *saved search* (switch between them from the top bar).
2. **Employment reports:** find the top 3 MBA programs in the city (QS rankings) and their latest employment
   report PDFs, or upload your own.
3. **Employers by industry:** extract every employer from the reports into an interactive table (search, filter by
   industry/school, "confirmed hires" vs "recruits there").
4. **Research companies:** salary (from the reports' salary tables, web as fallback), MBA roles, offices, visa
   sponsorship, recruiting timeline; rank by salary or by fit.
5. **Tracker:** pick 5-15 companies; status, careers page, research and open roles in one table.
6. **Job postings:** check each tracked company for all internship / MBA / early-career postings in the city.

## How it works: the agents

A **boss agent** talks to the student and hands work to specialist agents through tools (same pattern as the
Lecture 10 app). All agents use `gpt-6-luna` through Portkey.

```
                         ┌────────────── Boss (Career Scout) ──────────────┐
 student ⇄ chat UI ⇄     │ guided path, saved searches, buttons, tracker   │
                         └──┬──────┬──────┬──────┬──────┬──────┬──────┬────┘
           Program Scout ◀──┘      │      │      │      │      │      └──▶ Job Posting Scout
  (top MBA programs, QS; web)      │      │      │      │      │          (careers pages + postings; web)
       Employment Report Finder ◀──┘      │      │      │      └──▶ Company Researcher (+ fit ranker)
  (report PDFs; web + link checks)        │      │      │           (salary, roles, visa, recruiting; web)
                Report Analyst ◀──────────┘      │      └──▶ Geo Verifier (hires in country?; web)
   (PDF → employers, page-cited)                 │
     + Salary Extractor (salary tables)          └──▶ Report Summarizer (industries, top 100 picks)
```

| Agent | Job | Tools / data |
|---|---|---|
| Boss | Runs the conversation and the 6-step path; calls the specialists | 16 tools (set location, find/download/analyze reports, summarize, research, rank, tracker, job checks…) |
| Program Scout | Top MBA programs in a country/city | OpenAI web search (QS rankings) |
| Employment Report Finder | Latest full-time MBA employment report PDF per school, 3 per city | Web search; code checks each link is a real PDF < 25 MB |
| Report Analyst | Employers from a report: name, internship/full-time, function, page, hired vs recruiting | PDF text with page markers |
| Salary Extractor | Salary-by-industry/function tables | Only the pages that look like salary tables |
| Report Summarizer | Groups employers into industries, picks top 100 | Merged employer list from SQLite |
| Company Researcher (+ ranker) | Salary, MBA roles, offices, visa, recruiting; fit scores | Web search; report salary tables first |
| Job Posting Scout | Careers page + early-career postings in the city | Web search; code link check |
| Geo Verifier | Does a company hire in the country? | Web search |

Code: `backend/boss.py` (boss + tools), one file per specialist in `backend/`, prompts in `backend/prompts/`,
storage in `backend/db.py` (SQLite), API in `backend/main.py` (FastAPI), UI in `frontend/` (React; the built copy
in `frontend/dist/` is served by FastAPI, so no Node is needed to run it).

## Safety

| Risk | Defense (in code, not just the prompt) |
|---|---|
| Invented companies / facts | Every employer must cite a PDF page and its name must be on that page; salaries kept only if the number is on the cited page; geo answers need an evidence URL that mentions the country; web URLs validated |
| Prompt injection (PDFs, web pages) | Prompts treat all fetched content as data; code drops companies named only in instruction-like text ("note to automated readers…"); provider prompt shield blocks jailbreak wording |
| Wrong actions | Downloads only after the student confirms; link checks before download (real PDF, < 25 MB, HTTPS) |
| Infinite loops / overspending | Hard caps on every run (boss: 25 model calls / 250k tokens; specialists: 5 calls / 120k); max 20 companies researched per request, 15 tracked; caches (programs 30 days, research 30 days, postings 24 h); only the last 10 chat turns sent to the model |
| Data leaks | Accounts with scrypt-hashed passwords; tokens stored hashed; every search/tracker query scoped to the logged-in user; state can't leak through reused ids |

Tests (no API key needed): `.venv/bin/python -m pytest tests -q` (12 tests).
Live prompt-injection test (1 small model call): `.venv/bin/python -m tests.injection_demo`
(results in `logs/injection_demo.txt`, and `logs/injection_demo_before_fix.txt` for the run before the fix).

## Token usage and cost

Every model call is logged with input, cached input and output tokens to `logs/usage_log.json`
(`backend/llm.py → run_logged`). Average tokens per call from real runs:

| Agent | Calls logged | Input | Cached input | Output |
|---|---:|---:|---:|---:|
| Boss (per chat turn) | 67 | 6,731 | 3,046 | 343 |
| Company Researcher (per company) | 19 | 18,763 | 3,799 | 988 |
| Job Posting Scout (per company) | 18 | 20,070 | 3,211 | 1,096 |
| Report Summarizer (per city) | 12 | 19,616 | 0 | 4,031 |
| Employment Report Finder | 12 | 14,244 | 3,418 | 430 |
| Report Analyst (per report) | 6 | 6,060 | 0 | 8,390 |

Cost cuts: reports analyzed once and shared by all users; report salary tables replace web salary searches; low
search-context web search; caches; history trimming. Details and cost-at-scale math are in the report.

## Email (optional, not needed for grading)
Sign-up verification and password-reset emails are written to `logs/outbox/` (open the newest `.eml` file and
copy the link). Real sending can be turned on later with SMTP settings; see `backend/emailer.py`.

## Developing the UI
```bash
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api to port 8000
npm run build                               # refresh frontend/dist (served at http://localhost:8000)
```

## Project layout
```
backend/      FastAPI app, boss agent + specialists, prompts, SQLite helpers, auth, email
frontend/     React app (src/) and its built copy (dist/)
data/         demo.db (test data), reports/ (downloaded PDFs, not in git), employers.db (working DB, not in git)
logs/         usage_log.json (token log), injection test results
tests/        safety tests + live prompt-injection test
run.sh / run.bat   one-command start
```

## Limits
- QS hides rank numbers behind JavaScript, so ranks are often blank (the order still follows QS).
- Some schools don't publish reports (e.g. Ted Rogers), so the finder may use a school outside the city.
- Job sites that render postings with JavaScript can be missed; students can paste a missed link into the tracker.
- Scanned (image-only) PDFs can't be read.
