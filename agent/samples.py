"""Hand-made sample objects + stand-in implementations of teammates' contract functions.

Used ONLY until the real module exists (see agent/providers.py). Everything here is
fake but schema-valid, so the agent, server and UI can run end to end at M0.
Every object is tagged so nobody mistakes it for real data (citations say note="sample").
"""

from __future__ import annotations

import hashlib
import math

from shared.schemas import (
    Assumption,
    Brief,
    CatalogItem,
    Citation,
    HeroImage,
    ImageScore,
    Inspection,
    Layout,
    LayoutItem,
    NeighborhoodProfile,
    Numbers,
    Opening,
    PanoRef,
    POI,
    Room,
    Space,
    ValidationReport,
    Violation,
)

SQFT_PER_M2 = 10.7639
SAMPLE = "sample data (stand-in until the real module exists)"


def _h(s: str) -> float:
    """Deterministic 0..1 value from a string, so samples vary but never change between runs."""
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


# name, neighborhood, lat, lon, sqft, rent/month
_HOUSTON = [
    ("2410 Westheimer Rd", "Montrose", 29.7425, -95.4103, 1450, 5400),
    ("1919 Taft St", "Montrose", 29.7480, -95.3920, 1180, 4650),
    ("3301 White Oak Dr", "Heights", 29.7743, -95.3984, 1620, 5900),
    ("214 W 19th St", "Heights", 29.8030, -95.4010, 1300, 6400),
    ("1001 Texas Ave", "Downtown", 29.7604, -95.3632, 1850, 7200),
    ("2600 Travis St", "Midtown", 29.7470, -95.3790, 1500, 5650),
    ("5115 Buffalo Speedway", "Upper Kirby", 29.7300, -95.4300, 1250, 5100),
    ("4400 Washington Ave", "Washington Corridor", 29.7700, -95.4100, 1700, 6100),
    ("6501 Harrisburg Blvd", "East End", 29.7280, -95.3150, 1400, 3900),
    ("3500 Main St", "Midtown", 29.7400, -95.3830, 980, 4200),
]
_LA = [
    ("1120 W Sunset Blvd", "Echo Park", 34.0780, -118.2580, 1300, 7400),
    ("4501 York Blvd", "Highland Park", 34.1210, -118.2080, 1150, 5600),
    ("2210 E 1st St", "Boyle Heights", 34.0450, -118.2150, 1500, 4800),
]
# Office suites (property_type "Office"): size and rent are for the whole suite.
_LA_OFFICE = [
    ("633 W 5th St, Suite 1200", "Downtown", 34.0510, -118.2550, 4600, 18500),
    ("811 Wilshire Blvd, Suite 900", "Downtown", 34.0490, -118.2590, 5200, 21000),
    ("350 S Grand Ave, Suite 2100", "Bunker Hill", 34.0530, -118.2510, 3900, 17200),
    ("700 S Flower St, Suite 600", "Financial District", 34.0480, -118.2600, 4300, 16400),
    ("1200 S Figueroa St, Suite 300", "South Park", 34.0420, -118.2650, 5800, 19800),
    ("3780 Wilshire Blvd, Suite 500", "Koreatown", 34.0620, -118.3070, 4800, 14500),
]
_HOUSTON_OFFICE = [
    ("1001 Fannin St, Suite 1500", "Downtown", 29.7570, -95.3660, 4200, 9800),
    ("2700 Post Oak Blvd, Suite 800", "Uptown", 29.7420, -95.4600, 3600, 8900),
    ("3000 Weslayan St, Suite 200", "Greenway", 29.7330, -95.4350, 3100, 7200),
]


