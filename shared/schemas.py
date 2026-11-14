"""Hestia shared data contracts.

THIS FILE IS THE SINGLE SOURCE OF TRUTH for every object that moves between
team members' code (agent <-> data <-> reimagine <-> server <-> frontend).

Rules
-----
* Every cross-member function returns one of these models (see shared/contracts.py).
* Changing a model = tell the team in chat first (Biniyam mirrors these in TypeScript).
* Conventions (also in README):
    - Lengths are METERS, areas m^2. sqft only for display (``shared.units``).
    - Money is USD; rent is USD per month unless the field name says otherwise.
    - Floor-plan coordinates are Matterport model coordinates on the floor
      plane: (x, z) in meters, y is up. ``rotation_deg`` is about +y.
    - File references are URL paths relative to the API server root, e.g.
      ``media/panos/abc/scan1_front.jpg`` or ``assets/glb/oven.glb``.
      Folder names are in ``shared/conventions.py``.
    - Every fact that came from data carries a ``Citation``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0.0"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contract(BaseModel):
    """Base for all shared models: unknown fields are an error, not silently dropped."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_serialization_defaults_required=True,
    )


# --------------------------------------------------------------------------- #
# Enums / aliases
# --------------------------------------------------------------------------- #

BusinessType = Literal[
    "bakery", "cafe", "restaurant", "retail", "clinic", "gym", "salon", "office", "other"
]
City = Literal["Houston", "Los Angeles"]
Source = Literal["costar", "matterport", "vexcel", "model", "assumption", "user"]
Zone = Literal["entrance", "front_of_house", "seating", "service", "back_of_house"]
CubeFace = Literal["front", "back", "left", "right", "up", "down", "equirect"]
CandidateStatus = Literal["screened", "inspected", "fitted", "rejected", "failed"]
TodoStatus = Literal["pending", "in_progress", "completed"]
RunState = Literal["queued", "running", "done", "error"]
FeedbackKind = Literal["reject", "prefer", "constraint", "other"]
ViolationKind = Literal[
    "out_of_bounds",
    "overlap",
    "aisle_too_narrow",
    "entrance_blocked",
    "unreachable",
    "seat_shortfall",
    "other",
]
EventType = Literal[
    "run_started",
    "plan_update",
    "subagent_started",
    "subagent_finished",
    "tool_call",
    "tool_result",
    "file_written",
    "funnel_update",
    "candidate_ready",
    "feedback_received",
    "run_finished",
    "error",
    "log",
]

XZ = tuple[float, float]
XYZ = tuple[float, float, float]


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


class Citation(Contract):
    """Where a fact came from, e.g. Citation(source="costar", dataset="commercial_listing", record_id="123", field="asking_rent", value=6200)."""

    source: Source
    dataset: str | None = Field(None, description="e.g. 'commercial_listing', 'property/extract', 'rooms'")
    record_id: str | None = None
    field: str | None = None
    value: str | float | int | bool | None = None
    note: str | None = None


# --------------------------------------------------------------------------- #
# The user's request
# --------------------------------------------------------------------------- #


class Feedback(Contract):
    text: str
    kind: FeedbackKind = "constraint"
    space_id: str | None = Field(None, description="Set when the feedback is about one result")
    created_at: datetime = Field(default_factory=utcnow)


class Brief(Contract):
    """Structured version of what the business owner asked for."""

    raw_text: str = ""
    business_type: BusinessType = "bakery"
    city: City | None = None
    area_hint: str | None = Field(None, description="Free text like 'near downtown' or 'close to transit'")
    seats_wanted: int | None = Field(
        None, ge=0, description="Customer seats for food businesses; desks (= headcount) for offices"
    )
    sqft_min: float | None = Field(None, ge=0)
    sqft_max: float | None = Field(None, ge=0)
    max_rent_month: float | None = Field(None, ge=0)
    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    style: str | None = Field(None, description="Look and feel, e.g. 'warm artisan, wood and white tile'")
    feedback_history: list[Feedback] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Data layer (owner: Data Engine)
# --------------------------------------------------------------------------- #


class Space(Contract):
    """One candidate space: a CoStar property/listing joined to its Matterport model."""

    space_id: str
    costar_property_id: str | None = None
    listing_id: str | None = None
    matterport_model_id: str | None = None
    address: str
    city: City | None = None
    lat: float
    lon: float
    property_type: str | None = None
    sqft: float | None = None
    asking_rent_month: float | None = None
    rent_per_sqft_year: float | None = None
    year_built: int | None = None
    has_scan: bool = False
    citations: list[Citation] = Field(default_factory=list)


