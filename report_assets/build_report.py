"""Builds report.html (self-contained: images embedded) from real logs and screenshots.
Run from the project folder: .venv/bin/python report_assets/build_report.py
"""
import base64
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
costs = json.loads((HERE / "costs.json").read_text())
trace = json.loads((HERE / "run_trace.json").read_text())
pytest_out = (HERE / "pytest_output.txt").read_text().strip()
inj_after = (ROOT / "logs" / "injection_demo.txt").read_text().strip()
inj_before = (ROOT / "logs" / "injection_demo_before_fix.txt").read_text().strip()

REPO = "https://github.com/shritanjay/career-scout"  # TODO: confirm repo URL before submitting


def img(name: str, caption: str, width: str = "86%") -> str:
    data = base64.b64encode((HERE / "img" / name).read_bytes()).decode()
    return (f'<figure><img src="data:image/jpeg;base64,{data}" style="width:{width}" alt="{html.escape(caption)}">'
            f'<figcaption>{caption}</figcaption></figure>')


def usd(x: float, digits: int = 2) -> str:
    return f"${x:,.{digits}f}"


per = costs["per_agent"]
P = {k: v["total_cost"] for k, v in per.items()}

# --- traced run table ---------------------------------------------------------------------------------------------
IN, CACHED, OUT, SEARCH = 0.20 / 1e6, 0.02 / 1e6, 0.50 / 1e6, 10 / 1000
trace_rows, tot = [], {"in": 0, "cached": 0, "out": 0, "search": 0, "cost": 0.0, "secs": 0.0}
for t in trace["turns"]:
    cost = 0.0
    agents = []
    for c in t["calls"]:
        i, ca, o, s = c["input_tokens"], c["cached_input_tokens"] or 0, c["output_tokens"], c.get("web_searches") or 0
        cost += (i - ca) * IN + ca * CACHED + o * OUT + s * SEARCH
        tot["in"] += i; tot["cached"] += ca; tot["out"] += o; tot["search"] += s
        agents.append(c["label"].split(":")[0].replace("_", " "))
    tot["cost"] += cost; tot["secs"] += t["seconds"]
    trace_rows.append((t["user"], ", ".join(agents), sum(c["input_tokens"] for c in t["calls"]),
                       sum(c["cached_input_tokens"] or 0 for c in t["calls"]), sum(c["output_tokens"] for c in t["calls"]),
                       t["seconds"], cost, ", ".join(t["actions"]) or "–"))

trace_html = "".join(
    f"<tr><td>{html.escape(u)}</td><td>{html.escape(a)}</td><td class=n>{i:,}</td><td class=n>{c:,}</td>"
    f"<td class=n>{o:,}</td><td class=n>{s:.1f}s</td><td class=n>{usd(cost, 4)}</td><td>{html.escape(b)}</td></tr>"
    for u, a, i, c, o, s, cost, b in trace_rows)

agent_rows = "".join(
    f"<tr><td>{k.replace('_', ' ').title()}</td><td class=n>{v['calls']}</td><td class=n>{v['input']:,}</td>"
    f"<td class=n>{v['cached']:,}</td><td class=n>{v['output']:,}</td><td class=n>{v['searches']}</td>"
    f"<td class=n>{usd(v['token_cost'], 4)}</td><td class=n>{usd(v['total_cost'], 4)}</td></tr>"
    for k, v in sorted(per.items(), key=lambda x: -x[1]["calls"]))

run_rows = "".join(f"<tr><td>{k}</td><td class=n>{usd(v, 3)}</td></tr>" for k, v in costs["run"].items())
city_rows = "".join(f"<tr><td>{k}</td><td class=n>{usd(v, 3)}</td></tr>" for k, v in costs["city"].items())
rt = costs["run_tokens"]
month = costs["month"]
s100, s10k = costs["scale"]["100"], costs["scale"]["10000"]
# research cache is shared across users: at 10k users (150 cities), research is capped by ~200 unique companies/city/month
research_naive = 10_000 * 10 * P["company_researcher"]
research_shared = 150 * 200 * P["company_researcher"]
s10k_shared = s10k - research_naive + research_shared
run_token_cost = (rt["input"] - rt["cached"]) * IN + rt["cached"] * CACHED + rt["output"] * OUT
search_share = 1 - run_token_cost / costs["run_total"]