def _make_spaces() -> dict[str, Space]:
    out: dict[str, Space] = {}
    groups = (("Houston", _HOUSTON, "hou", "Retail"), ("Los Angeles", _LA, "la", "Retail"),
              ("Los Angeles", _LA_OFFICE, "la-off", "Office"), ("Houston", _HOUSTON_OFFICE, "hou-off", "Office"))
    for city, rows, prefix, ptype in groups:
        for i, (addr, hood, lat, lon, sqft, rent) in enumerate(rows, start=1):
            sid = f"sample-{prefix}-{i:02d}"
            out[sid] = Space(
                space_id=sid,
                costar_property_id=f"P{9000 + i}",
                listing_id=f"L{7000 + i}",
                matterport_model_id=f"mp_{sid}",
                address=f"{addr}, {city} ({hood})",
                city=city,  # type: ignore[arg-type]
                lat=lat,
                lon=lon,
                property_type=ptype,
                sqft=sqft,
                asking_rent_month=rent,
                rent_per_sqft_year=round(rent * 12 / sqft, 2),
                year_built=1960 + int(_h(sid) * 60),
                has_scan=True,
                citations=[
                    Citation(source="costar", dataset="commercial_listing", record_id=f"L{7000 + i}",
                             field="asking_rent", value=rent, note=SAMPLE),
                    Citation(source="costar", dataset="commercial_listing", record_id=f"L{7000 + i}",
                             field="sqft", value=sqft, note=SAMPLE),
                ],
            )
    return out


SPACES = _make_spaces()


# --------------------------------------------------------------------------- #
# Data Engine stand-ins (Natnael)
# --------------------------------------------------------------------------- #


def count_spaces() -> int:
    return 600  # pretend the full candidate set is ~600 so the funnel counter looks real


def is_office(space: Space) -> bool:
    return (space.property_type or "").lower() == "office"


def query_spaces(brief: Brief, limit: int = 200) -> list[Space]:
    want_office = brief.business_type == "office"
    out = []
    for s in SPACES.values():
        if is_office(s) != want_office:  # office -> office spaces; others -> retail/restaurant
            continue
        if brief.city and s.city != brief.city:
            continue
        if brief.max_rent_month and s.asking_rent_month and s.asking_rent_month > brief.max_rent_month * 1.15:
            continue  # keep slightly-over-budget spaces for trade-offs
        if brief.sqft_min and s.sqft and s.sqft < brief.sqft_min * 0.9:
            continue
        if brief.sqft_max and s.sqft and s.sqft > brief.sqft_max * 1.1:
            continue
        out.append(s)
    return out[:limit]


def get_space(space_id: str) -> Space:
    if space_id not in SPACES:
        raise KeyError(f"unknown space_id {space_id}")
    return SPACES[space_id]


def get_rooms(space_id: str) -> list[Room]:
    """Two rooms: a front room with the storefront on z=0, and a back-of-house room behind it."""
    s = get_space(space_id)
    area = (s.sqft or 1200) / SQFT_PER_M2
    width = round((12.0 if is_office(s) else 7.0) + _h(space_id + "w") * 3.0, 2)  # frontage width, x
    depth = round(area / width, 2)
    front_d = round(depth * 0.68, 2)
    return [
        Room(room_id=f"{space_id}-r1", space_id=space_id, label="Open office" if is_office(s) else "Front room",
             room_type="office" if is_office(s) else "retail",
             polygon_m=[(0, 0), (width, 0), (width, front_d), (0, front_d)],
             ceiling_m=round(3.0 + _h(space_id + "c") * 1.5, 2), area_m2=round(width * front_d, 2),
             openings=[Opening(kind="door", a=(width / 2 - 0.5, 0), b=(width / 2 + 0.5, 0)),
                       Opening(kind="window", a=(0.5, 0), b=(width / 2 - 1.0, 0)),
                       Opening(kind="window", a=(width / 2 + 1.0, 0), b=(width - 0.5, 0)),
                       Opening(kind="opening", a=(width - 2.0, front_d), b=(width - 1.0, front_d))]),
        Room(room_id=f"{space_id}-r2", space_id=space_id, label="Back room", room_type="storage",
             polygon_m=[(0, front_d), (width, front_d), (width, depth), (0, depth)],
             ceiling_m=3.0, area_m2=round(width * (depth - front_d), 2),
             openings=[Opening(kind="opening", a=(width - 2.0, front_d), b=(width - 1.0, front_d))]),
    ]


