import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, ChatAction, ChatMsg } from "../api";

const GREETING = `**Hey! Where do you want to work after your MBA?**

Tell me the city and country, for example *"Berlin, Germany"*, or just a country if you're open to anywhere there.

From there I'll walk you through it step by step: find the employment reports of the top MBA programs in that city, pull out the companies that hire their grads, research the ones you like, and track their job postings.`;
const RETURNING = ["Continue where I left off", "Check my tracked companies for new postings", "Show my tracker"];

type ChatProps = {
  searchId: number | null; // reload the conversation when the open search changes
  onReply: () => void;
  onReset: () => void;
  onAction: (a: ChatAction) => Promise<string | void>; // open a tab, add to tracker…
  returning: boolean; // the open search already has a location
  outgoing?: { text: string; id: number } | null;
  focusTick?: number;
};

export default function Chat({ searchId, onReply, onReset, onAction, returning, outgoing, focusTick }: ChatProps) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [usedActions, setUsedActions] = useState<Record<string, string>>({}); // "msgIndex:actionIndex" -> result
  const endRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    if (focusTick) inputRef.current?.focus();
  }, [focusTick]);
  useEffect(() => {
    if (searchId === null) return;
    setUsedActions({});
    api.history().then(setMessages).catch(() => {});
  }, [searchId]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);
  // Messages sent from elsewhere in the app (e.g. "Research selected" in the Employers table).
  useEffect(() => {
    if (outgoing) send(outgoing.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outgoing?.id]);

  async function send(text: string) {
    const msg = text.trim();
    if (!msg || busy) return;
    setInput("");
    setError("");
    setMessages((m) => [...m, { role: "user", text: msg }]);
    setBusy(true);
    try {
      const { answer, actions } = await api.chat(msg);
      setMessages((m) => [...m, { role: "assistant", text: answer, actions }]);
      onReply();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function runAction(key: string, a: ChatAction) {
    if (a.type === "say") return send(a.text);
    const result = await onAction(a);
    if (a.type === "track") setUsedActions((u) => ({ ...u, [key]: result || "Added ✓" }));
  }

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setError("");
    const saved: string[] = [];
    for (const f of Array.from(files)) {
      try {
        saved.push((await api.upload(f)).saved);
      } catch (err) {
        setError(`${f.name}: ${(err as Error).message}`);
      }
    }
    if (fileRef.current) fileRef.current.value = "";
    if (saved.length) send(`I uploaded ${saved.join(", ")}. Please analyze ${saved.length > 1 ? "them" : "it"}.`);
  }

  async function reset(newSearch: boolean) {
    setResetting(true);
    setError("");
    try {
      await api.newChat({ new_search: newSearch });
      setMessages([]);
      setInput("");
      setResetOpen(false);
      onReset();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setResetting(false);
    }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  return (
    <section className="chat card">
      <div className="chat-head">
        <div>
          <h2>Your career scout</h2>
          <p className="muted">Ask in plain words. I'll hand the work to the right specialist.</p>
        </div>
        {(messages.length > 0 || returning) && (
          <button className="btn btn-ghost" onClick={() => setResetOpen(true)} disabled={busy}>New chat</button>
        )}
      </div>

      <div className="chat-log">
        {messages.length === 0 && !busy && !returning && (
          <div className="msg msg-assistant">
            <ReactMarkdown>{GREETING}</ReactMarkdown>
          </div>
        )}
        {messages.length === 0 && !busy && returning && (
          <div className="chat-empty">
            <p className="serif-lg">Welcome back.</p>
            <div className="chips">
              {RETURNING.map((s) => (
                <button key={s} className="chip" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg-wrap msg-wrap-${m.role}`}>
            <div className={`msg msg-${m.role}`}>
              {m.role === "assistant" ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: (p) => <a {...p} target="_blank" rel="noreferrer" /> }}>{m.text}</ReactMarkdown>
              ) : (
                m.text
              )}
            </div>
            {m.actions && m.actions.length > 0 && (
              <div className="msg-actions">
                {m.actions.map((a, j) => {
                  const key = `${i}:${j}`;
                  return usedActions[key] ? (
                    <span key={key} className="action-done">{usedActions[key]}</span>
                  ) : (
                    <button key={key} className={`action-btn ${j === 0 ? "primary" : ""}`} onClick={() => runAction(key, a)} disabled={busy}>
                      {a.label}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="msg msg-assistant msg-thinking">
            <span className="dots"><i /><i /><i /></span>
            Working on it. Research and job searches can take a minute or two.
          </div>
        )}
        <div ref={endRef} />
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {resetOpen && (
        <div className="modal-backdrop" onClick={() => !resetting && setResetOpen(false)}>
          <div className="modal card" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3>Start fresh?</h3>
            <div className="reset-options">
              <button className="reset-option" onClick={() => reset(false)} disabled={resetting}>
                <strong>New chat</strong>
                <span>Clear this conversation. Keep this search's city, progress, employer table and tracker.</span>
              </button>
              <button className="reset-option primary" onClick={() => reset(true)} disabled={resetting}>
                <strong>Start a new search</strong>
                <span>Pick a new place from scratch. This search is saved; switch back any time from the search menu at the top.</span>
              </button>
            </div>
            <div className="modal-foot">
              <button className="btn btn-ghost" onClick={() => setResetOpen(false)} disabled={resetting}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      <form className="composer" onSubmit={(e: FormEvent) => (e.preventDefault(), send(input))}>
        <input ref={fileRef} type="file" accept="application/pdf" multiple hidden onChange={(e) => upload(e.target.files)} />
        <button type="button" className="btn btn-ghost icon-btn" title="Upload employment report PDFs" onClick={() => fileRef.current?.click()} disabled={busy}>
          ＋ PDF
        </button>
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          placeholder={messages.length === 0 && !returning ? "Type a city and country…" : "Message Career Scout…"}
          rows={1}
          disabled={busy}
        />
        <button className="btn btn-primary" disabled={busy || !input.trim()}>Send</button>
      </form>
    </section>
  );
}
