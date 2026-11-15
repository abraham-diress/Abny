"""render_hero: the photoreal "this is your business" image for one space.

Steps: pick the panorama face that shows the most of the layout (furniture-free first) ->
render_guide (boxes + mask) -> generate N images -> score each -> keep the best -> one retry
with new seeds if none pass.

Images come from Stability AI on Amazon Bedrock (stability.py; AWS_BEARER_TOKEN_BEDROCK or AWS
credentials). The prompt names the furniture this photo actually shows, so a box marked "café
table" gets a table and not whatever the business is best known for.
HERO_MODE (env):
  inpaint   (default) furniture painted into the real photo; the room outside the boxes is kept
  condition the whole scene is generated from the guide image
  preview   no AI: the guide image itself (frontend work, or demo fallback)
If image generation fails (no key, quota, network), render_hero returns the preview instead of
raising, so a result always has a picture; its `model` says why.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import cv2

from agent.layout.templates import TEMPLATES
from agent.staging import stability
from agent.staging.files import ensure_dirs, mask_url_for, to_path, to_url
from agent.staging.guide import render_guide, view_score, visible_items
from agent.staging.score import score_image
from shared.conventions import HEROES_DIR, RUNS_DIR
from shared.schemas import HeroImage, ImageScore, Layout, PanoRef

log = logging.getLogger("hestia.hero")
VARIANTS = int(os.environ.get("HERO_VARIANTS", "2"))
MAX_ROUNDS = 2


def render_hero(space_id: str, layout: Layout, style: str | None = None) -> HeroImage:
    ensure_dirs()
    panos = _panoramas(space_id)
    if not panos:  # nothing cached for this space: the top-down plan is still a picture of the layout
        return _floorplan_hero(space_id, layout, build_prompt(layout, style))
    pano = pick_panorama(panos, layout)
    guide_url = render_guide(layout, pano)
    prompt = build_prompt(layout, style, visible_items(layout, pano))
    mode = os.environ.get("HERO_MODE", "inpaint").lower()

    if mode == "preview":
        return _preview(space_id, layout, pano, guide_url, prompt)

    original = cv2.imread(str(to_path(pano.path)), cv2.IMREAD_COLOR)
    guide = cv2.imread(str(to_path(guide_url)), cv2.IMREAD_COLOR)
    mask = cv2.imread(str(to_path(mask_url_for(guide_url))), cv2.IMREAD_GRAYSCALE)
    best: tuple[ImageScore, str, int] | None = None
    attempt = 0
    for round_ in range(MAX_ROUNDS):
        seed = 7 + round_ * 101
        try:
            images = generate_images(mode, original, guide, mask, prompt, n=VARIANTS, seed=seed)
        except stability.StabilityError as exc:
            log.warning("hero %s: image generation failed: %s", layout.layout_id, exc)
            if best is None:
                return _preview(space_id, layout, pano, guide_url, prompt, why=str(exc))
            break
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
        return _preview(space_id, layout, pano, guide_url, prompt, why="no images returned")
    s, url, att = best
    return HeroImage(
        hero_id=f"{layout.layout_id}-hero{att}",
        space_id=space_id,
        layout_id=layout.layout_id,
        path=url,
        source_pano_id=pano.pano_id,
        guide_path=guide_url,
        model=f"{_model_name()} ({mode})",
        prompt=prompt,
        attempt=att,
        score=s,
    )


def provider() -> str:
    return "bedrock_stability"


def _model_name() -> str:
    return stability.model_id()


def generate_images(mode: str, original, guide, mask, prompt: str, n: int = 2, seed: int = 7) -> list:
    """n images. Stability inpaints: it repaints only the masked furniture areas of the real photo
    (it sees no guide image), so walls and windows stay. HERO_MODE=condition also inpaints."""
    return stability.inpaint(original, mask, prompt, n=n, seed=seed)


def _preview(space_id: str, layout: Layout, pano: PanoRef, guide_url: str, prompt: str, why: str | None = None) -> HeroImage:
    """The guide image (plan drawn on the real photo) as the hero: no AI, always works."""
    return HeroImage(
        hero_id=f"{layout.layout_id}-preview",
        space_id=space_id,
        layout_id=layout.layout_id,
        path=guide_url,
        source_pano_id=pano.pano_id,
        guide_path=guide_url,
        model="preview-guide" + (f" (image generation unavailable: {why[:120]})" if why else ""),
        prompt=prompt,
        attempt=0,
        score=None,
    )


def _floorplan_hero(space_id: str, layout: Layout, prompt: str) -> HeroImage:
    from pipeline.queries import get_rooms  # Natnael's contract function

    from agent.staging.guide import render_floorplan

    plan = render_floorplan(layout, get_rooms(space_id))
    return HeroImage(
        hero_id=f"{layout.layout_id}-plan",
        space_id=space_id,
        layout_id=layout.layout_id,
        path=plan,
        source_pano_id="",
        guide_path=plan,
        model="floor-plan (no panoramas cached for this space)",
        prompt=prompt,
        attempt=0,
        score=None,
    )


def pick_panorama(panos: list[PanoRef], layout: Layout) -> PanoRef:
    """Face that shows the layout best (view_score); furniture-free versions win ties. Skips up/down faces."""
    usable = [p for p in panos if p.face not in ("up", "down")] or panos
    if not usable:
        raise ValueError(f"No panoramas for space {layout.space_id}")
    return max(usable, key=lambda p: (round(view_score(layout, p), 2), p.defurnished))


# How each item should look in the photo (Stability paints what the prompt names).
LOOKS = {
    "table_2": "small round wooden café tables with dark bentwood chairs",
    "table_4": "small round wooden café tables with dark bentwood chairs",
    "bench_table_4": "a wooden bench table with bentwood chairs",
    "display_case": "a glass pastry display case full of bread and pastries",
    "service_counter": "a wooden service counter with a cash register",
    "espresso_bar": "an espresso bar with a coffee machine",
    "condiment_station": "a small condiment station",
    "retail_shelf": "wooden shelves with neatly arranged products",
    "deck_oven": "stainless steel bakery ovens",
    "convection_oven": "stainless steel bakery ovens",
    "proofing_cabinet": "stainless steel kitchen equipment",
    "reach_in_fridge": "a stainless steel fridge",
    "prep_table": "a stainless steel prep table",
    "three_comp_sink": "a stainless steel sink",
    "spiral_mixer": "a stainless steel dough mixer",
    "desk_pod": "white office desks with monitors and black mesh office chairs",
    "single_desk": "a white office desk with a monitor and a black mesh office chair",
    "meeting_table": "a wooden meeting table with black high-back office chairs",
    "reception_desk": "a wooden reception desk",
    "sofa": "a dark leather sofa",
    "phone_booth": "an acoustic phone booth",
    "storage_cabinet": "a storage cabinet with drawers",
    "kitchenette_counter": "a kitchenette counter",
}


def build_prompt(layout: Layout, style: str | None, shown: list | None = None) -> str:
    """Photo prompt. `shown` = the items visible in the chosen photo: the prompt names exactly those."""
    tpl = TEMPLATES.get(layout.business_type)
    what = tpl.prompt_hint if tpl else f"{layout.business_type} interior"
    if shown:
        looks = list(dict.fromkeys(LOOKS.get(i.item_type, i.item_type.replace("_", " ")) for i in shown))
        what = f"{layout.business_type} with " + ", ".join(looks)
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
