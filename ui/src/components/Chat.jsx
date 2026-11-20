import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowUp, BookOpen, Brain, Check, ChevronDown, ClipboardCopy, FileSearch, FileText,
  Library, ListTree, Loader2, Quote, ShieldAlert, ShieldCheck, Sparkles, Square, ThumbsDown, ThumbsUp,
} from "lucide-react";
import { api, getSessionRuns, runQuery, runsToMessages } from "../api.js";
import { pages, parseAnswer, where } from "../answer.js";

const TOOL_META = {
  think: { icon: Brain, label: "Planning" },
  list_documents: { icon: Library, label: "Checking the library" },
  search_documents: { icon: FileSearch, label: "Searching" },
  get_clause: { icon: ListTree, label: "Reading clause" },
  find_definition: { icon: BookOpen, label: "Looking up definition" },
  read_pages: { icon: FileText, label: "Reading pages" },
  reasoning: { icon: Sparkles, label: "Reasoning" },
  read_source_pages: { icon: FileText, label: "Reading original file" },
  read_markdown_section: { icon: ListTree, label: "Reading section from file" },
  grep_source: { icon: FileSearch, label: "Scanning original files" },
};

function toolSummary(tool) {
  const a = tool.args || {};
  switch (tool.name) {
    case "think": return a.thought;
    case "search_documents": return `“${a.query || ""}”${a.document ? ` in ${a.document}` : ""}`;
    case "get_clause": return `${a.clause || ""}${a.document ? ` · ${a.document}` : ""}`;
    case "find_definition": return `“${a.term || ""}”${a.document ? ` in ${a.document}` : ""}`;
    case "read_pages": return `${a.document || ""} from p. ${a.start_page || ""}`;
    case "list_documents": return a.filter || "all documents";
    case "read_source_pages": return `${a.document || ""} · p. ${a.start_page || 1}${a.end_page ? `–${a.end_page}` : ""}${a.keep_layout ? " (layout)" : ""}`;
    case "read_markdown_section": return `${a.document || ""} · ${a.heading || ""}`;
    case "grep_source": return `“${a.pattern || ""}”${a.document ? ` in ${a.document}` : a.folder ? ` in ${a.folder}` : ""}`;
    case "reasoning": return a.thought;
    default: return JSON.stringify(a);
  }
}

function hitCount(tool) {
  const n = (tool.result || "").match(/\[C\d+\]/g)?.length || 0;
  return tool.name === "think" || tool.name === "list_documents" || tool.name === "reasoning" ? null : n;
}

