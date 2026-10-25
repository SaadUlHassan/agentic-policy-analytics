"""Application settings, loaded from environment variables (and `.env` in local dev)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Provider = Literal["bedrock", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://policy:policy@localhost:5432/policy"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # LLM providers (plan §4.7). Defaults are the models that passed the Day-1 probe
    # (eval/results/probe/). Nova Pro via the APAC profile keeps inference in-region; switch
    # BEDROCK_MODEL_ID to an Anthropic model once its use-case access is granted.
    llm_provider_order: Annotated[list[Provider], NoDecode] = ["bedrock", "openai"]
    aws_bedrock_region: str = "ap-southeast-1"
    aws_bedrock_api_key: SecretStr | None = None
    bedrock_model_id: str = "apac.amazon.nova-pro-v1:0"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.5"

    # Data (plan §4.5-4.6)
    data_mode: Literal["live", "snapshot"] = "live"
    datagov_api_key: SecretStr | None = None

    # Dev/demo only; forced off in prod (plan §2).
    enable_fault_injection: bool = False

    health_check_timeout_s: float = Field(default=2.0, gt=0)

    @field_validator("llm_provider_order", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("enable_fault_injection")
    @classmethod
    def _no_faults_in_prod(cls, v: bool, info: ValidationInfo) -> bool:
        if v and info.data.get("app_env") == "prod":
            raise ValueError("ENABLE_FAULT_INJECTION must be false when APP_ENV=prod")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