class Opening(Contract):
    """A door/window segment on a room boundary, as (x, z) endpoints in meters."""

    kind: Literal["door", "window", "opening", "unknown"] = "unknown"
    a: XZ
    b: XZ


class Room(Contract):
    room_id: str
    space_id: str
    label: str | None = None
    room_type: str | None = Field(None, description="Matterport room classification if available")
    floor_index: int = 0
    polygon_m: list[XZ] = Field(..., description="Room outline on the floor plane, meters, model coordinates")
    floor_y_m: float = 0.0
    ceiling_m: float | None = Field(None, description="Ceiling height in meters if known")
    area_m2: float
    openings: list[Opening] = Field(default_factory=list)


class PanoRef(Contract):
    """One cached panorama image (a cube face or equirect) with its camera pose."""

    pano_id: str
    space_id: str
    scan_id: str
    room_id: str | None = None
    face: CubeFace = "front"
    path: str = Field(..., description="URL path, e.g. media/panos/<model>/<scan>_front.jpg")
    defurnished: bool = False
    position_m: XYZ
    rotation_quat: tuple[float, float, float, float] | None = Field(None, description="x, y, z, w")
    fov_deg: float = 90.0
    width_px: int
    height_px: int


class POI(Contract):
    name: str
    kind: str = Field(
        ..., description="competitor | transit | parking | anchor | residential | amenity (food/gym near an office) | other"
    )
    lat: float
    lon: float
    distance_m: float
    citation: Citation | None = None


class NeighborhoodProfile(Contract):
    space_id: str
    nearby_tenant_count: int = 0
    nearby_employees_est: int | None = None
    nearby_residential_units: int = 0
    competitors: list[POI] = Field(default_factory=list, description="Same-business tenants nearby; empty for offices")
    amenities: list[POI] = Field(default_factory=list, description="Food, cafés, gyms within walking distance (offices)")
    transit: list[POI] = Field(default_factory=list)
    parking_score: float | None = Field(None, ge=0, le=1)
    parking_notes: str | None = None
    footprint_wkt: str | None = None
    parcel_wkt: str | None = None
    aerial_ortho_path: str | None = None
    aerial_oblique_path: str | None = None
    score: float = Field(0.0, ge=0, le=1, description="Overall neighborhood fit for the brief")
    citations: list[Citation] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Inspection (owner: Brain)
# --------------------------------------------------------------------------- #


class Inspection(Contract):
    space_id: str
    storefront_glass: bool | None = None
    existing_kitchen: bool | None = None
    existing_restroom: bool | None = None
    vent_hood: bool | None = None
    ceiling_height_m: float | None = None
    natural_light: float | None = Field(None, ge=0, le=1, description="0 = no daylight, 1 = windows on most walls (key for offices)")
    existing_build_out: str | None = Field(
        None, description="What is already built: 'open plan', 'private offices', 'restaurant kitchen', 'shell'..."
    )
    notes: list[str] = Field(default_factory=list)
    pano_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0, le=1)
    unverified_fields: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Layout + visuals (owner: Reimaginer)
# --------------------------------------------------------------------------- #


class CatalogItem(Contract):
    """One placeable furniture/equipment type. Real catalog lives in assets/catalog.json."""

    item_type: str
    label: str
    glb_asset: str = Field(..., description="URL path, e.g. assets/glb/display_case.glb")
    width_m: float
    depth_m: float
    height_m: float
    clearance_front_m: float = 0.0
    seats: int = 0
    zone: Zone
    business_types: list[BusinessType] = Field(default_factory=list)


class LayoutItem(Contract):
    item_id: str
    item_type: str = Field(..., description="Key into the catalog")
    glb_asset: str
    room_id: str
    x_m: float
    z_m: float
    rotation_deg: float = Field(0.0, description="About +y; 0 means the item's front faces +z")
    width_m: float
    depth_m: float
    height_m: float
    zone: Zone | None = None
    seats: int = 0


class Layout(Contract):
    layout_id: str
    space_id: str
    business_type: BusinessType
    entrance_xz: XZ | None = None
    items: list[LayoutItem] = Field(default_factory=list)
    seat_count: int = 0
    strategy: str | None = None
    notes: list[str] = Field(default_factory=list)


