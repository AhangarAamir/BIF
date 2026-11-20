import { useEffect, useState } from "react";
import { CheckCircle2, KeyRound, Loader2, Plus, RefreshCw, Save, Trash2, XCircle, Zap } from "lucide-react";
import { api, getAdminToken, setAdminToken } from "../api.js";
import { PROVIDER_COLORS } from "./ModelSwitcher.jsx";

const blankProfile = (presets, provider = "ollama") => ({
  id: null, name: "", provider, base_url: presets?.[provider]?.base_url || "", api_key: "",
  model: "", api: presets?.[provider]?.api || "chat", reasoning_summary: "",
  temperature: null, max_tokens: null, reasoning_effort: "", timeout: 300,
});

const API_LABEL = { chat: "Chat Completions", responses: "Responses" };

function TestResult({ result }) {
  if (!result) return null;
  if (result.loading) return <span className="test pending"><Loader2 size={14} className="spin" /> Testing…</span>;
  return result.ok ? (
    <span className="test ok"><CheckCircle2 size={14} /> Works · {result.latency_ms} ms{result.dimensions ? ` · ${result.dimensions} dims` : ""}{result.reply ? ` · “${result.reply}”` : ""}</span>
  ) : (
    <span className="test bad"><XCircle size={14} /> {result.error}</span>
  );
}

function ModelPicker({ value, onChange, query }) {
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setModels((await api.listModels(query)).models);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="model-picker">
      <div className="input-row">
        <input list={`models-${query.profile_id || "x"}-${query.embedding ? "e" : "c"}`} value={value} onChange={(e) => onChange(e.target.value)} placeholder="e.g. qwen3:8b or gpt-4.1" />
        <datalist id={`models-${query.profile_id || "x"}-${query.embedding ? "e" : "c"}`}>
          {models.map((m) => <option key={m} value={m} />)}
        </datalist>
        <button type="button" className="btn" onClick={load} disabled={loading || !query.base_url} title="Fetch models from the endpoint">
          {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} Fetch
        </button>
      </div>
      {error && <small className="field-error">{error}</small>}
      {models.length > 0 && <small className="field-hint">{models.length} models available — start typing to filter.</small>}
    </div>
  );
}

