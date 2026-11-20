import { useEffect, useState } from "react";
import { ExternalLink, FileText, X } from "lucide-react";
import { api } from "../api.js";
import { pages, where } from "../answer.js";

// PDF text keeps the page's line breaks. Join wrapped lines; keep breaks
// before numbered clauses and (a)/(i) items.
const reflow = (text) =>
  text.replace(/([^\n])\n(?!\n|\s*(?:\(?[a-z0-9]{1,4}[).]|\d+\.\d+|ARTICLE|Article|[A-Z][A-Z ]{6,}$))/gm, "$1 ");

export default function SourcePanel({ chunkId, onClose }) {
  const [hit, setHit] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!chunkId) return;
    setHit(null);
    setError("");
    api.chunks([chunkId]).then((rows) => (rows[0] ? setHit(rows[0]) : setError("Passage not found."))).catch((e) => setError(e.message));
  }, [chunkId]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!chunkId) return null;
  const external = hit && hit.url !== hit.local_url;
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="source-panel" role="dialog" aria-label="Source passage">
        <header>
          <div>
            <span className="eyebrow">Source passage</span>
            <h3>{hit ? hit.document : "Loading…"}</h3>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </header>
        {error && <p className="banner-error">{error}</p>}
        {hit && (
          <>
            <dl className="facts">
              <div><dt>Location</dt><dd>{where(hit)}</dd></div>
              {hit.article_title && <div><dt>Article</dt><dd>{/^\d+$/.test(hit.article) ? `Article ${hit.article} · ` : ""}{hit.article_title}</dd></div>}
              <div><dt>Pages</dt><dd>{pages(hit)}{hit.parts > 1 ? ` · part ${hit.part} of ${hit.parts}` : ""}</dd></div>
              <div><dt>File</dt><dd className="mono">{hit.cite_path || hit.path}</dd></div>
              {(hit.family || hit.status || hit.doc_date) && (
                <div><dt>Document</dt><dd>{[hit.family, hit.status, hit.doc_date].filter(Boolean).join(" · ")}</dd></div>
              )}
            </dl>
            <div className="passage">{reflow(hit.text)}</div>
            <div className="panel-actions">
              {external && <a className="btn primary" href={hit.url} target="_blank" rel="noreferrer" title={hit.url}><ExternalLink size={15} /> Open in Document Center</a>}
              <a className={external ? "btn" : "btn primary"} href={hit.local_url} target="_blank" rel="noreferrer">
                <FileText size={15} /> {/\.pdf$/i.test(hit.path) ? `Local PDF at ${pages(hit)}` : "Local file"}
              </a>
            </div>
          </>
        )}
      </aside>
    </>
  );
}
