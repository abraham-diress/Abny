"""One place to build chat models, so switching Bedrock / Anthropic / Gemini is one env var (LLM_PROVIDER)."""

from __future__ import annotations

import os
from functools import lru_cache

from agent import config


def llm_available() -> bool:
    """True when credentials for the configured provider look present (no network call)."""
    if config.LLM_PROVIDER == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if config.LLM_PROVIDER == "gemini":
        return bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    # A Bedrock API key (AWS_BEARER_TOKEN_BEDROCK) is picked up by boto3 directly.
    if os.getenv("AWS_BEARER_TOKEN_BEDROCK") or os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"):
        return True
    try:  # an SSO/instance profile also counts
        import boto3

        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


@lru_cache(maxsize=4)
def get_chat_model(fast: bool = False, max_tokens: int = 4096):
    """Chat model for the configured provider. `fast=True` uses FAST_MODEL_ID when set."""
    if config.LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic

        model = (fast and config.FAST_MODEL_ID) or config.ANTHROPIC_MODEL
        return ChatAnthropic(model=model, max_tokens=max_tokens, timeout=120, max_retries=2)

    if config.LLM_PROVIDER == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = (fast and config.FAST_MODEL_ID) or config.GEMINI_MODEL
        key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        # Quick calls (brief parsing, inspection) don't need long thinking; the orchestrator gets the default.
        extra = {"reasoning_effort": "low"} if fast else {}
        return ChatGoogleGenerativeAI(model=model, google_api_key=key, max_output_tokens=max_tokens,
                                      timeout=120, max_retries=6, rate_limiter=_gemini_limiter(), **extra)

    from langchain_aws import ChatBedrockConverse

    model = (fast and config.FAST_MODEL_ID) or config.BEDROCK_MODEL_ID
    return ChatBedrockConverse(model=model, region_name=config.AWS_REGION, max_tokens=max_tokens)


@lru_cache(maxsize=1)
def _gemini_limiter():
    """One shared pacer for every Gemini call: the free tier allows only a few requests per minute,
    and a Deep Agent run makes dozens. Waiting beats a 429 crash. Raise GEMINI_RPM on a paid key."""
    from langchain_core.rate_limiters import InMemoryRateLimiter

    rpm = float(os.getenv("GEMINI_RPM", "8"))
    return InMemoryRateLimiter(requests_per_second=rpm / 60, check_every_n_seconds=0.2, max_bucket_size=2)