DIAGRAM = """
<svg viewBox="0 0 820 400" class="diagram" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system, Segoe UI, Arial">
  <defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#9a5230"/></marker></defs>
  <rect x="20" y="160" width="120" height="70" rx="12" fill="#efe6d7" stroke="#d6c3a3"/>
  <text x="80" y="190" text-anchor="middle" font-size="14" font-weight="700" fill="#3b2f25">Student</text>
  <text x="80" y="210" text-anchor="middle" font-size="11" fill="#8a7764">chat · tables · buttons</text>
  <line x1="140" y1="195" x2="228" y2="195" stroke="#9a5230" stroke-width="2" marker-end="url(#a)"/>
  <line x1="228" y1="205" x2="142" y2="205" stroke="#9a5230" stroke-width="2" marker-end="url(#a)"/>
  <rect x="230" y="140" width="190" height="110" rx="14" fill="#b4643c"/>
  <text x="325" y="178" text-anchor="middle" font-size="16" font-weight="700" fill="#fbf8f2">Boss: Career Scout</text>
  <text x="325" y="200" text-anchor="middle" font-size="11" fill="#f6f0e6">6-step guided path · 16 tools</text>
  <text x="325" y="217" text-anchor="middle" font-size="11" fill="#f6f0e6">saved searches · tracker · buttons</text>
  <text x="325" y="234" text-anchor="middle" font-size="11" fill="#f6f0e6">caps: 25 calls / 250k tokens</text>
  {boxes}
  <rect x="230" y="300" width="190" height="70" rx="12" fill="#fbf8f2" stroke="#6e7b4f" stroke-dasharray="5 4"/>
  <text x="325" y="328" text-anchor="middle" font-size="13" font-weight="700" fill="#4f5b37">SQLite</text>
  <text x="325" y="347" text-anchor="middle" font-size="11" fill="#5b4a3b">employers · salaries · caches · users</text>
  <line x1="325" y1="250" x2="325" y2="298" stroke="#6e7b4f" stroke-width="2" marker-end="url(#a)"/>
</svg>"""
specialists = [("Program Scout", "top MBA programs (QS) · web"), ("Report Finder", "report PDFs · web + checks"),
               ("Report Analyst", "PDF → page-cited employers"), ("Salary Extractor", "salary tables in reports"),
               ("Report Summarizer", "industries · top 100"), ("Company Researcher", "salary · roles · visa · web"),
               ("Job Posting Scout", "careers pages · postings · web"), ("Geo Verifier", "hires in country? · web")]
boxes = []
for i, (name, sub) in enumerate(specialists):
    y = 20 + i * 46
    boxes.append(f'<rect x="560" y="{y}" width="240" height="38" rx="9" fill="#fbf8f2" stroke="#d6c3a3"/>'
                 f'<text x="574" y="{y + 16}" font-size="12.5" font-weight="700" fill="#3b2f25">{name}</text>'
                 f'<text x="574" y="{y + 31}" font-size="10.5" fill="#8a7764">{sub}</text>'
                 f'<line x1="420" y1="195" x2="558" y2="{y + 19}" stroke="#d6c3a3" stroke-width="1.5" marker-end="url(#a)"/>')
DIAGRAM = DIAGRAM.replace("{boxes}", "".join(boxes))

