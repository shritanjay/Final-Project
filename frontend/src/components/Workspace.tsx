import { useCallback, useEffect, useRef, useState } from "react";
import { api, EmployerView, Me, Posting, TrackerRow } from "../api";
import Brand from "./Brand";
import Chat from "./Chat";
import EmployersTable from "./EmployersTable";
import Sidebar from "./Sidebar";
import { actionFor, NextAction, nextAction } from "../nextStep";

export default function Workspace({ onLogout }: { onLogout: () => void }) {
  const [me, setMe] = useState<Me | null>(null);
  const [tracker, setTracker] = useState<TrackerRow[]>([]);
  const [postings, setPostings] = useState<Posting[]>([]);
  const [verifySent, setVerifySent] = useState(false);
  const [employers, setEmployers] = useState<EmployerView | null>(null);
  const [tab, setTab] = useState<"chat" | "employers">("chat");
  const [outgoing, setOutgoing] = useState<{ text: string; id: number } | null>(null);
  const lastTable = useRef<string | null | undefined>(undefined);

  // Re-read saved state after every assistant reply (the boss may have changed the tracker, location, postings
  // or built a new employer table). A freshly built table opens its tab automatically.
  const refresh = useCallback(async () => {
    const [m, t, e] = await Promise.all([api.me(), api.tracker(), api.employers()]);
    setMe(m);
    setTracker(t);
    setEmployers(e);
    if (lastTable.current !== undefined && e && e.created_at !== lastTable.current) setTab("employers");
    lastTable.current = e?.created_at ?? null;
    setPostings(m.country ? await api.postings() : []);
  }, []);

  async function track(companies: string[]) {
    const r = await api.addTracker(companies);
    refresh();
    const parts = [r.added.length ? `Added ${r.added.length} to your tracker (${r.count}/${r.max}).` : "Already tracked."];
    if (r.full.length) parts.push(`Tracker is full, so ${r.full.length} weren't added.`);
    return parts.join(" ");
  }

  function research(companies: string[]) {
    setTab("chat");
    setOutgoing({ text: `Please research these companies: ${companies.join(", ")}.`, id: Date.now() });
  }

  useEffect(() => {
    refresh().catch(() => {});
  }, [refresh]);

  const [focusTick, setFocusTick] = useState(0);
  const next = nextAction(me, tracker, employers);

  function runAction(a: NextAction) {
    if (a.kind === "employers") return setTab("employers");
    setTab("chat");
    if (a.kind === "focus") return setFocusTick((t) => t + 1);
    setOutgoing({ text: a.message!, id: Date.now() });
  }

  // Clicking a step in "Your path" jumps to that step.
  function goToStep(step: number) {
    const list = tracker.map((t) => t.company).slice(0, 15).join(", ");
    runAction(actionFor(step, tracker.length, list, !!employers));
  }

  async function logout() {
    await api.logout().catch(() => {});
    localStorage.removeItem("career-scout-token");
    onLogout();
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <Brand small />
        <div className="topbar-right">
          {me && <span className="muted">{me.email}</span>}
          <button className="btn btn-ghost" onClick={logout}>Log out</button>
        </div>
      </header>

      {me && !me.email_verified && (
        <div className="banner">
          Please verify your email so you can reset your password if you ever need to.{" "}
          {verifySent ? (
            <strong>Link sent. Check your inbox.</strong>
          ) : (
            <button className="link" onClick={() => api.resendVerify().then(() => setVerifySent(true))}>Resend link</button>
          )}
        </div>
      )}

      <main className="workspace">
        <div className="main-col">
          <nav className="tabs">
            <button className={tab === "chat" ? "on" : ""} onClick={() => setTab("chat")}>Chat</button>
            <button className={tab === "employers" ? "on" : ""} onClick={() => setTab("employers")}>
              Employers {employers && <span>{employers.rows.length}</span>}
            </button>
          </nav>
          <div className={tab === "chat" ? "tab-pane" : "tab-pane hidden"}>
            <Chat
              onReply={refresh}
              onReset={() => {
                setTab("chat");
                lastTable.current = undefined; // don't auto-jump to a table on this refresh
                refresh();
              }}
              returning={!!me?.country}
              hasTracker={tracker.length > 0}
              outgoing={outgoing}
              focusTick={focusTick}
            />
          </div>
          <div className={tab === "employers" ? "tab-pane" : "tab-pane hidden"}>
            <EmployersTable view={employers} tracker={tracker} onTrack={track} onResearch={research} next={next} onNext={runAction} />
          </div>
        </div>
        <Sidebar me={me} tracker={tracker} postings={postings} onChange={refresh} next={next} onNext={runAction} onStep={goToStep} />
      </main>
    </div>
  );
}
