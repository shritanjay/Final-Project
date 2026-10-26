import { useEffect, useRef, useState } from "react";
import { Search } from "../api";

type Props = {
  searches: Search[];
  onSwitch: (id: number | "new") => Promise<void>;
  onDelete: (id: number) => Promise<void>;
};

// Dropdown in the top bar: each saved search is one location with its own chat, employers and tracker.
export default function SearchSwitcher({ searches, onSwitch, onDelete }: Props) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const active = searches.find((s) => s.active);

  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && (setOpen(false), setConfirming(null));
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  if (!active) return <div className="switcher" />;

  return (
    <div className="switcher" ref={ref}>
      <button className={`switcher-btn ${open ? "open" : ""}`} onClick={() => setOpen((o) => !o)}>
        <span className="switcher-pin">◎</span>
        <span className="switcher-label">{active.label}</span>
        <span className="switcher-caret">▾</span>
      </button>
      {open && (
        <div className="switcher-menu card">
          <div className="switcher-title">Your searches</div>
          {searches.map((s) => (
            <div key={s.id} className={`switcher-item ${s.active ? "active" : ""}`}>
              <button className="switcher-pick" onClick={() => (setOpen(false), !s.active && onSwitch(s.id))}>
                <span className="switcher-name">{s.label}</span>
                <span className="switcher-meta">
                  {s.steps_done}/6 steps · {s.tracked} tracked
                </span>
              </button>
              {searches.length > 1 &&
                (confirming === s.id ? (
                  <button className="btn-mini danger" onClick={() => (setConfirming(null), onDelete(s.id))}>Delete?</button>
                ) : (
                  <button className="x always" title="Delete this search" onClick={() => setConfirming(s.id)}>×</button>
                ))}
            </div>
          ))}
          <button className="switcher-new" onClick={() => (setOpen(false), onSwitch("new"))}>＋ New search</button>
        </div>
      )}
    </div>
  );
}
