"""Cost and revenue benchmarks used by estimate_costs. Every value becomes an `Assumption`.

These are planning-grade industry ranges, not quotes. Each has a `note` explaining where
it comes from; replace a value with a better-sourced one (and update the note) any time.
(low, high) tuples: low = cheaper / less revenue.
"""

from __future__ import annotations

# Build-out $/sqft (construction + MEP + finishes, excluding equipment).
# "Second-generation" = space was already a food business (existing kitchen).
FITOUT_PSF: dict[str, dict[str, tuple[float, float]]] = {
    "bakery":     {"raw": (100, 200), "second_gen": (35, 90)},
    "cafe":       {"raw": (90, 180),  "second_gen": (30, 80)},
    "restaurant": {"raw": (150, 300), "second_gen": (50, 120)},
    "retail":     {"raw": (40, 110),  "second_gen": (20, 60)},
    "salon":      {"raw": (70, 150),  "second_gen": (30, 80)},
    "gym":        {"raw": (40, 100),  "second_gen": (20, 60)},
    "clinic":     {"raw": (120, 250), "second_gen": (50, 120)},
    "office":     {"raw": (40, 100),  "second_gen": (15, 50)},
    "other":      {"raw": (50, 120),  "second_gen": (25, 70)},
}
FITOUT_NOTE = ("Typical small-business tenant build-out ranges ($/sqft, before equipment) from contractor and "
               "restaurant-industry guides; second-generation space reuses plumbing, grease trap and electrical.")

# Commercial kitchen hood + fire suppression install, saved if a hood is already there.
VENT_HOOD_COST = (15_000, 40_000)

# Equipment cost per catalog item_type (Yared's catalog). Unknown types use DEFAULT_ITEM_COST.
ITEM_COST: dict[str, tuple[float, float]] = {
    "deck_oven": (12_000, 35_000),
    "oven": (8_000, 30_000),
    "convection_oven": (5_000, 15_000),
    "display_case": (3_000, 9_000),
    "service_counter": (2_500, 8_000),
    "counter": (2_000, 7_000),
    "prep_table": (400, 1_500),
    "sink": (800, 3_000),
    "proofing_rack": (1_500, 5_000),
    "proofer": (2_500, 8_000),
    "mixer": (3_000, 12_000),
    "refrigerator": (3_000, 8_000),
    "espresso_machine": (6_000, 20_000),
    "menu_board": (200, 1_500),
    # Yared's catalog (assets/catalog.json). Tables are "with chairs": table + chairs priced together.
    "espresso_bar": (8_000, 25_000),     # bar counter + commercial espresso machine + grinder
    "proofing_cabinet": (2_500, 8_000),
    "spiral_mixer": (4_000, 15_000),
    "three_comp_sink": (1_000, 3_500),   # NSF three-compartment sink, installed
    "reach_in_fridge": (3_000, 8_000),
    "table_4": (620, 1_900),             # table (300–900) + 4 chairs (80–250 each)
    "condiment_station": (500, 2_000),
    "bread_shelf": (600, 2_500),          # wooden bread shelving + baskets
    "retail_shelf": (200, 1_000),
    "table_2": (410, 1_200),             # table (250–700) + 2 chairs (80–250 each)
    "table_for_2": (410, 1_200),
    "bench_table_4": (600, 1_800),
    "bench_table_for_4": (600, 1_800),
    "table": (250, 900),
    "chair": (80, 250),
    "stool": (60, 200),
}
ITEM_COST.setdefault("plant_large", (60, 300))   # dressing pieces in shops (not on the default price)
ITEM_COST.setdefault("floor_lamp", (80, 400))
DEFAULT_ITEM_COST = (300, 1_500)
# Used when no layout yet: a starter equipment package.
EQUIPMENT_PACKAGE: dict[str, tuple[float, float]] = {
    "bakery": (35_000, 90_000), "cafe": (25_000, 70_000), "restaurant": (60_000, 150_000),
    "retail": (10_000, 40_000), "salon": (15_000, 45_000), "gym": (30_000, 120_000),
    "clinic": (40_000, 150_000), "office": (5_000, 20_000), "other": (10_000, 40_000),
}
EQUIPMENT_NOTE = "Commercial equipment price ranges (new/refurbished) from restaurant-supply list prices."

CONTINGENCY_PCT = 0.10       # permits, design, surprises
SOFT_COSTS_PCT = 0.08        # architect/engineering drawings, permits

# Revenue model per business type.
#   ticket:          average spend per transaction ($)
#   turns_per_seat:  dine-in transactions per seat per day
#   counter_tx:      takeout / counter transactions per day (not using a seat)
#   days:            open days per month
REVENUE: dict[str, dict[str, tuple[float, float] | float]] = {
    "bakery":     {"ticket": (8, 12),  "turns_per_seat": (2.0, 3.5), "counter_tx": (60, 130), "days": 26},
    "cafe":       {"ticket": (6, 10),  "turns_per_seat": (2.5, 4.0), "counter_tx": (80, 180), "days": 28},
    "restaurant": {"ticket": (18, 35), "turns_per_seat": (1.2, 2.2), "counter_tx": (10, 40),  "days": 26},
    "retail":     {"ticket": (25, 60), "turns_per_seat": (0, 0),     "counter_tx": (30, 90),  "days": 28},
    "salon":      {"ticket": (40, 80), "turns_per_seat": (0, 0),     "counter_tx": (10, 30),  "days": 25},
    "other":      {"ticket": (20, 50), "turns_per_seat": (0, 0),     "counter_tx": (20, 60),  "days": 26},
}
REVENUE_NOTE = "Small independent operator benchmarks (avg ticket, seat turns, counter traffic); a starting point, not a forecast."