function ResearchTrail({ tools, streaming }) {
  const [open, setOpen] = useState(false);
  if (!tools?.length) return null;
  const running = tools.some((t) => t.status === "running");
  const searches = tools.filter((t) => !["think", "reasoning"].includes(t.name)).length;
  return (
    <div className={`trail ${open || running ? "open" : ""}`}>
      <button className="trail-head" onClick={() => setOpen(!open)}>
        {running || streaming ? <Loader2 size={15} className="spin" /> : <Check size={15} />}
        <span>{running ? "Researching…" : `Researched · ${searches} lookup${searches === 1 ? "" : "s"}`}</span>
        <ChevronDown size={15} className="chev" />
      </button>
      {(open || running) && (
        <ol className="trail-steps">
          {tools.map((tool, i) => {
            const meta = TOOL_META[tool.name] || { icon: Sparkles, label: tool.name };
            const Icon = meta.icon;
            const n = hitCount(tool);
            return (
              <li key={tool.id || i} className={`step ${tool.status}`}>
                <span className="step-icon"><Icon size={14} /></span>
                <div className="step-body">
                  <div className="step-title">
                    {meta.label}
                    {tool.status === "running" && <Loader2 size={12} className="spin" />}
                    {n !== null && tool.status === "done" && <span className="pill">{n} passage{n === 1 ? "" : "s"}</span>}
                    {tool.status === "error" && <span className="pill danger">error</span>}
                  </div>
                  <div className="step-detail">{toolSummary(tool)}</div>
                  {tool.result && open && (
                    <details className="step-result">
                      <summary>Tool output</summary>
                      <pre>{tool.result.slice(0, 4000)}</pre>
                    </details>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

function useSources(ids) {
  const [map, setMap] = useState({});
  const key = ids.join(",");
  useEffect(() => {
    const missing = ids.filter((id) => !map[id]);
    if (!missing.length) return;
    let live = true;
    api.chunks(missing).then((rows) => {
      if (!live) return;
      setMap((m) => ({ ...m, ...Object.fromEntries(rows.map((r) => [r.id, r])) }));
    }).catch(() => {});
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return map;
}

function AnswerBody({ message, onCite }) {
  const parsed = useMemo(() => parseAnswer(message.content), [message.content]);
  const sources = useSources(message.streaming ? [] : parsed.order);
  const components = {
    a({ href, children, ...rest }) {
      if (href?.startsWith("#cite-")) {
        const id = Number(href.slice(6));
        const hit = sources[id];
        return (
          <button
            className="cite"
            title={hit ? `${hit.document} — ${where(hit)} (${pages(hit)})` : `Passage C${id}`}
            onClick={() => onCite(id)}
          >
            {children}
          </button>
        );
      }
      return <a href={href} target="_blank" rel="noreferrer" {...rest}>{children}</a>;
    },
    table({ children }) {
      return <div className="table-wrap"><table>{children}</table></div>;
    },
  };
  const highlighted = parsed.body.replace(/\*\*(CONFLICT|INSUFFICIENT EVIDENCE|NOT IN FORCE|DRAFT|MISSING HOP|POSSIBLE OCR ERROR)\*\*/g, "`⚑ $1`");
  return (
    <>
      {(parsed.thinking || message.reasoning) && (
        <details className="thinking"><summary><Brain size={13} /> Model reasoning</summary><pre>{parsed.thinking || message.reasoning}</pre></details>
      )}
      <div className="markdown">
        <Markdown remarkPlugins={[remarkGfm]} components={components}>{highlighted}</Markdown>
        {message.streaming && <span className="caret" />}
      </div>
      {!message.streaming && parsed.order.length > 0 && (
        <div className="sources">
          {parsed.order.map((id, i) => {
            const hit = sources[id];
            return (
              <button key={id} className="source-card" onClick={() => onCite(id)}>
                <span className="num">{i + 1}</span>
                <span className="source-meta">
                  <strong>{hit ? hit.document : `Passage C${id}`}</strong>
                  <small>{hit ? `${where(hit)} · ${pages(hit)}` : "loading…"}</small>
                </span>
              </button>
            );
          })}
        </div>
      )}
      {!message.streaming && parsed.verified && (
        parsed.verification ? (
          <div className="verify warn"><ShieldAlert size={16} /><span>{parsed.verification}</span></div>
        ) : parsed.order.length > 0 ? (
          <div className="verify ok"><ShieldCheck size={15} /><span>Every citation was checked against the retrieved passages.</span></div>
        ) : null
      )}
    </>
  );
}

function Feedback({ message, query, sessionId, userId }) {
  const [rating, setRating] = useState(0);
  const [copied, setCopied] = useState(false);
  const send = async (value) => {
    setRating(value);
    try {
      await api.feedback({ rating: value, run_id: message.runId, session_id: sessionId, user_id: userId, query, answer: message.content, model: message.model || "" });
    } catch { /* non-blocking */ }
  };
  const copy = async () => {
    await navigator.clipboard.writeText(parseAnswer(message.content).body.replace(/\[(\d+)\]\(#cite-\d+\)/g, "[$1]"));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const m = message.metrics;
  return (
    <div className="msg-actions">
      <button className="icon-btn" onClick={copy} title="Copy">{copied ? <Check size={15} /> : <ClipboardCopy size={15} />}</button>
      <button className={`icon-btn ${rating === 1 ? "on" : ""}`} onClick={() => send(1)} title="Good answer"><ThumbsUp size={15} /></button>
      <button className={`icon-btn ${rating === -1 ? "on bad" : ""}`} onClick={() => send(-1)} title="Wrong or incomplete"><ThumbsDown size={15} /></button>
      <span className="meta">
        {message.model && <span>{message.model}</span>}
        {m?.duration && <span>{m.duration.toFixed(1)}s</span>}
        {m?.total_tokens && <span>{m.total_tokens.toLocaleString()} tokens</span>}
      </span>
    </div>
  );
}

const SUGGESTIONS = [
  { title: "Read a clause", text: "What does Article 10.7 of the KG-D6 PSC say?" },
  { title: "Find a definition", text: "How is “Discovery Area” defined in the KG-D6 PSC?" },
  { title: "Check a premise", text: "Does RIL hold 90% participating interest in KG-D6?" },
  { title: "Compare sources", text: "What royalty rate applies after Amendment No. 1, and do the MC minutes agree?" },
];

export default function Chat({ sessionId, fresh, userId, status, onSessionsChanged, onCite, embed }) {
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const scroller = useRef(null);
  const abort = useRef(null);
  const local = useRef(new Set());
  const inputRef = useRef(null);

  useEffect(() => {
    if (fresh || local.current.has(sessionId)) return;
    setError("");
    getSessionRuns(sessionId, userId).then((runs) => setMessages(runsToMessages(runs))).catch(() => setMessages([]));
  }, [sessionId, userId, fresh]);

  useEffect(() => {
    const el = scroller.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 240) el.scrollTo({ top: el.scrollHeight });
  }, [messages]);

  const autosize = () => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 220) + "px";
  };

  const send = async (text) => {
    const message = (text ?? draft).trim();
    if (!message || busy) return;
    local.current.add(sessionId);
    const assistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: message },
      { id: assistantId, role: "assistant", content: "", tools: [], streaming: true, model: status?.model?.model },
    ]);
    setDraft("");
    setTimeout(autosize);
    setBusy(true);
    setError("");
    const patch = (fn) => setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)));
    const controller = new AbortController();
    abort.current = controller;
    try {
      await runQuery({
        message, sessionId, userId, signal: controller.signal,
        onEvent: (event, data) => {
          if (event === "RunStarted") patch((m) => ({ ...m, runId: data.run_id }));
          else if (event === "ToolCallStarted") {
            const t = data.tool || {};
            patch((m) => ({ ...m, tools: [...m.tools, { id: t.tool_call_id, name: t.tool_name, args: t.tool_args || {}, result: "", status: "running" }] }));
          } else if (event === "ToolCallCompleted" || event === "ToolCallError") {
            const t = data.tool || {};
            patch((m) => ({
              ...m,
              tools: m.tools.map((x) => (x.id === t.tool_call_id ? { ...x, args: t.tool_args || x.args, result: typeof t.result === "string" ? t.result : data.error || "", status: event === "ToolCallError" || t.tool_call_error ? "error" : "done" } : x)),
            }));
          } else if (event === "RunContent" && typeof data.content === "string") {
            patch((m) => ({ ...m, content: m.content + data.content }));
          } else if (event === "ReasoningContentDelta" || (event === "RunContent" && data.reasoning_content)) {
            const piece = data.reasoning_content || "";
            if (piece) patch((m) => ({ ...m, reasoning: (m.reasoning || "") + piece }));
          } else if (event === "RunCompleted") {
            patch((m) => ({ ...m, content: typeof data.content === "string" ? data.content : m.content, metrics: data.metrics, streaming: false }));
          } else if (event === "RunError") {
            patch((m) => ({ ...m, error: data.content || data.error || "The run failed.", streaming: false }));
          } else if (event === "RunCancelled") {
            patch((m) => ({ ...m, streaming: false, error: "Stopped." }));
          }
        },
      });
    } catch (err) {
      if (err.name !== "AbortError") {
        patch((m) => ({ ...m, error: err.message }));
        setError(err.message);
      }
    } finally {
      patch((m) => ({ ...m, streaming: false, tools: m.tools.map((t) => (t.status === "running" ? { ...t, status: "done" } : t)) }));
      setBusy(false);
      abort.current = null;
      onSessionsChanged?.();
      inputRef.current?.focus();
    }
  };

  const empty = messages.length === 0;
  const lib = status?.library;

  return (
    <div className={`chat ${embed ? "embed" : ""}`}>
      <div className="thread" ref={scroller}>
        {empty ? (
          <div className="welcome">
            <div className="welcome-mark"><Quote size={26} /></div>
            <h1>What would you like to research?</h1>
            <p>
              Answers come only from your {lib ? <strong>{lib.documents} indexed documents</strong> : "indexed documents"},
              with every statement linked to the clause it came from.
            </p>
            {!embed && (
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s.title} onClick={() => send(s.text)}>
                    <strong>{s.title}</strong>
                    <span>{s.text}</span>
                  </button>
                ))}
              </div>
            )}
            {lib && lib.documents === 0 && (
              <p className="hint">The library is empty — add documents on the <a href="/library">Library</a> page.</p>
            )}
          </div>
        ) : (
          <div className="messages">
            {messages.map((m, i) => (
              <article key={m.id} className={`msg ${m.role}`}>
                {m.role === "user" ? (
                  <div className="user-bubble">{m.content}</div>
                ) : (
                  <div className="assistant">
                    <div className="avatar"><Sparkles size={15} /></div>
                    <div className="assistant-body">
                      <ResearchTrail tools={m.tools} streaming={m.streaming} />
                      {m.content || !m.streaming ? (
                        <AnswerBody message={m} onCite={onCite} />
                      ) : (
                        <div className="typing"><span /><span /><span /></div>
                      )}
                      {m.error && <div className="verify warn"><ShieldAlert size={16} /><span>{m.error}</span></div>}
                      {!m.streaming && m.content && (
                        <Feedback message={m} query={messages[i - 1]?.content || ""} sessionId={sessionId} userId={userId} />
                      )}
                    </div>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </div>
      <div className="composer-wrap">
        {error && <div className="banner-error">{error}</div>}
        <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <textarea
            ref={inputRef}
            rows={1}
            value={draft}
            placeholder="Ask about a clause, definition, party, date…"
            onChange={(e) => { setDraft(e.target.value); autosize(); }}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          />
          {busy ? (
            <button type="button" className="send stop" onClick={() => abort.current?.abort()} title="Stop"><Square size={14} /></button>
          ) : (
            <button type="submit" className="send" disabled={!draft.trim()} title="Send"><ArrowUp size={18} /></button>
          )}
        </form>
        <p className="composer-note">
          Answers cite your documents; check the cited clause before relying on it.
        </p>
      </div>
    </div>
  );
}
