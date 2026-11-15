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
from dataclasses import dataclass, replace

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
    # Dressing: pieces that make a big floor look lived in. They add no seats and are placed last,
    # each kept only if everyone can still reach everything (see planner._dress).
    #   (item_type, m2 of floor per piece, max pieces, "wall" | "free", group): the count grows with the floor.
    #   group "social" pieces gather around the biggest empty patch, "work" pieces sit near the desks,
    #   "" pieces go wherever the floor is emptiest.
    dress_program: tuple[tuple[str, float, int, str, str], ...] = ()
    dress_fill_large: tuple[str, ...] = ()  # then fill the biggest empty patches with these (a big void)
    dress_fill_small: tuple[str, ...] = ()  # ...or these (a smaller void)
    dress_target_empty: float = 0.12  # stop filling when this share of the floor is still empty
    dress_fill_cap: float = 0.30  # never dress a floor that is already this full of furniture
    dress_whole_floor: bool = False  # offices dress every room; shops only the front room
    dress_rugs: tuple[tuple[str, str, float], ...] = ()  # (piece, rug under it, how far the rug sits toward the piece's front, m)


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
    dress_program=(("plant_large", 40, 4, "wall", ""),),
    dress_fill_cap=0.35,
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
    dress_program=(("plant_large", 40, 4, "wall", ""), ("floor_lamp", 60, 2, "wall", "")),
    dress_fill_cap=0.35,
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
    # A 25-desk team in a 460 m2 floor still has 300 m2 to live in: lounges, huddle tables, a coffee bar,
    # shelves, whiteboards and plants, in the quantities a floor that size would really have.
    dress_program=(
        ("coffee_bar", 100, 1, "wall", "social"),
        ("lounge_set", 150, 3, "wall", "social"),
        ("huddle_table", 80, 4, "free", "social"),
        # Recreation, only on a floor big enough to spare the room (one per 200 / 300 / 450 m2 of floor):
        ("foosball_table", 200, 1, "free", "social"),
        ("table_tennis", 300, 2, "free", "social"),
        ("fish_pond", 450, 1, "free", "social"),
        ("printer_station", 120, 1, "wall", "work"),
        ("whiteboard", 90, 3, "wall", "work"),
        ("bookshelf", 70, 4, "wall", "work"),
        ("planter_divider", 110, 3, "free", "social"),
        ("floor_lamp", 90, 4, "wall", ""),
        ("plant_large", 45, 8, "wall", "")
    ),
    dress_fill_large=("huddle_table", "lounge_set"),
    dress_fill_small=("plant_large",),
    dress_whole_floor=True,
    dress_rugs=(("lounge_set", "rug_lounge", 0.55), ("huddle_table", "rug_huddle", 0.0), ("meeting_table", "rug_meeting", 0.0)),
)

TEMPLATES: dict[str, BusinessTemplate] = {"bakery": BAKERY, "cafe": CAFE, "retail": RETAIL, "office": OFFICE}

_TWO_OVENS = re.compile(r"\b(two|2|double)\s+(deck\s+)?ovens?\b", re.I)


M2_PER_DESK = 9.0  # gross floor per desk: the desk, its aisles and its share of meeting, lounge and support space


def desk_capacity(area_m2: float) -> int:
    """About how many desks a floor of this size seats comfortably."""
    return int(area_m2 // M2_PER_DESK)


def _clamp(x: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, round(x)))


def scale_to_room(tpl: BusinessTemplate, area_m2: float) -> BusinessTemplate:
    """Decide the pieces that belong to the *room*, not to the headcount, from the floor area first:
    meeting tables, phone booths, kitchenettes and storage. (The desks still follow the brief; the
    amenities in `dress_program` also scale with the floor.) A 140 m2 floor and a 460 m2 floor get
    different counts for the same 25 desks."""
    if tpl.business_type != "office":
        return tpl
    return replace(
        tpl,
        anchor_items=("meeting_table",) * _clamp(area_m2 / 160, 1, 4),
        boh_required=("kitchenette_counter",) * _clamp(area_m2 / 260, 1, 3),
        boh_optional=("storage_cabinet",) * _clamp(area_m2 / 110, 2, 8),
        foh_extras=("sofa",) + ("phone_booth",) * _clamp(area_m2 / 90, 1, 6),
    )


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
