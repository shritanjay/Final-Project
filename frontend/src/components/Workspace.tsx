import { useCallback, useEffect, useState } from "react";
import { api, Me, Posting, TrackerRow } from "../api";
import Brand from "./Brand";
import Chat from "./Chat";
import Sidebar from "./Sidebar";

export default function Workspace({ onLogout }: { onLogout: () => void }) {
  const [me, setMe] = useState<Me | null>(null);
  const [tracker, setTracker] = useState<TrackerRow[]>([]);
  const [postings, setPostings] = useState<Posting[]>([]);
  const [verifySent, setVerifySent] = useState(false);

  // Re-read saved state after every assistant reply (the boss may have changed the tracker, location or postings).
  const refresh = useCallback(async () => {
    const [m, t] = await Promise.all([api.me(), api.tracker()]);
    setMe(m);
    setTracker(t);
    setPostings(m.country ? await api.postings() : []);
  }, []);

  useEffect(() => {
    refresh().catch(() => {});
  }, [refresh]);

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
        <Chat onReply={refresh} returning={tracker.length > 0} />
        <Sidebar me={me} tracker={tracker} postings={postings} onChange={refresh} />
      </main>
    </div>
  );
}
