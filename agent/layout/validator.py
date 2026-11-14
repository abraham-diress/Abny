"""validate_layout: geometry checks every layout must pass before anyone sees it.

Checks
------
* out_of_bounds    every item footprint lies inside the rooms
* overlap          no two footprints overlap (touching is fine: counters sit side by side)
* entrance_blocked nothing in the clear area just inside the entrance
* unreachable      customers can walk from the entrance to every seat, service and
                   front-of-house item along a route at least MIN_AISLE_M wide;
                   staff can reach every back-of-house item from the service area
* other            seat_count matches the items

min_aisle_m reports the widest route width (0.05 m steps) at which every customer-facing
item is still reachable: a single number for "how roomy is this layout".
"""

from __future__ import annotations

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from agent.layout.geometry import Frame, inward_normal, item_footprint, nearest_edge, rooms_union, unit
from shared.conventions import DOOR_CLEARANCE_M, MIN_AISLE_M
from shared.schemas import Layout, LayoutItem, Room, ValidationReport, Violation

OVERLAP_TOLERANCE_M2 = 0.0025  # 5 cm x 5 cm
REACH_ALLOWANCE_M = 0.3  # how far a person can reach/step from the route to use an item
DEFAULT_DOOR_WIDTH_M = 0.9
CUSTOMER_ZONES = {"seating", "front_of_house", "service"}


def validate_layout(layout: Layout, rooms: list[Room]) -> ValidationReport:
    floor = rooms_union(rooms)
    fps = {it.item_id: item_footprint(it) for it in layout.items}
    violations: list[Violation] = []

    # --- bounds --------------------------------------------------------------
    inside = floor.buffer(0.02)
    for it in layout.items:
        if not inside.contains(fps[it.item_id]):
            violations.append(Violation(kind="out_of_bounds", item_ids=[it.item_id], message=f"{it.item_type} sticks out of the rooms"))

    # --- overlaps ------------------------------------------------------------
    items = layout.items
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = fps[items[i].item_id], fps[items[j].item_id]
            if a.intersects(b) and a.intersection(b).area > OVERLAP_TOLERANCE_M2:
                violations.append(
                    Violation(
                        kind="overlap",
                        item_ids=[items[i].item_id, items[j].item_id],
                        message=f"{items[i].item_type} overlaps {items[j].item_type}",
                    )
                )

    # --- entrance ------------------------------------------------------------
    entrance_zone = _entrance_zone(layout, rooms, floor)
    if entrance_zone is not None:
        for it in items:
            if fps[it.item_id].intersection(entrance_zone).area > 0.01:
                violations.append(
                    Violation(kind="entrance_blocked", item_ids=[it.item_id], message=f"{it.item_type} blocks the entrance clear area")
                )

    # --- seat count ------------------------------------------------------------
    seats = sum(it.seats for it in items)
    if seats != layout.seat_count:
        violations.append(Violation(kind="other", message=f"seat_count says {layout.seat_count} but items seat {seats}"))

    # --- reachability ------------------------------------------------------------
    unreachable = unreachable_items(layout, rooms, MIN_AISLE_M, floor=floor, fps=fps)
    for it in unreachable:
        violations.append(
            Violation(
                kind="unreachable",
                item_ids=[it.item_id],
                message=f"{it.item_type} can't be reached by a {MIN_AISLE_M:.2f} m wide route",
            )
        )

    return ValidationReport(
        layout_id=layout.layout_id,
        passed=not violations,
        violations=violations,
        min_aisle_m=_widest_route(layout, rooms, floor, fps),
        seat_count=seats,
    )


# --------------------------------------------------------------------------- #
# Reachability
# --------------------------------------------------------------------------- #