CSS = """
:root{--cream:#f6f0e6;--paper:#fbf8f2;--linen:#efe6d7;--sand:#e4d7c3;--esp:#3b2f25;--bark:#5b4a3b;--muted:#8a7764;--terra:#b4643c;--olive:#6e7b4f}
*{box-sizing:border-box} body{margin:0;background:var(--cream);color:var(--esp);font:15.5px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
main{max-width:900px;margin:0 auto;padding:48px 40px 80px;background:var(--paper)}
h1,h2,h3{font-family:"Iowan Old Style",Palatino,Georgia,serif;color:var(--esp);line-height:1.2}
h1{font-size:40px;margin:0 0 6px} h2{font-size:26px;margin:44px 0 12px;padding-top:14px;border-top:2px solid var(--sand)}
h3{font-size:18px;margin:26px 0 8px} em.t{color:var(--terra);font-style:italic}
.sub{color:var(--muted);font-size:16px;margin:0 0 18px} .links a{color:#9a5230}
.pitch{font-size:18px;background:var(--linen);border-left:4px solid var(--terra);padding:12px 16px;border-radius:0 10px 10px 0}
table{width:100%;border-collapse:collapse;margin:12px 0 18px;font-size:13.5px} th,td{padding:7px 9px;border-bottom:1px solid var(--sand);text-align:left;vertical-align:top}
th{background:var(--linen);font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)} td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
tr.total td{font-weight:700;background:#f3eadb}
figure{margin:16px 0 22px} figure img{display:block;margin:0 auto;border-radius:10px;border:1px solid var(--sand);box-shadow:0 6px 20px rgba(59,47,37,.08)}
figcaption{font-size:13px;color:var(--muted);margin-top:6px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0} .kpi{background:var(--cream);border:1px solid var(--sand);border-radius:12px;padding:12px}
.kpi b{display:block;font-family:Georgia,serif;font-size:24px;color:var(--terra)} .kpi span{font-size:12.5px;color:var(--muted)}
pre{background:#2f261e;color:#f2e9da;padding:14px 16px;border-radius:10px;font-size:12px;line-height:1.5;overflow-x:auto;white-space:pre-wrap}
.callout{background:#e8ecdc;border:1px solid #cfd6b8;border-radius:10px;padding:12px 16px;margin:14px 0}
.todo{background:#fbe9d8;border:2px dashed #b4643c;border-radius:10px;padding:12px 16px;margin:14px 0}
.diagram{width:100%;height:auto;background:var(--cream);border:1px solid var(--sand);border-radius:12px;margin:10px 0}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px} ul{padding-left:20px} li{margin:4px 0}
code{background:var(--linen);padding:1px 5px;border-radius:5px;font-size:13px}
@media print{body{background:#fff} main{padding:0;max-width:none} h2{break-before:auto;break-after:avoid} figure,table,pre,.kpis{break-inside:avoid}}
"""

