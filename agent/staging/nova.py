"""Amazon Nova Canvas on Bedrock (image generation).

Two ways to make the hero image:
* inpaint():     repaint ONLY the masked area of the real photo -> walls/windows can't move.
* conditioned(): new image guided by the edges/segments of the guide image.

Env (see .env.example): AWS_REGION, IMAGE_MODEL_ID (default amazon.nova-canvas-v1:0),
NOVA_MASK_BLACK_IS_EDIT (default 1: black mask pixels are repainted). VERIFY the mask polarity
and request fields with the gate G3 script (eval/g3_image_test.py) before relying on them.
"""

from __future__ import annotations

import base64
import json
import os
from functools import lru_cache

import cv2
import numpy as np

MAX_SIDE = 1024
NEGATIVE = "people, person, text, watermark, logo, distorted walls, warped windows, blurry, cartoon, illustration, extra doors"


class NovaError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _client():
    import boto3

    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _model_id() -> str:
    return os.environ.get("IMAGE_MODEL_ID", "amazon.nova-canvas-v1:0")


def _invoke(body: dict) -> list[bytes]:
    try:
        resp = _client().invoke_model(
            modelId=_model_id(), body=json.dumps(body), accept="application/json", contentType="application/json"
        )
    except Exception as exc:  # botocore ClientError, credentials, network
        raise NovaError(f"Nova Canvas request failed: {exc}") from exc
    payload = json.loads(resp["body"].read())
    if payload.get("error"):
        raise NovaError(f"Nova Canvas error: {payload['error']}")
    return [base64.b64decode(img) for img in payload.get("images", [])]


def fit_size(img: np.ndarray) -> np.ndarray:
    """Resize so the long side <= MAX_SIDE and both sides are multiples of 64 (>= 320)."""
    h, w = img.shape[:2]
    scale = min(1.0, MAX_SIDE / max(h, w))
    nw = max(320, int(round(w * scale / 64)) * 64)
    nh = max(320, int(round(h * scale / 64)) * 64)
    return cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)


def _png_b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise NovaError("Could not encode image")
    return base64.b64encode(buf.tobytes()).decode()


def inpaint(image: np.ndarray, mask: np.ndarray, prompt: str, n: int = 2, seed: int = 7, cfg_scale: float = 6.5) -> list[np.ndarray]:
    """Repaint the masked area. `mask` is 255 where items go (as written by render_guide)."""
    img = fit_size(image)
    m = cv2.resize(mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    black_is_edit = os.environ.get("NOVA_MASK_BLACK_IS_EDIT", "1") not in ("0", "false", "no")
    nova_mask = np.where(m > 127, 0, 255) if black_is_edit else np.where(m > 127, 255, 0)
    nova_mask = cv2.cvtColor(nova_mask.astype(np.uint8), cv2.COLOR_GRAY2BGR)
    body = {
        "taskType": "INPAINTING",
        "inPaintingParams": {
            "image": _png_b64(img),
            "maskImage": _png_b64(nova_mask),
            "text": prompt[:1000],
            "negativeText": NEGATIVE,
        },
        "imageGenerationConfig": {"numberOfImages": n, "quality": "standard", "cfgScale": cfg_scale, "seed": seed},
    }
    return [_decode(b) for b in _invoke(body)]


def conditioned(guide: np.ndarray, prompt: str, n: int = 2, seed: int = 7, mode: str = "CANNY_EDGE", strength: float = 0.7, cfg_scale: float = 6.5) -> list[np.ndarray]:
    """Generate from text, constrained by the guide's structure (CANNY_EDGE or SEGMENTATION)."""
    g = fit_size(guide)
    body = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {
            "text": prompt[:1000],
            "negativeText": NEGATIVE,
            "conditionImage": _png_b64(g),
            "controlMode": mode,
            "controlStrength": strength,
        },
        "imageGenerationConfig": {
            "numberOfImages": n,
            "quality": "standard",
            "cfgScale": cfg_scale,
            "seed": seed,
            "width": g.shape[1],
            "height": g.shape[0],
        },
    }
    return [_decode(b) for b in _invoke(body)]


def _decode(data: bytes) -> np.ndarray:
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise NovaError("Nova Canvas returned an image that could not be decoded")
    return arr
