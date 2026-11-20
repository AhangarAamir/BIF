import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { BookOpenText, Library, MessageSquarePlus, MessagesSquare, Moon, PanelLeftClose, PanelLeftOpen, Settings2, Sun, Trash2 } from "lucide-react";
import { api, deleteSession, getUserId, listSessions } from "./api.js";
import Chat from "./components/Chat.jsx";
import LibraryPage from "./components/Library.jsx";
import ModelSwitcher from "./components/ModelSwitcher.jsx";
import Settings from "./components/Settings.jsx";
import SourcePanel from "./components/SourcePanel.jsx";
import "./styles.css";

const params = new URLSearchParams(location.search);
// Sessions started in this tab have no stored runs yet; skip fetching them.
export const FRESH = new Set();
const freshId = () => { const id = crypto.randomUUID(); FRESH.add(id); return id; };
const EMBED = params.get("embed") === "1";

function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem("bif-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("bif-theme", theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

function groupSessions(sessions) {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const groups = { Today: [], "Previous 7 days": [], Older: [] };
  for (const s of sessions) {
    const t = new Date(s.updated_at || s.created_at).getTime();
    if (t >= start) groups.Today.push(s);
    else if (t >= start - 7 * 864e5) groups["Previous 7 days"].push(s);
    else groups.Older.push(s);
  }
  return Object.entries(groups).filter(([, v]) => v.length);
}

function App() {
  const userId = useMemo(() => getUserId(), []);
  const [page, setPage] = useState(() => (EMBED ? "chat" : location.pathname.replace(/^\//, "") || "chat"));
  const [sessionId, setSessionId] = useState(freshId);
  const [sessions, setSessions] = useState([]);
  const [status, setStatus] = useState(null);
  const [cite, setCite] = useState(null);
  const [collapsed, setCollapsed] = useState(() => innerWidth < 900);
  const [theme, toggleTheme] = useTheme();

  const refreshStatus = useCallback(() => api.status().then(setStatus).catch(() => {}), []);
  const refreshSessions = useCallback(() => listSessions(userId).then((p) => setSessions(p.data || [])).catch(() => {}), [userId]);
  useEffect(() => { refreshStatus(); refreshSessions(); }, [refreshStatus, refreshSessions]);

  const go = (next) => {
    setPage(next);
    history.pushState({}, "", next === "chat" ? "/" : `/${next}`);
  };
  useEffect(() => {
    const onPop = () => setPage(location.pathname.replace(/^\//, "") || "chat");
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);

  const newChat = () => { setSessionId(freshId()); go("chat"); };

  if (EMBED) {
    return (
      <div className="embed-shell">
        <header className="embed-head">
          <span className="brand-mark"><BookOpenText size={16} /></span>
          <strong>Legal Research</strong>
          <span className="spacer" />
          <button className="icon-btn" onClick={newChat} title="New chat"><MessageSquarePlus size={17} /></button>
        </header>
        <Chat key={sessionId} sessionId={sessionId} fresh={FRESH.has(sessionId)} userId={userId} status={status} onCite={setCite} embed />
        <SourcePanel chunkId={cite} onClose={() => setCite(null)} />
      </div>
    );
  }

  return (
    <div className={`shell ${collapsed ? "collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark"><BookOpenText size={18} /></span>
          <div><strong>BIF</strong><small>Legal Research</small></div>
          <button className="icon-btn" onClick={() => setCollapsed(true)} title="Hide sidebar"><PanelLeftClose size={17} /></button>
        </div>
        <button className="new-chat" onClick={newChat}><MessageSquarePlus size={16} /> New research</button>
        <nav className="nav">
          <button className={page === "chat" ? "on" : ""} onClick={() => go("chat")}><MessagesSquare size={16} /> Research</button>
          <button className={page === "library" ? "on" : ""} onClick={() => go("library")}><Library size={16} /> Library {status && <span className="count">{status.library.documents}</span>}</button>
          <button className={page === "settings" ? "on" : ""} onClick={() => go("settings")}><Settings2 size={16} /> Models</button>
        </nav>
        <div className="history">
          {sessions.length === 0 && <p className="empty">Your research sessions appear here.</p>}
          {groupSessions(sessions).map(([label, items]) => (
            <div key={label}>
              <p className="history-label">{label}</p>
              {items.map((s) => (
                <div key={s.session_id} className={`session ${s.session_id === sessionId && page === "chat" ? "on" : ""}`}>
                  <button onClick={() => { setSessionId(s.session_id); go("chat"); }} title={s.session_name}>{s.session_name || "Untitled"}</button>
                  <button className="del" title="Delete" onClick={async () => { await deleteSession(s.session_id).catch(() => {}); if (s.session_id === sessionId) newChat(); refreshSessions(); }}><Trash2 size={13} /></button>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="sidebar-foot">
          <button className="icon-btn" onClick={toggleTheme} title="Toggle theme">{theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}</button>
          <a href="/widget-demo" onClick={(e) => { e.preventDefault(); go("widget-demo"); }} className="foot-link">Embed widget</a>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          {collapsed && <button className="icon-btn" onClick={() => setCollapsed(false)} title="Show sidebar"><PanelLeftOpen size={17} /></button>}
          <ModelSwitcher status={status} onChanged={refreshStatus} />
          <span className="spacer" />
          {status?.embedding?.needs_reembed && <button className="pill warn clickable" onClick={() => go("library")}>Embeddings out of date</button>}
          {status && <span className="topbar-meta">{status.library.documents} docs · {status.library.chunks.toLocaleString()} passages</span>}
        </header>
        {page === "chat" && <Chat key={sessionId} sessionId={sessionId} fresh={FRESH.has(sessionId)} userId={userId} status={status} onSessionsChanged={refreshSessions} onCite={setCite} />}
        {page === "library" && <LibraryPage status={status} refreshStatus={refreshStatus} />}
        {page === "settings" && <Settings status={status} refreshStatus={refreshStatus} />}
        {page === "widget-demo" && <WidgetDemo />}
      </main>
      <SourcePanel chunkId={cite} onClose={() => setCite(null)} />
    </div>
  );
}

function WidgetDemo() {
  const snippet = `<script src="${location.origin}/widget.js" data-title="Legal Research" data-color="#4f46e5" defer></script>`;
  useEffect(() => {
    if (document.getElementById("bif-widget-demo")) return;
    const s = document.createElement("script");
    s.id = "bif-widget-demo";
    s.src = "/widget.js";
    document.body.appendChild(s);
  }, []);
  return (
    <div className="page">
      <header className="page-head"><div><h1>Embed widget</h1><p>Add the research assistant to any intranet page with one script tag. The launcher in the bottom-right corner of this page is a live preview.</p></div></header>
      <section className="card">
        <h2>Snippet</h2>
        <pre className="code">{snippet}</pre>
        <p>Options: <code>data-title</code>, <code>data-color</code>, <code>data-position="left"</code>. Allow the host page's origin in <code>CORS_ALLOWED_ORIGINS</code>.</p>
      </section>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
