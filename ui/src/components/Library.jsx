import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronRight, FileText, FolderUp, Layers, Loader2, RefreshCw, Search, Trash2, UploadCloud, Wand2 } from "lucide-react";
import { api } from "../api.js";
import { classify, fromDrop, fromFileList, uploadAll } from "../upload.js";

function ReviewPanel({ pending, folder, setFolder, keepTop, setKeepTop, onCancel, onConfirm }) {
  const [autoAnchor, setAutoAnchor] = useState(true);
  const [preview, setPreview] = useState(null);
  const [folders, setFolders] = useState([]);
  const [error, setError] = useState("");
  const paths = pending.accepted.map((i) => i.path);
  const top = paths[0]?.includes("/") ? paths[0].split("/")[0] : "";

  useEffect(() => { api.folders().then(setFolders).catch(() => {}); }, []);
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      api.uploadPreview({ paths, folder, keep_top: keepTop, auto_anchor: autoAnchor })
        .then((p) => live && (setPreview(p), setError("")))
        .catch((e) => live && setError(e.message));
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [folder, keepTop, autoAnchor, pending]); // eslint-disable-line react-hooks/exhaustive-deps

  const needsChoice = preview && preview.unanchored > 0;
  return (
    <section className="card review">
      <div className="review-head">
        <div>
          <h2>Review upload{top ? ` · “${top}”` : ""}</h2>
          <p>
            {pending.accepted.length} file{pending.accepted.length === 1 ? "" : "s"} to upload
            {pending.skipped.length ? ` · ${pending.skipped.length} will be skipped (unsupported or hidden)` : ""}.
            The browser does not tell us where this folder sits in the Document Center, so check the places and links below.
          </p>
        </div>
      </div>

      {preview && (
        <div className="destinations">
          {Object.entries(preview.destinations).map(([dest, n]) => (
            <span key={dest} className="pill">{n} → {dest}</span>
          ))}
        </div>
      )}

      {needsChoice && (
        <div className="callout">
          {preview.unanchored === 1 ? "1 file has" : `${preview.unanchored} files have`} no Document Center folder
          (JOA, PSC, sites, “Document Center”…) in {preview.unanchored === 1 ? "its" : "their"} path, so{" "}
          {preview.unanchored === 1 ? "it goes" : "they go"} under the “Save under” folder below
          {folder ? ` (“${folder}”)` : " (currently the Document Center root)"}.
          {preview.suggestion && (
            <> Suggested: <button className="link-btn" onClick={() => setFolder(preview.suggestion)}>{preview.suggestion}</button> ({preview.suggestion_reason}).</>
          )}
        </div>
      )}

      <div className="review-options">
        <label>Save under (for files without a detected place)
          <input list="corpus-folders" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="Document Center root" />
          <datalist id="corpus-folders">{folders.map((f) => <option key={f} value={f} />)}</datalist>
        </label>
        <label className="check"><input type="checkbox" checked={keepTop} onChange={(e) => setKeepTop(e.target.checked)} /> Keep the picked folder's own name{top ? ` (“${top}”)` : ""}</label>
        <label className="check"><input type="checkbox" checked={autoAnchor} onChange={(e) => setAutoAnchor(e.target.checked)} /> Detect the Document Center place from the path</label>
      </div>

      {error && <p className="banner-error">{error}</p>}
      {preview && (
        <div className="table-wrap">
          <table className="preview-table">
            <thead><tr><th>File</th><th>Saved as</th><th>Link</th></tr></thead>
            <tbody>
              {preview.rows.map((r) => (
                <tr key={r.file}>
                  <td className="mono">{r.file}</td>
                  <td><span className="mono">{r.saved_as}</span><br /><small>{r.how}</small></td>
                  <td><a className="mono" href={r.link} target="_blank" rel="noreferrer">{decodeURI(r.link).replace(/^https?:\/\/[^/]+/, "")}</a></td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview.total > preview.rows.length && <small className="more">…and {preview.total - preview.rows.length} more</small>}
        </div>
      )}

      <div className="editor-actions">
        <span className="spacer" />
        <button className="btn ghost" onClick={onCancel}>Cancel</button>
        <button className="btn primary" disabled={!preview} onClick={() => onConfirm({ folder, keepTop, autoAnchor })}>
          <UploadCloud size={15} /> Upload {pending.accepted.length} file{pending.accepted.length === 1 ? "" : "s"}
        </button>
      </div>
    </section>
  );
}

function UploadPanel({ upload, onClose }) {
  if (!upload) return null;
  const { phase, sent, total, saved, skipped, failed } = upload;
  const pct = total ? Math.round((sent / total) * 100) : 100;
  const byReason = skipped.reduce((acc, s) => ({ ...acc, [s.reason]: (acc[s.reason] || 0) + 1 }), {});
  return (
    <div className={`job ${failed.length ? "error" : phase === "done" ? "done" : "running"}`}>
      <div className="job-line">
        {phase !== "done" && <Loader2 size={15} className="spin" />}
        <strong>{phase === "uploading" ? "Uploading" : phase === "indexing" ? "Starting indexing" : "Upload finished"}</strong>
        <span>
          {saved.length} uploaded{total ? ` of ${total}` : ""}
          {skipped.length ? ` · ${skipped.length} skipped` : ""}
          {failed.length ? ` · ${failed.length} failed` : ""}
        </span>
        <span className="spacer" />
        {phase === "done" && <button className="btn ghost" onClick={onClose}>Dismiss</button>}
      </div>
      <div className="progress"><span style={{ width: `${pct}%` }} /></div>
      {skipped.length > 0 && (
        <details className="skipped">
          <summary>
            Skipped: {Object.entries(byReason).map(([r, n]) => `${n} × ${r}`).join(", ")}
          </summary>
          <ul>{skipped.slice(0, 200).map((s, i) => <li key={i}><span className="mono">{s.file}</span> — {s.reason}</li>)}</ul>
          {skipped.length > 200 && <small>…and {skipped.length - 200} more</small>}
        </details>
      )}
      {failed.length > 0 && (
        <ul className="job-issues">{failed.slice(0, 20).map((f, i) => <li key={i}><AlertTriangle size={13} /> {f.file}: {f.reason}</li>)}</ul>
      )}
    </div>
  );
}

function Stat({ icon: Icon, label, value, hint }) {
  return (
    <div className="stat">
      <Icon size={18} />
      <div><strong>{value ?? "–"}</strong><span>{label}</span>{hint && <small>{hint}</small>}</div>
    </div>
  );
}

function JobBar({ job }) {
  if (!job) return null;
  const p = job.progress || {};
  const pct = p.total ? Math.round((p.done / p.total) * 100) : job.state === "running" ? 5 : 100;
  const r = job.result;
  return (
    <div className={`job ${job.state}`}>
      <div className="job-line">
        {job.state === "running" ? <Loader2 size={15} className="spin" /> : null}
        <strong>
          {job.state === "running"
            ? (job.kind === "reembed" ? "Embedding" : "Indexing")
            : job.state === "error"
              ? (job.kind === "reembed" ? "Embedding failed" : "Indexing failed")
              : (job.kind === "reembed" ? "Embedding finished" : "Indexing finished")}
        </strong>
        <span>{job.state === "running" ? (p.current || "starting…") : job.state === "error" ? job.error : r?.added ? `${r.added.length} added · ${r.updated.length} updated · ${r.skipped.length} unchanged · ${r.failed.length} failed${r.removed?.length ? ` · ${r.removed.length} removed (file gone)` : ""}` : r?.embedded !== undefined ? `${r.embedded} passages embedded` : "done"}</span>
        <span className="spacer" />
        {p.total ? <small>{p.done}/{p.total}</small> : null}
      </div>
      <div className="progress"><span style={{ width: `${pct}%` }} /></div>
      {r?.failed?.length > 0 && <ul className="job-issues">{r.failed.map((f) => <li key={f.file}><AlertTriangle size={13} /> {f.file}: {f.error}</li>)}</ul>}
      {r?.warnings?.length > 0 && <ul className="job-issues warn">{r.warnings.slice(0, 8).map((w) => <li key={w}><AlertTriangle size={13} /> {w}</li>)}</ul>}
    </div>
  );
}

function Outline({ doc }) {
  const [data, setData] = useState(null);
  useEffect(() => { api.outline(doc.id).then(setData).catch(() => {}); }, [doc.id]);
  if (!data) return <div className="outline"><Loader2 size={14} className="spin" /></div>;
  const groups = [];
  for (const c of data.chunks) {
    const key = c.article || (c.kind === "toc" ? "Contents" : c.kind === "preamble" ? "Preamble" : "Text");
    let g = groups[groups.length - 1];
    if (!g || g.key !== key) groups.push((g = { key, title: c.article_title, items: [] }));
    g.items.push(c);
  }
  return (
    <div className="outline">
      {doc.summary && <p className="summary">{doc.summary}</p>}
      {doc.parties?.length > 0 && <p className="parties"><strong>Parties:</strong> {doc.parties.join(" · ")}</p>}
      <div className="outline-groups">
        {groups.map((g, i) => (
          <div key={i} className="og">
            <div className="og-head">{/^\d+$/.test(g.key) ? `Article ${g.key}` : g.key}{g.title ? ` — ${g.title}` : ""}</div>
            <div className="og-items">
              {g.items.filter((c) => c.clause_id || c.defined_term).map((c) => (
                <span key={c.id} className={`chip ${c.kind}`} title={`pp. ${c.page_start}–${c.page_end}`}>
                  {c.kind === "definition" ? c.defined_term : c.clause_id}{c.parts > 1 ? ` (${c.part}/${c.parts})` : ""}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function LibraryPage({ status, refreshStatus }) {
  const [docs, setDocs] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [filter, setFilter] = useState("");
  const [folder, setFolder] = useState("");
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);
  const [keepTop, setKeepTop] = useState(true);
  const fileInput = useRef(null);
  const folderInput = useRef(null);

  const load = useCallback(async () => {
    try {
      const [d, j] = await Promise.all([api.documents(), api.jobs()]);
      setDocs(d);
      setJobs(j);
      return j;
    } catch (e) { setError(e.message); return []; }
  }, []);

  useEffect(() => { load(); }, [load]);
  const running = jobs.some((j) => j.state === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const j = await load();
      if (!j.some((x) => x.state === "running")) refreshStatus();
    }, 1500);
    return () => clearInterval(t);
  }, [running, load, refreshStatus]);

  const act = async (fn) => {
    setError("");
    try { await fn(); await load(); } catch (e) { setError(e.message); }
  };
  const [upload, setUpload] = useState(null); // { phase, sent, total, saved, skipped, failed }

  const [pending, setPending] = useState(null); // { accepted, skipped } awaiting review

  // Step 1: pick / drop -> review where files will go. Nothing is uploaded yet.
  const startUpload = (items) => {
    setError("");
    const { accepted, skipped } = classify(items);
    if (!accepted.length) {
      setUpload({ phase: "done", sent: 0, total: 0, saved: [], skipped, failed: [] });
      return;
    }
    setUpload(null);
    // Every selection starts from scratch: a "save under" left over from the last
    // upload would silently misplace this one.
    setFolder("");
    setKeepTop(true);
    setPending({ accepted, skipped });
  };

  // Step 2: confirmed in the review panel.
  const confirmUpload = async (options) => {
    const { accepted, skipped } = pending;
    setPending(null);
    setUpload({ phase: "uploading", sent: 0, total: accepted.length, saved: [], skipped, failed: [] });
    const result = await uploadAll(accepted, options, (p) =>
      setUpload((u) => ({ ...u, sent: p.sent, saved: p.saved, failed: p.failed, skipped: [...skipped, ...p.skipped] })),
    );
    setUpload((u) => ({ ...u, phase: "indexing", saved: result.saved, failed: result.failed, skipped: [...skipped, ...result.skipped] }));
    try {
      // Files can land in several Document Center folders; scanning skips unchanged files.
      if (result.saved.length) await api.ingest({ path: "" });
    } catch (e) {
      // Another job is running: the files are saved; "Scan corpus" indexes them later.
      setError(`Files saved, but indexing could not start: ${e.message}. Click “Scan corpus” when the current job finishes.`);
    }
    setUpload((u) => ({ ...u, phase: "done" }));
    await load();
  };
  const onDrop = async (e) => {
    e.preventDefault();
    setDrag(false);
    startUpload(await fromDrop(e.dataTransfer));
  };

  const busy = Boolean(pending) || upload?.phase === "uploading" || upload?.phase === "indexing";
  const lib = status?.library;
  const shown = docs.filter((d) => !filter || `${d.title} ${d.short_name} ${d.rel_path} ${d.family}`.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Library</h1><p>Documents the agent answers from. Files are parsed into articles, clauses and definitions with page numbers.</p></div>
        <div className="head-actions">
          <button className="btn" disabled={running} onClick={() => act(() => api.ingest({ path: "" }))}><RefreshCw size={15} /> Scan corpus</button>
          {status?.embedding?.needs_reembed && <button className="btn" disabled={running} onClick={() => act(() => api.reembed())}><Wand2 size={15} /> Re-embed</button>}
        </div>
      </header>

      <div className="stats">
        <Stat icon={FileText} label="documents" value={lib?.documents} />
        <Stat icon={Layers} label="passages" value={lib?.chunks?.toLocaleString()} hint={`${lib?.pages ?? 0} pages`} />
        <Stat icon={Wand2} label="embedded" value={lib ? `${lib.chunks ? Math.round((lib.embedded / lib.chunks) * 100) : 0}%` : "–"} hint={lib?.embedding_model || "no model"} />
        <Stat icon={AlertTriangle} label="pages without text" value={lib?.empty_pages} hint="need OCR" />
      </div>

      {error && <p className="banner-error">{error}</p>}
      {jobs.slice(0, 1).map((j) => <JobBar key={j.id} job={j} />)}

      <div
        className={`dropzone ${drag ? "drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
      >
        <UploadCloud size={28} />
        <div className="drop-text">
          <strong>Drop files or whole folders here</strong>
          <span>Sub-folders are kept and placed to match the Document Center, so links are right. You review where files go before anything is uploaded. Only PDF, Markdown and TXT are uploaded.</span>
          <div className="drop-actions">
            <button type="button" className="btn" disabled={busy} onClick={() => fileInput.current?.click()}><FileText size={14} /> Upload files</button>
            <button type="button" className="btn" disabled={busy} onClick={() => folderInput.current?.click()}><FolderUp size={14} /> Upload folder</button>
          </div>
        </div>
        <input ref={fileInput} type="file" multiple hidden onChange={(e) => { startUpload(fromFileList(e.target.files)); e.target.value = ""; }} />
        <input ref={folderInput} type="file" multiple hidden webkitdirectory="" directory="" onChange={(e) => { startUpload(fromFileList(e.target.files)); e.target.value = ""; }} />
      </div>
      {pending && (
        <ReviewPanel
          pending={pending}
          folder={folder}
          setFolder={setFolder}
          keepTop={keepTop}
          setKeepTop={setKeepTop}
          onCancel={() => setPending(null)}
          onConfirm={confirmUpload}
        />
      )}
      <UploadPanel upload={upload} onClose={() => setUpload(null)} />

      <div className="table-tools">
        <div className="input-icon grow"><Search size={14} /><input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter documents" /></div>
      </div>

      <div className="doc-list">
        {shown.length === 0 && <p className="empty">No documents yet.</p>}
        {shown.map((d) => (
          <div key={d.id} className={`doc ${open === d.id ? "open" : ""}`}>
            <div className="doc-row" onClick={() => setOpen(open === d.id ? null : d.id)}>
              <ChevronRight size={15} className="chev" />
              <span className="fam">{d.family || "—"}</span>
              <div className="doc-text">
                <strong>{d.short_name || d.title}</strong>
                <small className="mono">{d.rel_path}</small>
              </div>
              <span className="doc-meta">
                {d.status && <span className="pill">{d.status}</span>}
                {d.doc_date && <span>{d.doc_date}</span>}
                <span>{d.pages} pp · {d.chunks} passages</span>
                {d.empty_pages?.length > 0 && <span className="pill warn" title={`Pages ${d.empty_pages.join(", ")}`}>{d.empty_pages.length} need OCR</span>}
              </span>
              <a className="icon-btn" href={`/files/${d.rel_path.split("/").map(encodeURIComponent).join("/")}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} title="Open"><FileText size={15} /></a>
              <button className="icon-btn" title="Remove from index" onClick={(e) => { e.stopPropagation(); if (confirm(`Remove ${d.filename} from the index? The file stays on disk.`)) act(() => api.deleteDocument(d.id, false)); }}><Trash2 size={15} /></button>
            </div>
            {open === d.id && <Outline doc={d} />}
          </div>
        ))}
      </div>
    </div>
  );
}
