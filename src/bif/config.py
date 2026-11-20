"""Paths and environment settings.

Model endpoints are not fixed here. They live in data/settings.json and can
be changed at runtime from the UI (see bif.settings). Environment values only
seed that file the first time the app starts.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _path(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    path = Path(raw).expanduser() if raw else default
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


DATA_DIR = _path("DATA_DIR", ROOT_DIR / "data")
# PDFs (and .txt / .md) that the agent answers from. Point this at an
# existing tree such as ../aamir-rag/data/ril_data to reuse its corpus.
CORPUS_DIR = _path("CORPUS_DIR", DATA_DIR / "corpus")
INDEX_DB = DATA_DIR / "index.db"
SESSIONS_DB = DATA_DIR / "sessions.db"
SETTINGS_FILE = DATA_DIR / "settings.json"
UI_DIST = ROOT_DIR / "ui" / "dist"

for _dir in (DATA_DIR, CORPUS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
CORS_ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
# When set, settings / ingest / delete endpoints require the header
# X-Admin-Token with this value. Chat stays open.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()

# Retrieval
SEARCH_TOP_K = int(os.getenv("SEARCH_TOP_K", "8"))
CHUNK_MAX_CHARS = int(os.getenv("CHUNK_MAX_CHARS", "2400"))
NUM_HISTORY_RUNS = int(os.getenv("NUM_HISTORY_RUNS", "4"))
TOOL_CALL_LIMIT = int(os.getenv("TOOL_CALL_LIMIT", "18"))

# One LLM call per document at ingest to read title, parties, block, date
# and status from the first pages. Falls back to filename heuristics.
INGEST_LLM_PROFILE = _bool("INGEST_LLM_PROFILE", True)
# Files processed in parallel during ingest (extraction, profile call, embeddings).
# Raise for remote APIs (OpenAI embeddings); for local Ollama it only helps when
# the server allows parallel requests (OLLAMA_NUM_PARALLEL) or has a GPU.
# Default 1: with several workers, concurrent SQLite writes can fail with
# "database is locked" (open issue). Use --workers > 1 only after that is fixed.
INGEST_WORKERS = max(1, int(os.getenv("INGEST_WORKERS", "1")))

# Citation links, same rules as aamir-rag: files under sites/ link from SITES_BASE_URL,
# every other file from DOC_CENTER_BASE_URL plus its folder path; names end in .pdf.
# Set both to empty strings in .env to link to the local file served by this app instead.
DOC_CENTER_BASE_URL = os.getenv("DOC_CENTER_BASE_URL", "https://enp1.ril.com/sites/Regulatory/Document%20Center").strip()
SITES_BASE_URL = os.getenv("SITES_BASE_URL", "https://enp1.ril.com").strip()
