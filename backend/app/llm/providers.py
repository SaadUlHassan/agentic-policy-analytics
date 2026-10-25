"""Chat model construction per provider. SDK retries are disabled: the router owns retries."""

from __future__ import annotations

import os

from botocore.config import Config
from langchain_aws import ChatBedrockConverse
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import Provider, Settings

MAX_OUTPUT_TOKENS = 2000


def build_bedrock(settings: Settings, model_id: str | None = None, timeout_s: float = 60) -> BaseChatModel:
    if settings.aws_bedrock_api_key:
        # botocore reads Bedrock API keys from this variable.
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = settings.aws_bedrock_api_key.get_secret_value()
    # total_max_attempts=1 => exactly one HTTP request (max_attempts=1 would still allow a retry).
    config = Config(
        retries={"total_max_attempts": 1, "mode": "standard"}, read_timeout=timeout_s, connect_timeout=10
    )
    return ChatBedrockConverse(
        model_id=model_id or settings.bedrock_model_id,
        region_name=settings.aws_bedrock_region,
        config=config,
        temperature=0,
        max_tokens=MAX_OUTPUT_TOKENS,
    )


def build_openai(settings: Settings, model_id: str | None = None, timeout_s: float = 60) -> BaseChatModel:
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    return ChatOpenAI(
        model=model_id or settings.openai_model,
        api_key=key,
        max_retries=0,
        timeout=timeout_s,
        max_tokens=MAX_OUTPUT_TOKENS,
    )


def build(provider: Provider, settings: Settings) -> BaseChatModel:
    return {"bedrock": build_bedrock, "openai": build_openai}[provider](settings)


def model_id(provider: Provider, settings: Settings) -> str:
    return settings.bedrock_model_id if provider == "bedrock" else settings.openai_model