def get_panoramas(space_id: str) -> list[PanoRef]:
    s = get_space(space_id)
    out = []
    for scan in ("scan1", "scan2"):
        for face in ("front", "left", "right"):
            out.append(PanoRef(
                pano_id=f"{space_id}-{scan}-{face}", space_id=space_id, scan_id=scan,
                room_id=f"{space_id}-r1", face=face,  # type: ignore[arg-type]
                path=f"media/panos/{s.matterport_model_id}/{scan}_{face}.jpg",
                defurnished=True, position_m=(3.0, 1.5, 2.0 if scan == "scan1" else 5.0),
                rotation_quat=(0, 0, 0, 1), fov_deg=90, width_px=1024, height_px=1024))
    return out


def neighborhood_profile(space_id: str) -> NeighborhoodProfile:
    s = get_space(space_id)
    h = _h(space_id + "n")
    n_comp = int(_h(space_id + "comp") * 4)
    n_transit = int(_h(space_id + "tr") * 3)

    def poi(kind: str, j: int, name: str) -> POI:
        ang = _h(f"{space_id}{kind}{j}") * 2 * math.pi
        d = 80 + _h(f"{space_id}{kind}{j}d") * 600
        return POI(name=name, kind=kind, distance_m=round(d),
                   lat=s.lat + d / 111_000 * math.sin(ang), lon=s.lon + d / 96_000 * math.cos(ang),
                   citation=Citation(source="costar", dataset="location_occupancy", note=SAMPLE))

    parking = round(0.2 + _h(space_id + "p") * 0.8, 2)
    if is_office(s):  # offices: amenities instead of competitors, more transit (README: business types)
        names = ["Grab-and-go lunch spot", "Coffee bar", "Fitness club", "Salad place", "Food hall"]
        return NeighborhoodProfile(
            space_id=space_id, nearby_tenant_count=150 + int(h * 400), nearby_employees_est=5000 + int(h * 40000),
            nearby_residential_units=500 + int(_h(space_id + "res") * 5000), competitors=[],
            amenities=[poi("amenity", j, names[j]) for j in range(2 + int(_h(space_id + "am") * 4))],
            transit=[poi("transit", j, f"Metro station {j + 1}") for j in range(1 + int(_h(space_id + "tr") * 3))],
            parking_score=parking, parking_notes=f"garage parking at {80 + int(parking * 150)} USD/month (sample)",
            score=round(min(1.0, 0.4 + h * 0.55), 2),
            citations=[Citation(source="costar", dataset="location_occupancy", record_id=space_id, note=SAMPLE)])
    return NeighborhoodProfile(
        space_id=space_id,
        nearby_tenant_count=40 + int(h * 160),
        nearby_employees_est=500 + int(h * 4000),
        nearby_residential_units=200 + int(_h(space_id + "res") * 3000),
        competitors=[poi("competitor", j, f"Sample Bakery {j + 1}") for j in range(n_comp)],
        transit=[poi("transit", j, f"Metro stop {j + 1}") for j in range(n_transit)],
        parking_score=parking,
        parking_notes=f"{int(parking * 30)} surface spots on the parcel (sample)",
        score=round(min(1.0, 0.35 + h * 0.6 - n_comp * 0.04), 2),
        citations=[Citation(source="vexcel", dataset="property/extract", record_id=space_id,
                            field="parking", value=parking, note=SAMPLE)],
    )


