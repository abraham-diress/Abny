"""plan_layout: place a business's furniture and equipment inside the real rooms.

How it works
------------
1. Site analysis: find the entrance (an exterior door, else the storefront windows, else
   the longest wall), the front room, and a back room for the kitchen if there is one.
   Build a frame where u runs along the entrance wall and v points into the room.
2. Service line (display case + counter) faces the customers:
     back-counter: across the room near the back (or in front of the back room's door)
     side-counter: along a side wall (used when the room is too shallow for back-counter)
3. Back of house: required equipment against real walls behind the counter or in the back room.
4. Seating: wall benches, then free-standing table sets on a grid, keeping MIN_AISLE_M
   between sets, until the requested seats are reached.
5. Validate, remove any seating the validator says is unreachable, repeat.

Offices (template "office", strategy "open-plan"): reception desk on a side wall by the door,
meeting table in the back room (or the far end), kitchenette and storage on back walls, desk
pods on the grid and single desks along side walls; seat_count counts desks.

Every strategy is tried (unless one is requested) and the valid layout with the most
seats (closest to the request) wins. Nothing here calls an LLM: results are deterministic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from agent.layout.catalog import load_catalog
from agent.layout.geometry import (
    Frame,
    edges,
    facing_rotation,
    footprint,
    front_zone,
    inward_normal,
    nearest_edge,
    room_polygon,
    rooms_union,
    unit,
)
from agent.layout.templates import BusinessTemplate, target_seats, template_for
from agent.layout.validator import unreachable_items, validate_layout
from shared.conventions import DOOR_CLEARANCE_M, MIN_AISLE_M
from shared.schemas import Brief, CatalogItem, Inspection, Layout, LayoutItem, Room

STRATEGIES = ("back-counter", "side-counter")
GRID_STEP_M = 0.2
ANCHOR_M2_PER_SEAT = 6.0  # floor a seat/desk needs (with aisles) before an anchor may share the open area
EXCLUDED_ROOM_WORDS = ("bath", "restroom", "toilet", "wc", "closet", "stair", "elevator")


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def plan_layout(
    space_id: str,
    rooms: list[Room],
    inspection: Inspection | None,
    brief: Brief,
    strategy: str | None = None,
) -> Layout:
    """Place the business's items in the real rooms. See module docstring."""
    if not rooms:
        raise ValueError(f"No rooms for space {space_id}; can't plan a layout")
    catalog = load_catalog()
    tpl, tpl_notes = template_for(brief)
    site = analyze_site(rooms)
    wanted = target_seats(brief, tpl)

    tried = [strategy] if strategy in tpl.strategies else list(tpl.strategies)
    if strategy and strategy not in tpl.strategies:
        tpl_notes = tpl_notes + [f"Strategy '{strategy}' doesn't apply to a {tpl.business_type}; tried {', '.join(tpl.strategies)}."]
    candidates: list[Layout] = []
    for strat in tried:
        layout = _plan_one(space_id, site, rooms, catalog, tpl, wanted, strat)
        notes = tpl_notes + site.notes + _inspection_notes(inspection, site, tpl) + layout.notes
        layout.notes = [n for n in notes if n.startswith("WARNING")] + [n for n in notes if not n.startswith("WARNING")]
        candidates.append(layout)

    def score(lay: Layout) -> tuple:
        report = validate_layout(lay, site.floor_rooms)
        missing_boh = sum(1 for n in lay.notes if n.startswith("Could not fit"))
        close_enough = lay.seat_count >= 0.85 * wanted  # a couple of seats is worth a better flow
        preference = -tpl.strategies.index(lay.strategy) if lay.strategy in tpl.strategies else 0
        return (report.passed, -missing_boh, close_enough, preference, lay.seat_count)

    best = max(candidates, key=score)
    if len(candidates) > 1:
        others = ", ".join(f"{c.strategy}: {c.seat_count} {tpl.seat_word}" for c in candidates if c is not best)
        best.notes.append(f"Also tried {others}.")
    return best


# --------------------------------------------------------------------------- #
# Site analysis
# --------------------------------------------------------------------------- #


