import { useState } from "react";
import { api, STATUSES, Status, TrackerDetail } from "../api";

type Props = {
  location: string | null;
  rows: TrackerDetail[];
  onChange: () => void;
  onAsk: (message: string) => void; // send a request to the boss (switches to Chat)
  onOpenEmployers: () => void;
};

const money = (n: number | null) => (n ? `$${Math.round(n / 1000)}k` : "?");

function salary(r: TrackerDetail["research"]) {
  if (!r || (!r.salary_low && !r.salary_high)) return null;
  const range = r.salary_low === r.salary_high || !r.salary_high ? money(r.salary_low) : `${money(r.salary_low)}–${money(r.salary_high)}`;
  return `${range}${r.currency ? " " + r.currency : ""}`;
}

const when = (ts: string | null) => {
  if (!ts) return null;
  const days = Math.floor((Date.now() - new Date(ts.replace(" ", "T") + "Z").getTime()) / 86400000);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
};

export default function TrackerTable({ location, rows, onChange, onAsk, onOpenEmployers }: Props) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState<string | null>(null); // two-click remove

  if (rows.length === 0) {
    return (
      <section className="card tracker-page tracker-empty">
        <h2>Your tracker is empty</h2>
        <p className="muted">
          Build your target list in the Employers table: tick the companies you like and press <strong>Track</strong> or{" "}
          <strong>Research &amp; track</strong>. They'll show up here with their careers page, research and open jobs.
        </p>
        <button className="btn btn-primary" onClick={onOpenEmployers}>Open the employer table →</button>
      </section>
    );
  }

  const toggle = (c: string) => setOpen((s) => {
    const n = new Set(s);
    n.has(c) ? n.delete(c) : n.add(c);
    return n;
  });
  const setStatus = (company: string, status: Status) => api.updateTracker(company, status).then(onChange);
  const remove = (company: string) => {
    if (confirming !== company) return setConfirming(company);
    setConfirming(null);
    api.removeTracker(company).then(onChange);
  };

  const unresearched = rows.filter((r) => !r.research).map((r) => r.company);
  const totalJobs = rows.reduce((n, r) => n + r.jobs.length, 0);
  const checked = rows.some((r) => r.jobs_checked);

  return (
    <section className="card tracker-page">
      <div className="emp-head">
        <div>
          <h2>Your tracker{location ? ` · ${location}` : ""}</h2>
          <p className="muted small">
            {rows.length} compan{rows.length === 1 ? "y" : "ies"} · {totalJobs} open early-career role{totalJobs === 1 ? "" : "s"}
            {" · "}click a row for details
          </p>
        </div>
        <div className="tracker-actions">
          {unresearched.length > 0 && (
            <button className="btn btn-ghost" onClick={() => onAsk(`Please research my tracked companies: ${unresearched.join(", ")}.`)}>
              Research {unresearched.length} missing
            </button>
          )}
          <button className="btn btn-primary" onClick={() => onAsk("Check my tracked companies for job postings.")}>
            {checked ? "Check for new jobs" : "Find jobs for these companies"}
          </button>
        </div>
      </div>

      <div className="table-wrap">
        <table className="emp-table trk-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Status</th>
              <th>Salary (avg base)</th>
              <th>Visa</th>
              <th>Open roles</th>
              <th>Careers page</th>
              <th className="col-act" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isOpen = open.has(r.company);
              const sal = salary(r.research);
              return [
                <tr key={r.company} className={`trk-row ${isOpen ? "open" : ""}`} onClick={() => toggle(r.company)}>
                  <td className="col-company"><span className="caret">{isOpen ? "▾" : "▸"}</span>{r.company}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <select className={`status status-${r.status}`} value={r.status} onChange={(e) => setStatus(r.company, e.target.value as Status)}>
                      {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </td>
                  <td>{sal ?? <span className="muted small">{r.research ? "n/a" : "not researched"}</span>}</td>
                  <td>{r.research ? <span className={`visa visa-${r.research.visa}`}>{r.research.visa}</span> : <span className="muted small">–</span>}</td>
                  <td>
                    {r.jobs.length > 0 ? (
                      <span className="jobs-count">{r.jobs.length} open</span>
                    ) : (
                      <span className="muted small">{r.jobs_checked ? "none right now" : "not checked"}</span>
                    )}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {r.careers_url && r.careers_url !== "-" ? (
                      <a className="btn-mini" href={r.careers_url} target="_blank" rel="noreferrer">Careers ↗</a>
                    ) : (
                      <span className="muted small">–</span>
                    )}
                  </td>
                  <td className="col-act" onClick={(e) => e.stopPropagation()}>
                    {confirming === r.company ? (
                      <button className="btn-mini danger" onClick={() => remove(r.company)} onBlur={() => setConfirming(null)} autoFocus>Remove?</button>
                    ) : (
                      <button className="x always" title="Remove from tracker" onClick={() => remove(r.company)}>×</button>
                    )}
                  </td>
                </tr>,
                isOpen && (
                  <tr key={r.company + "-detail"} className="trk-detail">
                    <td colSpan={7}>
                      <div className="detail-grid">
                        <div>
                          <h4>Research</h4>
                          {r.research ? (
                            <dl className="facts">
                              <dt>MBA roles</dt><dd>{r.research.roles.join(", ") || "–"}</dd>
                              <dt>Offices</dt><dd>{r.research.locations.join(", ") || "–"}</dd>
                              <dt>Recruiting</dt><dd>{r.research.recruiting || "–"}</dd>
                              {r.research.salary_note && (<><dt>Salary note</dt><dd className="small">{r.research.salary_note}</dd></>)}
                            </dl>
                          ) : (
                            <p className="muted small">
                              Not researched yet.{" "}
                              <button className="link" onClick={() => onAsk(`Please research ${r.company}.`)}>Research it</button>
                            </p>
                          )}
                        </div>
                        <div>
                          <h4>Open roles {r.jobs_checked && <span className="muted small">· checked {when(r.jobs_checked)}</span>}</h4>
                          {r.jobs.length === 0 ? (
                            <p className="muted small">{r.jobs_note || (r.jobs_checked ? "No early-career openings right now." : "Not checked yet.")}</p>
                          ) : (
                            r.jobs.map((j) => (
                              <a key={j.url} className="posting" href={j.url} target="_blank" rel="noreferrer">
                                <span className="posting-title">{j.title}</span>
                                <span className="posting-meta">
                                  <span className={`tag tag-${j.level}`}>{j.level}</span>
                                  {j.location.replace(/\s*\(location matched after hire\)/i, "")}
                                  {j.location_flexible ? <em> · location matched after hire</em> : null}
                                </span>
                              </a>
                            ))
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>
      <div className="emp-foot" />
    </section>
  );
}
