import { FormEvent, useState } from "react";
import { api, setToken } from "../api";
import Brand from "./Brand";

type Mode = "login" | "signup" | "forgot";

export default function AuthPage({ onAuthed }: { onAuthed: () => void }) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const switchTo = (m: Mode) => {
    setMode(m);
    setError("");
    setNotice("");
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "forgot") {
        await api.forgot(email);
        setNotice("If that email has an account, a reset link is on its way. Check your inbox.");
      } else {
        const { token } = mode === "signup" ? await api.signup(email, password) : await api.login(email, password);
        setToken(token);
        onAuthed();
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <section className="auth-story">
        <Brand />
        <h1>
          Find the companies that <em>actually hire</em> MBAs where you want to live.
        </h1>
        <p>
          Career Scout reads the employment reports of the top MBA programs in your city, groups employers by
          industry, researches pay and roles, and watches careers pages for internships and MBA openings.
        </p>
        <ol className="auth-steps">
          <li><span>01</span>Pick a country and city</li>
          <li><span>02</span>We read the top schools' employment reports</li>
          <li><span>03</span>Research, rank, and track 5–15 companies</li>
          <li><span>04</span>Check their careers pages for new postings</li>
        </ol>
      </section>

      <section className="auth-card-wrap">
        <form className="card auth-card" onSubmit={submit}>
          <h2>{mode === "login" ? "Welcome back" : mode === "signup" ? "Create your account" : "Reset your password"}</h2>
          <p className="muted">
            {mode === "login" && "Log in to pick up where you left off."}
            {mode === "signup" && "Your tracker and searches are saved to your account."}
            {mode === "forgot" && "We'll email you a link to set a new password."}
          </p>

          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          {mode !== "forgot" && (
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={mode === "signup" ? 8 : undefined}
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
              />
              {mode === "signup" && <small className="muted">At least 8 characters.</small>}
            </label>
          )}

          {error && <div className="alert alert-error">{error}</div>}
          {notice && <div className="alert alert-ok">{notice}</div>}

          <button className="btn btn-primary" disabled={busy}>
            {busy ? "One moment…" : mode === "login" ? "Log in" : mode === "signup" ? "Sign up" : "Send reset link"}
          </button>

          <div className="auth-links">
            {mode === "login" && (
              <>
                <button type="button" className="link" onClick={() => switchTo("forgot")}>Forgot password?</button>
                <span>New here? <button type="button" className="link" onClick={() => switchTo("signup")}>Create an account</button></span>
              </>
            )}
            {mode !== "login" && (
              <span>Already have an account? <button type="button" className="link" onClick={() => switchTo("login")}>Log in</button></span>
            )}
          </div>
        </form>
      </section>
    </div>
  );
}
