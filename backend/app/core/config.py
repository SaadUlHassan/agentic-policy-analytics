"""Application settings, loaded from environment variables (and `.env` in local dev)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url

Provider = Literal["bedrock", "openai"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://policy:policy@localhost:5432/policy"
    # Given on its own, the password may contain any character (@, /, :, %): it is encoded into
    # database_url here rather than pasted into a URL by hand.
    database_password: SecretStr | None = None
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
    # USD per million (input, output) tokens by model id, from the providers' published rates:
    # LLM_PRICES='{"<model id>": [<input>, <output>]}'. Empty by default: cost is shown only when every
    # model used has a configured price.
    llm_prices: dict[str, tuple[float, float]] = {}
    # "offline" answers every LLM step with a deterministic stand-in (app/llm/offline.py): end-to-end
    # tests and load runs, no provider calls. Refused in production.
    llm_mode: Literal["live", "offline"] = "live"

    # Data (plan §4.5-4.6). DATA_DIR holds the manifest, taxonomy and snapshots.
    data_mode: Literal["live", "snapshot"] = "live"
    data_dir: Path = Path(__file__).resolve().parents[3] / "data"
    datagov_api_key: SecretStr | None = None
    # Rate-limit tier the key was issued for (guide.data.gov.sg "API Rate Limits").
    datagov_key_tier: Literal["dev", "prod"] = "dev"

    # Dev/demo only; forced off in prod (plan §2).
    enable_fault_injection: bool = False

    health_check_timeout_s: float = Field(default=2.0, gt=0)
    # Active-time budget for one analysis execution (plan §3.5).
    analysis_deadline_s: float = Field(default=240.0, gt=0)

    @field_validator("llm_provider_order", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @model_validator(mode="after")
    def _password_into_url(self) -> Settings:
        if self.database_password is not None:
            url = make_url(self.database_url).set(password=self.database_password.get_secret_value())
            self.database_url = url.render_as_string(hide_password=False)
        return self

    @field_validator("enable_fault_injection")
    @classmethod
    def _no_faults_in_prod(cls, v: bool, info: ValidationInfo) -> bool:
        if v and info.data.get("app_env") == "prod":
            raise ValueError("ENABLE_FAULT_INJECTION must be false when APP_ENV=prod")
        return v

    @field_validator("llm_mode")
    @classmethod
    def _no_offline_llm_in_prod(cls, v: str, info: ValidationInfo) -> str:
        if v == "offline" and info.data.get("app_env") == "prod":
            raise ValueError("LLM_MODE=offline is for tests and load runs; it is refused when APP_ENV=prod")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
