import { useCallback, useEffect, useRef, useState } from "react";
import { api, ChatAction, EmployerView, Me, Search, TrackerDetail } from "../api";
import { actionFor, NextAction, nextAction } from "../nextStep";
import Brand from "./Brand";
import Chat from "./Chat";
import EmployersTable from "./EmployersTable";
import SearchSwitcher from "./SearchSwitcher";
import Sidebar from "./Sidebar";
import TrackerTable from "./TrackerTable";

type Tab = "chat" | "employers" | "tracker";

export default function Workspace({ onLogout }: { onLogout: () => void }) {
  const [me, setMe] = useState<Me | null>(null);
  const [tracker, setTracker] = useState<TrackerDetail[]>([]);
  const [trackerLoc, setTrackerLoc] = useState<string | null>(null);
  const [employers, setEmployers] = useState<EmployerView | null>(null);
  const [searches, setSearches] = useState<Search[]>([]);
  const [verifySent, setVerifySent] = useState(false);
  const [tab, setTab] = useState<Tab>("chat");
  const [outgoing, setOutgoing] = useState<{ text: string; id: number } | null>(null);
  const [focusTick, setFocusTick] = useState(0);
  const [celebrate, setCelebrate] = useState<string | null>(null); // "Step 3 done" banner
  const prevDone = useRef<number[] | null>(null);
  const prevSearch = useRef<number | null>(null);

  // Re-read saved state after every assistant reply / UI action.
  const refresh = useCallback(async () => {
    const [m, t, e, s] = await Promise.all([api.me(), api.trackerDetails(), api.employers(), api.searches()]);
    // Celebrate newly finished steps (not on first load or when switching searches).
    if (prevDone.current && prevSearch.current === m.search_id) {
      const fresh = m.steps_done.filter((n) => !prevDone.current!.includes(n));
      if (fresh.length) {
        const n = Math.max(...fresh);
        setCelebrate(`Step ${n} done: ${m.steps[n - 1]} ✓`);
        setTimeout(() => setCelebrate(null), 3200);
      }
    }
    prevDone.current = m.steps_done;
    prevSearch.current = m.search_id;
    setMe(m);
    setTracker(t.rows);
    setTrackerLoc(t.location);
    setEmployers(e);
    setSearches(s);
  }, []);

  useEffect(() => {
    refresh().catch(() => setTimeout(() => refresh().catch(() => {}), 1200)); // one retry on a failed first load
  }, [refresh]);

  async function track(companies: string[]) {
    const r = await api.addTracker(companies);
    refresh();
    const parts = [r.added.length ? `Added ${r.added.length} to your tracker (${r.count}/${r.max}).` : "Already tracked."];
    if (r.full.length) parts.push(`Tracker is full, so ${r.full.length} weren't added.`);
    return parts.join(" ");
  }

  function ask(text: string) {
    setTab("chat");
    setOutgoing({ text, id: Date.now() });
  }

  const research = (companies: string[]) => ask(`Please research these companies: ${companies.join(", ")}.`);

  async function researchAndTrack(companies: string[]) {
    const msg = await track(companies);
    ask(`I've added ${companies.join(", ")} to my tracker. Please research them.`);
    return msg;
  }

  async function onChatAction(a: ChatAction) {
    if (a.type === "open_tab") setTab(a.tab);
    if (a.type === "track") return track(a.companies);
  }

  const next = nextAction(me, tracker, employers);

  function runNext(a: NextAction) {
    if (a.kind === "employers") return setTab("employers");
    if (a.kind === "focus") return setTab("chat"), setFocusTick((t) => t + 1);
    ask(a.message!);
  }

  // Clicking a step in "Your path" jumps to that step.
  function goToStep(step: number) {
    const list = tracker.map((t) => t.company).slice(0, 15).join(", ");
    if (step === 5 && tracker.length) return setTab("tracker");
    if (step === 3 && employers) return setTab("employers");
    runNext(actionFor(step, tracker.length, list, !!employers));
  }

  async function switchTo(id: number | "new") {
    if (id === "new") await api.newSearch();
    else await api.switchSearch(id);
    setTab("chat");
    await refresh();
  }

  async function removeSearch(id: number) {
    await api.deleteSearch(id);
    await refresh();
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
        <SearchSwitcher searches={searches} onSwitch={switchTo} onDelete={removeSearch} />
        <div className="topbar-right">
          {me && <span className="muted email">{me.email}</span>}
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

      {celebrate && <div className="celebrate" key={celebrate}>{celebrate}</div>}

      <main className="workspace">
        <div className="main-col">
          <nav className="tabs">
            <button className={tab === "chat" ? "on" : ""} onClick={() => setTab("chat")}>Chat</button>
            <button className={tab === "employers" ? "on" : ""} onClick={() => setTab("employers")}>
              Employers {employers && <span>{employers.rows.length}</span>}
            </button>
            <button className={tab === "tracker" ? "on" : ""} onClick={() => setTab("tracker")}>
              Tracker {tracker.length > 0 && <span>{tracker.length}</span>}
            </button>
          </nav>
          <div className={tab === "chat" ? "tab-pane" : "tab-pane hidden"}>
            <Chat
              searchId={me?.search_id ?? null}
              onReply={refresh}
              onReset={() => {
                setTab("chat");
                refresh();
              }}
              onAction={onChatAction}
              returning={!!me?.country}
              outgoing={outgoing}
              focusTick={focusTick}
            />
          </div>
          <div className={tab === "employers" ? "tab-pane" : "tab-pane hidden"}>
            <EmployersTable
              view={employers}
              tracker={tracker}
              onTrack={track}
              onResearch={research}
              onResearchAndTrack={researchAndTrack}
              next={next}
              onNext={runNext}
            />
          </div>
          <div className={tab === "tracker" ? "tab-pane" : "tab-pane hidden"}>
            <TrackerTable location={trackerLoc} rows={tracker} onChange={refresh} onAsk={ask} onOpenEmployers={() => setTab("employers")} />
          </div>
        </div>
        <Sidebar me={me} tracker={tracker} next={next} onNext={runNext} onStep={goToStep} onOpenTracker={() => setTab("tracker")} />
      </main>
    </div>
  );
}
