from bif.models import BifResponses, build_chat_model
from bif.settings import ModelProfile, _migrate

from agno.models.openai.like import OpenAILike


def test_profile_api_picks_agno_class():
    chat = build_chat_model(ModelProfile(base_url="http://localhost:11434/v1", model="qwen3:8b"))
    resp = build_chat_model(ModelProfile(base_url="https://api.openai.com/v1", model="gpt-6-luna", api="responses", reasoning_effort="high"))
    assert isinstance(chat, OpenAILike) and isinstance(resp, BifResponses)
    assert resp._using_reasoning_model()
    assert resp.get_request_params(messages=[])["reasoning"] == {"effort": "high"}


def test_old_profiles_migrate_to_responses_for_openai():
    data = {"profiles": [
        {"name": "o", "provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-6-luna"},
        {"name": "l", "provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "qwen3:8b"},
        {"name": "k", "provider": "custom", "base_url": "https://x/v1", "model": "m", "api": "chat"},
    ]}
    assert [p["api"] for p in _migrate(data)["profiles"]] == ["responses", "chat", "chat"]
