"""score_image: did the building stay the same, does the image follow the layout, does it look real?

structure_preserved (0-1)  Outside the furniture mask, compare the real photo and the generated
                           image: edge agreement (walls, window frames, floor lines), correlation
                           of the image content, and pixel similarity. 1 = untouched.
plan_adherence (0-1)       Inside the mask, something new should appear: how much more the masked
                           area changed than the rest. Averaged with the LLM judge when enabled.
realism_1to5               LLM judge (SCORER_LLM=1). Without it: 3.0 and a note saying so.

passed = structure >= 0.55 and plan >= 0.4 and realism >= 3.
"""

from __future__ import annotations

import cv2
import numpy as np

from agent.staging import judge as llm_judge
from agent.staging.files import mask_url_for, to_path
from shared.schemas import ImageScore, Layout

WORK_WIDTH = 512
PASS_STRUCTURE = 0.55
PASS_PLAN = 0.4
PASS_REALISM = 3.0


def score_image(original_path: str, generated_path: str, layout: Layout, guide_path: str | None = None) -> ImageScore:
    original = _read(original_path)
    generated = _read(generated_path)
    guide = _read(guide_path) if guide_path else None
    mask = _read_mask(guide_path, original.shape) if guide_path else None
    return score_arrays(original, generated, mask, guide, layout)


def score_arrays(original: np.ndarray, generated: np.ndarray, mask: np.ndarray | None, guide: np.ndarray | None, layout: Layout | None = None) -> ImageScore:
    o, g, m = _common(original, generated, mask)
    notes: list[str] = []

    outside = m == 0 if m is not None else np.ones(o.shape[:2], bool)
    structure = 0.4 * _edge_agreement(o, g, outside) + 0.4 * _correlation(o, g, outside) + 0.2 * _pixel_similarity(o, g, outside)

    if m is not None and m.any():
        plan = _change_contrast(o, g, m > 0)
    else:
        plan = 0.5
        notes.append("No furniture mask: plan adherence not measured.")

    realism = PASS_REALISM
    verdict = llm_judge.judge(original, guide, generated)
    if verdict is not None:
        realism = verdict.realism_1to5
        plan = 0.5 * plan + 0.5 * verdict.plan_adherence
        if not verdict.structure_preserved:
            structure = min(structure, 0.5)
        if verdict.notes and verdict.notes.lower() != "ok":
            notes.append(verdict.notes)
    else:
        notes.append("Realism not scored (LLM judge off).")

    structure, plan = float(np.clip(structure, 0, 1)), float(np.clip(plan, 0, 1))
    passed = structure >= PASS_STRUCTURE and plan >= PASS_PLAN and realism >= PASS_REALISM
    return ImageScore(
        structure_preserved=round(structure, 3),
        plan_adherence=round(plan, 3),
        realism_1to5=round(float(realism), 2),
        passed=passed,
        notes=notes,
    )


# --------------------------------------------------------------------------- #


def _read(url: str) -> np.ndarray:
    img = cv2.imread(str(to_path(url)), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(url)
    return img


def _read_mask(guide_url: str, shape) -> np.ndarray | None:
    path = to_path(mask_url_for(guide_url))
    m = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return m


def _common(o: np.ndarray, g: np.ndarray, m: np.ndarray | None):
    h = int(o.shape[0] * WORK_WIDTH / o.shape[1])
    o2 = cv2.resize(o, (WORK_WIDTH, h), interpolation=cv2.INTER_AREA)
    g2 = cv2.resize(g, (WORK_WIDTH, h), interpolation=cv2.INTER_AREA)
    m2 = None
    if m is not None:
        m2 = cv2.resize(m, (WORK_WIDTH, h), interpolation=cv2.INTER_NEAREST)
        m2 = cv2.dilate((m2 > 127).astype(np.uint8) * 255, np.ones((15, 15), np.uint8))
    return o2, g2, m2


def _edges(img: np.ndarray) -> np.ndarray:
    gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    return cv2.Canny(gray, 50, 150) > 0


def _edge_agreement(o: np.ndarray, g: np.ndarray, region: np.ndarray) -> float:
    """F1 of edges (2 px tolerance) inside `region`."""
    eo, eg = _edges(o) & region, _edges(g) & region
    if eo.sum() < 50:
        return 1.0 if eg.sum() < 50 else 0.5
    k = np.ones((5, 5), np.uint8)
    eo_d = cv2.dilate(eo.astype(np.uint8), k) > 0
    eg_d = cv2.dilate(eg.astype(np.uint8), k) > 0
    recall = (eo & eg_d).sum() / max(1, eo.sum())
    precision = (eg & eo_d).sum() / max(1, eg.sum())
    return float(2 * precision * recall / max(1e-9, precision + recall))


def _correlation(o: np.ndarray, g: np.ndarray, region: np.ndarray) -> float:
    """Zero-mean normalized cross-correlation of the grayscale images inside `region` (clipped to 0-1)."""
    if region.sum() < 100:
        return 1.0
    a = cv2.GaussianBlur(cv2.cvtColor(o, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)[region]
    b = cv2.GaussianBlur(cv2.cvtColor(g, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)[region]
    a, b = a - a.mean(), b - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if denom < 1e-6:
        return 1.0 if np.abs(a - b).mean() < 2 else 0.0
    return float(np.clip((a * b).sum() / denom, 0, 1))


def _pixel_similarity(o: np.ndarray, g: np.ndarray, region: np.ndarray) -> float:
    if not region.any():
        return 1.0
    a = cv2.GaussianBlur(o, (9, 9), 0).astype(np.float32)
    b = cv2.GaussianBlur(g, (9, 9), 0).astype(np.float32)
    diff = np.abs(a - b).mean(axis=2)[region] / 255.0
    return float(1.0 - min(1.0, diff.mean() * 4))


def _change_contrast(o: np.ndarray, g: np.ndarray, inside: np.ndarray) -> float:
    """How much more the masked area changed than the rest (0 = no new furniture, 1 = clearly new)."""
    diff = np.abs(cv2.GaussianBlur(o, (5, 5), 0).astype(np.float32) - cv2.GaussianBlur(g, (5, 5), 0).astype(np.float32)).mean(axis=2) / 255.0
    d_in = diff[inside].mean()
    d_out = diff[~inside].mean() if (~inside).any() else 0.0
    return float(np.clip((d_in - d_out) / 0.12, 0, 1))
