import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, ChatMsg } from "../api";

const GREETING = `**Hey! Where do you want to work after your MBA?**

Tell me the city and country, for example *"Berlin, Germany"*, or just a country if you're open to anywhere there.

From there I'll walk you through it step by step: find the employment reports of the top MBA programs in that city, pull out the companies that hire their grads, research the ones you like, and track their job postings.`;
const RETURNING = ["Continue where I left off", "Check my tracked companies for new postings", "Show my tracker"];

type ChatProps = {
  onReply: () => void;
  onReset: () => void;
  returning: boolean; // student already has a saved location
  hasTracker: boolean;
  outgoing?: { text: string; id: number } | null;
};

export default function Chat({ onReply, onReset, returning, hasTracker, outgoing }: ChatProps) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [clearTracker, setClearTracker] = useState(false);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    api.history().then(setMessages).catch(() => {});
  }, []);
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
      const { answer } = await api.chat(msg);
      setMessages((m) => [...m, { role: "assistant", text: answer }]);
      onReply();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
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
      await api.newChat({ new_search: newSearch, clear_tracker: newSearch && clearTracker });
      setMessages([]);
      setInput("");
      setResetOpen(false);
      setClearTracker(false);
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
        {(messages.length > 0 || returning || hasTracker) && (
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
          <div key={i} className={`msg msg-${m.role}`}>
            {m.role === "assistant" ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: (p) => <a {...p} target="_blank" rel="noreferrer" /> }}>{m.text}</ReactMarkdown>
            ) : (
              m.text
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
                <span>Clear the conversation. Keep your city, progress, employer table and tracker.</span>
              </button>
              <button className="reset-option primary" onClick={() => reset(true)} disabled={resetting}>
                <strong>Start a new search</strong>
                <span>Clear the conversation, city, target roles, progress and employer table, and pick a new place.</span>
              </button>
            </div>
            {hasTracker && (
              <label className="check">
                <input type="checkbox" checked={clearTracker} onChange={(e) => setClearTracker(e.target.checked)} />
                Also empty my tracker (only with a new search)
              </label>
            )}
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
