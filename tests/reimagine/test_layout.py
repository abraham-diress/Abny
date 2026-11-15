from __future__ import annotations

import pytest

from agent.layout.catalog import load_catalog
from agent.layout.geometry import facing_rotation, footprint, front_vector, item_footprint
from agent.layout.planner import STRATEGIES, plan_layout
from agent.layout.validator import validate_layout
from shared.schemas import Brief


def test_rotation_convention_matches_conventions_file():
    # rotation 0 faces +z; 90 faces +x
    assert front_vector(0) == pytest.approx((0, 1))
    assert front_vector(90) == pytest.approx((1, 0), abs=1e-9)
    assert facing_rotation(1, 0) == pytest.approx(90)
    fp = footprint(0, 0, 2.0, 1.0, 90)  # width now along z
    minx, minz, maxx, maxz = fp.bounds
    assert maxx - minx == pytest.approx(1.0) and maxz - minz == pytest.approx(2.0)


@pytest.mark.parametrize("rooms_fixture", ["single_room", "front_and_kitchen", "rotated_l"])
def test_plans_are_valid_and_seat_the_request(rooms_fixture, bakery_brief, request):
    rooms = request.getfixturevalue(rooms_fixture)
    layout = plan_layout(rooms[0].space_id, rooms, None, bakery_brief)
    report = validate_layout(layout, rooms)
    assert report.passed, [v.message for v in report.violations]
    assert layout.seat_count == bakery_brief.seats_wanted
    assert report.min_aisle_m is not None and report.min_aisle_m >= 0.9
    types = {i.item_type for i in layout.items}
    assert {"display_case", "service_counter", "deck_oven", "prep_table", "three_comp_sink"} <= types
    assert sum(i.item_type == "deck_oven" for i in layout.items) == 2  # "two ovens" in the brief


def test_every_strategy_is_valid(single_room, bakery_brief):
    for strategy in STRATEGIES:
        layout = plan_layout("S1", single_room, None, bakery_brief, strategy=strategy)
        assert layout.strategy == strategy
        assert validate_layout(layout, single_room).passed


def test_layout_items_match_catalog(single_room, bakery_brief):
    cat = load_catalog()
    layout = plan_layout("S1", single_room, None, bakery_brief)
    for it in layout.items:
        c = cat[it.item_type]
        assert (it.width_m, it.depth_m, it.glb_asset, it.seats) == (c.width_m, c.depth_m, c.glb_asset, c.seats)


def test_deterministic(single_room, bakery_brief):
    a = plan_layout("S1", single_room, None, bakery_brief)
    b = plan_layout("S1", single_room, None, bakery_brief)
    assert a.model_dump() == b.model_dump()


def test_small_room_reports_shortfall():
    from shared.schemas import Opening, Room

    rooms = [Room(room_id="S", space_id="X", polygon_m=[(0, 0), (5, 0), (5, 6), (0, 6)], area_m2=30, openings=[Opening(kind="door", a=(2, 0), b=(3, 0))])]
    layout = plan_layout("X", rooms, None, Brief(business_type="cafe", seats_wanted=30))
    assert validate_layout(layout, rooms).passed
    assert layout.seat_count < 30
    assert any("seats requested" in n for n in layout.notes)


def test_unknown_business_falls_back_to_bakery(single_room):
    layout = plan_layout("S1", single_room, None, Brief(business_type="gym", seats_wanted=8))
    assert any("No template" in n for n in layout.notes)
    assert validate_layout(layout, single_room).passed


# --- validator catches broken layouts ---------------------------------------


def _base(single_room, bakery_brief):
    return plan_layout("S1", single_room, None, bakery_brief)


def test_validator_flags_overlap(single_room, bakery_brief):
    lay = _base(single_room, bakery_brief)
    a, b = lay.items[0], lay.items[1]
    lay.items[1] = b.model_copy(update={"x_m": a.x_m, "z_m": a.z_m})
    kinds = {v.kind for v in validate_layout(lay, single_room).violations}
    assert "overlap" in kinds


def test_validator_flags_out_of_bounds(single_room, bakery_brief):
    lay = _base(single_room, bakery_brief)
    lay.items[0] = lay.items[0].model_copy(update={"x_m": -3.0})
    assert "out_of_bounds" in {v.kind for v in validate_layout(lay, single_room).violations}


