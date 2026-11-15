"""Vision-model image judge: realism and "does it follow the plan".

Off by default; set SCORER_LLM=1 to enable. Uses LLM_PROVIDER (bedrock, the default | anthropic):
  anthropic: Anthropic API, model ANTHROPIC_MODEL (default claude-opus-5-5)
  bedrock:   Bedrock Converse API (boto3), model JUDGE_BEDROCK_MODEL or BEDROCK_MODEL_ID; works with a
             Bedrock API key (AWS_BEARER_TOKEN_BEDROCK) and with any Claude model the account can use
Returns None if disabled, unavailable, or the model declines; callers fall back to heuristics.
"""

from __future__ import annotations

import base64
import logging
import os
from functools import lru_cache

import cv2
import numpy as np
from pydantic import BaseModel, Field

log = logging.getLogger("hestia.judge")

RUBRIC = """You are checking an AI-generated interior image for a small-business owner.
Image 1 is the real, empty room. Image 2 is the plan: colored boxes mark where furniture goes
(amber = service counter/display case, blue = kitchen equipment, green = tables and chairs,
purple = other front-of-house items). Image 3 is the generated image.

Score image 3:
- realism_1to5: 5 = indistinguishable from a real photo; 3 = clearly rendered but plausible; 1 = broken.
- plan_adherence: 0-1, how well furniture in image 3 matches the boxes in image 2 (type and position).
- structure_preserved: true if walls, windows, doors, floor and ceiling match image 1.
- notes: one short sentence on the biggest problem, or "ok"."""


class JudgeResult(BaseModel):
    realism_1to5: float = Field(ge=1, le=5)
    plan_adherence: float = Field(ge=0, le=1)
    structure_preserved: bool
    notes: str


def enabled() -> bool:
    return os.environ.get("SCORER_LLM", "0").lower() in ("1", "true", "yes")


@lru_cache(maxsize=1)
def _client_and_model():
    from anthropic import Anthropic

    return Anthropic(), os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")


def _jpeg(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", _small(img), [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes()


def _judge_bedrock(images: list[np.ndarray]) -> JudgeResult | None:
    """Claude on Bedrock through the Converse API: one call shape for every Claude model there."""
    import json
    import re

    import boto3

    from botocore.config import Config

    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                          config=Config(retries={"max_attempts": 8, "mode": "adaptive"}))
    model = os.environ.get("JUDGE_BEDROCK_MODEL") or os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-6-v1")
    content = [{"image": {"format": "jpeg", "source": {"bytes": _jpeg(img)}}} for img in images]
    content.append({"text": RUBRIC + "\n\nReply with only a JSON object with the keys realism_1to5, "
                    "plan_adherence, structure_preserved and notes."})
    resp = client.converse(modelId=model, messages=[{"role": "user", "content": content}],
                           inferenceConfig={"maxTokens": 1000})
    if resp.get("stopReason") == "guardrail_intervened":
        return None
    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    found = re.search(r"\{.*\}", text, re.S)
    return JudgeResult.model_validate(json.loads(found.group(0))) if found else None


def _small(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    s = min(1.0, 1024 / max(h, w))
    return cv2.resize(img, (int(w * s), int(h * s))) if s < 1 else img


def _image_block(img: np.ndarray) -> dict:
    ok, buf = cv2.imencode(".jpg", _small(img), [cv2.IMWRITE_JPEG_QUALITY, 88])
    data = base64.standard_b64encode(buf.tobytes()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def judge(original: np.ndarray, guide: np.ndarray | None, generated: np.ndarray) -> JudgeResult | None:
    if not enabled():
        return None
    if os.environ.get("LLM_PROVIDER", "bedrock").lower() != "anthropic":
        try:
            return _judge_bedrock([original, guide if guide is not None else original, generated])
        except Exception as exc:  # noqa: BLE001 - judging is best-effort
            log.warning("Judge unavailable: %s", exc)
            return None
    try:
        client, model = _client_and_model()
        content = [_image_block(original), _image_block(guide if guide is not None else original), _image_block(generated)]
        content.append({"type": "text", "text": RUBRIC})
        response = client.messages.parse(
            model=model,
            max_tokens=4000,
            messages=[{"role": "user", "content": content}],
            output_format=JudgeResult,
        )
        if response.stop_reason == "refusal":
            log.warning("Judge declined to score the image")
            return None
        return response.parsed_output
    except Exception as exc:  # noqa: BLE001 - judging is best-effort
        log.warning("Judge unavailable: %s", exc)
        return None