def sample_inspection(space_id: str, business_type: str = "bakery") -> Inspection:
    """What a vision inspection might say; used only when there are no cached panorama files."""
    rooms = get_rooms(space_id)
    if is_office(get_space(space_id)) or business_type == "office":
        build = ["open plan", "private offices", "mixed offices", "shell"][int(_h(space_id + "b") * 4)]
        return Inspection(
            space_id=space_id, existing_restroom=_h(space_id + "rr") > 0.15, storefront_glass=False,
            existing_kitchen=False, natural_light=round(0.3 + _h(space_id + "nl") * 0.7, 2),
            existing_build_out=build, ceiling_height_m=rooms[0].ceiling_m,
            notes=["Sample inspection: no cached panoramas yet."], confidence=0.3,
            unverified_fields=["natural_light"],
            citations=[Citation(source="matterport", dataset="rooms", record_id=rooms[0].room_id,
                                field="ceiling_m", value=rooms[0].ceiling_m, note=SAMPLE)])
    return Inspection(
        space_id=space_id,
        storefront_glass=_h(space_id + "g") > 0.25,
        existing_kitchen=_h(space_id + "k") > 0.6,
        existing_restroom=_h(space_id + "rr") > 0.3,
        vent_hood=_h(space_id + "v") > 0.7,
        ceiling_height_m=rooms[0].ceiling_m,
        notes=["Sample inspection: no cached panoramas yet."],
        confidence=0.3,
        unverified_fields=["existing_kitchen", "vent_hood"],
        citations=[Citation(source="matterport", dataset="rooms", record_id=rooms[0].room_id,
                            field="ceiling_m", value=rooms[0].ceiling_m, note=SAMPLE)],
    )


def estimate_costs(space: Space, layout: Layout | None, inspection: Inspection | None, brief: Brief) -> Numbers:
    if brief.business_type == "office":
        return _office_costs(space, layout, inspection, brief)
    sqft = space.sqft or 1200
    lo, hi = (45, 95) if inspection and inspection.existing_kitchen else (80, 160)
    seats = layout.seat_count if layout else (brief.seats_wanted or 20)
    turns, ticket, days = 3.0, 14.0, 26
    takeaway = 90  # bakery counter sales per day not tied to seats
    rev_lo = (seats * turns * 0.7 + takeaway * 0.7) * ticket * days
    rev_hi = (seats * turns * 1.2 + takeaway * 1.2) * ticket * days
    rent = space.asking_rent_month or 0
    margin = 0.18  # contribution margin after cost of goods and labor
    be_lo = (sqft * lo) / max(1.0, rev_hi * margin) if rev_hi else None
    be_hi = (sqft * hi) / max(1.0, rev_lo * margin - 0) if rev_lo else None
    return Numbers(
        space_id=space.space_id, rent_month=rent or None,
        fitout_cost_low=round(sqft * lo), fitout_cost_high=round(sqft * hi),
        revenue_month_low=round(rev_lo), revenue_month_high=round(rev_hi),
        breakeven_months_low=round(be_lo, 1) if be_lo else None,
        breakeven_months_high=round(be_hi, 1) if be_hi else None,
        assumptions=[
            Assumption(name="fit-out cost", value=f"{lo}-{hi}", unit="USD/sqft", note=SAMPLE),
            Assumption(name="table turns per day", value=turns),
            Assumption(name="average ticket", value=ticket, unit="USD"),
            Assumption(name="open days per month", value=days),
            Assumption(name="contribution margin", value=margin),
        ],
        citations=space.citations[:1],
    )


LEASE_MONTHS = 60


def _office_costs(space: Space, layout: Layout | None, inspection: Inspection | None, brief: Brief) -> Numbers:
    """Offices: no revenue/break-even; the headline is cost per desk per month (rent + fit-out over the lease)."""
    sqft = space.sqft or 4000
    build = inspection.existing_build_out if inspection else None
    lo, hi = (15, 35) if build == "open plan" else (25, 55) if build in ("private offices", "mixed offices") else (45, 90)
    desks = (layout.seat_count if layout else 0) or brief.seats_wanted or 20
    rent = space.asking_rent_month or 0
    per_lo = (rent + sqft * lo / LEASE_MONTHS) / desks
    per_hi = (rent + sqft * hi / LEASE_MONTHS) / desks
    return Numbers(
        space_id=space.space_id, rent_month=rent or None,
        fitout_cost_low=round(sqft * lo), fitout_cost_high=round(sqft * hi),
        revenue_month_low=0, revenue_month_high=0, breakeven_months_low=None, breakeven_months_high=None,
        cost_per_seat_month_low=round(per_lo), cost_per_seat_month_high=round(per_hi),
        assumptions=[
            Assumption(name="office fit-out cost", value=f"{lo}-{hi}", unit="USD/sqft",
                       note=f"existing build-out: {build or 'unknown'} ({SAMPLE})"),
            Assumption(name="lease length (fit-out spread over)", value=LEASE_MONTHS, unit="months"),
            Assumption(name="desks", value=desks, note="from the layout" if layout else "from the brief"),
        ],
        citations=space.citations[:1],
    )


