"""Gemini image generation (the default hero-image provider; Bedrock/Nova is optional).

Gemini has no mask-inpainting mode, so it edits from instructions instead:
* edit():      image 1 = the real empty room, image 2 = the same photo with the plan's colored
               boxes. Gemini places furniture in the boxes and keeps the room as it is.
               The scorer then checks that the walls really stayed (structure outside the boxes).
* condition(): only the plan overlay; Gemini redraws the whole scene from it (more freedom,
               more risk of moved walls).

Env: GOOGLE_API_KEY (or GEMINI_API_KEY), GEMINI_IMAGE_MODEL (default gemini-3.1-flash-image).
"""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache

import cv2
import numpy as np

log = logging.getLogger("hestia.gemini_image")

MAX_SIDE = 1024
DEFAULT_MODEL = "gemini-3.1-flash-image"

EDIT_INSTRUCTIONS = (
    "Image 1 is a real photo of an empty commercial room. Image 2 is the same photo with everything darkened "
    "except the areas where furniture goes. Edit image 1: add realistic furniture inside the bright areas of "
    "image 2, at real-world scale, standing on the floor, and nothing elsewhere. The floor keeps its real "
    "material and color. Add no people and no text. Keep the walls, windows, doors, floor, ceiling, lighting "
    "and camera angle exactly as in image 1. Return one photorealistic image with the same framing as image 1."
)
CONDITION_INSTRUCTIONS = (
    "This photo shows a room with colored boxes marking where furniture goes. Produce a photorealistic "
    "photo of the same room from the same camera angle with real furniture inside each box and no boxes "
    "or text, and no people. Keep the room's walls, windows, doors, floor and ceiling where they are."
)


class GeminiImageError(RuntimeError):
    pass


def model_id() -> str:
    return os.environ.get("GEMINI_IMAGE_MODEL", DEFAULT_MODEL)


@lru_cache(maxsize=1)
def _client():
    from google import genai

    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise GeminiImageError("GOOGLE_API_KEY is not set")
    return genai.Client(api_key=key)


def _fit(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    s = min(1.0, MAX_SIDE / max(h, w))
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img


def _part(img: np.ndarray):
    from google.genai import types

    ok, buf = cv2.imencode(".png", _fit(img))
    if not ok:
        raise GeminiImageError("Could not encode image")
    return types.Part.from_bytes(data=buf.tobytes(), mime_type="image/png")


def _aspect(img: np.ndarray) -> str:
    """Closest aspect ratio Gemini accepts, so the output lines up with the photo."""
    h, w = img.shape[:2]
    options = {"1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "16:9": 16 / 9, "9:16": 9 / 16, "3:2": 1.5, "2:3": 2 / 3}
    return min(options, key=lambda k: abs(options[k] - w / h))


def _one(contents: list, aspect: str, seed: int) -> np.ndarray:
    from google.genai import types

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"], seed=seed, image_config=types.ImageConfig(aspect_ratio=aspect)
    )
    last: Exception | None = None
    for attempt in range(3):  # rate limits on the free tier: wait and retry
        try:
            resp = _client().models.generate_content(model=model_id(), contents=contents, config=config)
            for cand in resp.candidates or []:
                for part in (cand.content.parts if cand.content else None) or []:
                    if part.inline_data and part.inline_data.data:
                        img = cv2.imdecode(np.frombuffer(part.inline_data.data, np.uint8), cv2.IMREAD_COLOR)
                        if img is not None:
                            return img
            reason = resp.candidates[0].finish_reason if resp.candidates else getattr(resp, "prompt_feedback", None)
            raise GeminiImageError(f"Gemini returned no image (finish reason: {reason})")
        except GeminiImageError:
            raise
        except Exception as exc:  # noqa: BLE001 - network, quota, bad request
            last = exc
            if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc) or "503" in str(exc):
                time.sleep(8 * (attempt + 1))
                continue
            break
    raise GeminiImageError(f"Gemini image request failed: {last}") from last


def placement_map(original: np.ndarray, guide: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """The photo with everything outside the furniture areas darkened: shows where furniture goes
    without any foreign colors Gemini could copy into the room (an earlier colored map got painted
    onto the floor). `guide` is unused; kept so callers don't change."""
    h, w = original.shape[:2]
    m = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST) > 127
    out = (original.astype(np.float32) * 0.18).astype(np.uint8)
    out[m] = original[m]
    return out


def composite(original: np.ndarray, generated: np.ndarray, mask: np.ndarray, grow_px: int = 25) -> np.ndarray:
    """Generated pixels inside the (grown, feathered) furniture area, the real photo outside it.
    Walls and windows can't move; furniture slightly outside its box (chairs) still shows."""
    h, w = original.shape[:2]
    gen = cv2.resize(generated, (w, h))
    m = (cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST) > 127).astype(np.uint8) * 255
    grow = max(3, int(grow_px * max(h, w) / 1024))
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    alpha = cv2.GaussianBlur(m, (0, 0), grow / 2).astype(np.float32)[..., None] / 255.0
    return (gen.astype(np.float32) * alpha + original.astype(np.float32) * (1 - alpha)).astype(np.uint8)


def edit(original: np.ndarray, guide: np.ndarray, mask: np.ndarray, prompt: str, n: int = 2, seed: int = 7,
         keep_room: bool = True) -> list[np.ndarray]:
    """Furniture placed into the real photo where the mask says. keep_room=True pastes the original
    photo back outside the furniture areas (set GEMINI_COMPOSITE=0 to see Gemini's raw output)."""
    contents = [EDIT_INSTRUCTIONS + " Style: " + prompt, _part(original), _part(placement_map(original, guide, mask))]
    keep_room = keep_room and os.environ.get("GEMINI_COMPOSITE", "1") not in ("0", "false", "no")
    out = []
    for k in range(n):
        img = cv2.resize(_one(contents, _aspect(original), seed + k), (original.shape[1], original.shape[0]))
        out.append(composite(original, img, mask) if keep_room else img)
    return out


def condition(guide: np.ndarray, prompt: str, n: int = 2, seed: int = 7) -> list[np.ndarray]:
    """Whole scene redrawn from the guide image."""
    contents = [CONDITION_INSTRUCTIONS + " Style: " + prompt, _part(guide)]
    return [_one(contents, _aspect(guide), seed + k) for k in range(n)]
