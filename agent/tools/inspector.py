"""Contract: inspect_space(space_id) -> Inspection.

Looks at 3-5 cached panorama faces with Claude vision and a fixed checklist. Rules:
* Business-aware checklist: food (storefront glass, kitchen, vent hood, restroom) vs office
  (natural light, existing build-out, restroom). Both are asked in one call; only the relevant
  ones are flagged as unverified when the model can't see them.
* Only report what is visible. Anything the model can't confirm -> None + `unverified_fields`.
* Ceiling height prefers Matterport room data (measured) over the visual estimate.
* Every fact cites the panoramas (or room record) it came from.
* No images on disk or no LLM -> a clearly-labelled low-confidence result, never a crash.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agent import providers as P
from shared.conventions import MEDIA_DIR
from shared.schemas import Citation, Inspection, PanoRef

log = logging.getLogger(__name__)

MAX_PANOS = 5
MAX_IMAGE_BYTES = 3_500_000  # Bedrock's per-image limit is 3.75 MB
YesNo = Literal["yes", "no", "unknown"]
CHECKLIST = ("storefront_glass", "existing_kitchen", "existing_restroom", "vent_hood")  # yes/no fields
FOCUS = {
    "office": ("existing_restroom", "natural_light", "existing_build_out"),
    "food": ("storefront_glass", "existing_kitchen", "existing_restroom", "vent_hood"),
}
BuildOut = Literal["open plan", "private offices", "mixed offices", "retail shell", "restaurant kitchen", "shell", "unknown"]


def focus_fields(business_type: str) -> tuple[str, ...]:
    return FOCUS["office"] if business_type == "office" else FOCUS["food"]


class _Finding(BaseModel):
    answer: YesNo = Field(..., description="'unknown' unless you can clearly see it in the images")
    evidence: str = Field("", description="Which image number(s) and what you saw, in a few words")


class _VisionReport(BaseModel):
    storefront_glass: _Finding = Field(..., description="Large street-facing glass windows or glass doors")
    existing_kitchen: _Finding = Field(..., description="Commercial kitchen: stainless counters, sinks, ranges, walk-in, tiled kitchen floor")
    existing_restroom: _Finding = Field(..., description="A restroom: toilet, restroom door sign, or bathroom fixtures")
    vent_hood: _Finding = Field(..., description="Commercial exhaust hood over a cooking line")
    natural_light: float | None = Field(None, ge=0, le=1, description="Daylight: 0 = no windows, 0.5 = windows on one wall, 1 = windows on most walls. Null if you can't judge")
    existing_build_out: BuildOut = Field("unknown", description="What is already built inside")
    ceiling_height_m: float | None = Field(None, description="Estimated floor-to-ceiling height in meters, null if you can't judge")
    notes: list[str] = Field(default_factory=list, description="Up to 4 short observations relevant to opening a business here (condition, columns, light, damage)")
    confidence: float = Field(0.5, ge=0, le=1, description="How sure you are overall")


_PROMPT = (
    "You are inspecting an empty commercial space from {n} panorama images (numbered 1..{n} in order) "
    "for someone who wants to open a {business}. Answer the checklist strictly from what is visible. "
    "If something is not visible in any image, answer 'unknown': never guess. Typical doors are 2.1 m tall; "
    "use them to estimate ceiling height. {focus}"
)
_FOCUS_TEXT = {
    "office": "For an office, daylight, restrooms and what is already built (open plan vs private offices vs shell) matter most; a kitchen doesn't.",
    "food": "For a food business, storefront glass, an existing kitchen and a vent hood matter most (they cut fit-out cost).",
}


def _local_path(pano: PanoRef) -> Path:
    rel = pano.path.removeprefix("/").removeprefix("media/")
    return MEDIA_DIR / rel


def pick_panoramas(panos: list[PanoRef], k: int = MAX_PANOS) -> list[PanoRef]:
    """Prefer furniture-free horizontal faces, spread across different scans (more of the space)."""
    horizontal = [p for p in panos if p.face not in ("up", "down")] or panos
    horizontal.sort(key=lambda p: (not p.defurnished, p.face != "front"))
    picked: list[PanoRef] = []
    seen_scans: set[str] = set()
    for p in horizontal:  # first pass: one per scan
        if p.scan_id not in seen_scans:
            picked.append(p)
            seen_scans.add(p.scan_id)
        if len(picked) == k:
            return picked
    for p in horizontal:  # second pass: fill up
        if p not in picked:
            picked.append(p)
        if len(picked) == k:
            break
    return picked


def inspect_space(space_id: str, business_type: str = "bakery") -> Inspection:
    """Look at the space's cached panoramas and report what is physically there."""
    from agent.llm import llm_available

    panos = pick_panoramas(P.get_panoramas(space_id))
    images = []
    for p in panos:
        f = _local_path(p)
        if f.is_file() and f.stat().st_size <= MAX_IMAGE_BYTES:
            images.append((p, f))

    measured_ceiling, ceiling_cite = _measured_ceiling(space_id)

    if not images or not llm_available():
        reason = "no cached panoramas on disk" if not images else "no LLM credentials"
        if P.using_sample_data():
            from agent import samples

            insp = samples.sample_inspection(space_id, business_type)
            insp.notes.append(f"Vision skipped ({reason}).")
            return insp
        return Inspection(
            space_id=space_id, ceiling_height_m=measured_ceiling, confidence=0.1,
            notes=[f"Vision inspection skipped: {reason}."],
            pano_ids=[p.pano_id for p in panos], unverified_fields=list(focus_fields(business_type))
            + ([] if measured_ceiling else ["ceiling_height_m"]),
            citations=[ceiling_cite] if ceiling_cite else [],
        )

    report = _ask_vision([f for _, f in images], business_type)
    used = [p for p, _ in images]
    insp = Inspection(space_id=space_id, pano_ids=[p.pano_id for p in used],
                      confidence=report.confidence, notes=report.notes[:4])
    focus = focus_fields(business_type)
    src = ",".join(insp.pano_ids)
    for field in CHECKLIST:
        finding: _Finding = getattr(report, field)
        if finding.answer == "unknown":
            if field in focus:
                insp.unverified_fields.append(field)
            continue
        setattr(insp, field, finding.answer == "yes")
        insp.citations.append(Citation(source="matterport", dataset="panorama", record_id=src,
                                       field=field, value=finding.answer == "yes", note=finding.evidence[:200] or None))
    if report.natural_light is not None:
        insp.natural_light = round(report.natural_light, 2)
        insp.citations.append(Citation(source="model", dataset="panorama", record_id=src, field="natural_light",
                                       value=insp.natural_light, note="visual estimate from panoramas"))
    elif "natural_light" in focus:
        insp.unverified_fields.append("natural_light")
    if report.existing_build_out != "unknown":
        insp.existing_build_out = report.existing_build_out
        insp.citations.append(Citation(source="model", dataset="panorama", record_id=src, field="existing_build_out",
                                       value=insp.existing_build_out))
    elif "existing_build_out" in focus:
        insp.unverified_fields.append("existing_build_out")
    if measured_ceiling:
        insp.ceiling_height_m = measured_ceiling
        insp.citations.append(ceiling_cite)  # type: ignore[arg-type]
    elif report.ceiling_height_m and 2.0 <= report.ceiling_height_m <= 10:
        insp.ceiling_height_m = round(report.ceiling_height_m, 2)
        insp.citations.append(Citation(source="model", dataset="panorama", field="ceiling_height_m",
                                       value=insp.ceiling_height_m, note="visual estimate"))
        insp.unverified_fields.append("ceiling_height_m")  # an estimate, not a measurement
    else:
        insp.unverified_fields.append("ceiling_height_m")
    return insp