def test_validator_flags_blocked_entrance(single_room, bakery_brief):
    lay = _base(single_room, bakery_brief)
    seat = next(i for i in lay.items if i.seats)
    lay.items = [i for i in lay.items if i.item_id != seat.item_id] + [seat.model_copy(update={"x_m": 4.5, "z_m": 0.6})]
    assert "entrance_blocked" in {v.kind for v in validate_layout(lay, single_room).violations}


def test_validator_flags_unreachable_seat(single_room, bakery_brief):
    lay = _base(single_room, bakery_brief)
    seat = next(i for i in lay.items if i.item_type == "table_2" or i.seats)
    # Box the seat into the back-left corner behind a wall of prep tables.
    fp = item_footprint(seat)
    walled = seat.model_copy(update={"x_m": 0.9, "z_m": 6.0, "rotation_deg": 0.0})
    blockers = [
        lay.items[0].model_copy(update={"item_id": f"blk{k}", "item_type": "prep_table", "zone": "back_of_house", "seats": 0,
                                        "x_m": x, "z_m": z, "width_m": w, "depth_m": d, "rotation_deg": 0.0})
        for k, (x, z, w, d) in enumerate([(0.9, 4.6, 1.8, 0.4), (2.0, 6.0, 0.4, 3.2), (0.9, 7.4, 1.8, 0.4)])
    ]
    lay.items = [i for i in lay.items if i.item_id != seat.item_id] + [walled] + blockers
    lay.seat_count = sum(i.seats for i in lay.items)
    assert fp is not None
    report = validate_layout(lay, single_room)
    assert any(v.kind == "unreachable" and walled.item_id in v.item_ids for v in report.violations)


def test_validator_flags_wrong_seat_count(single_room, bakery_brief):
    lay = _base(single_room, bakery_brief)
    lay.seat_count += 3
    assert "other" in {v.kind for v in validate_layout(lay, single_room).violations}


def test_overlapping_rooms_are_flagged(bakery_brief):
    from agent.layout.planner import rooms_overlap
    from shared.schemas import Room

    stacked = [
        Room(room_id="F", space_id="X", polygon_m=[(0, 0), (8, 0), (8, 7), (0, 7)], area_m2=56),
        Room(room_id="K", space_id="X", polygon_m=[(0, 0), (8, 0), (8, 4), (0, 4)], area_m2=32),
    ]
    assert rooms_overlap(stacked) == ("F", "K")
    layout = plan_layout("X", stacked, None, bakery_brief)
    assert layout.notes[0].startswith("WARNING: rooms F and K overlap")


def test_touching_rooms_are_not_flagged(front_and_kitchen):
    from agent.layout.planner import rooms_overlap

    assert rooms_overlap(front_and_kitchen) is None


# --- offices -------------------------------------------------------------------


@pytest.fixture
def office_rooms():
    from shared.schemas import Opening, Room

    return [
        Room(room_id="open", space_id="O", label="Open office", polygon_m=[(0, 0), (14, 0), (14, 10), (0, 10)], area_m2=140,
             openings=[Opening(kind="door", a=(0.5, 0), b=(1.5, 0)), Opening(kind="window", a=(14, 0.5), b=(14, 9.5))]),
        Room(room_id="conf", space_id="O", label="Conference room", polygon_m=[(0, 10), (8, 10), (8, 15), (0, 15)], area_m2=40,
             openings=[Opening(kind="door", a=(1, 10), b=(2, 10))]),
        Room(room_id="kit", space_id="O", label="Kitchenette", polygon_m=[(8, 10), (14, 10), (14, 15), (8, 15)], area_m2=30,
             openings=[Opening(kind="opening", a=(10, 10), b=(11, 10))]),
    ]


def test_office_layout(office_rooms):
    brief = Brief(business_type="office", seats_wanted=25)
    lay = plan_layout("O", office_rooms, None, brief)
    rep = validate_layout(lay, office_rooms)
    assert rep.passed, [v.message for v in rep.violations]
    assert lay.business_type == "office" and lay.strategy == "open-plan"
    assert lay.seat_count >= 25  # desks
    by_type = {}
    for it in lay.items:
        by_type.setdefault(it.item_type, []).append(it)
    assert not {"deck_oven", "display_case", "table_2"} & set(by_type)  # no bakery items in an office
    assert by_type["meeting_table"][0].room_id == "conf"
    assert by_type["kitchenette_counter"][0].room_id == "kit"
    rec = by_type["reception_desk"][0]
    assert ((rec.x_m - 1.0) ** 2 + rec.z_m ** 2) ** 0.5 < 4.0  # by the front door
    assert all(i.seats == 0 for t in ("meeting_table", "sofa", "reception_desk") for i in by_type.get(t, []))


