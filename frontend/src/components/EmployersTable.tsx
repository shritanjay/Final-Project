import { useMemo, useState } from "react";
import { EmployerView, TrackerRow } from "../api";

type SortKey = "company" | "industry" | "schools";
type Props = {
  view: EmployerView | null;
  tracker: TrackerRow[];
  onTrack: (companies: string[]) => Promise<string>;
  onResearch: (companies: string[]) => void;
};

const PAGE = 60;

export default function EmployersTable({ view, tracker, onTrack, onResearch }: Props) {
  const [topOnly, setTopOnly] = useState(true);
  const [query, setQuery] = useState("");
  const [industries, setIndustries] = useState<Set<string>>(new Set());
  const [schools, setSchools] = useState<Set<string>>(new Set());
  const [multiOnly, setMultiOnly] = useState(false);
  const [hiredOnly, setHiredOnly] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "schools", dir: -1 });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [limit, setLimit] = useState(PAGE);
  const [toast, setToast] = useState("");
  const [fullOverview, setFullOverview] = useState(false);

  const tracked = useMemo(() => new Set(tracker.map((t) => t.company.toLowerCase())), [tracker]);
  const base = useMemo(() => (view ? view.rows.filter((r) => !topOnly || r.top_pick) : []), [view, topOnly]);
  const allSchools = useMemo(() => [...new Set(view?.rows.flatMap((r) => r.schools.map((s) => s.school)) ?? [])].sort(), [view]);

  // Industry chips show counts for the current search/school filters (but not the industry filter itself).
  const preIndustry = useMemo(() => {
    const q = query.trim().toLowerCase();
    return base.filter(
      (r) =>
        (!q || r.company.toLowerCase().includes(q)) &&
        (!multiOnly || r.schools.length > 1) &&
        (!hiredOnly || r.hired) &&
        (schools.size === 0 || r.schools.some((s) => schools.has(s.school))),
    );
  }, [base, query, multiOnly, hiredOnly, schools]);

  const industryCounts = useMemo(() => {
    const m = new Map<string, number>();
    preIndustry.forEach((r) => m.set(r.industry, (m.get(r.industry) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [preIndustry]);

  const rows = useMemo(() => {
    const out = preIndustry.filter((r) => industries.size === 0 || industries.has(r.industry));
    const val = (r: (typeof out)[number]) =>
      sort.key === "schools" ? r.schools.filter((s) => s.hired).length * 10 + r.schools.length : sort.key === "industry" ? r.industry.toLowerCase() : r.company.toLowerCase();
    return out.sort((a, b) => {
      const x = val(a), y = val(b);
      if (x !== y) return (x > y ? 1 : -1) * sort.dir;
      return a.company.localeCompare(b.company);
    });
  }, [preIndustry, industries, sort]);

  if (!view) {
    return (
      <section className="card employers employers-empty">
        <h2>No employer table yet</h2>
        <p className="muted">
          Tell the scout where you want to work and get the employment reports. Once the employers are pulled out,
          they'll show up here so you can filter and pick the ones to research.
        </p>
      </section>
    );
  }

  const toggle = (set: Set<string>, value: string, setter: (s: Set<string>) => void) => {
    const next = new Set(set);
    next.has(value) ? next.delete(value) : next.add(value);
    setter(next);
  };
  const sortBy = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: (s.dir * -1) as 1 | -1 } : { key, dir: key === "schools" ? -1 : 1 }));
  const arrow = (key: SortKey) => (sort.key === key ? (sort.dir === 1 ? " ↑" : " ↓") : "");
  const visible = rows.slice(0, limit);
  const allVisibleSelected = visible.length > 0 && visible.every((r) => selected.has(r.company));
  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 3500);
  };

  async function track(companies: string[]) {
    flash(await onTrack(companies));
    setSelected(new Set());
  }

  return (
    <section className="card employers">
      <div className="emp-head">
        <div>
          <h2>Employers in {view.location}</h2>
          <p className="muted small">
            From {view.files.length} employment report{view.files.length === 1 ? "" : "s"} ·{" "}
            {view.rows.length} employers · {view.rows.filter((r) => r.hired).length} confirmed hires ·{" "}
            {view.rows.filter((r) => r.schools.length > 1).length} listed by 2+ schools
          </p>
        </div>
        <div className="seg">
          <button className={topOnly ? "on" : ""} onClick={() => (setTopOnly(true), setLimit(PAGE))}>
            Top picks <span>{view.rows.filter((r) => r.top_pick).length}</span>
          </button>
          <button className={!topOnly ? "on" : ""} onClick={() => (setTopOnly(false), setLimit(PAGE))}>
            All <span>{view.rows.length}</span>
          </button>
        </div>
      </div>

      {view.overview && (
        <p className={`emp-overview ${fullOverview ? "" : "clamp"}`} onClick={() => setFullOverview((v) => !v)} title="Click to expand">
          {view.overview}
        </p>
      )}

      <div className="emp-controls">
        <input className="search" placeholder="Search companies…" value={query} onChange={(e) => (setQuery(e.target.value), setLimit(PAGE))} />
        <div className="school-filter">
          {allSchools.map((s) => (
            <button key={s} className={`chip-sm ${schools.has(s) ? "on" : ""}`} onClick={() => toggle(schools, s, setSchools)}>
              {s}
            </button>
          ))}
          <label className="check" title="Only companies a report says hired its MBA grads">
            <input type="checkbox" checked={hiredOnly} onChange={(e) => setHiredOnly(e.target.checked)} />
            Confirmed hires
          </label>
          <label className="check">
            <input type="checkbox" checked={multiOnly} onChange={(e) => setMultiOnly(e.target.checked)} />
            2+ schools
          </label>
        </div>
      </div>

      <div className="industry-chips">
        {industryCounts.map(([name, n]) => (
          <button key={name} className={`chip-sm ${industries.has(name) ? "on" : ""}`} onClick={() => toggle(industries, name, setIndustries)}>
            {name} <span>{n}</span>
          </button>
        ))}
        {(industries.size > 0 || schools.size > 0 || multiOnly || hiredOnly || query) && (
          <button className="link small" onClick={() => (setIndustries(new Set()), setSchools(new Set()), setMultiOnly(false), setHiredOnly(false), setQuery(""))}>
            Clear filters
          </button>
        )}
      </div>

      <div className="table-wrap">
        <table className="emp-table">
          <thead>
            <tr>
              <th className="col-check">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={() => {
                    const next = new Set(selected);
                    visible.forEach((r) => (allVisibleSelected ? next.delete(r.company) : next.add(r.company)));
                    setSelected(next);
                  }}
                  title="Select all shown"
                />
              </th>
              <th onClick={() => sortBy("company")}>Company{arrow("company")}</th>
              <th onClick={() => sortBy("industry")}>Industry{arrow("industry")}</th>
              <th onClick={() => sortBy("schools")}>Schools{arrow("schools")}</th>
              <th className="col-act" />
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => {
              const isTracked = tracked.has(r.company.toLowerCase());
              return (
                <tr key={r.company} className={selected.has(r.company) ? "sel" : ""}>
                  <td className="col-check">
                    <input type="checkbox" checked={selected.has(r.company)} onChange={() => toggle(selected, r.company, setSelected)} />
                  </td>
                  <td className="col-company">
                    {r.company}
                    {r.top_pick && !topOnly && <span className="pick" title="Top pick">★</span>}
                  </td>
                  <td><span className="ind">{r.industry}</span></td>
                  <td className="col-schools">
                    {r.schools.map((s) => (
                      <span key={s.school} className={`school ${s.hired ? "hired" : "recruit"}`}
                        title={s.hired ? `${s.school}'s report says it hired grads` : `Recruits / engages at ${s.school} (hire not confirmed)`}>
                        {s.hired && "✓ "}{s.school}
                      </span>
                    ))}
                  </td>
                  <td className="col-act">
                    {isTracked ? (
                      <span className="tracked">Tracked ✓</span>
                    ) : (
                      <button className="btn-mini" onClick={() => track([r.company])}>+ Track</button>
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="muted empty-row">No employers match these filters.</td>
              </tr>
            )}
          </tbody>
        </table>
        {rows.length > limit && (
          <button className="btn btn-ghost more" onClick={() => setLimit((l) => l + PAGE)}>
            Show more ({rows.length - limit} left)
          </button>
        )}
      </div>

      <div className="emp-foot">
        <span className="muted small">
          Showing {visible.length} of {rows.length} · <span className="school hired">✓ hired grads</span>{" "}
          <span className="school recruit">recruits there</span>
        </span>
        {toast && <span className="toast">{toast}</span>}
      </div>

      {selected.size > 0 && (
        <div className="selbar">
          <strong>{selected.size} selected</strong>
          <button className="btn btn-primary" onClick={() => (onResearch([...selected]), setSelected(new Set()))}>
            Research selected
          </button>
          <button className="btn btn-ghost" onClick={() => track([...selected])}>Add to tracker</button>
          <button className="link" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}
    </section>
  );
}