@dataclass
class Site:
    floor_rooms: list[Room]
    front: Room
    back: Room | None
    frame: Frame
    door_width: float
    entrance: tuple[float, float]
    back_opening: tuple[float, float] | None  # midpoint of the doorway into the back room
    windows: list[LineString]
    notes: list[str] = field(default_factory=list)

    @property
    def front_poly(self) -> Polygon:
        return room_polygon(self.front)

    @property
    def back_poly(self) -> Polygon | None:
        return room_polygon(self.back) if self.back else None


def analyze_site(rooms: list[Room]) -> Site:
    notes: list[str] = []
    usable = [r for r in rooms if not _excluded(r)] or rooms

    # Entrance: exterior door > storefront windows > longest wall of the largest room.
    entrance = None
    for room in usable:
        for op in room.openings:
            if op.kind == "door" and _is_exterior(op.a, op.b, room, rooms):
                cand = (room, op.a, op.b)
                if entrance is None or _window_len(room) > _window_len(entrance[0]):
                    entrance = cand
    if entrance is None:
        best = max(usable, key=_window_len)
        win = [op for op in best.openings if op.kind == "window"]
        if win:
            op = max(win, key=lambda o: Point(o.a).distance(Point(o.b)))
            mid = ((op.a[0] + op.b[0]) / 2, (op.a[1] + op.b[1]) / 2)
            entrance = (best, op.a, op.b)
            notes.append("No door found in the scan; assumed the entrance is at the storefront windows.")
        else:
            big = max(usable, key=lambda r: room_polygon(r).area)
            a, b = max(edges(room_polygon(big)), key=lambda e: LineString(e).length)
            entrance = (big, a, b)
            notes.append("No door or windows found in the scan; assumed the entrance is on the longest wall.")

    front, a, b = entrance
    floor_rooms = [r for r in rooms if r.floor_index == front.floor_index]
    fpoly = room_polygon(front)
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    ea, eb = nearest_edge(fpoly, mid)
    n = inward_normal(fpoly, ea, eb)
    t = unit(eb[0] - ea[0], eb[1] - ea[1])
    # Snap the entrance point onto the wall line.
    proj = LineString([ea, eb]).interpolate(LineString([ea, eb]).project(Point(mid)))
    origin = (proj.x, proj.y)
    door_width = Point(a).distance(Point(b))
    door_width = door_width if 0.7 <= door_width <= 2.5 else 0.9

    # Back room: adjacent, not a restroom, big enough for a kitchen; prefer 'kitchen'.
    back = None
    candidates = [
        r for r in floor_rooms
        if r.room_id != front.room_id and not _excluded(r) and room_polygon(r).area >= 6.0
        and room_polygon(r).distance(fpoly) < 0.3
    ]
    if candidates:
        back = max(candidates, key=lambda r: (("kitchen" in (r.room_type or r.label or "").lower()), room_polygon(r).area))

    back_opening = None
    if back is not None:
        bpoly = room_polygon(back)
        ops = [o for o in front.openings + back.openings if o.kind in ("door", "opening")]
        shared = [o for o in ops if Point(((o.a[0] + o.b[0]) / 2, (o.a[1] + o.b[1]) / 2)).distance(bpoly) < 0.3
                  and Point(((o.a[0] + o.b[0]) / 2, (o.a[1] + o.b[1]) / 2)).distance(fpoly) < 0.3]
        if shared:
            o = shared[0]
            back_opening = ((o.a[0] + o.b[0]) / 2, (o.a[1] + o.b[1]) / 2)
        else:
            inter = fpoly.buffer(0.15).intersection(bpoly.buffer(0.15))
            if not inter.is_empty:
                c = inter.centroid
                back_opening = (c.x, c.y)
            notes.append("Doorway to the back room not marked in the scan; assumed one where the rooms meet.")

    windows = [LineString([o.a, o.b]) for r in floor_rooms for o in r.openings if o.kind == "window"]
    overlap = rooms_overlap(floor_rooms)
    if overlap:
        notes.insert(0, f"WARNING: rooms {overlap[0]} and {overlap[1]} overlap in the data (room positions may be missing); "
                        "furniture may not line up with the 3D tour.")
    return Site(
        floor_rooms=floor_rooms,
        front=front,
        back=back,
        frame=Frame(origin=origin, t=t, n=n),
        door_width=door_width,
        entrance=origin,
        back_opening=back_opening,
        windows=windows,
        notes=notes,
    )


