"""Model profiles stored in data/settings.json.

A profile is any OpenAI-compatible chat/completions endpoint:
base_url (up to and including /v1), api_key, and model id. Ollama, OpenAI,
vLLM, LM Studio, OpenRouter, Groq and Together all fit this shape, so
switching from an open-source model to a paid one is only a profile change.

The embedding endpoint is configured the same way, separately, because a
change of embedding model needs a re-embed of the index.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from bif.config import SETTINGS_FILE

_LOCK = threading.RLock()
MASK_PREFIX = "••••"

PRESETS: dict[str, dict[str, str]] = {
    "ollama": {"label": "Ollama (local)", "base_url": "http://localhost:11434/v1"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "api": "responses"},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1"},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1"},
    "together": {"label": "Together AI", "base_url": "https://api.together.xyz/v1"},
    "vllm": {"label": "vLLM", "base_url": "http://localhost:8001/v1"},
    "lmstudio": {"label": "LM Studio", "base_url": "http://localhost:1234/v1"},
    "custom": {"label": "Custom (OpenAI-compatible)", "base_url": ""},
}


def normalize_base_url(value: str) -> str:
    return (value or "").strip().rstrip("/")


class ModelProfile(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str = "Model"
    provider: str = "custom"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    # "chat"      -> /v1/chat/completions via agno OpenAILike (Ollama, vLLM, most providers)
    # "responses" -> /v1/responses via agno OpenAIResponses (OpenAI; required for function
    #                tools together with reasoning on gpt-5 / gpt-6 class models)
    api: str = "chat"
    # Responses API only: "auto" / "concise" / "detailed" streams a reasoning summary
    # into the research trail. Some OpenAI orgs must be verified to use it.
    reasoning_summary: str = ""
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    # "none" turns thinking off on reasoning models (Ollama qwen3 / gpt-oss,
    # OpenAI o-series / gpt-5). Empty = provider default.
    reasoning_effort: str = ""
    # Seconds before a single model request is abandoned.
    timeout: float = 300.0

    @field_validator("base_url")
    @classmethod
    def _strip(cls, value: str) -> str:
        return normalize_base_url(value)

    @field_validator("api")
    @classmethod
    def _api(cls, value: str) -> str:
        value = (value or "chat").strip().lower()
        if value not in {"chat", "responses"}:
            raise ValueError('api must be "chat" or "responses"')
        return value


class EmbeddingSettings(BaseModel):
    enabled: bool = True
    provider: str = "ollama"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    model: str = "nomic-embed-text"
    batch_size: int = 64

    @field_validator("base_url")
    @classmethod
    def _strip(cls, value: str) -> str:
        return normalize_base_url(value)


class AppSettings(BaseModel):
    profiles: list[ModelProfile] = Field(default_factory=list)
    active_profile: str = ""
    # Optional cheaper / faster profile used for the one-call document profile at ingest.
    ingest_profile: str = ""
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)


def _seed() -> AppSettings:
    profiles: list[ModelProfile] = []
    llm_url = os.getenv("LLM_BASE_URL", PRESETS["ollama"]["base_url"])
    llm_model = os.getenv("LLM_MODEL", "qwen3:8b")
    llm_provider = os.getenv("LLM_PROVIDER", "ollama" if "11434" in llm_url else "custom")
    profiles.append(
        ModelProfile(
            name=os.getenv("LLM_NAME", f"{PRESETS.get(llm_provider, PRESETS['custom'])['label']} · {llm_model}"),
            provider=llm_provider,
            base_url=llm_url,
            api_key=os.getenv("LLM_API_KEY", ""),
            model=llm_model,
            api=os.getenv("LLM_API", "chat"),
            reasoning_effort=os.getenv("LLM_REASONING_EFFORT", ""),
        )
    )
    if os.getenv("OPENAI_API_KEY"):
        profiles.append(
            ModelProfile(
                name=f"OpenAI · {os.getenv('OPENAI_MODEL', 'gpt-4.1')}",
                provider="openai",
                base_url=PRESETS["openai"]["base_url"],
                api_key=os.getenv("OPENAI_API_KEY", ""),
                model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
                api="responses",
                reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", ""),
            )
        )
    embedding = EmbeddingSettings(
        enabled=os.getenv("EMBED_ENABLED", "true").lower() not in {"0", "false", "no", "off"},
        provider=os.getenv("EMBED_PROVIDER", "ollama"),
        base_url=os.getenv("EMBED_BASE_URL", PRESETS["ollama"]["base_url"]),
        api_key=os.getenv("EMBED_API_KEY", ""),
        model=os.getenv("EMBED_MODEL", "nomic-embed-text"),
    )
    return AppSettings(profiles=profiles, active_profile=profiles[0].id, embedding=embedding)


_cache: Optional[AppSettings] = None


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Profiles saved before the `api` field existed: OpenAI -> Responses, others -> chat."""
    for profile in data.get("profiles", []):
        if not profile.get("api"):
            is_openai = profile.get("provider") == "openai" or "api.openai.com" in (profile.get("base_url") or "")
            profile["api"] = "responses" if is_openai else "chat"
    return data


