import { api, Me, Posting, STATUSES, Status, TrackerRow } from "../api";
import { NextAction } from "../nextStep";

type Props = {
  me: Me | null;
  tracker: TrackerRow[];
  postings: Posting[];
  onChange: () => void;
  next: NextAction | null;
  onNext: (a: NextAction) => void;
  onStep: (step: number) => void;
};

export default function Sidebar({ me, tracker, postings, onChange, next, onNext, onStep }: Props) {
  const location = me?.country ? `${me.city ? me.city + ", " : ""}${me.country}` : null;
  const byCompany = postings.reduce<Record<string, Posting[]>>((acc, p) => {
    (acc[p.company] ||= []).push(p);
    return acc;
  }, {});

  const setStatus = (company: string, status: Status) => api.updateTracker(company, status).then(onChange);
  const remove = (company: string) => confirm(`Remove ${company} from your tracker?`) && api.removeTracker(company).then(onChange);

  return (
    <aside className="sidebar">
      {me && (
        <div className="card side-card">
          <div className="side-head">
            <h3>Your path</h3>
            <span className="count">{me.steps_done.length}/{me.steps.length}</span>
          </div>
          <ol className="path">
            {me.steps.map((name, i) => {
              const state = me.steps_done.includes(i + 1) ? "done" : me.next_step === i + 1 ? "now" : "todo";
              return (
                <li key={name} className={`path-${state}`}>
                  <button className="path-step" onClick={() => onStep(i + 1)} title={`Go to: ${name}`}>
                    <span className="path-dot">{state === "done" ? "✓" : i + 1}</span>
                    {name}
                  </button>
                </li>
              );
            })}
          </ol>
          {next && (
            <div className="next-box">
              <button className="btn btn-primary next-btn" onClick={() => onNext(next)}>{next.label}</button>
              <p className="muted small">{next.hint}</p>
            </div>
          )}
        </div>
      )}

      <div className="card side-card">
        <h3>Your search</h3>
        <dl className="facts">
          <dt>Location</dt>
          <dd>{location ?? <span className="muted">Not set yet</span>}</dd>
          <dt>Job search</dt>
          <dd>All internship, MBA &amp; early-career roles</dd>
        </dl>
      </div>

      <div className="card side-card">
        <div className="side-head">
          <h3>Tracker</h3>
          <span className="count">{tracker.length}/15</span>
        </div>
        {tracker.length === 0 ? (
          <p className="muted small">Ask the scout to add companies once you've picked your favourites.</p>
        ) : (
          <ul className="tracker">
            {tracker.map((t) => (
              <li key={t.company}>
                <div className="tracker-main">
                  {t.careers_url !== "-" ? (
                    <a href={t.careers_url} target="_blank" rel="noreferrer">{t.company}</a>
                  ) : (
                    <span>{t.company}</span>
                  )}
                  <button className="x" title="Remove" onClick={() => remove(t.company)}>×</button>
                </div>
                <select className={`status status-${t.status}`} value={t.status} onChange={(e) => setStatus(t.company, e.target.value as Status)}>
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card side-card">
        <div className="side-head">
          <h3>Open roles</h3>
          <span className="count">{postings.length}</span>
        </div>
        {postings.length === 0 ? (
          <p className="muted small">Ask the scout to check your tracked companies for internship, MBA and early-career postings.</p>
        ) : (
          Object.entries(byCompany).map(([company, list]) => (
            <div key={company} className="postings-group">
              <h4>{company}</h4>
              {list.map((p) => (
                <a key={p.url} className="posting" href={p.url} target="_blank" rel="noreferrer">
                  <span className="posting-title">{p.title}</span>
                  <span className="posting-meta">
                    <span className={`tag tag-${p.level}`}>{p.level}</span>
                    {p.location.replace(/\s*\(location matched after hire\)/i, "")}
                    {p.location_flexible ? <em> · location matched after hire</em> : null}
                  </span>
                </a>
              ))}
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