def draft_broker_email(space: Space, brief: Brief) -> str:
    if brief.business_type == "office":
        return (f"Subject: Tour request: {space.address}\n\nHi,\n\nWe're looking for an office for a team of "
                f"{brief.seats_wanted or 'about 20'} and your suite at {space.address} looks like a good fit. Could we "
                f"tour it this week? We'd also like to confirm the asking rent, lease term and any existing furniture.\n\nThanks!")
    return (
        f"Subject: Tour request: {space.address}\n\n"
        f"Hi,\n\nI'm looking for a space for a {brief.business_type}"
        f"{f' with about {brief.seats_wanted} seats' if brief.seats_wanted else ''} and your listing at "
        f"{space.address} looks like a good fit. Could we schedule a visit this week? "
        f"I'd also like to confirm the asking rent and whether the space has existing plumbing and venting.\n\nThanks!"
    )


# --------------------------------------------------------------------------- #
# Reimaginer stand-ins (Yared)
# --------------------------------------------------------------------------- #

CATALOG: list[CatalogItem] = [
    CatalogItem(item_type="display_case", label="Pastry display case", glb_asset="assets/glb/display_case.glb",
                width_m=1.8, depth_m=0.9, height_m=1.3, clearance_front_m=1.0, zone="service", business_types=["bakery", "cafe"]),
    CatalogItem(item_type="service_counter", label="Service counter", glb_asset="assets/glb/service_counter.glb",
                width_m=2.4, depth_m=0.8, height_m=1.05, clearance_front_m=1.0, zone="service", business_types=["bakery", "cafe"]),
    CatalogItem(item_type="deck_oven", label="Deck oven", glb_asset="assets/glb/deck_oven.glb",
                width_m=1.6, depth_m=1.1, height_m=1.8, clearance_front_m=1.2, zone="back_of_house", business_types=["bakery"]),
    CatalogItem(item_type="prep_table", label="Prep table", glb_asset="assets/glb/prep_table.glb",
                width_m=1.8, depth_m=0.75, height_m=0.9, clearance_front_m=0.9, zone="back_of_house", business_types=["bakery", "cafe"]),
    CatalogItem(item_type="table_2", label="Table for 2", glb_asset="assets/glb/table_2.glb",
                width_m=0.7, depth_m=0.7, height_m=0.75, clearance_front_m=0.6, seats=2, zone="seating", business_types=["bakery", "cafe"]),
    CatalogItem(item_type="bench_table_4", label="Bench table for 4", glb_asset="assets/glb/bench_table_4.glb",
                width_m=1.4, depth_m=0.8, height_m=0.75, clearance_front_m=0.6, seats=4, zone="seating", business_types=["bakery", "cafe"]),
    # Office
    CatalogItem(item_type="reception_desk", label="Reception desk", glb_asset="assets/glb/reception_desk.glb",
                width_m=2.0, depth_m=0.8, height_m=1.05, clearance_front_m=1.2, zone="entrance", business_types=["office"]),
    CatalogItem(item_type="desk_pod_4", label="Desk pod (4 desks)", glb_asset="assets/glb/desk_pod_4.glb",
                width_m=2.8, depth_m=1.6, height_m=0.75, clearance_front_m=1.0, seats=4, zone="seating", business_types=["office"]),
    CatalogItem(item_type="single_desk", label="Single desk", glb_asset="assets/glb/single_desk.glb",
                width_m=1.4, depth_m=0.7, height_m=0.75, clearance_front_m=1.0, seats=1, zone="seating", business_types=["office"]),
    CatalogItem(item_type="meeting_table", label="Meeting table (8)", glb_asset="assets/glb/meeting_table.glb",
                width_m=3.0, depth_m=1.2, height_m=0.75, clearance_front_m=1.0, zone="front_of_house", business_types=["office"]),
    CatalogItem(item_type="kitchenette_counter", label="Kitchenette counter", glb_asset="assets/glb/kitchenette_counter.glb",
                width_m=2.4, depth_m=0.65, height_m=0.95, clearance_front_m=1.0, zone="back_of_house", business_types=["office"]),
    CatalogItem(item_type="storage", label="Storage cabinets", glb_asset="assets/glb/storage.glb",
                width_m=1.8, depth_m=0.5, height_m=2.0, clearance_front_m=0.9, zone="back_of_house", business_types=["office"]),
]
_CAT = {c.item_type: c for c in CATALOG}