def test_small_office_keeps_desks_over_meeting_table():
    from shared.schemas import Opening, Room

    rooms = [Room(room_id="R", space_id="S", polygon_m=[(0, 0), (9, 0), (9, 7), (0, 7)], area_m2=63,
                  openings=[Opening(kind="door", a=(4, 0), b=(5, 0))])]
    lay = plan_layout("S", rooms, None, Brief(business_type="office", seats_wanted=10))
    assert validate_layout(lay, rooms).passed
    assert lay.seat_count >= 8
    assert any("desks" in n for n in lay.notes) or "meeting_table" in {i.item_type for i in lay.items}


def test_unknown_strategy_tries_the_templates_own(single_room, bakery_brief):
    lay = plan_layout("S1", single_room, None, bakery_brief, strategy="compact")
    assert lay.strategy in STRATEGIES and any("doesn't apply" in n for n in lay.notes)
    assert validate_layout(lay, single_room).passed


# --- dressing: a big floor must not look bare ------------------------------------


@pytest.fixture
def big_office_rooms():
    """24 x 18 m open floor (432 m2) with a door and a window wall: far more room than 25 desks need."""
    from shared.schemas import Opening, Room

    return [Room(room_id="big", space_id="B", label="Open office", polygon_m=[(0, 0), (24, 0), (24, 18), (0, 18)], area_m2=432,
                 openings=[Opening(kind="door", a=(11, 0), b=(12, 0)), Opening(kind="window", a=(24, 2), b=(24, 16))])]


def test_big_office_floor_is_dressed(big_office_rooms):
    from eval.layout_fill import empty_share

    lay = plan_layout("B", big_office_rooms, None, Brief(business_type="office", seats_wanted=25))
    assert validate_layout(lay, big_office_rooms).passed
    types = {i.item_type for i in lay.items}
    assert {"lounge_set", "huddle_table", "coffee_bar", "bookshelf", "plant_large"} <= types
    floor_m2, furniture_m2, empty = empty_share(lay, big_office_rooms)
    assert empty < 0.15, f"{empty:.0%} of the floor is still empty"
    assert 0.15 < furniture_m2 / floor_m2 < 0.40
    assert any(n.startswith("Dressed the floor") for n in lay.notes)


def test_dressing_never_costs_a_desk(big_office_rooms, monkeypatch):
    from dataclasses import replace

    from agent.layout import templates

    brief = Brief(business_type="office", seats_wanted=25)
    dressed = plan_layout("B", big_office_rooms, None, brief)
    monkeypatch.setitem(templates.TEMPLATES, "office", replace(templates.OFFICE, dress_program=(), dress_fill_large=(), dress_fill_small=()))
    bare = plan_layout("B", big_office_rooms, None, brief)
    assert dressed.seat_count == bare.seat_count
    # the same desks, in the same places: dressing only adds zero-seat pieces around them
    desks = lambda lay: sorted((i.item_type, i.x_m, i.z_m) for i in lay.items if i.seats > 0)
    assert desks(dressed) == desks(bare)
    assert all(i.seats == 0 for i in dressed.items if i.item_type in {"lounge_set", "huddle_table", "plant_large", "coffee_bar"})


def test_dressing_is_deterministic(big_office_rooms):
    brief = Brief(business_type="office", seats_wanted=25)
    assert plan_layout("B", big_office_rooms, None, brief).model_dump() == plan_layout("B", big_office_rooms, None, brief).model_dump()


def test_full_small_floor_is_not_overstuffed(office_rooms):
    """A floor already near the fill cap gets no extra pieces."""
    from eval.layout_fill import empty_share

    lay = plan_layout("O", office_rooms, None, Brief(business_type="office", seats_wanted=25))
    floor_m2, furniture_m2, _ = empty_share(lay, office_rooms)
    assert furniture_m2 / floor_m2 < 0.45


