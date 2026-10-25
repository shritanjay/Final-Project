import { FormEvent, useState } from "react";
import { api } from "../api";
import Brand from "./Brand";

export default function ResetPage({ token, onDone }: { token: string; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) return setError("Passwords don't match.");
    setBusy(true);
    setError("");
    try {
      await api.reset(token, password);
      setDone(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-shell">
      <Brand />
      <form className="card narrow-card" onSubmit={submit}>
        <h2>Choose a new password</h2>
        {done ? (
          <>
            <div className="alert alert-ok">Password updated. You've been logged out on all devices.</div>
            <button type="button" className="btn btn-primary" onClick={onDone}>Go to log in</button>
          </>
        ) : (
          <>
            <label>
              New password
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required autoComplete="new-password" />
            </label>
            <label>
              Confirm password
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} minLength={8} required autoComplete="new-password" />
            </label>
            {error && <div className="alert alert-error">{error}</div>}
            <button className="btn btn-primary" disabled={busy || !token}>{busy ? "Saving…" : "Save password"}</button>
          </>
        )}
      </form>
    </div>
  );
}
