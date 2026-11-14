"""Runtime settings for the Brain (agent + server), read from the environment / .env."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from shared import conventions as C

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def demo_mode() -> bool:
    return os.getenv("DEMO", "0").strip().lower() in {"1", "true", "yes"}


# auto = real LLM Deep Agent when credentials exist, else the scripted funnel.
# llm = always the Deep Agent. scripted = never call an LLM for orchestration.
AGENT_MODE = os.getenv("AGENT_MODE", "auto").strip().lower()
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "bedrock").strip().lower()
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-opus-5-5")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Optional cheaper/faster model for brief parsing + vision inspection (defaults to the main one).
FAST_MODEL_ID = os.getenv("FAST_MODEL_ID", "")

FUNNEL_FILTER_LIMIT = _int("FUNNEL_FILTER_LIMIT", C.FUNNEL_FILTER_LIMIT)
FUNNEL_INSPECT_TOP = _int("FUNNEL_INSPECT_TOP", C.FUNNEL_INSPECT_TOP)
FUNNEL_FIT_TOP = _int("FUNNEL_FIT_TOP", C.FUNNEL_FIT_TOP)

TOOL_TIMEOUT_S = _float("TOOL_TIMEOUT_S", 90.0)  # per single contract-function call
HERO_TIMEOUT_S = _float("HERO_TIMEOUT_S", 180.0)  # image generation is slower
MAX_WORKERS = _int("MAX_WORKERS", 6)  # parallel inspections / fit-outs
DEMO_SPEED = _float("DEMO_SPEED", 1.0)  # >1 replays recorded runs faster
DEMO_RUN_FILE = os.getenv("DEMO_RUN_FILE", "")  # force one recording for every replay
# Business types to replay from a recording even when DEMO=0, e.g. DEMO_REPLAY=office:
# the bakery runs live on stage while "click the office brief" replays (README demo script, step 5).
DEMO_REPLAY = {t.strip() for t in os.getenv("DEMO_REPLAY", "").split(",") if t.strip()}
