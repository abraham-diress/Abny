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
