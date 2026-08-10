"""Chat OpenAI configuration — public status without exposing secrets."""

from __future__ import annotations

from app.services.ai_config import chat_ai_public_status, openai_key_status


def test_missing_key_rules_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    status = chat_ai_public_status(chat_enabled=True, chat_model="gpt-4o-mini")
    assert status["openai_key_status"] == "missing"
    assert status["ai_mode"] == "rules_fallback"
    assert status["ai_enabled"] is False


def test_configured_key_openai_tools(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-with-enough-length-here")
    status = chat_ai_public_status(chat_enabled=True, chat_model="gpt-4o-mini")
    assert status["openai_key_status"] == "configured"
    assert status["ai_mode"] == "openai_tools"
    assert status["env_var"] == "OPENAI_API_KEY"
    assert "sk-" not in str(status.values())
    assert openai_key_status() == "configured"
