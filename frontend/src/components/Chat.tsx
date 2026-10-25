import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, ChatMsg } from "../api";

const STARTERS = [
  "Help me find companies to apply to",
  "How does Career Scout work?",
  "I have employment reports to upload",
];
const RETURNING = ["Check my tracked companies for new postings", "Show my tracker", "Research my tracked companies"];

export default function Chat({ onReply, returning }: { onReply: () => void; returning: boolean }) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.history().then(setMessages).catch(() => {});
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

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

  async function newChat() {
    if (!confirm("Start a new conversation? Your tracker and saved settings stay.")) return;
    await api.newChat();
    setMessages([]);
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
        {messages.length > 0 && <button className="btn btn-ghost" onClick={newChat} disabled={busy}>New chat</button>}
      </div>

      <div className="chat-log">
        {messages.length === 0 && !busy && (
          <div className="chat-empty">
            <p className="serif-lg">{returning ? "Welcome back." : "Where do you want to work after your MBA?"}</p>
            <div className="chips">
              {(returning ? RETURNING : STARTERS).map((s) => (
                <button key={s} className="chip" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg msg-${m.role}`}>
            {m.role === "assistant" ? (
              <ReactMarkdown components={{ a: (p) => <a {...p} target="_blank" rel="noreferrer" /> }}>{m.text}</ReactMarkdown>
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

      <form className="composer" onSubmit={(e: FormEvent) => (e.preventDefault(), send(input))}>
        <input ref={fileRef} type="file" accept="application/pdf" multiple hidden onChange={(e) => upload(e.target.files)} />
        <button type="button" className="btn btn-ghost icon-btn" title="Upload employment report PDFs" onClick={() => fileRef.current?.click()} disabled={busy}>
          ＋ PDF
        </button>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          placeholder="Message Career Scout…"
          rows={1}
          disabled={busy}
        />
        <button className="btn btn-primary" disabled={busy || !input.trim()}>Send</button>
      </form>
    </section>
  );
}
