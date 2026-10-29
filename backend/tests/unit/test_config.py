from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.connectors.http import api_keys
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


def test_a_database_password_with_url_special_characters_is_encoded_for_both_drivers():
    from psycopg.conninfo import conninfo_to_dict
    from sqlalchemy.engine import make_url

    from app.jobs.checkpoint import checkpoint_conninfo

    password = "p@ss:w/rd%#?&x"
    settings = Settings(
        _env_file=None, database_url="postgresql+asyncpg://policy@db:5432/policy", database_password=password
    )

    assert make_url(settings.database_url).password == password  # SQLAlchemy (api, worker)
    assert conninfo_to_dict(checkpoint_conninfo(settings.database_url))["password"] == password  # checkpoints
    assert make_url(settings.database_url).host == "db"


def test_offline_llm_mode_is_refused_in_production():
    assert Settings(_env_file=None, llm_mode="offline").llm_mode == "offline"
    with pytest.raises(ValidationError, match="LLM_MODE=offline"):
        Settings(_env_file=None, app_env="prod", llm_mode="offline")


def test_an_empty_api_key_means_no_key(monkeypatch):
    for name in ("DATAGOV_API_KEY", "OPENAI_API_KEY", "AWS_BEDROCK_API_KEY"):
        monkeypatch.setenv(name, " ")
    settings = Settings(_env_file=None)
    assert settings.datagov_api_key is None and settings.openai_api_key is None
    assert settings.aws_bedrock_api_key is None
    assert api_keys(settings) == []  # keyless: no x-api-key header, keyless rate limits