def plan_layout(space_id: str, rooms: list[Room], inspection: Inspection | None, brief: Brief,
                strategy: str | None = None) -> Layout:
    """Very simple rule layout in axis-aligned rectangular rooms (stand-in for Yared's planner)."""
    if brief.business_type == "office":
        return _plan_office(space_id, rooms, brief, strategy)
    front, back = rooms[0], rooms[-1]
    xs, zs = [p[0] for p in front.polygon_m], [p[1] for p in front.polygon_m]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    items: list[LayoutItem] = []

    def put(kind: str, room: Room, x: float, z: float, rot: float = 0.0) -> None:
        c = _CAT[kind]
        items.append(LayoutItem(item_id=f"{kind}-{len(items) + 1}", item_type=kind, glb_asset=c.glb_asset,
                                room_id=room.room_id, x_m=round(x, 2), z_m=round(z, 2), rotation_deg=rot,
                                width_m=c.width_m, depth_m=c.depth_m, height_m=c.height_m, zone=c.zone, seats=c.seats))

    # Service line across the back of the front room, facing the door (+z is into the store, so face -z).
    put("service_counter", front, x0 + 0.6 + 1.2, z1 - 0.6, 180)
    put("display_case", front, x0 + 0.6 + 2.4 + 0.3 + 0.9, z1 - 0.6, 180)
    # Back of house.
    bxs, bzs = [p[0] for p in back.polygon_m], [p[1] for p in back.polygon_m]
    put("deck_oven", back, min(bxs) + 1.0, max(bzs) - 0.7, 180)
    put("prep_table", back, min(bxs) + 3.2, max(bzs) - 0.5, 180)

    # Seating grid in the front zone, keeping the entrance clear and a 1 m aisle at the door.
    want = brief.seats_wanted or 20
    if strategy == "fewer_tables":
        want = max(2, int(want * 0.75))
    seats = 0
    door_x = (x0 + x1) / 2
    z = z0 + 1.6
    while z + 0.8 < z1 - 2.2 and seats < want:
        x = x0 + 0.8
        while x + 0.8 < x1 - 0.4 and seats < want:
            if abs(x - door_x) > 1.3:
                kind = "bench_table_4" if want - seats >= 4 and x + 1.4 < x1 - 0.4 else "table_2"
                put(kind, front, x + _CAT[kind].width_m / 2, z)
                seats += _CAT[kind].seats
                x += _CAT[kind].width_m + 1.0
            else:
                x += 0.5
        z += 1.9
    lid = f"layout-{space_id}-{brief.seats_wanted or 0}-{strategy or 'default'}"
    return Layout(layout_id=lid, space_id=space_id, business_type=brief.business_type,
                  entrance_xz=(door_x, z0), items=items, seat_count=seats,
                  strategy=strategy or "rule_template", notes=["Sample layout from the stand-in planner."])