def _measured_ceiling(space_id: str) -> tuple[float | None, Citation | None]:
    try:
        rooms = P.get_rooms(space_id)
    except Exception:  # noqa: BLE001
        return None, None
    best = max((r for r in rooms if r.ceiling_m), key=lambda r: r.area_m2, default=None)
    if not best:
        return None, None
    return best.ceiling_m, Citation(source="matterport", dataset="rooms", record_id=best.room_id,
                                    field="ceiling_m", value=best.ceiling_m)


def _ask_vision(files: list[Path], business_type: str) -> _VisionReport:
    from agent.llm import get_chat_model

    focus = _FOCUS_TEXT["office" if business_type == "office" else "food"]
    content: list[dict] = [{"type": "text", "text": _PROMPT.format(n=len(files), business=business_type, focus=focus)}]
    for i, f in enumerate(files, start=1):
        mime = "image/png" if f.suffix.lower() == ".png" else "image/jpeg"
        content.append({"type": "text", "text": f"Image {i}:"})
        content.append({"type": "image", "source_type": "base64", "mime_type": mime,
                        "data": base64.b64encode(f.read_bytes()).decode()})
    model = get_chat_model(fast=True, max_tokens=1500).with_structured_output(_VisionReport)
    return model.invoke([{"role": "user", "content": content}])  # type: ignore[return-value]
