import { Me, TrackerDetail } from "../api";
import { NextAction } from "../nextStep";

type Props = {
  me: Me | null;
  tracker: TrackerDetail[];
  next: NextAction | null;
  onNext: (a: NextAction) => void;
  onStep: (step: number) => void;
  onOpenTracker: () => void;
};

export default function Sidebar({ me, tracker, next, onNext, onStep, onOpenTracker }: Props) {
  const location = me?.country ? `${me.city ? me.city + ", " : ""}${me.country}` : null;
  const done = me?.steps_done.length ?? 0;
  const total = me?.steps.length ?? 6;
  const jobs = tracker.reduce((n, r) => n + r.jobs.length, 0);
  const applied = tracker.filter((r) => r.status !== "interested").length;

  return (
    <aside className="sidebar">
      {me && (
        <div className="card side-card">
          <div className="side-head">
            <h3>Your path</h3>
            <span className="count">{done}/{total}</span>
          </div>
          <div className="progress"><div className="progress-fill" style={{ width: `${(done / total) * 100}%` }} /></div>
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
              <button key={next.label} className="btn btn-primary next-btn" onClick={() => onNext(next)}>{next.label}</button>
              <p className="muted small">{next.hint}</p>
            </div>
          )}
        </div>
      )}

      <div className="card side-card">
        <h3>This search</h3>
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
          <p className="muted small">Pick 5–15 companies from the employer table to track their careers pages and jobs.</p>
        ) : (
          <>
            <div className="stats">
              <div><strong>{tracker.length}</strong><span>tracked</span></div>
              <div><strong>{jobs}</strong><span>open roles</span></div>
              <div><strong>{applied}</strong><span>in progress</span></div>
            </div>
            <button className="btn btn-ghost full" onClick={onOpenTracker}>Open tracker →</button>
          </>
        )}
      </div>
    </aside>
  );
}
