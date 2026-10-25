import { useEffect, useState } from "react";
import { getToken } from "./api";
import AuthPage from "./components/AuthPage";
import ResetPage from "./components/ResetPage";
import VerifyPage from "./components/VerifyPage";
import Workspace from "./components/Workspace";

// Tiny hash router: #/verify?token=..., #/reset?token=..., everything else = app or login.
function useHash() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

export default function App() {
  const hash = useHash();
  const [loggedIn, setLoggedIn] = useState(!!getToken());

  useEffect(() => {
    const out = () => setLoggedIn(false);
    window.addEventListener("logged-out", out);
    return () => window.removeEventListener("logged-out", out);
  }, []);

  const [route, query] = hash.replace(/^#/, "").split("?");
  const token = new URLSearchParams(query).get("token") ?? "";
  const goHome = () => (window.location.hash = "");

  if (route === "/verify") return <VerifyPage token={token} onDone={goHome} />;
  if (route === "/reset") return <ResetPage token={token} onDone={goHome} />;
  if (!loggedIn) return <AuthPage onAuthed={() => setLoggedIn(true)} />;
  return <Workspace onLogout={() => setLoggedIn(false)} />;
}
