"""Stability AI "Stable Image Inpaint" on Amazon Bedrock (image generation).

The hero image is the real photo with the furniture painted into the masked area, so walls, windows and
floor can't move. Used when IMAGE_PROVIDER=bedrock_stability. Auth is the usual Bedrock one (a Bedrock API
key in AWS_BEARER_TOKEN_BEDROCK, or normal AWS credentials) in AWS_REGION.

Env:
  STABILITY_MODEL_ID     default us.stability.stable-image-inpaint-v1:0 (the cross-region inference profile)
  STABILITY_CONCURRENCY  image requests in flight at once (default 2): Bedrock throttles a burst of parallel
                         requests, and a run renders several spaces at the same time. A throttled request
                         is retried with a growing pause.

Mask: 255 = repaint, 0 = keep, the same as the mask render_guide writes, so it is passed through unchanged.
The model returns one image per call, so `n` images take `n` calls (with different seeds).
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from functools import lru_cache

import cv2
import numpy as np

MAX_SIDE = 2048  # keeps a 2048 x 2048 pano as is; anything bigger is shrunk first
NEGATIVE = "people, person, text, watermark, logo, distorted walls, warped windows, blurry, cartoon, illustration, extra doors, floating furniture"


class StabilityError(RuntimeError):
    pass


_SLOTS = threading.BoundedSemaphore(max(1, int(os.environ.get("STABILITY_CONCURRENCY", "2"))))
RETRIES = 8  # tries per image when Bedrock says "too many requests" (about two minutes of waiting in all)


@lru_cache(maxsize=1)
def _client():
    import boto3

    return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def model_id() -> str:
    return os.environ.get("STABILITY_MODEL_ID", "us.stability.stable-image-inpaint-v1:0")


def _png_b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise StabilityError("Could not encode image")
    return base64.b64encode(buf.tobytes()).decode()


def _fit(img: np.ndarray, interpolation) -> np.ndarray:
    h, w = img.shape[:2]
    scale = min(1.0, MAX_SIDE / max(h, w))
    return img if scale == 1.0 else cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=interpolation)


def inpaint(image: np.ndarray, mask: np.ndarray, prompt: str, n: int = 2, seed: int = 7) -> list[np.ndarray]:
    """Repaint the masked area of `image`. `mask` is 255 where items go (as written by render_guide)."""
    img = _fit(image, cv2.INTER_AREA)
    m = cv2.resize(mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    m = np.where(m > 127, 255, 0).astype(np.uint8)
    out: list[np.ndarray] = []
    for k in range(n):
        body = {
            "prompt": prompt[:9000],
            "negative_prompt": NEGATIVE,
            "image": _png_b64(img),
            "mask": _png_b64(m),
            "output_format": "png",
            "seed": (seed + k * 101) % 4294967294,
        }
        out.append(_decode(_invoke(body)))
    return out


def _invoke(body: dict) -> bytes:
    resp = None
    for attempt in range(RETRIES):
        try:
            with _SLOTS:
                resp = _client().invoke_model(modelId=model_id(), body=json.dumps(body), accept="application/json", contentType="application/json")
            break
        except Exception as exc:  # botocore ClientError, credentials, network
            throttled = any(w in str(exc) for w in ("Throttling", "TooManyRequests", "ServiceUnavailable"))
            if throttled and attempt < RETRIES - 1:
                time.sleep(min(30.0, 3.0 * 2 ** attempt))
                continue
            raise StabilityError(f"Stability inpaint request failed: {exc}") from exc
    payload = json.loads(resp["body"].read())
    reasons = [r for r in payload.get("finish_reasons", []) if r]
    if reasons or not payload.get("images"):
        raise StabilityError(f"Stability inpaint returned no image: {', '.join(reasons) or 'empty response'}")
    return base64.b64decode(payload["images"][0])


def _decode(data: bytes) -> np.ndarray:
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise StabilityError("Stability returned an image that could not be decoded")
    return arr
