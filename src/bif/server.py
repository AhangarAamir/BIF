"""AgentOS runtime + JSON API + web UI.

AgentOS provides the agent endpoints (POST /agents/query-agent/runs, SSE)
and /sessions, the same shape aamir-rag used. The /api routes below add model
profiles, the document library, ingest jobs, citation lookup and feedback.

    uv run bif serve        ->  http://127.0.0.1:8000
"""

from __future__ import annotations

import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from agno.os import AgentOS
from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bif import settings as app_settings
from bif.agent.agents import (
    QUERY_AGENT_ID,
    SESSIONS_DB_ID,
    apply_active_model,
    build_ingest_agent,
    build_query_agent,
    sessions_db,
)
from bif.config import ADMIN_TOKEN, CORPUS_DIR, CORS_ALLOWED_ORIGINS, UI_DIST
from bif.domain import family_codes
from bif.index import store
from bif.index.search import get_chunks, search
from bif.ingest.extract import SUPPORTED_SUFFIXES
from bif.models import list_models, test_chat, test_embedding

api = APIRouter(prefix="/api", tags=["bif"])


def require_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    if ADMIN_TOKEN and x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Admin token required.")


# ------------------------------------------------------------------ status

@api.get("/status")
def status() -> dict[str, Any]:
    s = app_settings.load()
    profile = app_settings.active_profile(s)
    stats = store.stats()
    emb = s.embedding
    return {
        "agent_id": QUERY_AGENT_ID,
        "db_id": SESSIONS_DB_ID,
        "model": {
            "id": profile.id, "name": profile.name, "model": profile.model,
            "provider": profile.provider, "api": profile.api,
        },
        "embedding": {
            "enabled": emb.enabled,
            "model": emb.model,
            "indexed_with": stats["embedding_model"],
            "needs_reembed": emb.enabled and stats["chunks"] > 0 and (
                stats["embedded"] < stats["chunks"] or (stats["embedding_model"] and stats["embedding_model"] != emb.model)
            ),
        },
        "library": stats,
        "admin_required": bool(ADMIN_TOKEN),
        "families": family_codes(),
    }


# ------------------------------------------------------------------ settings

class ProfileIn(BaseModel):
    id: Optional[str] = None
    name: str
    provider: str = "custom"
    base_url: str
    api_key: Optional[str] = None
    model: str
    api: str = "chat"
    reasoning_summary: str = ""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    reasoning_effort: str = ""
    timeout: float = 300.0


class EmbeddingIn(BaseModel):
    enabled: bool = True
    provider: str = "custom"
    base_url: str
    api_key: Optional[str] = None
    model: str
    batch_size: int = 64


class ActiveIn(BaseModel):
    profile_id: str


class ModelsQuery(BaseModel):
    base_url: str = ""
    api_key: Optional[str] = None
    profile_id: Optional[str] = None
    embedding: bool = False


@api.get("/settings")
def get_settings() -> dict[str, Any]:
    return app_settings.public_view()