def unreachable_items(
    layout: Layout,
    rooms: list[Room],
    aisle: float,
    floor: Polygon | None = None,
    fps: dict[str, Polygon] | None = None,
) -> list[LayoutItem]:
    """Items a person (route width `aisle`) can't get to. Customers start at the entrance;
    staff start anywhere next to the service line."""
    floor = floor if floor is not None else rooms_union(rooms)
    fps = fps if fps is not None else {it.item_id: item_footprint(it) for it in layout.items}
    if not layout.items:
        return []

    half = aisle / 2.0
    obstacles = unary_union(list(fps.values()))
    walk = floor.buffer(-half).difference(obstacles.buffer(half))
    parts = _parts(walk)
    if not parts:
        return list(layout.items)

    start = _entrance_point(layout, rooms, floor, half)
    entrance_part = None
    if start is not None:
        near = [(p.distance(start), p) for p in parts]
        d, p = min(near, key=lambda x: x[0])
        if d <= 0.5:
            entrance_part = p

    reach = half + REACH_ALLOWANCE_M
    service_fps = [fps[it.item_id] for it in layout.items if it.zone == "service"]
    staff_parts = [p for p in parts if any(p.distance(s) <= reach for s in service_fps)]
    if entrance_part is not None:
        staff_parts.append(entrance_part)

    bad: list[LayoutItem] = []
    for it in layout.items:
        fp = fps[it.item_id]
        if it.zone in CUSTOMER_ZONES or it.seats > 0:
            ok = entrance_part is not None and entrance_part.distance(fp) <= reach
        elif it.zone == "back_of_house":
            ok = any(p.distance(fp) <= reach for p in staff_parts)
        else:
            ok = True
        if not ok:
            bad.append(it)
    return bad


def _widest_route(layout: Layout, rooms: list[Room], floor: Polygon, fps: dict[str, Polygon]) -> float | None:
    customer = [it for it in layout.items if it.zone in CUSTOMER_ZONES or it.seats > 0]
    if not customer:
        return None

    def ok(aisle: float) -> bool:
        bad = unreachable_items(layout, rooms, aisle, floor=floor, fps=fps)
        return not any(b.zone in CUSTOMER_ZONES or b.seats > 0 for b in bad)

    if not ok(0.5):
        return 0.0
    lo, hi = 0.5, 2.5
    while hi - lo > 0.05:
        mid = (lo + hi) / 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return round(lo, 2)


# --------------------------------------------------------------------------- #
# Entrance helpers
# --------------------------------------------------------------------------- #


def _entrance_frame(layout: Layout, rooms: list[Room], floor: Polygon) -> tuple[Frame, float] | None:
    if layout.entrance_xz is None:
        return None
    e = layout.entrance_xz
    parts = _parts(floor)
    if not parts:
        return None
    poly = min(parts, key=lambda p: p.distance(Point(e)))
    a, b = nearest_edge(poly, e)
    n = inward_normal(poly, a, b)
    t = unit(b[0] - a[0], b[1] - a[1])
    width = DEFAULT_DOOR_WIDTH_M
    best = None
    for room in rooms:
        for op in room.openings:
            if op.kind not in ("door", "opening"):
                continue
            mid = ((op.a[0] + op.b[0]) / 2, (op.a[1] + op.b[1]) / 2)
            dist = Point(mid).distance(Point(e))
            if dist <= 1.0 and (best is None or dist < best[0]):
                best = (dist, Point(op.a).distance(Point(op.b)))
    if best is not None:
        width = max(0.7, best[1])
    return Frame(origin=e, t=t, n=n), width


def _entrance_zone(layout: Layout, rooms: list[Room], floor: Polygon) -> Polygon | None:
    got = _entrance_frame(layout, rooms, floor)
    if got is None:
        return None
    frame, width = got
    hw = width / 2 + 0.15
    return Polygon([frame.to_world(-hw, 0), frame.to_world(hw, 0), frame.to_world(hw, DOOR_CLEARANCE_M), frame.to_world(-hw, DOOR_CLEARANCE_M)])


def _entrance_point(layout: Layout, rooms: list[Room], floor: Polygon, half: float) -> Point | None:
    got = _entrance_frame(layout, rooms, floor)
    if got is None:
        return None
    frame, _ = got
    return Point(frame.to_world(0, half + 0.05))


def _parts(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if not g.is_empty]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon) and not g.is_empty]