body = f"""
<h1>Career <em class="t">Scout</em></h1>
<p class="sub">Shritanjay Bhatia · MGT 409 Final Project · Fall 2026</p>
<p class="links">GitHub: <a href="{REPO}">{REPO}</a> · Live app: runs locally (see README; one command, ~1 minute)</p>
<p class="pitch">Career Scout tells an MBA student who wants to work in a new city which companies actually hire MBAs
there: it reads the employment reports of that city's top MBA programs, turns them into a searchable employer
list, researches the companies the student picks, and tracks their careers pages for internship and MBA openings.</p>

<div class="kpis">
 <div class="kpi"><b>1,281</b><span>employers found for Toronto from 3 schools' reports</span></div>
 <div class="kpi"><b>{tot['secs']:.0f} s</b><span>end-to-end traced run (city → employers → research → jobs)</span></div>
 <div class="kpi"><b>{usd(costs['run_total'])}</b><span>cost of a full uncached student run (90% web search)</span></div>
 <div class="kpi"><b>12/12</b><span>safety tests passing; injection test blocked</span></div>
</div>

<h2>1. Motivation</h2>
<p><b>Who has the problem.</b> MBA students who want to work somewhere other than where they study: international
students heading home or to a third country, career switchers relocating, partners following a spouse. I am one of
them: I'm studying in the US and want to work in <b>Canada</b> after my MBA.</p>
<p><b>How they handle it today.</b> Your own school's career office knows the employers that recruit <i>at your
school</i>, in <i>your school's</i> region. For a different city you're on your own. The usual approach is to:
(1) guess which companies hire MBAs there (big names you already know), (2) search LinkedIn and job boards one
company at a time, (3) dig up other schools' employment reports and read them page by page, and (4) keep a
spreadsheet of careers pages and check them by hand every week.</p>
<p><b>What that costs.</b> The best source of truth, other schools' employment reports, is the hardest to use:
each is a 12-16 page PDF with an alphabetical list of several hundred employers, no search, and different
definitions of "employer" (Rotman lists companies that <i>hired</i> its MBAs; Schulich lists companies <i>recruiting</i>
at the school; Ivey lists every company that <i>engaged</i> with students and marks real hires with an asterisk).
Reading three reports carefully, cleaning the lists and merging them is a multi-hour job (my estimate: 3-5 hours
for one city, before any company research), so most students skip it and apply to the same handful of brand names
as everyone else. Then, keeping 10-15 careers pages under watch is a recurring weekly chore that's easy to drop
in the middle of recruiting season.</p>

<h2>2. What is new here</h2>
<table>
<tr><th>Existing option</th><th>What it does well</th><th>What it misses for this problem</th></tr>
<tr><td>LinkedIn Jobs / Indeed</td><td>Huge job inventory, alerts</td><td>Doesn't tell you <i>which</i> companies hire MBAs in a city; generic "MBA" searches return thousands of mid-career roles</td></tr>
<tr><td>School career portals (12twenty, Handshake)</td><td>Employers that recruit at <i>your</i> school</td><td>Weak for other cities/countries; no view of other schools' outcomes</td></tr>
<tr><td>Poets&amp;Quants, school employment reports</td><td>Authoritative outcome data</td><td>PDFs; top-line stats only; employer lists not searchable or comparable across schools</td></tr>
<tr><td>Glassdoor / Levels.fyi</td><td>Salary and reviews</td><td>No discovery of who hires MBAs in a city; MBA-level pay is sparse outside the US</td></tr>
<tr><td>ChatGPT / general chatbots</td><td>Quick answers</td><td>Lists employers from memory with no sources (often invented or outdated); no tracking</td></tr>
</table>
<p><b>What Career Scout does differently.</b></p>
<ul>
<li><b>Discovery from evidence, not memory:</b> the employer list comes from the target city's top MBA programs'
own employment reports, and every employer is tied to the PDF page it appears on (invented names are dropped in code).</li>
<li><b>Hired vs. recruiting:</b> it reads each report's legend and headings and marks whether a school says the
company <i>hired</i> its MBAs or only <i>recruits</i> there, so "356 confirmed hires" isn't padded by 900 companies that
merely attended a networking event.</li>
<li><b>Cross-school view:</b> 134 Toronto employers appear in 2+ schools' reports; 24 in all three, a strong signal
that a company really hires MBAs in that city.</li>
<li><b>Salaries from the reports themselves:</b> each school's salary-by-industry table (with page cites) is the
primary salary source, which is more reliable than scraped salary sites for MBA roles outside the US.</li>
<li><b>From list to action:</b> one place to research, shortlist (5-15), and keep checking careers pages for
<i>all</i> internship / MBA / early-career postings in the city, including country-wide programs whose city is
"matched after hire".</li>
</ul>
<p>It is <b>not</b> a resume reviewer, document chat or trip planner: the PDFs are a data source for a
discovery-and-tracking workflow across many agents, not something you chat with.</p>

<h2>3. The agents</h2>
<p>A <b>boss agent</b> owns the conversation and hands work to <b>eight specialist agents</b> through tools. The boss
never answers facts from memory: every company, salary and posting comes from a specialist's tool result.</p>
{DIAGRAM}
<p class="sub" style="font-size:13px">Who hands work to whom: the student only talks to the boss; the boss calls specialists as tools; results are
stored in SQLite (shared caches across users) and shown in the chat, the Employers table and the Tracker.</p>

<table>
<tr><th>Agent</th><th>Job</th><th>Tools / inputs</th><th>Code-level guardrails</th></tr>
<tr><td><b>Boss (Career Scout)</b></td><td>Runs the 6-step guided path; explains each step; attaches buttons</td><td>16 tools: set location, research programs, find / download / analyze reports, summarize, research, rank, tracker (add / view / update), job checks, geo verify</td><td>Progress tracked in code (not by the model); downloads only after a "yes"; 25 calls / 250k tokens per turn</td></tr>
<tr><td>Program Scout</td><td>Top full-time MBA programs in a country/city</td><td>OpenAI web search, QS MBA rankings</td><td>URLs validated; cached 30 days</td></tr>
<tr><td>Employment Report Finder</td><td>Latest report PDF for 3 programs per city, moving to the next school if one has none</td><td>Web search; known links first (free)</td><td>Each link checked: HTTPS, real <code>%PDF</code>, &lt; 25 MB; max 2 search rounds</td></tr>
<tr><td>Report Analyst</td><td>Every employer: name, internship/full-time, function, page, hired vs. recruiting</td><td>PDF text with <code>=== PAGE n ===</code> markers</td><td>Name must appear on the cited page; companies named only in instruction-like text dropped; footnote marks cleaned</td></tr>
<tr><td>Salary Extractor</td><td>Salary-by-industry / function tables</td><td>Only pages that look like salary tables</td><td>Number must appear on the cited page; currency only if written</td></tr>
<tr><td>Report Summarizer</td><td>Groups employers into industries; picks top 100 (confirmed hires first)</td><td>Merged list from SQLite (code dedupes names)</td><td>Names not in the input dropped; 100 cap enforced in code</td></tr>
<tr><td>Company Researcher (+ fit ranker)</td><td>Salary, MBA roles, offices, visa sponsorship, recruiting timeline; 1-10 fit scores</td><td>Web search; report salary tables first</td><td>Max 20 per request; salary dropped if no source; cached 30 days</td></tr>
<tr><td>Job Posting Scout</td><td>Careers page + all early-career postings in the city</td><td>Web search (company careers site + multi-office ads)</td><td>404/fake hosts dropped; cached 24 h; never hides postings a student added</td></tr>
<tr><td>Geo Verifier</td><td>Does a company hire in the country?</td><td>Web search</td><td>"yes/no" needs an evidence URL; "yes" evidence must name the country</td></tr>
</table>

<h3>Models used and why</h3>
<p>All agents use <b>gpt-6-luna</b> through Portkey with the course key. It is cheap (list prices
{usd(costs['prices']['input'])} / {usd(costs['prices']['cached'])} / {usd(costs['prices']['output'])} per million input / cached input / output tokens), fast enough for chat, supports JSON-schema
structured output (every specialist returns a typed Pydantic object) and OpenAI's built-in web search through the
Responses API. Two practical constraints shaped the design: on Portkey this model rejects tool-based structured output
with reasoning on Chat Completions, so specialists use native JSON-schema output, and the boss (which needs function
tools) runs on the Responses API.</p>

<h3>One real run, step by step</h3>
<p>A fresh account (<code>demo@careerscout.test</code>) running the full path for Toronto on the demo data, recorded
from the app's token log. The boss called, in order:
<code>{" → ".join(trace["boss_tools"])}</code>.</p>
<table>
<tr><th>Student message</th><th>Agents called</th><th class=n>Input</th><th class=n>Cached</th><th class=n>Output</th><th class=n>Time</th><th class=n>Cost</th><th>Buttons shown</th></tr>
{trace_html}
<tr class="total"><td>Total</td><td></td><td class=n>{tot['in']:,}</td><td class=n>{tot['cached']:,}</td><td class=n>{tot['out']:,}</td><td class=n>{tot['secs']:.0f}s</td><td class=n>{usd(tot['cost'], 3)}</td><td></td></tr>
</table>
<ol>
<li><b>"Toronto, Canada"</b> → the boss calls <code>set_country</code>, marks step 1 done and asks one question: find the
reports, or upload them?</li>
<li><b>"Yes, find them for me"</b> → <code>research_programs</code> (QS list, cached) → <code>find_reports</code>: Rotman and Schulich were
already analyzed; Ted Rogers has no public report, so the finder searched the web (4 searches) and moved on to Ivey
(London, Ontario, flagged as outside Toronto). <code>analyze_reports</code> → <code>summarize_employers</code> builds the table and the
boss explains what it did:</li>
</ol>
{img("02_step3_chat.jpg", "Step 3 in the app: the boss explains what it did (3 schools, 1,281 employers, 356 confirmed hires, top industries) and gives one next step, with a button to the employer table.")}
{img("03_employers.jpg", "The Employers table: search, school filters, confirmed-hire and 2+ school toggles, industry chips with live counts; ✓ = the school's report says it hired its MBAs, dashed = recruits there only. Selecting companies offers Research & track, Research, or Track.")}
<ol start="3">
<li><b>Research &amp; track</b> on Amazon, Bain and McKinsey → the UI adds them to the tracker and the boss calls
<code>research_companies</code>. All three were in the 30-day research cache, so this turn cost {usd(trace_rows[2][6], 4)} instead of
about {usd(3 * P['company_researcher'], 2)}. Salaries come from the schools' salary tables (Ivey, Rotman, Schulich) with a note that they're
industry averages, not company-specific pay.</li>
<li><b>"Find job postings"</b> → <code>check_job_postings</code> (24 h cache) returns 12 open early-career roles, e.g. McKinsey's
Toronto <i>Associate Intern</i> (MBA) and <i>Business Analyst</i>, Bain's <i>Summer Associate</i>, Amazon's Canada-wide <i>MBA Pathways</i>.</li>
</ol>
{img("06_tracker.jpg", "The Tracker: status, average base salary from the reports, visa, open roles and careers link per company; expanding McKinsey shows its research and its two open Toronto roles, plus a box to paste a job link the scout missed.")}

<h2>4. Tokenomics</h2>
<p>Every model call goes through <code>run_logged()</code>, which writes input, cached input and output tokens (and web search
count) to <code>logs/usage_log.json</code>. The numbers below are averages over <b>{costs['log_calls']} real logged calls</b> made while building
and testing the app. Prices: gpt-6-luna list prices above; web search is billed per call (OpenAI's list price,
$10 per 1,000 searches, assumed the same through Portkey).</p>
<table>
<tr><th>Agent (per call)</th><th class=n>Calls</th><th class=n>Input</th><th class=n>Cached</th><th class=n>Output</th><th class=n>Web searches</th><th class=n>Token cost</th><th class=n>With search</th></tr>
{agent_rows}
</table>

<h3>Cost per run and per user</h3>
<div class="two">
<div><p><b>Typical student run</b> (a city whose reports another student already analyzed; 15 chat turns, research 10
companies, job check for 8):</p>
<table>{run_rows}<tr class="total"><td>Total per run</td><td class=n>{usd(costs['run_total'], 2)}</td></tr></table>
<p>Tokens per typical run: <b>{rt['input']:,} input</b> (of which {rt['cached']:,} cached) and <b>{rt['output']:,} output</b>.
Token cost is only {usd(run_token_cost, 3)}; <b>{search_share:.0%} of the cost is web search fees.</b></p></div>
<div><p><b>One-time cost per new city</b> (shared by every later student who picks it):</p>
<table>{city_rows}<tr class="total"><td>Total per city</td><td class=n>{usd(costs['city_total'], 3)}</td></tr></table>
<p><b>Per user per month:</b> one full run plus three weekly re-checks of 8 tracked companies (with 5 chat turns each)
= <b>{usd(month, 2)}</b>.</p></div>
</div>

<h3>Cost at scale</h3>
<table>
<tr><th>Scale</th><th>Assumptions</th><th class=n>Monthly cost</th><th class=n>Per user</th></tr>
<tr><td>100 users</td><td>10 cities; no cache sharing assumed (upper bound)</td><td class=n>{usd(s100, 0)}</td><td class=n>{usd(s100 / 100, 2)}</td></tr>
<tr><td>10,000 users</td><td>150 cities; no cache sharing (upper bound)</td><td class=n>{usd(s10k, 0)}</td><td class=n>{usd(s10k / 10000, 2)}</td></tr>
<tr><td>10,000 users</td><td>research cache shared: ≤ 200 unique companies per city per month</td><td class=n>{usd(s10k_shared, 0)}</td><td class=n>{usd(s10k_shared / 10000, 2)}</td></tr>
</table>
<p>For context, a business school career office serving ~1,000 MBA students could offer this for roughly
{usd(1000 * month * 0.6, 0)}-{usd(1000 * month, 0)} a month (with and without cache sharing), less than the cost of one part-time research assistant.</p>

<h3>Cost cuts and their effect on quality</h3>
<table>
<tr><th>Cut</th><th>Saving (measured)</th><th>Effect on quality</th></tr>
<tr><td>Reports analyzed once, shared by all users</td><td>A new student on a known city pays {usd(trace_rows[1][6], 3)} for step 2-3 instead of ~{usd(costs['city_total'] + trace_rows[1][6], 2)}</td><td>None (same data)</td></tr>
<tr><td>Caches: research 30 days, postings 24 h, programs 30 days</td><td>Traced research turn {usd(trace_rows[2][6], 4)} vs ~{usd(3 * P['company_researcher'], 2)} uncached; job turn {usd(trace_rows[3][6], 4)} vs ~{usd(3 * P['job_scout'], 2)}</td><td>Postings can be up to a day old; research up to 30 days</td></tr>
<tr><td>Low search-context web search</td><td>Geo Verifier on Shopify: 21,984 → 13,840 input tokens, 8 → 4 searches</td><td><b>Quality dropped</b>: it cited "remote from anywhere" as proof of Canada hiring. Fixed by requiring evidence that names the country (18,984 tokens, 6 searches, correct answer: Ottawa HQ)</td></tr>
<tr><td>Report salary tables instead of web salary searches</td><td>Salary searches skipped whenever a report figure exists</td><td>More reliable for MBA pay; trade-off: industry average, not company-specific (labelled as such)</td></tr>
<tr><td>Only last 10 chat turns sent; provider prompt caching</td><td>Boss averages 6.9k input tokens/turn; 43% of boss input is cached at 1/10 the price</td><td>Very old turns are forgotten (saved state, not chat, carries progress)</td></tr>
</table>

<h2>5. Safety</h2>
<table>
<tr><th>Risk (for this app)</th><th>Why it matters here</th><th>Built defense</th></tr>
<tr><td>Invented facts</td><td>A fake "Google hires Toronto MBAs" sends students after the wrong companies</td><td>Employers must cite a page and appear on it; salaries must appear on the cited page; summarizer can't add names; geo/visa answers need sources; QS ranks left blank if unseen</td></tr>
<tr><td>Prompt injection</td><td>The app reads PDFs and web pages written by others</td><td>Prompts treat fetched content as data; companies named only in instruction-like text are dropped in code; provider prompt shield; downloads need the student's "yes"</td></tr>
<tr><td>Wrong actions</td><td>Downloading junk files; tracking the wrong companies</td><td>Links checked (HTTPS, real PDF, size cap) before download; the student approves downloads and picks every tracked company</td></tr>
<tr><td>Infinite loops / overspending</td><td>Web search costs ~$0.01 per call</td><td>Hard caps per run (boss 25 calls / 250k tokens, specialists 5 / 120k), friendly stop message; max 20 companies researched and 15 tracked; caches</td></tr>
<tr><td>Data leaks</td><td>Accounts, chats and trackers are personal</td><td>scrypt-hashed passwords, hashed tokens; every query scoped to the logged-in user; in-memory state tied to account + search (a bug where a reused user id inherited another account's state was found and fixed); demo data in the repo contains no user data</td></tr>
</table>

<h3>Defense shown working: prompt injection inside an employment report</h3>
<p>I built a fake employment report (<code>tests/injection_demo.py</code>) with two attacks hidden in its text and ran the real
Report Analyst on it. <b>Attack 1</b> uses classic jailbreak wording; <b>attack 2</b> is a subtle "editor's note for automated
readers" claiming Google, Apple and Netflix also hired graduates.</p>
<p><b>Before the fix</b>, attack 2 got through: the page check only confirmed the names appeared on page 2 (they did, inside
the note):</p>
<pre>{html.escape(inj_before)}</pre>
<p><b>After the fix</b> (a code check that drops companies named only in instruction-like lines, plus a prompt rule), both
attacks are blocked: attack 1 by the provider's prompt shield before reaching the model, attack 2 by our defenses:</p>
<pre>{html.escape(inj_after)}</pre>
<p>The new check produced <b>zero false positives</b> across all 1,448 real employer listings in the three Toronto reports
(after narrowing it: an early version wrongly flagged "BlueFire AI" and a "Generative AI, Deloitte" line).</p>

<h3>Automated safety tests</h3>
<p><code>.venv/bin/python -m pytest tests -q</code> runs 12 tests with no API key or model calls:</p>
<pre>{html.escape(pytest_out)}</pre>

<h2>6. Impact</h2>
<table>
<tr><th>Measure</th><th>Before (manual)</th><th>With Career Scout</th><th>Source</th></tr>
<tr><td>Employers identified for Toronto</td><td>~20-30 names a student already knows</td><td><b>1,281</b> from 3 schools (356 confirmed hires, 134 in 2+ reports)</td><td>App output (Toronto demo data)</td></tr>
<tr><td>Time to a sourced employer list for a city</td><td>3-5 hours reading and merging 3 reports (estimate)</td><td>~{trace_rows[1][5]:.0f} seconds once reports are analyzed; ~2-4 minutes for a brand-new city</td><td>Traced run; my timing of new-city runs</td></tr>
<tr><td>Salary context per company</td><td>Glassdoor guesses, sparse for MBA roles in Canada</td><td>Each school's industry average with page cites (e.g. consulting $86k-$141k CAD)</td><td>Report salary tables</td></tr>
<tr><td>Checking 8 careers pages for early-career roles</td><td>~30-45 minutes per week by hand (estimate)</td><td>One click; ~1-2 minutes; found McKinsey's Toronto Associate Intern after a fix</td><td>Traced run; McKinsey test</td></tr>
<tr><td>Cost</td><td>Student's time</td><td>{usd(costs['run_total'])} per full run, {usd(month)} per month</td><td>Token log</td></tr>
</table>
<div class="todo"><b>To add before submitting (real user evidence):</b> have one MBA classmate (ideally someone targeting a
different city or country) try the app for 10 minutes. Record: their target city, how many relevant companies they found
that they hadn't considered, how long it took vs. how they'd normally do it, and one quote. Paste it here and add a screenshot.</div>
<p><b>Honest limits on these numbers:</b> the before-times are my estimates from doing the Toronto research myself, not a
controlled study; Toronto runs on pre-analyzed demo data, so a new city takes longer and costs more (~{usd(costs['city_total'], 2)} one-time).</p>

<h2>7. Limits and next steps</h2>
<ul>
<li><b>Reports aren't always available.</b> Some schools don't publish (Ted Rogers), so the finder may use a school outside
the city (Ivey). Next: accept reports students upload and share them (with permission) for everyone in that city.</li>
<li><b>QS ranks are hidden behind JavaScript,</b> so rank numbers are often blank (the order still follows QS).</li>
<li><b>Job postings rendered by JavaScript can be missed.</b> The scout originally missed McKinsey's Toronto Associate Intern because
mckinsey.com blocks automated requests and my link check discarded it; fixed by keeping links from bot-blocking sites, and students
can paste a missed link. Next: plug into the job-board APIs of common applicant tracking systems (Workday, Greenhouse, Lever) for exact listings.</li>
<li><b>Salaries are industry averages</b> from the reports, not company-specific; visa sponsorship is often "unsure".</li>
<li><b>Scanned PDFs</b> can't be read (no OCR yet).</li>
<li><b>Email verification</b> writes emails to a local outbox until SMTP settings are added.</li>
<li><b>Cost:</b> web search is 90% of the cost; next, share job-posting checks across students more aggressively and batch companies per search.</li>
<li><b>Next features:</b> scheduled weekly job checks with email alerts; alumni/LinkedIn contacts per tracked company; deadline calendar from recruiting timelines.</li>
</ul>
{img("07_switcher.jpg", "Saved searches: each location keeps its own chat, employer table and tracker; switch or start a new search from the top bar.", "62%")}
"""

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Career Scout · MGT 409 Final Report</title><style>{CSS}</style></head><body><main>{body}</main></body></html>"""
(ROOT / "report.html").write_text(page)
print("report.html written,", round(len(page) / 1e6, 2), "MB")