def rooms_overlap(rooms: list[Room], threshold: float = 0.2) -> tuple[str, str] | None:
    """First pair of rooms whose overlap is more than `threshold` of the smaller room, else None."""
    polys = [(r.room_id, room_polygon(r)) for r in rooms]
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            (ia, a), (ib, b) = polys[i], polys[j]
            small = min(a.area, b.area)
            if small > 0 and a.intersection(b).area > threshold * small:
                return ia, ib
    return None


def _named_room(site: Site, words: tuple[str, ...]) -> Room | None:
    """A room on this floor (not the front room) whose type/label contains one of `words`."""
    for r in site.floor_rooms:
        text = f"{r.room_type or ''} {r.label or ''}".lower()
        if r.room_id != site.front.room_id and any(w in text for w in words):
            return r
    return None


def _excluded(room: Room) -> bool:
    text = f"{room.room_type or ''} {room.label or ''}".lower()
    return any(w in text for w in EXCLUDED_ROOM_WORDS)


def _window_len(room: Room) -> float:
    return sum(Point(o.a).distance(Point(o.b)) for o in room.openings if o.kind == "window")


def _is_exterior(a, b, room: Room, rooms: list[Room]) -> bool:
    mid = Point(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    return not any(r.room_id != room.room_id and room_polygon(r).distance(mid) < 0.3 for r in rooms)


def _inspection_notes(inspection: Inspection | None, site: Site, tpl: BusinessTemplate | None = None) -> list[str]:
    if inspection is None:
        return []
    notes = []
    if tpl is not None and tpl.business_type == "office":
        build_out = (inspection.existing_build_out or "").lower()
        if "private" in build_out:
            notes.append("The space has private offices today; this open-plan layout assumes some walls come out.")
        if inspection.natural_light is not None and inspection.natural_light < 0.3:
            notes.append("Little daylight in the scan: plan for good lighting at the desks.")
        return notes
    if inspection.existing_kitchen and site.back is not None:
        notes.append("Kitchen equipment goes in the existing back kitchen (reuses plumbing).")
    if inspection.storefront_glass is False:
        notes.append("Inspection found no storefront glass; seating placed away from the entrance wall anyway.")
    if inspection.ceiling_height_m is not None and inspection.ceiling_height_m < 2.6:
        notes.append(f"Low ceiling ({inspection.ceiling_height_m:.1f} m): check vent hood clearance on site.")
    return notes


# --------------------------------------------------------------------------- #
# Placement bookkeeping
# --------------------------------------------------------------------------- #


@dataclass
class Placed:
    item: LayoutItem | None  # None = keep-out area
    fp: Polygon
    front: Polygon | None


class Placer:
    def __init__(self, floor: Polygon, catalog: dict[str, CatalogItem], layout_id: str) -> None:
        self.floor = floor
        self.floor_prep = prep(floor.buffer(1e-3))
        self.catalog = catalog
        self.layout_id = layout_id
        self.placed: list[Placed] = []
        self._n = 0

    def keep_out(self, poly: Polygon) -> None:
        if not poly.is_empty:
            self.placed.append(Placed(None, poly, None))

    def fits(self, fp: Polygon, fz: Polygon | None, region_prep=None, gap: float = 0.0) -> bool:
        if not (region_prep or self.floor_prep).contains(fp):
            return False
        if fz is not None and not self.floor_prep.contains(fz):
            return False
        for p in self.placed:
            if p.item is None:
                if fp.intersects(p.fp) and fp.intersection(p.fp).area > 1e-4:
                    return False
                continue
            if fp.intersects(p.fp) and fp.intersection(p.fp).area > 1e-4:
                return False
            if gap > 0 and fp.distance(p.fp) < gap - 1e-6:
                return False
            if p.front is not None and fp.intersects(p.front) and fp.intersection(p.front).area > 1e-4:
                return False
            if fz is not None and fz.intersects(p.fp) and fz.intersection(p.fp).area > 1e-4:
                return False
        return True

    def add(self, item_type: str, room_id: str, x: float, z: float, rot: float) -> LayoutItem:
        c = self.catalog[item_type]
        self._n += 1
        item = LayoutItem(
            item_id=f"{self.layout_id}-I{self._n:02d}",
            item_type=item_type,
            glb_asset=c.glb_asset,
            room_id=room_id,
            x_m=round(x, 3),
            z_m=round(z, 3),
            rotation_deg=round(rot % 360.0, 1),
            width_m=c.width_m,
            depth_m=c.depth_m,
            height_m=c.height_m,
            zone=c.zone,
            seats=c.seats,
        )
        self.placed.append(Placed(item, footprint(x, z, c.width_m, c.depth_m, rot), front_zone(x, z, c.width_m, c.depth_m, rot, c.clearance_front_m)))
        return item

    def remove(self, item_id: str) -> None:
        self.placed = [p for p in self.placed if p.item is None or p.item.item_id != item_id]

    def items(self) -> list[LayoutItem]:
        return [p.item for p in self.placed if p.item is not None]


# --------------------------------------------------------------------------- #
# One strategy
# --------------------------------------------------------------------------- #


def _plan_one(space_id: str, site: Site, rooms: list[Room], catalog, tpl: BusinessTemplate, wanted: int, strategy: str) -> Layout:
    layout_id = f"{space_id}-{_short_hash(space_id, tpl.business_type, strategy, wanted)}"
    floor = rooms_union(site.floor_rooms)
    placer = Placer(floor, catalog, layout_id)
    frame = site.frame
    notes: list[str] = []
    fpoly = site.front_poly

    # Keep the entrance and the back doorway clear.
    hw = site.door_width / 2 + 0.15
    placer.keep_out(Polygon([frame.to_world(-hw, -0.1), frame.to_world(hw, -0.1), frame.to_world(hw, DOOR_CLEARANCE_M), frame.to_world(-hw, DOOR_CLEARANCE_M)]))
    if site.back_opening is not None:
        placer.keep_out(Point(site.back_opening).buffer(0.9))

    v_min, v_max = frame.depth_extent(fpoly)
    service_types = [t for t in tpl.service_line if t in catalog]
    svc_depth = max((catalog[t].depth_m for t in service_types), default=0.0)
    svc_clear = max((catalog[t].clearance_front_m for t in service_types), default=0.0)
    boh_types = [t for t in tpl.boh_required if t in catalog]
    boh_depth = max((catalog[t].depth_m for t in boh_types), default=0.0)
    boh_clear = max((catalog[t].clearance_front_m for t in boh_types), default=0.0)

    seat_region = fpoly
    if strategy == "back-counter" and service_types:
        if site.back is not None:
            back_v = frame.to_local(site.back_opening)[1] if site.back_opening else v_max
            v_line = min(back_v, v_max) - tpl.staff_aisle_m - svc_depth / 2
        else:
            v_line = v_max - (boh_depth + max(boh_clear, tpl.staff_aisle_m)) - svc_depth / 2 if boh_types else v_max - tpl.staff_aisle_m - svc_depth / 2
        placed_line = _place_service_line(placer, site, catalog, tpl, frame, fpoly, v_line, notes)
        if placed_line:
            front_edge = v_line - svc_depth / 2 - svc_clear - tpl.queue_depth_m
            seat_region = frame.band(fpoly, v_min - 1, front_edge)
            boh_region = site.back_poly if site.back is not None else frame.band(fpoly, v_line + svc_depth / 2, v_max + 1)
        else:
            boh_region = site.back_poly if site.back is not None else fpoly
    else:  # side-counter (or no service line)
        if service_types and not _place_service_on_wall(placer, site, catalog, tpl, fpoly, frame, notes):
            notes.append("Could not fit the service counter.")
        boh_region = site.back_poly if site.back is not None else fpoly

    # Entry items (reception) on a side wall by the door; anchors (meeting table) before the seats.
    for t in tpl.entry_items:
        if t in catalog and not _place_unit_on_wall(placer, site, catalog, [t], fpoly, prefer="side_near_entrance"):
            notes.append(f"Could not fit the {catalog[t].label.lower()}.")
    for t in tpl.anchor_items:
        if t not in catalog:
            continue
        named = _named_room(site, ("conference", "meeting", "board"))
        regions = ([room_polygon(named)] if named is not None else []) + ([site.back_poly] if site.back is not None else [])
        open_area = seat_region if not seat_region.is_empty else fpoly
        # In the open area only if the requested seats/desks still fit (~6 m2 each with aisles).
        if open_area.area >= ANCHOR_M2_PER_SEAT * wanted + 2 * catalog[t].width_m * catalog[t].depth_m:
            regions.append(open_area)
        if not any(_place_free(placer, site, catalog, t, r) for r in regions):
            notes.append(f"No room for the {catalog[t].label.lower()} without losing {tpl.seat_word}.")

    def blocked() -> set[str]:
        lay = _layout(placer, space_id, layout_id, tpl, site, strategy, notes)
        return {b.item_id for b in unreachable_items(lay, site.floor_rooms, MIN_AISLE_M)}

    # Required back of house first, then seats, then optional extras (they only use leftover space).
    def place_boh(t: str) -> bool:
        ok = _place_on_walls(placer, site, catalog, t, boh_region, prefer="far_from_entrance")
        if not ok and site.back is not None:
            ok = _place_on_walls(placer, site, catalog, t, fpoly, prefer="far_from_entrance")
        return ok

    for t in boh_types:
        if not place_boh(t):
            notes.append(f"Could not fit {catalog[t].label.lower()}.")

    _place_seating(placer, site, catalog, tpl, seat_region, wanted)

    for t in tpl.boh_optional:
        if t in catalog:
            before = blocked()
            if place_boh(t) and blocked() - before:  # optional: keep only if reachable and blocks nobody
                placer.remove(placer.items()[-1].item_id)
    foh_region = seat_region if not seat_region.is_empty else fpoly

    # Optional extras never cost access: keep each one only if it cuts nobody off.
    for t in tpl.foh_extras:
        if t not in catalog:
            continue
        before = blocked()
        if not _place_on_walls(placer, site, catalog, t, foh_region, prefer="near_entrance", avoid_windows=True):
            break
        if blocked() - before:
            placer.remove(placer.items()[-1].item_id)
            break

    layout = _layout(placer, space_id, layout_id, tpl, site, strategy, notes)

    # Repair: drop seating the validator can't reach; if equipment is boxed in, drop the seat nearest it.
    for _ in range(12):
        bad = unreachable_items(layout, site.floor_rooms, MIN_AISLE_M)
        drop = {b.item_id for b in bad if b.seats > 0 or b.zone == "front_of_house"}
        for b in bad:
            if b.zone == "back_of_house" and b.item_id not in drop:
                here = Point(b.x_m, b.z_m)
                # Optional front-of-house pieces (meeting table, sofa) go before any seat or desk.
                extras = [i for i in layout.items if i.zone == "front_of_house" and i.seats == 0 and i.item_id not in drop]
                seats_left = [i for i in layout.items if i.seats > 0 and i.item_id not in drop]
                pool = extras or seats_left
                if pool:
                    drop.add(min(pool, key=lambda i: here.distance(Point(i.x_m, i.z_m))).item_id)
        if not drop:
            break
        for item_id in drop:
            placer.remove(item_id)
        layout = _layout(placer, space_id, layout_id, tpl, site, strategy, notes)

    seats = layout.seat_count
    if wanted and seats < wanted:
        layout.notes.append(f"Fits {seats} of the {wanted} {tpl.seat_word} requested.")
    return layout


def _layout(placer: Placer, space_id, layout_id, tpl, site: Site, strategy, notes) -> Layout:
    items = placer.items()
    return Layout(
        layout_id=layout_id,
        space_id=space_id,
        business_type=tpl.business_type,
        entrance_xz=(round(site.entrance[0], 3), round(site.entrance[1], 3)),
        items=items,
        seat_count=sum(i.seats for i in items),
        strategy=strategy,
        notes=list(notes),
    )


# --------------------------------------------------------------------------- #
# Service line
# --------------------------------------------------------------------------- #


def _place_service_line(placer: Placer, site: Site, catalog, tpl: BusinessTemplate, frame: Frame, fpoly: Polygon, v_line: float, notes) -> bool:
    line = LineString([frame.to_world(-200, v_line), frame.to_world(200, v_line)]).intersection(fpoly)
    segs = _segments(line)
    if not segs:
        return False
    seg = max(segs, key=lambda s: s.length)
    us = sorted(frame.to_local(c)[0] for c in seg.coords)
    u0, u1 = us[0], us[-1]

    types = [t for t in tpl.service_line if t in catalog]
    optional = [t for t in tpl.service_optional if t in types]
    while types and sum(catalog[t].width_m for t in types) > (u1 - u0) - 0.2:
        drop = optional.pop() if optional else types[-1]
        types.remove(drop)
        notes.append(f"Dropped the {catalog[drop].label.lower()}: the room is too narrow.")
    if not types:
        return False

    total = sum(catalog[t].width_m for t in types)
    rot = facing_rotation(-frame.n[0], -frame.n[1])
    region = prep(fpoly.buffer(1e-3))
    # Prefer centered; slide sideways if the center collides with a keep-out.
    center = (u0 + u1) / 2
    offsets = [0.0] + [s * k * 0.2 for k in range(1, 30) for s in (1, -1)]
    for off in offsets:
        start = center + off - total / 2
        if start < u0 + 0.05 or start + total > u1 - 0.05:
            continue
        plan, u = [], start
        for t in types:
            c = catalog[t]
            x, z = frame.to_world(u + c.width_m / 2, v_line)
            plan.append((t, x, z, footprint(x, z, c.width_m, c.depth_m, rot), front_zone(x, z, c.width_m, c.depth_m, rot, c.clearance_front_m)))
            u += c.width_m
        if all(placer.fits(fp, fz, region) for _, _, _, fp, fz in plan):
            for t, x, z, _, _ in plan:
                placer.add(t, site.front.room_id, x, z, rot)
            return True
    return False


def _place_service_on_wall(placer: Placer, site: Site, catalog, tpl, fpoly, frame, notes) -> bool:
    """Side-counter: the whole service line as one unit against a side wall."""
    types = [t for t in tpl.service_line if t in catalog]
    optional = [t for t in tpl.service_optional if t in types]
    while types:
        if _place_unit_on_wall(placer, site, catalog, types, fpoly, prefer="side_walls"):
            return True
        drop = optional.pop() if optional else types[-1]
        types.remove(drop)
        notes.append(f"Dropped the {catalog[drop].label.lower()} to fit the counter.")
    return False


# --------------------------------------------------------------------------- #
# Wall placement
# --------------------------------------------------------------------------- #


def _wall_slots(site: Site, region, span: float, prefer: str):
    """Positions along real walls inside `region` where a run of length `span` fits.
    Yields (x, z, t, n) best-first: the run's center point on the wall, wall direction, inward normal."""
    walls = rooms_union(site.floor_rooms).boundary.buffer(0.05)
    entrance = Point(site.entrance)
    cands = []
    for poly in _polys(region):
        for a, b in edges(poly):
            seg = LineString([a, b])
            if seg.length < span or not walls.contains(seg):
                continue
            t = unit(b[0] - a[0], b[1] - a[1])
            n = inward_normal(poly, a, b)
            parallel_to_entrance = abs(t[0] * site.frame.t[0] + t[1] * site.frame.t[1])
            s = span / 2
            while s <= seg.length - span / 2 + 1e-9:
                x, z = a[0] + t[0] * s, a[1] + t[1] * s
                d_ent = entrance.distance(Point(x, z))
                if prefer == "far_from_entrance":
                    key = -d_ent
                elif prefer == "near_entrance":
                    key = d_ent
                elif prefer == "side_near_entrance":  # side walls first, then closest to the door
                    key = parallel_to_entrance * 100 + d_ent
                else:  # side walls first, then closer to the back
                    key = parallel_to_entrance * 100 - d_ent
                cands.append((key, x, z, t, n))
                s += GRID_STEP_M
    cands.sort(key=lambda k: k[0])
    for _, x, z, t, n in cands:
        yield x, z, t, n


def _place_on_walls(placer: Placer, site: Site, catalog, item_type: str, region, prefer: str, avoid_windows: bool = False) -> bool:
    return _place_unit_on_wall(placer, site, catalog, [item_type], region, prefer, avoid_windows)


def _place_unit_on_wall(placer: Placer, site: Site, catalog, types: list[str], region, prefer: str, avoid_windows: bool = False) -> bool:
    """Place items side by side against one wall, backs to the wall, fronts facing into the room."""
    if region is None or region.is_empty or not types:
        return False
    items = [catalog[t] for t in types]
    span = sum(c.width_m for c in items)
    tall = avoid_windows or any(c.height_m > 1.1 for c in items)
    windows = unary_union([w.buffer(0.35) for w in site.windows]) if tall and site.windows else None
    region_prep = prep(region.buffer(1e-3))
    for wx, wz, t, n in _wall_slots(site, region, span, prefer):
        rot = facing_rotation(*n)
        plan, offset = [], -span / 2
        for typ, c in zip(types, items):
            along = offset + c.width_m / 2
            x = wx + t[0] * along + n[0] * (c.depth_m / 2 + 0.01)
            z = wz + t[1] * along + n[1] * (c.depth_m / 2 + 0.01)
            plan.append((typ, x, z, footprint(x, z, c.width_m, c.depth_m, rot), front_zone(x, z, c.width_m, c.depth_m, rot, c.clearance_front_m)))
            offset += c.width_m
        if windows is not None and any(fp.intersects(windows) for _, _, _, fp, _ in plan):
            continue
        if all(placer.fits(fp, fz, region_prep) for _, _, _, fp, fz in plan):
            for typ, x, z, _, _ in plan:
                placer.add(typ, _room_at(site.floor_rooms, x, z), x, z, rot)
            return True
    return False


# --------------------------------------------------------------------------- #
# Seating
# --------------------------------------------------------------------------- #


def _place_seating(placer: Placer, site: Site, catalog, tpl: BusinessTemplate, region, wanted: int) -> int:
    if wanted <= 0 or region is None or region.is_empty:
        return 0
    seats = 0
    gap = MIN_AISLE_M + 0.02
    region_prep = prep(region.buffer(1e-3))

    # 1) Wall benches along side walls, up to ~40% of the seats (the rest go in the middle).
    bench_cap = max(4, round(wanted * 0.4))
    for t in tpl.seating_wall:
        if t not in catalog:
            continue
        while seats < min(wanted, bench_cap) and _place_wall_seating(placer, site, catalog, t, region, region_prep, gap):
            seats += catalog[t].seats

    # 2) Free-standing sets on a grid, nearest the storefront first.
    frame = site.frame
    types = [t for t in tpl.seating_free if t in catalog]
    if not types:
        return seats
    v0, v1 = frame.depth_extent(region if isinstance(region, Polygon) else region.convex_hull)
    us = [frame.to_local(c)[0] for p in _polys(region) for c in p.exterior.coords]
    u0, u1 = min(us), max(us)
    rots = [facing_rotation(*frame.n), facing_rotation(*frame.t)]
    v = v0 + 0.1
    while v <= v1 and seats < wanted:
        u = u0 + 0.1
        while u <= u1 and seats < wanted:
            remaining = wanted - seats
            order = sorted(types, key=lambda t: (catalog[t].seats > remaining, -catalog[t].seats))
            for t in order:
                c = catalog[t]
                placed = False
                for rot in rots:
                    x, z = frame.to_world(u + c.width_m / 2, v + c.depth_m / 2)
                    fp = footprint(x, z, c.width_m, c.depth_m, rot)
                    if placer.fits(fp, None, region_prep, gap=gap):
                        placer.add(t, _room_at(site.floor_rooms, x, z), x, z, rot)
                        seats += c.seats
                        placed = True
                        break
                if placed:
                    break
            u += GRID_STEP_M
        v += GRID_STEP_M
    for t in tpl.seating_wall:
        while t in catalog and seats < wanted and _place_wall_seating(placer, site, catalog, t, region, region_prep, gap):
            seats += catalog[t].seats
    return seats


def _place_free(placer: Placer, site: Site, catalog, item_type: str, region) -> bool:
    """One free-standing item (e.g. a meeting table): farthest from the entrance first,
    with a walkable aisle all around it and away from the walls."""
    if region is None or region.is_empty:
        return False
    c = catalog[item_type]
    gap = MIN_AISLE_M + 0.02
    inner = region.buffer(-gap * 0.6)  # keep a walkway between the item and the walls
    if inner.is_empty:
        return False
    region_prep = prep(inner.buffer(1e-3))
    frame, entrance = site.frame, Point(site.entrance)
    minx, minz, maxx, maxz = inner.bounds
    cands = []
    x = minx
    while x <= maxx:
        z = minz
        while z <= maxz:
            cands.append((-entrance.distance(Point(x, z)), x, z))
            z += GRID_STEP_M
        x += GRID_STEP_M
    cands.sort()
    rots = [facing_rotation(*frame.n), facing_rotation(*frame.t)]
    for _, x, z in cands:
        for rot in rots:
            fp = footprint(x, z, c.width_m, c.depth_m, rot)
            if placer.fits(fp, None, region_prep, gap=gap):
                placer.add(item_type, _room_at(site.floor_rooms, x, z), x, z, rot)
                return True
    return False


def _place_wall_seating(placer: Placer, site: Site, catalog, item_type, region, region_prep, gap) -> bool:
    c = catalog[item_type]
    walls = rooms_union(site.floor_rooms).boundary.buffer(0.05)
    windows = unary_union([w.buffer(0.2) for w in site.windows]) if site.windows else None
    best = None
    for poly in _polys(region):
        for a, b in edges(poly):
            seg = LineString([a, b])
            if seg.length < c.width_m or not walls.contains(seg):
                continue
            t = unit(b[0] - a[0], b[1] - a[1])
            n = inward_normal(poly, a, b)
            # Only side walls (perpendicular to the entrance wall).
            if abs(t[0] * site.frame.t[0] + t[1] * site.frame.t[1]) > 0.3:
                continue
            rot = facing_rotation(*n)
            s = c.width_m / 2
            while s <= seg.length - c.width_m / 2 + 1e-9:
                x = a[0] + t[0] * s + n[0] * (c.depth_m / 2 + 0.01)
                z = a[1] + t[1] * s + n[1] * (c.depth_m / 2 + 0.01)
                fp = footprint(x, z, c.width_m, c.depth_m, rot)
                if (windows is None or not fp.intersects(windows)) and placer.fits(fp, None, region_prep, gap=gap):
                    key = site.frame.to_local((x, z))[1]
                    if best is None or key < best[0]:
                        best = (key, x, z, rot)
                s += GRID_STEP_M
    if best is None:
        return False
    _, x, z, rot = best
    placer.add(item_type, _room_at(site.floor_rooms, x, z), x, z, rot)
    return True


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _polys(geom) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def _segments(geom) -> list[LineString]:
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, LineString)]


def _room_at(rooms: list[Room], x: float, z: float) -> str:
    p = Point(x, z)
    best = min(rooms, key=lambda r: room_polygon(r).distance(p))
    return best.room_id


def _short_hash(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:6].upper()


__all__ = ["plan_layout", "analyze_site", "rooms_overlap", "STRATEGIES"]

