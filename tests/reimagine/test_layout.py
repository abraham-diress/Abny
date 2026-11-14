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
