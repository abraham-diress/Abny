"""render_hero: the photoreal "this is your business" image for one space.

Steps: pick the panorama face that shows the most of the layout (furniture-free first) ->
render_guide (boxes + mask) -> generate N images -> score each -> keep the best -> one retry
with new seeds if none pass.

HERO_MODE (env):
  inpaint   (default) Nova Canvas repaints only the furniture area of the real photo
  condition Nova Canvas generates from the guide's edges
  preview   no AI: the guide image itself (frontend work without AWS, or demo fallback)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import cv2

from agent.layout.templates import TEMPLATES
from agent.staging import nova
from agent.staging.files import ensure_dirs, mask_url_for, to_path, to_url
from agent.staging.guide import count_visible, render_guide
from agent.staging.score import score_image
from shared.conventions import HEROES_DIR, RUNS_DIR
from shared.schemas import HeroImage, ImageScore, Layout, PanoRef

log = logging.getLogger("hestia.hero")
VARIANTS = 2
MAX_ROUNDS = 2


def render_hero(space_id: str, layout: Layout, style: str | None = None) -> HeroImage:
    ensure_dirs()
    pano = pick_panorama(_panoramas(space_id), layout)
    guide_url = render_guide(layout, pano)
    prompt = build_prompt(layout, style)
    mode = os.environ.get("HERO_MODE", "inpaint").lower()

    if mode == "preview":
        return HeroImage(
            hero_id=f"{layout.layout_id}-preview",
            space_id=space_id,
            layout_id=layout.layout_id,
            path=guide_url,
            source_pano_id=pano.pano_id,
            guide_path=guide_url,
            model="preview-guide",
            prompt=prompt,
            attempt=0,
            score=None,
        )

    original = cv2.imread(str(to_path(pano.path)), cv2.IMREAD_COLOR)
    guide = cv2.imread(str(to_path(guide_url)), cv2.IMREAD_COLOR)
    mask = cv2.imread(str(to_path(mask_url_for(guide_url))), cv2.IMREAD_GRAYSCALE)
    best: tuple[ImageScore, str, int] | None = None
    attempt = 0
    for round_ in range(MAX_ROUNDS):
        seed = 7 + round_ * 101
        if mode == "condition":
            images = nova.conditioned(guide, prompt, n=VARIANTS, seed=seed)
        else:
            images = nova.inpaint(original, mask, prompt, n=VARIANTS, seed=seed)
        for k, img in enumerate(images):
            attempt += 1
            out = HEROES_DIR / f"{layout.layout_id}_{attempt}.png"
            cv2.imwrite(str(out), cv2.resize(img, (original.shape[1], original.shape[0])))
            url = to_url(out)
            s = score_image(pano.path, url, layout, guide_url)
            log.info("hero %s attempt %d: %s", layout.layout_id, attempt, s)
            _log_attempt(layout, pano, url, guide_url, mode, seed, s)
            if best is None or _rank(s) > _rank(best[0]):
                best = (s, url, attempt)
        if best and best[0].passed:
            break

    if best is None:
        raise nova.NovaError("Nova Canvas returned no images")
    s, url, att = best
    return HeroImage(
        hero_id=f"{layout.layout_id}-hero{att}",
        space_id=space_id,
        layout_id=layout.layout_id,
        path=url,
        source_pano_id=pano.pano_id,
        guide_path=guide_url,
        model=f"{nova._model_id()} ({mode})",
        prompt=prompt,
        attempt=att,
        score=s,
    )


def pick_panorama(panos: list[PanoRef], layout: Layout) -> PanoRef:
    """Face that shows the most items; furniture-free versions win ties. Skips up/down faces."""
    usable = [p for p in panos if p.face not in ("up", "down")] or panos
    if not usable:
        raise ValueError(f"No panoramas for space {layout.space_id}")
    return max(usable, key=lambda p: (count_visible(layout, p), p.defurnished))


def build_prompt(layout: Layout, style: str | None) -> str:
    tpl = TEMPLATES.get(layout.business_type)
    what = tpl.prompt_hint if tpl else f"{layout.business_type} interior"
    parts = [
        f"Photorealistic interior photograph of a {what}",
        f"styled as {style}" if style else "warm, inviting and modern",
        "furniture placed exactly in the marked areas, realistic scale, natural daylight from the windows",
        "keep the existing walls, windows, doors, floor and ceiling exactly as they are",
    ]
    return ", ".join(parts) + "."


def _log_attempt(layout: Layout, pano: PanoRef, url: str, guide_url: str, mode: str, seed: int, s: ImageScore) -> None:
    """Every attempt goes to data/runs/hero_log.jsonl for eval/image_eval.py."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "space_id": layout.space_id,
        "layout_id": layout.layout_id,
        "pano": pano.path,
        "hero": url,
        "guide": guide_url,
        "mode": mode,
        "seed": seed,
        "score": s.model_dump(),
    }
    with open(RUNS_DIR / "hero_log.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")


def _rank(s: ImageScore) -> tuple:
    return (s.passed, s.structure_preserved + s.plan_adherence + s.realism_1to5 / 5)


def _panoramas(space_id: str) -> list[PanoRef]:
    from pipeline.queries import get_panoramas  # Natnael's contract function

    return get_panoramas(space_id)
