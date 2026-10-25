from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_provider_order_parses_csv():
    s = Settings(_env_file=None, llm_provider_order="openai, bedrock")
    assert s.llm_provider_order == ["openai", "bedrock"]


def test_list_settings_parse_csv_from_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "openai,bedrock")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    s = Settings(_env_file=None)
    assert s.llm_provider_order == ["openai", "bedrock"]
    assert s.cors_origins == ["http://a.test", "http://b.test"]


def test_unknown_provider_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider_order="bedrock,gemini")


def test_fault_injection_rejected_in_prod():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="prod", enable_fault_injection=True)


def test_secrets_are_not_rendered():
    s = Settings(_env_file=None, openai_api_key="sk-test-secret")
    assert "sk-test-secret" not in repr(s)
