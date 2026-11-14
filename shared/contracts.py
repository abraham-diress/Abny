"""Hestia function contracts: WHAT each member's code must expose. No implementations here.

Each stub below shows the exact name, parameters and return type (from shared/schemas.py)
that the owner implements in their own module. Other members import the real function
from that module once it exists, e.g.::

    from pipeline.queries import query_spaces

Until then, build against a small hand-made object of the return type in your own code.
Changing a signature here = tell the team first.
"""

from __future__ import annotations

from shared.schemas import (
    Brief,
    HeroImage,
    ImageScore,
    Inspection,
    Layout,
    NeighborhoodProfile,
    Numbers,
    PanoRef,
    Room,
    Space,
    ValidationReport,
)

# =========================================================================== #
# Abraham (The Brain)
# =========================================================================== #


def parse_brief(text: str) -> Brief:
    """Free text from the business owner -> structured Brief.

    Module: agent/brief.py
    Returns: Brief with raw_text set; fields the user didn't mention stay None/empty.
    TODO(Abraham): implement with LLM structured output.
    """
    raise NotImplementedError


def inspect_space(space_id: str) -> Inspection:
    """Look at the space's cached panoramas and report what is physically there.

    Module: agent/tools/inspector.py
    Uses: get_panoramas(space_id)
    Returns: Inspection (storefront glass, existing kitchen/restroom/vent hood, ceiling height).
             Anything the model can't confirm goes in unverified_fields; list pano_ids used.
    TODO(Abraham): implement with Claude vision + a checklist prompt.
    """
    raise NotImplementedError


# =========================================================================== #
# Natnael (The Data Engine)
# =========================================================================== #


def query_spaces(brief: Brief, limit: int = 200) -> list[Space]:
    """Cheap filter over the local database: city, size range, rent, has_scan.

    Module: pipeline/queries.py
    Returns: up to `limit` Spaces, each with citations to its CoStar records.
             Keep slightly-over-budget spaces so the agent can reason about trade-offs.
    TODO(Natnael)
    """
    raise NotImplementedError


def get_space(space_id: str) -> Space:
    """One Space by id. Module: pipeline/queries.py. TODO(Natnael)"""
    raise NotImplementedError


def get_rooms(space_id: str) -> list[Room]:
    """Matterport rooms for the space (polygon in meters, floor height, ceiling, openings).

    Module: pipeline/queries.py
    TODO(Natnael)
    """
    raise NotImplementedError


def get_panoramas(space_id: str) -> list[PanoRef]:
    """Cached panorama faces with camera pose; prefer furniture-free versions.

    Module: pipeline/queries.py
    Returns: PanoRef.path is a URL path under media/ (see shared/conventions.py).
    TODO(Natnael)
    """
    raise NotImplementedError


def neighborhood_profile(space_id: str) -> NeighborhoodProfile:
    """Nearby tenants, residents, competitors, transit, parking and a 0–1 fit score.

    Module: pipeline/queries.py
    Sources: CoStar occupancy/company detail/apartment listings, Vexcel property + embedding search.
    Returns: every value backed by a Citation.
    TODO(Natnael)
    """
    raise NotImplementedError


def estimate_costs(space: Space, layout: Layout | None, inspection: Inspection | None, brief: Brief) -> Numbers:
    """Rent, fit-out cost range, revenue range, break-even months.

    Module: agent/analyst/costs.py
    Returns: Numbers with every assumption listed in `assumptions` and data in `citations`.
             Fit-out cost should be lower when inspection.existing_kitchen is True.
    TODO(Natnael)
    """
    raise NotImplementedError


def draft_broker_email(space: Space, brief: Brief) -> str:
    """Short email to the listing broker asking to visit. Module: agent/analyst/costs.py. TODO(Natnael)"""
    raise NotImplementedError


def visual_search(text: str, k: int = 20) -> list[tuple[str, float]]:
    """STRETCH. (space_id, similarity) for a free-text visual query over panorama embeddings.

    Module: pipeline/visual_search.py
    TODO(Natnael): only after core tasks.
    """
    raise NotImplementedError


# =========================================================================== #
# Yared (The Reimaginer)
# =========================================================================== #


def plan_layout(
    space_id: str,
    rooms: list[Room],
    inspection: Inspection | None,
    brief: Brief,
    strategy: str | None = None,
) -> Layout:
    """Place the business's items inside the real rooms.

    Module: agent/layout/planner.py
    Returns: Layout whose items use catalog item_types and model coordinates (x, z meters);
             seat_count = sum of item seats. Must pass validate_layout.
    TODO(Yared)
    """
    raise NotImplementedError


def validate_layout(layout: Layout, rooms: list[Room]) -> ValidationReport:
    """Geometry checks: inside rooms, no overlaps, aisles >= MIN_AISLE_M, entrance clear, seats.

    Module: agent/layout/validator.py
    TODO(Yared)
    """
    raise NotImplementedError


def render_guide(layout: Layout, pano: PanoRef) -> str:
    """Draw the layout's item boxes onto a panorama face.

    Module: agent/staging/guide.py
    Returns: URL path of the guide image under media/guides/.
    TODO(Yared)
    """
    raise NotImplementedError


def render_hero(space_id: str, layout: Layout, style: str | None = None) -> HeroImage:
    """Photoreal 'this is your business' image, already scored (best of N attempts).

    Module: agent/staging/generate.py
    Uses: render_guide, score_image
    TODO(Yared)
    """
    raise NotImplementedError


def score_image(original_path: str, generated_path: str, layout: Layout, guide_path: str | None = None) -> ImageScore:
    """Did the building stay the same, does the image follow the layout, does it look real?

    Module: agent/staging/score.py
    TODO(Yared)
    """
    raise NotImplementedError