# Operating costs as a share of revenue: (pessimistic, optimistic) -> pessimistic has HIGHER costs.
COGS_PCT = {"bakery": (0.34, 0.28), "cafe": (0.33, 0.27), "restaurant": (0.34, 0.28), "retail": (0.55, 0.45), "other": (0.40, 0.30)}
LABOR_PCT = {"bakery": (0.33, 0.27), "cafe": (0.33, 0.26), "restaurant": (0.35, 0.28), "retail": (0.18, 0.12), "other": (0.30, 0.22)}
OTHER_OPEX_PCT = (0.20, 0.15)   # utilities, insurance, marketing, card fees, repairs, supplies
NNN_PCT_OF_RENT = (0.25, 0.15)  # taxes, insurance, CAM on top of base rent if the listing is NNN
COST_NOTE = ("Food-service cost structure benchmarks (prime cost = COGS + labor ≈ 55–67% of sales); "
             "the midpoint of each range is used.")

DEFAULT_SQFT = 1_500

# --------------------------------------------------------------------------- #
# Offices (business_type="office"): no revenue model; cost per desk instead.
# --------------------------------------------------------------------------- #

# Build-out $/sqft by what is already there (Inspection.existing_build_out). Open plan only: we add no walls.
OFFICE_FITOUT_PSF: dict[str, tuple[float, float]] = {
    "open_plan": (10, 35),         # already open: paint, carpet, lighting tweaks, power/data drops
    "private_offices": (25, 60),   # take out or repurpose some offices to open the floor
    "shell": (60, 130),            # raw: ceilings, HVAC distribution, lighting, finishes
    "other": (35, 90),             # converting retail/restaurant space to office
    "unknown": (20, 75),           # most listed office space is second-generation
}
OFFICE_FITOUT_NOTE = ("Typical office tenant-improvement ranges ($/sqft, before furniture) from commercial "
                      "construction cost guides; open-plan second-generation space needs the least work.")

# Furniture per catalog item_type (Yared's office catalog). Unknown types use DEFAULT_ITEM_COST.
OFFICE_ITEM_COST: dict[str, tuple[float, float]] = {
    "desk_pod": (2_500, 7_000), "single_desk": (400, 1_500), "desk": (400, 1_500), "standing_desk": (500, 1_500),
    "office_chair": (200, 900), "task_chair": (200, 900), "meeting_table": (1_500, 6_000),
    "conference_table": (2_000, 8_000), "reception_desk": (2_000, 8_000), "sofa": (800, 3_000),
    "lounge_chair": (300, 1_200), "phone_booth": (4_000, 12_000), "storage": (300, 1_500),
    "storage_cabinet": (300, 1_500), "kitchenette_counter": (2_000, 8_000), "kitchenette": (2_000, 8_000),
    "whiteboard": (150, 800),
    # Dressing pieces the layout planner adds on a big floor (see agent/layout/templates.py)
    "lounge_set": (2_000, 7_000),       # sofa, two armchairs and a coffee table
    "huddle_table": (1_200, 4_000),     # small table with four chairs
    "coffee_bar": (1_500, 5_000),
    "bookshelf": (200, 900),
    "printer_station": (800, 3_500),    # cabinet and a commercial printer
    "plant_large": (60, 300),
    "planter_divider": (400, 1_500),
    "floor_lamp": (80, 400),
    "table_tennis": (500, 2_500), "fish_pond": (3_000, 15_000), "foosball_table": (300, 1_500),
    "rug_lounge": (300, 1_200), "rug_huddle": (150, 600), "rug_meeting": (300, 1_500),
}
FURNITURE_PER_DESK = (1_200, 3_500)  # no layout yet: desk + chair + share of meeting, lounge and storage
IT_PER_DESK = (300, 900)             # network cabling, Wi-Fi, share of AV
OFFICE_FURNITURE_NOTE = "Commercial office furniture price ranges (new, mid-market contract furniture)."

OFFICE_LEASE_TERM_MONTHS = 60  # typical small-office lease; fit-out is spread over it
SQFT_PER_DESK = 175            # used when no desk count is given

# Operating costs the tenant pays on top of rent, $/sqft/yr, by the listing's service type.
OFFICE_OPEX_PSF_YEAR: dict[str, tuple[float, float]] = {
    "full_service": (0, 0),     # gross: taxes, insurance, CAM and utilities included
    "modified_gross": (2, 5),   # tenant usually pays utilities/janitorial
    "net": (8, 14),             # NNN: tenant pays taxes, insurance, CAM
    "unknown": (0, 10),
}
