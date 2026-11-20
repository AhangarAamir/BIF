"""Build Agno models from a profile.

Two wire APIs, picked per profile:
  api="chat"       agno OpenAILike      -> {base_url}/chat/completions
                   Ollama, vLLM, LM Studio, Groq, OpenRouter, Together, ...
  api="responses"  agno OpenAIResponses -> {base_url}/responses
                   OpenAI. Reasoning models (gpt-5 / gpt-6 class) reject function tools
                   with reasoning_effort on chat/completions, and Responses keeps their
                   reasoning items between tool calls (chained with previous_response_id).

Switching from an open-source model to a paid one is only a profile change.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from agno.models.base import Model
from agno.models.openai.like import OpenAILike
from agno.models.openai.responses import OpenAIResponses
from openai import OpenAI

from bif.settings import EmbeddingSettings, ModelProfile, active_profile


def _key(api_key: str) -> str:
    # The OpenAI client refuses an empty key. Local servers ignore it.
    return api_key or "not-needed"


class BifResponses(OpenAIResponses):
    """OpenAIResponses that also treats Luna-named and o-series ids as reasoning models,
    so their reasoning items are carried across tool calls."""

    def _using_reasoning_model(self) -> bool:
        name = (self.id or "").lower()
        return super()._using_reasoning_model() or "luna" in name or name.startswith(("o1", "o3", "o4"))


def build_chat_model(profile: Optional[ModelProfile] = None) -> Model:
    profile = profile or active_profile()
    kwargs: dict[str, Any] = {
        "id": profile.model,
        "name": profile.name,
        "base_url": profile.base_url,
        "api_key": _key(profile.api_key),
        "timeout": profile.timeout,
        "max_retries": 2,
    }
    # Leave these unset unless chosen: several reasoning models reject them.
    if profile.temperature is not None:
        kwargs["temperature"] = profile.temperature
    if profile.reasoning_effort:
        kwargs["reasoning_effort"] = profile.reasoning_effort
    if profile.api == "responses":
        if profile.max_tokens:
            kwargs["max_output_tokens"] = profile.max_tokens
        if profile.reasoning_summary:
            kwargs["reasoning_summary"] = profile.reasoning_summary
        model: Model = BifResponses(**kwargs)
    else:
        if profile.max_tokens:
            kwargs["max_tokens"] = profile.max_tokens
        model = OpenAILike(**kwargs)
    return model


def client_for(base_url: str, api_key: str, timeout: float = 30.0) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=_key(api_key), timeout=timeout, max_retries=0)


def list_models(base_url: str, api_key: str) -> list[str]:
    client = client_for(base_url, api_key, timeout=15.0)
    return sorted({item.id for item in client.models.list()})


_PING_TOOL = {
    "name": "ping",
    "description": "Connectivity check. Never needs to be called.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}


def complete(
    profile: ModelProfile,
    prompt: str,
    *,
    json_mode: bool = False,
    max_tokens: Optional[int] = None,
    with_tool: bool = False,
    timeout: float = 120.0,
) -> tuple[str, str]:
    """One direct call (no agent) through the profile's API. Returns (text, model id)."""
    client = client_for(profile.base_url, profile.api_key, timeout=min(profile.timeout, timeout))
    if profile.api == "responses":
        kwargs: dict[str, Any] = {"model": profile.model, "input": [{"role": "user", "content": prompt}]}
        reasoning: dict[str, Any] = {}
        if profile.reasoning_effort:
            reasoning["effort"] = profile.reasoning_effort
        if reasoning:
            kwargs["reasoning"] = reasoning
        if profile.temperature is not None:
            kwargs["temperature"] = profile.temperature
        if max_tokens:
            kwargs["max_output_tokens"] = max_tokens
        if json_mode:
            kwargs["text"] = {"format": {"type": "json_object"}}
        if with_tool:
            kwargs["tools"] = [{"type": "function", "strict": False, **_PING_TOOL}]
        response = client.responses.create(**kwargs)
        return (response.output_text or "").strip(), response.model or profile.model

    kwargs = {"model": profile.model, "messages": [{"role": "user", "content": prompt}]}
    if profile.reasoning_effort:
        kwargs["reasoning_effort"] = profile.reasoning_effort
    if profile.temperature is not None:
        kwargs["temperature"] = profile.temperature
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if with_tool:
        kwargs["tools"] = [{"type": "function", "function": _PING_TOOL}]
    if json_mode:
        try:
            response = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
        except Exception:
            response = client.chat.completions.create(**kwargs)
    else:
        response = client.chat.completions.create(**kwargs)
    return (response.choices[0].message.content or "").strip(), response.model or profile.model


def test_chat(profile: ModelProfile) -> dict[str, Any]:
    """A real call with a function tool attached, the way the agent calls the model.

    Endpoint/model combinations that reject tools (for example reasoning_effort + tools
    on chat/completions for gpt-6 models, or an Ollama model without tool support) fail
    here instead of in the middle of a research run.
    """
    started = time.perf_counter()
    try:
        text, model_id = complete(profile, "Reply with the single word: OK", with_tool=True)
    except Exception as exc:
        message = str(exc)
        if "/v1/responses" in message and profile.api != "responses":
            message += " → Set this profile's API to “Responses”."
        return {"ok": False, "error": message}
    result: dict[str, Any] = {
        "ok": True,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "reply": text[:200],
        "model": model_id,
        "api": profile.api,
    }
    context = ollama_context_length(profile.base_url, profile.model)
    if context:
        result["context_length"] = context
        if context < MIN_CONTEXT:
            result["ok"] = False
            result["error"] = (
                f"Ollama runs this model with a {context:,}-token context. Research turns need about "
                f"{MIN_CONTEXT:,}+; Ollama silently drops the start of longer prompts (including the "
                "instructions). Set OLLAMA_CONTEXT_LENGTH=32768 for the Ollama server and restart it, "
                "or create a variant with 'PARAMETER num_ctx 32768' in a Modelfile."
            )
    return result


MIN_CONTEXT = 12_000


def ollama_context_length(base_url: str, model: str) -> Optional[int]:
    """Context window an Ollama server has loaded for `model`; None if not Ollama."""
    import httpx

    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    try:
        ps = httpx.get(f"{root}/api/ps", timeout=3.0)
        if ps.status_code != 200:
            return None
        for item in ps.json().get("models", []):
            if item.get("name") == model or item.get("model") == model or item.get("name") == f"{model}:latest":
                return int(item.get("context_length") or 0) or None
    except Exception:
        return None
    return None


def test_embedding(settings: EmbeddingSettings) -> dict[str, Any]:
    started = time.perf_counter()
    client = client_for(settings.base_url, settings.api_key)
    response = client.embeddings.create(model=settings.model, input=["participating interest"])
    return {
        "ok": True,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "dimensions": len(response.data[0].embedding),
        "model": settings.model,
    }
