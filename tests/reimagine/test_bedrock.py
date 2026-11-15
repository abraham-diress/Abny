"""Bedrock as the image and judge provider: no network, the Bedrock client is faked."""

from __future__ import annotations

import base64
import io
import json

import cv2
import numpy as np
import pytest

from agent.staging import generate, stability


def _png(color: int) -> bytes:
    return cv2.imencode(".png", np.full((64, 64, 3), color, np.uint8))[1].tobytes()


class FakeRuntime:
    def __init__(self, finish_reasons=None, images=None):
        self.calls: list[dict] = []
        self.finish_reasons, self.images = finish_reasons or [None], images
        self.model_ids: list[str] = []

    def invoke_model(self, modelId, body, accept, contentType):
        self.model_ids.append(modelId)
        self.calls.append(json.loads(body))
        images = self.images if self.images is not None else [base64.b64encode(_png(120)).decode()]
        return {"body": io.BytesIO(json.dumps({"images": images, "finish_reasons": self.finish_reasons, "seeds": [1]}).encode())}


@pytest.fixture
def fake(monkeypatch):
    f = FakeRuntime()
    monkeypatch.setattr(stability, "_client", lambda: f)
    return f


def test_inpaint_sends_photo_mask_and_prompt_and_makes_n_images(fake):
    photo = np.full((100, 200, 3), 200, np.uint8)
    mask = np.zeros((100, 200), np.uint8)
    mask[20:60, 50:120] = 255
    out = stability.inpaint(photo, mask, "an office with desks", n=2, seed=7)
    assert len(out) == 2 and all(o.shape == (64, 64, 3) for o in out)
    assert len(fake.calls) == 2 and fake.calls[0]["seed"] != fake.calls[1]["seed"]  # one image per call, different seeds
    assert fake.model_ids[0] == "us.stability.stable-image-inpaint-v1:0"
    body = fake.calls[0]
    assert body["prompt"] == "an office with desks" and "people" in body["negative_prompt"]
    sent_mask = cv2.imdecode(np.frombuffer(base64.b64decode(body["mask"]), np.uint8), cv2.IMREAD_GRAYSCALE)
    assert sent_mask[40, 80] == 255 and sent_mask[5, 5] == 0  # white = repaint, the same convention as render_guide's mask
    assert set(np.unique(sent_mask)) <= {0, 255}


def test_a_big_photo_is_shrunk_before_sending(fake):
    stability.inpaint(np.zeros((3000, 3000, 3), np.uint8), np.zeros((3000, 3000), np.uint8), "x", n=1)
    sent = cv2.imdecode(np.frombuffer(base64.b64decode(fake.calls[0]["image"]), np.uint8), cv2.IMREAD_COLOR)
    assert max(sent.shape[:2]) == stability.MAX_SIDE


@pytest.mark.parametrize("reasons,images", [(["CONTENT_FILTERED"], []), ([None], [])])
def test_a_refused_or_empty_answer_is_an_error(monkeypatch, reasons, images):
    monkeypatch.setattr(stability, "_client", lambda: FakeRuntime(finish_reasons=reasons, images=images))
    with pytest.raises(stability.StabilityError):
        stability.inpaint(np.zeros((64, 64, 3), np.uint8), np.zeros((64, 64), np.uint8), "x", n=1)


def test_provider_switch_routes_to_stability(monkeypatch, fake):
    monkeypatch.setenv("IMAGE_PROVIDER", "bedrock_stability")
    imgs = generate.generate_images("inpaint", np.zeros((64, 64, 3), np.uint8), np.zeros((64, 64, 3), np.uint8), np.zeros((64, 64), np.uint8), "p", n=1)
    assert len(imgs) == 1 and fake.calls
    assert generate._model_name() == "us.stability.stable-image-inpaint-v1:0"


def test_judge_reads_the_json_from_a_bedrock_converse_answer(monkeypatch):
    import boto3

    from agent.staging import judge

    answer = 'Here is my score:\n{"realism_1to5": 4, "plan_adherence": 0.8, "structure_preserved": true, "notes": "ok"}'

    class FakeBedrock:
        def converse(self, **kw):
            assert kw["messages"][0]["content"][0]["image"]["format"] == "jpeg" and len(kw["messages"][0]["content"]) == 4
            return {"output": {"message": {"content": [{"text": answer}]}}}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: FakeBedrock())
    monkeypatch.setenv("SCORER_LLM", "1")
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    img = np.zeros((32, 32, 3), np.uint8)
    r = judge.judge(img, None, img)
    assert r is not None and r.realism_1to5 == 4 and r.plan_adherence == 0.8 and r.structure_preserved


def test_a_throttled_request_is_retried_then_succeeds(monkeypatch):
    class Throttled(FakeRuntime):
        def invoke_model(self, **kw):
            if len(self.calls) < 2:
                self.calls.append({})
                raise RuntimeError("An error occurred (ThrottlingException) when calling the InvokeModel operation: Too many requests")
            return super().invoke_model(**kw)

    f = Throttled()
    monkeypatch.setattr(stability, "_client", lambda: f)
    monkeypatch.setattr(stability.time, "sleep", lambda s: None)
    out = stability.inpaint(np.zeros((64, 64, 3), np.uint8), np.zeros((64, 64), np.uint8), "x", n=1)
    assert len(out) == 1 and len(f.calls) == 3  # two throttled tries, then the image


def test_a_request_that_keeps_getting_throttled_gives_up_with_a_clear_error(monkeypatch):
    class Always:
        def invoke_model(self, **kw):
            raise RuntimeError("ThrottlingException: Too many requests")

    monkeypatch.setattr(stability, "_client", lambda: Always())
    monkeypatch.setattr(stability.time, "sleep", lambda s: None)
    with pytest.raises(stability.StabilityError, match="Throttling"):
        stability.inpaint(np.zeros((64, 64, 3), np.uint8), np.zeros((64, 64), np.uint8), "x", n=1)