def load() -> AppSettings:
    global _cache
    with _LOCK:
        if _cache is not None:
            return _cache.model_copy(deep=True)
        if SETTINGS_FILE.is_file():
            _cache = AppSettings.model_validate(_migrate(json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))))
        else:
            _cache = _seed()
            _write(_cache)
        return _cache.model_copy(deep=True)


def _write(settings: AppSettings) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = SETTINGS_FILE.with_suffix(".tmp")
    temp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)  # holds API keys
    except OSError:
        pass
    temp.replace(SETTINGS_FILE)


def save(settings: AppSettings) -> AppSettings:
    global _cache
    with _LOCK:
        if not settings.profiles:
            raise ValueError("At least one model profile is required.")
        ids = {profile.id for profile in settings.profiles}
        if settings.active_profile not in ids:
            settings.active_profile = settings.profiles[0].id
        if settings.ingest_profile and settings.ingest_profile not in ids:
            settings.ingest_profile = ""
        _write(settings)
        _cache = settings.model_copy(deep=True)
        return settings


def active_profile(settings: Optional[AppSettings] = None) -> ModelProfile:
    settings = settings or load()
    for profile in settings.profiles:
        if profile.id == settings.active_profile:
            return profile
    return settings.profiles[0]


def ingest_profile(settings: Optional[AppSettings] = None) -> ModelProfile:
    settings = settings or load()
    for profile in settings.profiles:
        if profile.id == settings.ingest_profile:
            return profile
    return active_profile(settings)


def get_profile(profile_id: str, settings: Optional[AppSettings] = None) -> Optional[ModelProfile]:
    settings = settings or load()
    return next((p for p in settings.profiles if p.id == profile_id), None)


# ---------------------------------------------------------------- masking

def mask_key(key: str) -> str:
    key = key or ""
    if not key:
        return ""
    if len(key) <= 8:
        return MASK_PREFIX
    return f"{MASK_PREFIX}{key[-4:]}"


def is_masked(value: Optional[str]) -> bool:
    return bool(value) and str(value).startswith(MASK_PREFIX)


def public_view(settings: Optional[AppSettings] = None) -> dict[str, Any]:
    """Settings for the browser. API keys never leave the server in full."""
    settings = settings or load()
    data = settings.model_dump()
    for profile in data["profiles"]:
        profile["has_api_key"] = bool(profile["api_key"])
        profile["api_key"] = mask_key(profile["api_key"])
    data["embedding"]["has_api_key"] = bool(data["embedding"]["api_key"])
    data["embedding"]["api_key"] = mask_key(data["embedding"]["api_key"])
    data["presets"] = deepcopy(PRESETS)
    return data


def merge_secret(new_value: Optional[str], old_value: str) -> str:
    """The browser sends the masked key back unchanged; keep the stored one."""
    if new_value is None or is_masked(new_value):
        return old_value
    return new_value.strip()