function ProfileEditor({ profile, presets, onSaved, onCancel }) {
  const [p, setP] = useState(profile);
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState(null);
  const [error, setError] = useState("");
  const set = (k, v) => setP((x) => ({ ...x, [k]: v }));

  const choosePreset = (provider) => {
    setP((x) => ({
      ...x, provider,
      base_url: presets[provider]?.base_url ?? x.base_url,
      api: presets[provider]?.api || "chat",
      name: x.name || "",
    }));
  };
  const runTest = async () => {
    setTest({ loading: true });
    try { setTest(await api.testModel({ ...p, name: p.name || "test" })); } catch (e) { setTest({ ok: false, error: e.message }); }
  };
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const name = p.name || `${presets[p.provider]?.label || "Model"} · ${p.model}`;
      await api.saveProfile({ ...p, name });
      onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="editor">
      <div className="presets">
        {Object.entries(presets).map(([key, preset]) => (
          <button key={key} type="button" className={`preset ${p.provider === key ? "on" : ""}`} onClick={() => choosePreset(key)}>
            <span className="dot" style={{ background: PROVIDER_COLORS[key] }} />{preset.label}
          </button>
        ))}
      </div>
      <div className="grid2">
        <label>Display name<input value={p.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Local Qwen 8B" /></label>
        <label>Base URL <small>(up to /v1)</small><input value={p.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder="http://localhost:11434/v1" /></label>
        <label>API key <small>{p.provider === "ollama" ? "(not needed for Ollama)" : ""}</small>
          <div className="input-icon"><KeyRound size={14} /><input type="password" value={p.api_key} onChange={(e) => set("api_key", e.target.value)} placeholder={profile.has_api_key ? "Saved — leave as is to keep" : "sk-…"} autoComplete="off" /></div>
        </label>
        <label>Model<ModelPicker value={p.model} onChange={(v) => set("model", v)} query={{ base_url: p.base_url, api_key: p.api_key, profile_id: p.id }} /></label>
        <label>API
          <div className="segmented">
            {["chat", "responses"].map((a) => (
              <button key={a} type="button" className={p.api === a ? "on" : ""} onClick={() => set("api", a)}>
                {API_LABEL[a]} <code>/{a === "chat" ? "chat/completions" : "responses"}</code>
              </button>
            ))}
          </div>
          <small>{p.api === "responses"
            ? "OpenAI Responses API. Needed for tools + reasoning on gpt-5 / gpt-6 models."
            : "Works with Ollama, vLLM, LM Studio, Groq, OpenRouter and most providers."}</small>
        </label>
        {p.api === "responses" && (
          <label>Reasoning summary <small>(shown in the research trail)</small>
            <select value={p.reasoning_summary || ""} onChange={(e) => set("reasoning_summary", e.target.value)}>
              <option value="">Off</option>
              <option value="auto">Auto</option>
              <option value="concise">Concise</option>
              <option value="detailed">Detailed</option>
            </select>
          </label>
        )}
        <label>Thinking
          <select value={p.reasoning_effort} onChange={(e) => set("reasoning_effort", e.target.value)}>
            <option value="">Provider default</option>
            <option value="none">Off (fastest)</option>
            <option value="minimal">Minimal</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="xhigh">Extra high</option>
          </select>
        </label>
        <label>Temperature <small>(blank = default)</small>
          <input type="number" step="0.1" min="0" max="2" value={p.temperature ?? ""} onChange={(e) => set("temperature", e.target.value === "" ? null : Number(e.target.value))} />
        </label>
      </div>
      {error && <p className="banner-error">{error}</p>}
      <div className="editor-actions">
        <button type="button" className="btn" onClick={runTest} disabled={!p.base_url || !p.model}><Zap size={14} /> Test connection</button>
        <TestResult result={test} />
        <span className="spacer" />
        <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>
        <button type="button" className="btn primary" onClick={save} disabled={saving || !p.base_url || !p.model}>
          {saving ? <Loader2 size={14} className="spin" /> : <Save size={14} />} Save
        </button>
      </div>
    </div>
  );
}

function EmbeddingCard({ settings, status, onSaved }) {
  const [e, setE] = useState(settings.embedding);
  const [test, setTest] = useState(null);
  const [msg, setMsg] = useState("");
  useEffect(() => setE(settings.embedding), [settings]);
  const set = (k, v) => setE((x) => ({ ...x, [k]: v }));
  const save = async () => {
    try {
      await api.saveEmbedding(e);
      setMsg("Saved.");
      onSaved();
    } catch (err) { setMsg(err.message); }
  };
  const changed = status?.embedding?.indexed_with && status.embedding.indexed_with !== e.model;
  return (
    <section className="card">
      <div className="card-head">
        <div><h2>Embeddings</h2><p>Semantic search. Any OpenAI-compatible <code>/v1/embeddings</code> endpoint. Keyword search works without it.</p></div>
        <label className="switch"><input type="checkbox" checked={e.enabled} onChange={(ev) => set("enabled", ev.target.checked)} /><span /></label>
      </div>
      <div className="grid2">
        <label>Base URL<input value={e.base_url} onChange={(ev) => set("base_url", ev.target.value)} /></label>
        <label>API key<input type="password" value={e.api_key} onChange={(ev) => set("api_key", ev.target.value)} placeholder={settings.embedding.has_api_key ? "Saved" : "optional"} /></label>
        <label>Model<ModelPicker value={e.model} onChange={(v) => set("model", v)} query={{ base_url: e.base_url, api_key: e.api_key, embedding: true }} /></label>
        <label>Batch size<input type="number" min="1" max="512" value={e.batch_size} onChange={(ev) => set("batch_size", Number(ev.target.value))} /></label>
      </div>
      {changed && <p className="callout">The library was embedded with <strong>{status.embedding.indexed_with}</strong>. After saving a different model, run <em>Re-embed</em> on the Library page.</p>}
      <div className="editor-actions">
        <button className="btn" onClick={async () => { setTest({ loading: true }); setTest(await api.testEmbedding(e).catch((x) => ({ ok: false, error: x.message }))); }}><Zap size={14} /> Test</button>
        <TestResult result={test} />
        <span className="spacer" />
        {msg && <small>{msg}</small>}
        <button className="btn primary" onClick={save}><Save size={14} /> Save</button>
      </div>
    </section>
  );
}

export default function Settings({ status, refreshStatus }) {
  const [settings, setSettings] = useState(null);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState("");
  const [token, setToken] = useState(getAdminToken());

  const load = () => api.settings().then(setSettings).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  if (!settings) return <div className="page"><p>{error || "Loading…"}</p></div>;

  const activate = async (id) => {
    try { await api.setActive(id); await load(); refreshStatus(); } catch (e) { setError(e.message); }
  };
  const remove = async (id) => {
    if (!confirm("Delete this model profile?")) return;
    try { await api.deleteProfile(id); await load(); refreshStatus(); } catch (e) { setError(e.message); }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Models</h1>
          <p>Any OpenAI-compatible chat/completions endpoint — Ollama, vLLM, LM Studio, OpenAI, OpenRouter, Groq… Switching from open-source to paid is just picking another profile.</p>
        </div>
        <button className="btn primary" onClick={() => setEditing(blankProfile(settings.presets))}><Plus size={15} /> Add model</button>
      </header>
      {error && <p className="banner-error">{error}</p>}

      {editing && !editing.id && (
        <section className="card"><h2>New model</h2>
          <ProfileEditor profile={editing} presets={settings.presets} onCancel={() => setEditing(null)} onSaved={async () => { setEditing(null); await load(); refreshStatus(); }} />
        </section>
      )}

      <div className="profiles">
        {settings.profiles.map((p) => (
          <section key={p.id} className={`card profile ${p.id === settings.active_profile ? "active" : ""}`}>
            {editing?.id === p.id ? (
              <ProfileEditor profile={editing} presets={settings.presets} onCancel={() => setEditing(null)} onSaved={async () => { setEditing(null); await load(); refreshStatus(); }} />
            ) : (
              <div className="profile-row">
                <span className="provider-badge" style={{ background: PROVIDER_COLORS[p.provider] || "#475569" }}>{(settings.presets[p.provider]?.label || p.provider).split(" ")[0]}</span>
                <div className="profile-text">
                  <strong>{p.name}</strong>
                  <small className="mono">{p.model} · {p.base_url}/{p.api === "responses" ? "responses" : "chat/completions"}{p.has_api_key ? " · key " + p.api_key : ""}{p.reasoning_effort ? ` · thinking ${p.reasoning_effort}` : ""}</small>
                </div>
                {p.id === settings.active_profile ? <span className="pill ok">Active</span> : <button className="btn" onClick={() => activate(p.id)}>Use</button>}
                <button className="btn ghost" onClick={() => setEditing({ ...p })}>Edit</button>
                <button className="icon-btn" onClick={() => remove(p.id)} title="Delete"><Trash2 size={15} /></button>
              </div>
            )}
          </section>
        ))}
      </div>

      <section className="card">
        <h2>Ingest model</h2>
        <p>One call per document reads its title, parties, block, date and status. A small fast model is enough.</p>
        <select value={settings.ingest_profile || ""} onChange={async (e) => { await api.setIngestProfile(e.target.value); load(); }}>
          <option value="">Same as the active model</option>
          {settings.profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </section>

      <EmbeddingCard settings={settings} status={status} onSaved={() => { load(); refreshStatus(); }} />

      <section className="card">
        <h2>Admin token</h2>
        <p>Needed only when the server sets <code>ADMIN_TOKEN</code>. Stored in this browser.</p>
        <div className="input-row">
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="optional" />
          <button className="btn" onClick={() => { setAdminToken(token); load(); }}>Save</button>
        </div>
      </section>
    </div>
  );
}