@api.post("/settings/profiles", dependencies=[Depends(require_admin)])
def upsert_profile(body: ProfileIn) -> dict[str, Any]:
    s = app_settings.load()
    existing = app_settings.get_profile(body.id, s) if body.id else None
    data = body.model_dump()
    data["api_key"] = app_settings.merge_secret(body.api_key, existing.api_key if existing else "")
    if not data["base_url"]:
        raise HTTPException(400, "base_url is required (for example http://localhost:11434/v1).")
    if not data["model"]:
        raise HTTPException(400, "model is required.")
    if existing:
        data["id"] = existing.id
    else:
        data.pop("id", None)
    try:
        profile = app_settings.ModelProfile(**data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if existing:
        s.profiles = [profile if p.id == existing.id else p for p in s.profiles]
    else:
        s.profiles.append(profile)
    app_settings.save(s)
    if existing and existing.id == s.active_profile:
        apply_active_model()
    return app_settings.public_view()


@api.delete("/settings/profiles/{profile_id}", dependencies=[Depends(require_admin)])
def delete_profile(profile_id: str) -> dict[str, Any]:
    s = app_settings.load()
    if len(s.profiles) <= 1:
        raise HTTPException(400, "Keep at least one model profile.")
    s.profiles = [p for p in s.profiles if p.id != profile_id]
    app_settings.save(s)
    apply_active_model()
    return app_settings.public_view()


@api.post("/settings/active", dependencies=[Depends(require_admin)])
def set_active(body: ActiveIn) -> dict[str, Any]:
    s = app_settings.load()
    if not app_settings.get_profile(body.profile_id, s):
        raise HTTPException(404, "Unknown profile.")
    s.active_profile = body.profile_id
    app_settings.save(s)
    apply_active_model()
    return app_settings.public_view()


@api.post("/settings/ingest-profile", dependencies=[Depends(require_admin)])
def set_ingest_profile(body: ActiveIn) -> dict[str, Any]:
    s = app_settings.load()
    s.ingest_profile = body.profile_id if app_settings.get_profile(body.profile_id, s) else ""
    app_settings.save(s)
    return app_settings.public_view()


@api.put("/settings/embedding", dependencies=[Depends(require_admin)])
def set_embedding(body: EmbeddingIn) -> dict[str, Any]:
    s = app_settings.load()
    data = body.model_dump()
    data["api_key"] = app_settings.merge_secret(body.api_key, s.embedding.api_key)
    s.embedding = app_settings.EmbeddingSettings(**data)
    app_settings.save(s)
    return app_settings.public_view()


def _resolve_endpoint(body: ModelsQuery) -> tuple[str, str]:
    s = app_settings.load()
    stored = ""
    if body.embedding:
        stored = s.embedding.api_key
    elif body.profile_id and (p := app_settings.get_profile(body.profile_id, s)):
        stored = p.api_key
        if not body.base_url:
            body.base_url = p.base_url
    key = app_settings.merge_secret(body.api_key, stored)
    base = app_settings.normalize_base_url(body.base_url or (s.embedding.base_url if body.embedding else ""))
    if not base:
        raise HTTPException(400, "base_url is required.")
    return base, key


@api.post("/models/list", dependencies=[Depends(require_admin)])
def models_list(body: ModelsQuery) -> dict[str, Any]:
    base, key = _resolve_endpoint(body)
    try:
        return {"models": list_models(base, key)}
    except Exception as exc:
        raise HTTPException(502, f"Could not list models at {base}/models: {exc}")


@api.post("/models/test", dependencies=[Depends(require_admin)])
def models_test(body: ProfileIn) -> dict[str, Any]:
    existing = app_settings.get_profile(body.id) if body.id else None
    data = body.model_dump()
    data["api_key"] = app_settings.merge_secret(body.api_key, existing.api_key if existing else "")
    data.pop("id", None)
    try:
        return test_chat(app_settings.ModelProfile(**data))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@api.post("/models/test-embedding", dependencies=[Depends(require_admin)])
def models_test_embedding(body: EmbeddingIn) -> dict[str, Any]:
    data = body.model_dump()
    data["api_key"] = app_settings.merge_secret(body.api_key, app_settings.load().embedding.api_key)
    try:
        return test_embedding(app_settings.EmbeddingSettings(**data))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ------------------------------------------------------------------ jobs

class Jobs:
    """One background ingest / re-embed job at a time, with progress for the UI."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.running: Optional[str] = None

    def start(self, kind: str, target, **kwargs) -> dict[str, Any]:
        with self._lock:
            if self.running and self.jobs[self.running]["state"] == "running":
                raise HTTPException(409, "Another library job is running.")
            job_id = uuid.uuid4().hex[:10]
            job = {"id": job_id, "kind": kind, "state": "running", "started": time.time(),
                   "progress": {"done": 0, "total": 0, "current": ""}, "result": None, "error": None}
            self.jobs[job_id] = job
            self.running = job_id

        def progress(event: dict[str, Any]) -> None:
            p = job["progress"]
            if event["type"] == "file":
                p.update(done=event["index"] - 1, total=event["total"], current=event["file"])
            elif event["type"] == "embed":
                p.update(done=event["done"], total=event["total"], current="embedding")
            elif event["type"] == "done":
                p.update(done=event["total"], total=event["total"], current="")

        def run() -> None:
            try:
                result = target(on_progress=progress, **kwargs)
                job["result"] = result.as_dict() if hasattr(result, "as_dict") else result
                job["state"] = "done"
            except Exception as exc:
                job["error"] = str(exc)
                job["state"] = "error"
            job["finished"] = time.time()

        threading.Thread(target=run, daemon=True, name=f"bif-{kind}").start()
        return job

    def list(self) -> list[dict[str, Any]]:
        return sorted(self.jobs.values(), key=lambda j: -j["started"])[:20]


JOBS = Jobs()


class IngestIn(BaseModel):
    path: str = ""
    force: bool = False
    use_llm: Optional[bool] = None


@api.post("/ingest", dependencies=[Depends(require_admin)])
def start_ingest(body: IngestIn) -> dict[str, Any]:
    from bif.ingest.pipeline import ingest_path, resolve_corpus_path

    try:
        resolve_corpus_path(body.path or None)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc))
    return JOBS.start("ingest", ingest_path, path=body.path or None, force=body.force, use_llm=body.use_llm)


@api.post("/reembed", dependencies=[Depends(require_admin)])
def start_reembed() -> dict[str, Any]:
    from bif.ingest.pipeline import reembed

    return JOBS.start("reembed", reembed)


@api.get("/jobs")
def jobs() -> list[dict[str, Any]]:
    return JOBS.list()


# ------------------------------------------------------------------ library

# Only characters that are unsafe in file paths are replaced; real names are kept so
# Document Center links still match the original file names.
_SAFE = re.compile(r'[<>:"|?*\x00-\x1f]')


def _safe_rel(path: str) -> Path:
    """Relative path with '..', '.', empty and absolute parts removed."""
    parts = [p.strip() for p in (path or "").replace("\\", "/").split("/")]
    parts = [_SAFE.sub("_", p) for p in parts if p and p not in {".", ".."}]
    return Path(*parts) if parts else Path()


@api.get("/documents")
def documents() -> list[dict[str, Any]]:
    out = []
    for d in store.list_documents():
        d.pop("alias_keys", None)
        out.append(d)
    return out


@api.get("/documents/{doc_id}/outline")
def document_outline(doc_id: int) -> dict[str, Any]:
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Unknown document.")
    rows = store.query(
        "SELECT id, kind, article, article_title, clause_id, heading, defined_term, page_start, page_end, part, parts"
        " FROM chunks WHERE doc_id=? ORDER BY ord",
        (doc_id,),
    )
    doc.pop("alias_keys", None)
    return {"document": doc, "chunks": [dict(r) for r in rows]}


@api.delete("/documents/{doc_id}", dependencies=[Depends(require_admin)])
def delete_document(doc_id: int, delete_file: bool = False) -> dict[str, Any]:
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Unknown document.")
    store.delete_document(doc_id)
    if delete_file:
        target = (CORPUS_DIR / doc["rel_path"]).resolve()
        if CORPUS_DIR.resolve() in target.parents and target.is_file():
            target.unlink()
    return {"deleted": doc["rel_path"]}


@api.post("/documents/upload", dependencies=[Depends(require_admin)])
async def upload(
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(default=[]),
    folder: str = Form(""),
    ingest: bool = Form(True),
) -> dict[str, Any]:
    """Save files under the corpus, keeping their folder structure.

    `paths[i]` is the relative path of `files[i]` inside an uploaded folder
    (e.g. "JOA/New JOA/file.pdf"); without it the bare file name is used.
    Unsupported extensions and hidden files are skipped, not rejected, so a
    folder upload always continues. The UI sends large folders in batches with
    ingest=false, then starts one ingest job.
    """
    corpus = CORPUS_DIR.resolve()
    base = (corpus / _safe_rel(folder)).resolve()
    if base != corpus and corpus not in base.parents:
        raise HTTPException(400, "Folder must be inside the corpus.")
    saved: list[str] = []
    skipped: list[dict[str, str]] = []
    for index, item in enumerate(files):
        raw = (paths[index] if index < len(paths) and paths[index] else item.filename) or "upload"
        rel = _safe_rel(raw)
        if not rel.parts:
            skipped.append({"file": raw, "reason": "empty name"})
            continue
        if any(part.startswith(".") for part in rel.parts):
            skipped.append({"file": raw, "reason": "hidden file"})
            continue
        if rel.suffix.lower() not in SUPPORTED_SUFFIXES:
            skipped.append({"file": raw, "reason": f"unsupported type {rel.suffix or '(none)'}"})
            continue
        target = (base / rel).resolve()
        if corpus not in target.parents:
            skipped.append({"file": raw, "reason": "outside the corpus"})
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as fh:
                shutil.copyfileobj(item.file, fh)
        except OSError as exc:
            skipped.append({"file": raw, "reason": f"could not save: {exc}"})
            continue
        saved.append(target.relative_to(corpus).as_posix())
    job = None
    if ingest and saved:
        from bif.ingest.pipeline import ingest_path

        rel_folder = _safe_rel(folder).as_posix()
        job = JOBS.start("ingest", ingest_path, path=rel_folder if rel_folder != "." else None)
    return {"saved": saved, "skipped": skipped, "job": job}


@api.get("/chunks/{chunk_id}")
def chunk(chunk_id: int) -> dict[str, Any]:
    hits = get_chunks([chunk_id])
    if not hits:
        raise HTTPException(404, "Unknown passage.")
    return hits[0]


@api.get("/chunks")
def chunks(ids: str) -> list[dict[str, Any]]:
    wanted = [int(x) for x in re.findall(r"\d+", ids)][:100]
    return get_chunks(wanted)


@api.get("/search")
def search_api(q: str, document: str = "", family: str = "", k: int = 8) -> dict[str, Any]:
    return search(q, document=document, family=family, top_k=max(1, min(k, 30)))


class FeedbackIn(BaseModel):
    rating: int = 0
    comment: str = ""
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    query: str = ""
    answer: str = ""
    model: str = ""


@api.post("/feedback")
def feedback(body: FeedbackIn) -> dict[str, Any]:
    return {"id": store.add_feedback(**body.model_dump())}


# ------------------------------------------------------------------ app

base_app = FastAPI(title="BIF Legal Research")
base_app.include_router(api)


@base_app.get("/files/{path:path}", include_in_schema=False)
def corpus_file(path: str):
    target = (CORPUS_DIR / path).resolve()
    if CORPUS_DIR.resolve() not in target.parents or not target.is_file():
        raise HTTPException(404, "File not found.")
    media = "application/pdf" if target.suffix.lower() == ".pdf" else "text/plain; charset=utf-8"
    return FileResponse(target, media_type=media, content_disposition_type="inline")


WIDGET_JS = r"""(function(){
  var s=document.currentScript, origin=(s&&s.src)?new URL(s.src).origin:location.origin;
  var title=(s&&s.dataset.title)||'Legal Research', color=(s&&s.dataset.color)||'#4f46e5';
  var pos=(s&&s.dataset.position)==='left'?'left':'right';
  var btn=document.createElement('button');
  btn.setAttribute('aria-label','Open '+title);
  btn.innerHTML='<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  btn.style.cssText='position:fixed;bottom:24px;'+pos+':24px;width:60px;height:60px;border-radius:50%;border:0;cursor:pointer;z-index:2147483646;background:'+color+';box-shadow:0 10px 30px rgba(0,0,0,.25);display:flex;align-items:center;justify-content:center;transition:transform .2s';
  btn.onmouseenter=function(){btn.style.transform='scale(1.06)'};btn.onmouseleave=function(){btn.style.transform='scale(1)'};
  var frame=document.createElement('iframe');
  frame.title=title; frame.src=origin+'/?embed=1';
  frame.style.cssText='position:fixed;bottom:96px;'+pos+':24px;width:min(420px,calc(100vw - 32px));height:min(680px,calc(100vh - 120px));border:0;border-radius:18px;box-shadow:0 24px 60px rgba(0,0,0,.28);z-index:2147483647;display:none;background:#fff';
  btn.onclick=function(){frame.style.display=frame.style.display==='none'?'block':'none'};
  document.body.appendChild(frame);document.body.appendChild(btn);
})();"""


@base_app.get("/widget.js", include_in_schema=False)
def widget_js() -> Response:
    return Response(WIDGET_JS, media_type="application/javascript")


def _index() -> Response:
    index = UI_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse(
        "<!doctype html><body style='font-family:system-ui;padding:3rem'><h2>UI not built</h2>"
        "<p>Run <code>cd ui &amp;&amp; npm install &amp;&amp; npm run build</code>, then restart.</p>"
        "<p>The API is up: <a href='/docs'>/docs</a></p></body>",
        status_code=503,
    )


for route in ("/", "/library", "/settings", "/widget-demo"):
    base_app.add_api_route(route, _index, include_in_schema=False)

if (UI_DIST / "assets").is_dir():
    base_app.mount("/assets", StaticFiles(directory=str(UI_DIST / "assets")), name="assets")

query_agent = build_query_agent()
ingest_agent = build_ingest_agent()

agent_os = AgentOS(
    id="bif-os",
    name="BIF Legal Research",
    description="Legal research agent with verified citations over contract PDFs.",
    agents=[query_agent, ingest_agent],
    db=sessions_db(),
    base_app=base_app,
    on_route_conflict="preserve_base_app",
    cors_allowed_origins=CORS_ALLOWED_ORIGINS,
)
app = agent_os.get_app()