def test_rugs_lie_under_the_pieces_and_never_block(big_office_rooms):
    from agent.layout.geometry import is_flat, item_footprint

    lay = plan_layout("B", big_office_rooms, None, Brief(business_type="office", seats_wanted=25))
    rugs = [i for i in lay.items if is_flat(i)]
    assert {r.item_type for r in rugs} >= {"rug_lounge", "rug_huddle"}
    assert validate_layout(lay, big_office_rooms).passed  # a rug under a sofa is not an overlap
    for rug in rugs:  # each rug sits under something
        assert any(item_footprint(rug).intersects(item_footprint(i)) for i in lay.items if not is_flat(i))
    assert sum(i.seats for i in lay.items) == lay.seat_count


def test_desks_spread_over_a_roomy_floor(big_office_rooms):
    """25 desks in 432 m2 must not huddle at the door: the desks span a good part of the floor."""
    from shapely.geometry import MultiPoint

    lay = plan_layout("B", big_office_rooms, None, Brief(business_type="office", seats_wanted=25))
    desks = [(i.x_m, i.z_m) for i in lay.items if i.seats > 0]
    assert len(desks) >= 9  # pods + singles
    hull = MultiPoint(desks).convex_hull
    assert hull.area > 0.25 * 24 * 18, f"desks only cover {hull.area:.0f} m2 of the floor"


def test_a_small_floor_keeps_its_desks_tight():
    from shared.schemas import Opening, Room

    rooms = [Room(room_id="R", space_id="S", polygon_m=[(0, 0), (9, 0), (9, 7), (0, 7)], area_m2=63,
                  openings=[Opening(kind="door", a=(4, 0), b=(5, 0))])]
    lay = plan_layout("S", rooms, None, Brief(business_type="office", seats_wanted=10))
    assert validate_layout(lay, rooms).passed and lay.seat_count >= 8  # spreading never costs seats


# --- the room decides the extras, the brief decides the desks --------------------


def test_room_size_sets_the_counts_of_room_pieces():
    from agent.layout.templates import OFFICE, desk_capacity, scale_to_room

    small, big = scale_to_room(OFFICE, 140), scale_to_room(OFFICE, 460)
    assert len(small.anchor_items) == 1 and len(big.anchor_items) == 3  # meeting tables
    assert big.foh_extras.count("phone_booth") > small.foh_extras.count("phone_booth")
    assert len(big.boh_optional) > len(small.boh_optional) and len(big.boh_required) >= len(small.boh_required)
    assert desk_capacity(460) > desk_capacity(140) > 0
    assert scale_to_room(OFFICE, 140).business_type == "office" and scale_to_room(__import__("agent.layout.templates", fromlist=["BAKERY"]).BAKERY, 460).anchor_items == ()


def test_recreation_only_when_the_floor_can_spare_it(big_office_rooms, office_rooms):
    big = {i.item_type for i in plan_layout("B", big_office_rooms, None, Brief(business_type="office", seats_wanted=25)).items}
    assert {"foosball_table", "table_tennis"} <= big  # 432 m2
    small = {i.item_type for i in plan_layout("O", office_rooms, None, Brief(business_type="office", seats_wanted=25)).items}
    assert not {"table_tennis", "fish_pond"} & small  # 210 m2


def test_big_floor_gets_more_room_pieces_than_a_small_one_for_the_same_desks(big_office_rooms, office_rooms):
    brief = Brief(business_type="office", seats_wanted=25)
    count = lambda lay, t: sum(i.item_type == t for i in lay.items)
    big = plan_layout("B", big_office_rooms, None, brief)
    small = plan_layout("O", office_rooms, None, brief)
    assert count(big, "phone_booth") > count(small, "phone_booth")
    assert count(big, "meeting_table") >= count(small, "meeting_table")


def test_plan_says_how_many_desks_the_floor_could_take(big_office_rooms):
    lay = plan_layout("B", big_office_rooms, None, Brief(business_type="office", seats_wanted=25))
    assert any(n.startswith("Room to grow") and 45 <= int(n.split("about ")[1].split(" desks")[0]) <= 48 for n in lay.notes), lay.notes


def test_a_full_floor_gets_no_extras(big_office_rooms):
    """Ask for as many desks as the floor holds and the desks take it; no amenities squeeze in."""
    lay = plan_layout("B", big_office_rooms, None, Brief(business_type="office", seats_wanted=100))
    assert validate_layout(lay, big_office_rooms).passed
    assert lay.seat_count >= 80
    assert not {i.item_type for i in lay.items} & {"table_tennis", "fish_pond", "foosball_table"}
    assert not any(n.startswith("Room to grow") for n in lay.notes)