class Violation(Contract):
    kind: ViolationKind
    item_ids: list[str] = Field(default_factory=list)
    message: str


class ValidationReport(Contract):
    layout_id: str
    passed: bool
    violations: list[Violation] = Field(default_factory=list)
    min_aisle_m: float | None = None
    seat_count: int = 0


class ImageScore(Contract):
    structure_preserved: float = Field(..., ge=0, le=1, description="1 = walls/windows unchanged")
    plan_adherence: float = Field(..., ge=0, le=1, description="1 = items match the layout")
    realism_1to5: float = Field(..., ge=1, le=5)
    passed: bool
    notes: list[str] = Field(default_factory=list)


class HeroImage(Contract):
    hero_id: str
    space_id: str
    layout_id: str
    path: str
    source_pano_id: str
    guide_path: str | None = None
    model: str
    prompt: str
    attempt: int = 1
    score: ImageScore | None = None


# --------------------------------------------------------------------------- #
# Numbers (owner: Data Engine)
# --------------------------------------------------------------------------- #


class Assumption(Contract):
    name: str
    value: float | str
    unit: str | None = None
    source: Source = "assumption"
    note: str | None = None


class Numbers(Contract):
    space_id: str
    rent_month: float | None = None
    fitout_cost_low: float
    fitout_cost_high: float
    revenue_month_low: float = Field(0.0, description="0 for offices (they don't sell to walk-in customers)")
    revenue_month_high: float = 0.0
    breakeven_months_low: float | None = Field(None, description="None for offices")
    breakeven_months_high: float | None = None
    cost_per_seat_month_low: float | None = Field(
        None, description="(rent + fit-out spread over the lease) / seats or desks. The headline number for offices"
    )
    cost_per_seat_month_high: float | None = None
    assumptions: list[Assumption] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Results + run state (owner: Brain; rendered by Experience)
# --------------------------------------------------------------------------- #


class CandidateResult(Contract):
    run_id: str | None = None
    rank: int
    rank_score: float = Field(0.0, ge=0, le=1)
    rank_reasons: list[str] = Field(default_factory=list)
    status: CandidateStatus = "screened"
    space: Space
    neighborhood: NeighborhoodProfile | None = None
    inspection: Inspection | None = None
    layout: Layout | None = None
    validation: ValidationReport | None = None
    hero: HeroImage | None = None
    numbers: Numbers | None = None
    broker_email: str | None = None


class FunnelStats(Contract):
    total: int = 0
    filtered: int = 0
    ranked: int = 0
    inspected: int = 0
    fitted: int = 0


class TodoItem(Contract):
    content: str
    status: TodoStatus = "pending"


class AgentEvent(Contract):
    """One server-sent event. Payload shape per ``type`` is documented in README §5.4."""

    run_id: str
    seq: int
    type: EventType
    ts: datetime = Field(default_factory=utcnow)
    agent: str | None = Field(None, description="'orchestrator' or a subagent name")
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# HTTP API bodies (server implements, frontend calls)
# --------------------------------------------------------------------------- #


class CreateRunRequest(Contract):
    text: str
    brief: Brief | None = Field(None, description="Optional pre-filled brief; otherwise parsed from text")


class CreateRunResponse(Contract):
    run_id: str


class FeedbackRequest(Contract):
    text: str
    kind: FeedbackKind = "constraint"
    space_id: str | None = None


class RunStatus(Contract):
    run_id: str
    state: RunState
    brief: Brief | None = None
    funnel: FunnelStats = Field(default_factory=FunnelStats)
    result_count: int = 0
    round: int = Field(0, description="Increments every time feedback triggers a re-plan")
    error: str | None = None


ALL_MODELS: list[type[Contract]] = [
    Citation,
    Feedback,
    Brief,
    Space,
    Opening,
    Room,
    PanoRef,
    POI,
    NeighborhoodProfile,
    Inspection,
    CatalogItem,
    LayoutItem,
    Layout,
    Violation,
    ValidationReport,
    ImageScore,
    HeroImage,
    Assumption,
    Numbers,
    CandidateResult,
    FunnelStats,
    TodoItem,
    AgentEvent,
    CreateRunRequest,
    CreateRunResponse,
    FeedbackRequest,
    RunStatus,
]
