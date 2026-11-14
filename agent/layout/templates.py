"""What each business needs and where it goes. Pure data; the planner reads it.

Zones, from the entrance inward:
  entrance clear area -> seating (front of house) -> customer queue -> service line
  -> staff aisle -> back of house (against the back wall, or in a separate back room)

Offices use the same pieces differently: no service line; the reception desk is an entry
item (side wall by the door), the meeting table is an anchor (back room if there is one),
desks are the "seats", and the kitchenette and storage are back of house.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.schemas import Brief, BusinessType


@dataclass(frozen=True)
class BusinessTemplate:
    business_type: BusinessType
    service_line: tuple[str, ...]  # placed side by side, fronts facing customers
    service_optional: tuple[str, ...] = ()  # dropped first when the line doesn't fit
    boh_required: tuple[str, ...] = ()  # back of house, in priority order
    boh_optional: tuple[str, ...] = ()
    seating_free: tuple[str, ...] = ()  # free-standing table sets, preferred order
    seating_wall: tuple[str, ...] = ()  # sets that sit against a wall
    foh_extras: tuple[str, ...] = ()  # against front-of-house walls
    queue_depth_m: float = 0.6  # extra customer space beyond the service clearance
    staff_aisle_m: float = 1.0
    default_seats: int = 16
    prompt_hint: str = ""
    entry_items: tuple[str, ...] = ()  # placed first, against a wall next to the entrance
    anchor_items: tuple[str, ...] = ()  # free-standing, placed before seating (back room first)
    strategies: tuple[str, ...] = ("back-counter", "side-counter")
    seat_word: str = "seats"  # what seat_count counts, for notes ("desks" for offices)


BAKERY = BusinessTemplate(
    business_type="bakery",
    service_line=("display_case", "service_counter"),
    boh_required=("deck_oven", "prep_table", "three_comp_sink", "reach_in_fridge"),
    boh_optional=("proofing_cabinet", "spiral_mixer"),
    seating_free=("table_2", "table_4"),
    seating_wall=("bench_table_4",),
    foh_extras=("condiment_station",),
    default_seats=16,
    prompt_hint="artisan bakery with a glass pastry display case full of bread and pastries, service counter, café tables",
)

CAFE = BusinessTemplate(
    business_type="cafe",
    service_line=("display_case", "espresso_bar", "service_counter"),
    service_optional=("display_case",),
    boh_required=("convection_oven", "prep_table", "three_comp_sink", "reach_in_fridge"),
    boh_optional=("proofing_cabinet",),
    seating_free=("table_2", "table_4"),
    seating_wall=("bench_table_4",),
    foh_extras=("condiment_station",),
    default_seats=24,
    prompt_hint="specialty coffee shop with an espresso bar, pastry case and café seating",
)

RETAIL = BusinessTemplate(
    business_type="retail",
    service_line=("service_counter",),
    foh_extras=("retail_shelf",) * 6,
    default_seats=0,
    staff_aisle_m=0.0,
    queue_depth_m=0.3,
    prompt_hint="bright boutique retail store with wall shelving and a checkout counter",
)

OFFICE = BusinessTemplate(
    business_type="office",
    service_line=(),
    entry_items=("reception_desk",),
    anchor_items=("meeting_table",),
    boh_required=("kitchenette_counter",),
    boh_optional=("storage_cabinet", "storage_cabinet"),
    seating_free=("desk_pod",),  # pods fill the open floor; single desks line the side walls
    seating_wall=("single_desk",),
    foh_extras=("sofa", "phone_booth"),
    staff_aisle_m=0.0,
    default_seats=12,
    strategies=("open-plan",),
    seat_word="desks",
    prompt_hint=("bright modern open-plan office with white desk pods, black task chairs and monitors, "
                 "a wooden meeting table, a reception desk and a few plants"),
)

TEMPLATES: dict[str, BusinessTemplate] = {"bakery": BAKERY, "cafe": CAFE, "retail": RETAIL, "office": OFFICE}

_TWO_OVENS = re.compile(r"\b(two|2|double)\s+(deck\s+)?ovens?\b", re.I)


def template_for(brief: Brief) -> tuple[BusinessTemplate, list[str]]:
    """Template for the brief's business type, adjusted by what the brief asks for. Returns (template, notes)."""
    notes: list[str] = []
    tpl = TEMPLATES.get(brief.business_type)
    if tpl is None:
        notes.append(f"No template for '{brief.business_type}' yet; used the bakery template.")
        tpl = BAKERY
    text = " ".join([brief.raw_text, *brief.must_haves])
    if tpl is BAKERY and _TWO_OVENS.search(text):
        tpl = BusinessTemplate(**{**tpl.__dict__, "boh_required": ("deck_oven", "deck_oven", *tpl.boh_required[1:])})
        notes.append("Brief asks for two ovens.")
    return tpl, notes


def target_seats(brief: Brief, tpl: BusinessTemplate) -> int:
    return brief.seats_wanted if brief.seats_wanted is not None else tpl.default_seats
