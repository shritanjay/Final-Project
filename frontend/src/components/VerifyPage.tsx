import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Brand from "./Brand";

export default function VerifyPage({ token, onDone }: { token: string; onDone: () => void }) {
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [error, setError] = useState("");
  const ran = useRef(false); // StrictMode runs effects twice in dev; tokens are single-use

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    api.verify(token).then(
      () => setState("ok"),
      (err) => {
        setError((err as Error).message);
        setState("error");
      },
    );
  }, [token]);

  return (
    <div className="center-shell">
      <Brand />
      <div className="card narrow-card">
        <h2>Email verification</h2>
        {state === "working" && <p className="muted">Checking your link…</p>}
        {state === "ok" && <div className="alert alert-ok">Your email is verified. Thanks!</div>}
        {state === "error" && <div className="alert alert-error">{error}</div>}
        {state !== "working" && <button className="btn btn-primary" onClick={onDone}>Continue to Career Scout</button>}
      </div>
    </div>
  );
}