def _plan_office(space_id: str, rooms: list[Room], brief: Brief, strategy: str | None) -> Layout:
    """Reception by the door, meeting table, desk pods in the open area, kitchenette + storage at the back."""
    front, back = rooms[0], rooms[-1]
    xs, zs = [p[0] for p in front.polygon_m], [p[1] for p in front.polygon_m]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    items: list[LayoutItem] = []

    def put(kind: str, room: Room, x: float, z: float, rot: float = 0.0) -> None:
        c = _CAT[kind]
        items.append(LayoutItem(item_id=f"{kind}-{len(items) + 1}", item_type=kind, glb_asset=c.glb_asset,
                                room_id=room.room_id, x_m=round(x, 2), z_m=round(z, 2), rotation_deg=rot,
                                width_m=c.width_m, depth_m=c.depth_m, height_m=c.height_m, zone=c.zone, seats=c.seats))

    door_x = (x0 + x1) / 2
    put("reception_desk", front, x0 + 0.6 + 1.0, z0 + 2.2)
    put("meeting_table", front, x1 - 0.8 - 1.5, z0 + 1.8)
    bxs, bzs = [p[0] for p in back.polygon_m], [p[1] for p in back.polygon_m]
    put("kitchenette_counter", back, min(bxs) + 0.5 + 1.2, max(bzs) - 0.45, 180)
    put("storage", back, min(bxs) + 3.4 + 0.9, max(bzs) - 0.35, 180)

    want = brief.seats_wanted or 20
    if strategy == "fewer_tables":
        want = max(1, int(want * 0.8))
    desks = 0
    z = z0 + 4.2
    while z + 0.8 < z1 - 0.6 and desks < want:
        x = x0 + 0.8
        while x + 2.8 < x1 - 0.6 and desks < want:
            kind = "desk_pod_4" if want - desks >= 3 else "single_desk"
            put(kind, front, x + _CAT[kind].width_m / 2, z)
            desks += _CAT[kind].seats
            x += _CAT[kind].width_m + 1.1
        z += 1.6 + 1.2
    lid = f"layout-{space_id}-{brief.seats_wanted or 0}-{strategy or 'default'}"
    return Layout(layout_id=lid, space_id=space_id, business_type="office", entrance_xz=(door_x, z0), items=items,
                  seat_count=desks, strategy=strategy or "rule_template",
                  notes=["Sample office layout from the stand-in planner (open plan, no new walls)."])


def validate_layout(layout: Layout, rooms: list[Room]) -> ValidationReport:
    violations: list[Violation] = []
    rooms_by_id = {r.room_id: r for r in rooms}
    boxes = []
    for it in layout.items:
        w, d = (it.depth_m, it.width_m) if int(it.rotation_deg) % 180 == 90 else (it.width_m, it.depth_m)
        b = (it.x_m - w / 2, it.z_m - d / 2, it.x_m + w / 2, it.z_m + d / 2)
        boxes.append((it, b))
        r = rooms_by_id.get(it.room_id)
        if r:
            xs, zs = [p[0] for p in r.polygon_m], [p[1] for p in r.polygon_m]
            if b[0] < min(xs) - 1e-6 or b[2] > max(xs) + 1e-6 or b[1] < min(zs) - 1e-6 or b[3] > max(zs) + 1e-6:
                violations.append(Violation(kind="out_of_bounds", item_ids=[it.item_id], message=f"{it.item_id} leaves {r.room_id}"))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i][1], boxes[j][1]
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                violations.append(Violation(kind="overlap", item_ids=[boxes[i][0].item_id, boxes[j][0].item_id],
                                            message="items overlap"))
    return ValidationReport(layout_id=layout.layout_id, passed=not violations, violations=violations,
                            min_aisle_m=1.0, seat_count=layout.seat_count)


def render_hero(space_id: str, layout: Layout, style: str | None = None) -> HeroImage:
    pano = get_panoramas(space_id)[0]
    return HeroImage(
        hero_id=f"hero-{layout.layout_id}", space_id=space_id, layout_id=layout.layout_id,
        path=f"media/heroes/hero-{layout.layout_id}.png", source_pano_id=pano.pano_id,
        guide_path=f"media/guides/{layout.layout_id}.png", model="sample",
        prompt=(f"photorealistic modern open-plan office, {style or 'bright, light wood, plants'}"
                if layout.business_type == "office" else f"photorealistic artisan bakery, {style or 'warm artisan'}"),
        score=ImageScore(structure_preserved=0.9, plan_adherence=0.8, realism_1to5=4.0, passed=True,
                         notes=["sample score: no image was generated"]),
    )
