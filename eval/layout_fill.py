"""How empty do the planned layouts look? Same numbers before and after any planner change.

    python -m eval.layout_fill                      # office, 25 desks, on a spread of real scans
    python -m eval.layout_fill --type bakery --seats 20
    python -m eval.layout_fill --png out_dir        # also draw each plan as a PNG

Per scan it reports:
  furniture %   footprint of every placed item / usable floor of the floor the business is on
  empty %       share of that floor that is more than EMPTY_R_M from any furniture AND more than
                WALL_M from a wall: the "you could land a helicopter here" areas
  validator     must stay "ok" (no overlaps, nothing unreachable, entrance clear)
  desks         must still equal the request
Targets for offices: empty under 15 %, furniture 20-35 %.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
from shapely.ops import unary_union

from agent import providers
from agent.layout.geometry import footprint, is_flat, is_void, rooms_union
from agent.layout.planner import plan_layout
from agent.layout.validator import validate_layout
from shared.conventions import DB_PATH
from shared.schemas import Brief, Layout

EMPTY_R_M = 2.5
WALL_M = 1.0


def empty_share(layout: Layout, rooms) -> tuple[float, float, float]:
    """(floor m2, furniture m2, empty share) for the floor the layout is on."""
    fidx = next((r.floor_index for r in rooms if layout.items and r.room_id == layout.items[0].room_id), rooms[0].floor_index)
    floor = rooms_union([r for r in rooms if not is_void(r) and r.floor_index == fidx])
    fur = unary_union([footprint(i.x_m, i.z_m, i.width_m, i.depth_m, i.rotation_deg) for i in layout.items if not is_flat(i)])  # rugs don't count
    near = unary_union([fur.buffer(EMPTY_R_M), floor.boundary.buffer(WALL_M)])
    return floor.area, fur.area, floor.difference(near).area / max(floor.area, 1e-9)


def sample_spaces(limit: int, lo: float, hi: float) -> list[tuple[str, str, float]]:
    """(space_id, model_id, area) for distinct scans between lo and hi m2, spread over the size range."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = con.execute(
        "select model_id, min(space_id), sum(area_m2) a from mp_rooms group by 1 having sum(area_m2) between ? and ? order by a", [lo, hi]
    ).fetchall()
    if len(rows) > limit:
        step = (len(rows) - 1) / (limit - 1)
        rows = [rows[round(i * step)] for i in range(limit)]
    return [(sid, mid, a) for mid, sid, a in rows]


def draw_png(layout: Layout, rooms, path: Path) -> None:
    from PIL import Image, ImageDraw

    fidx = next((r.floor_index for r in rooms if layout.items and r.room_id == layout.items[0].room_id), rooms[0].floor_index)
    floor = rooms_union([r for r in rooms if not is_void(r) and r.floor_index == fidx])
    fur = unary_union([footprint(i.x_m, i.z_m, i.width_m, i.depth_m, i.rotation_deg) for i in layout.items if not is_flat(i)])  # rugs don't count
    empty = floor.difference(unary_union([fur.buffer(EMPTY_R_M), floor.boundary.buffer(WALL_M)]))
    minx, minz, maxx, maxz = floor.bounds
    s, pad = 22, 20
    img = Image.new("RGB", (int((maxx - minx) * s) + 2 * pad, int((maxz - minz) * s) + 2 * pad), "white")
    d = ImageDraw.Draw(img)

    def pts(poly):
        return [((x - minx) * s + pad, (z - minz) * s + pad) for x, z in poly.exterior.coords]

    def polys(g):
        parts = [g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))
        return [p for p in parts if p.geom_type == "Polygon" and not p.is_empty]

    for p in polys(floor):
        d.polygon(pts(p), fill=(244, 241, 234), outline=(40, 40, 40))
    for p in polys(empty):
        d.polygon(pts(p), fill=(250, 205, 205))
    colors = {"seating": (59, 130, 246), "front_of_house": (16, 185, 129), "back_of_house": (245, 158, 11), "service": (139, 92, 246)}
    for i in sorted(layout.items, key=lambda i: not is_flat(i)):  # rugs first, furniture on top
        poly = pts(footprint(i.x_m, i.z_m, i.width_m, i.depth_m, i.rotation_deg))
        if is_flat(i):
            d.polygon(poly, fill=(206, 224, 228), outline=(150, 175, 182))
        else:
            d.polygon(poly, fill=colors.get(i.zone, (130, 130, 130)), outline=(20, 20, 20))
    if layout.entrance_xz:
        ex, ez = (layout.entrance_xz[0] - minx) * s + pad, (layout.entrance_xz[1] - minz) * s + pad
        d.ellipse([ex - 6, ez - 6, ex + 6, ez + 6], fill=(0, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="office")
    ap.add_argument("--seats", type=int, default=25)
    ap.add_argument("--scans", type=int, default=8)
    ap.add_argument("--min-area", type=float, default=120.0)
    ap.add_argument("--max-area", type=float, default=900.0)
    ap.add_argument("--png", type=Path, default=None, help="folder to write one plan image per scan")
    args = ap.parse_args()

    brief = Brief(business_type=args.type, seats_wanted=args.seats)
    print(f"{args.type}, {args.seats} seats; empty = floor more than {EMPTY_R_M} m from furniture and {WALL_M} m from a wall")
    print(f"{'scan':12} {'floor m2':>8} {'items':>5} {'seats':>5} {'furn %':>7} {'empty %':>8} {'valid':>6} {'sec':>5}")
    tot_empty, n_ok = [], 0
    for sid, mid, _ in sample_spaces(args.scans, args.min_area, args.max_area):
        rooms = providers.get_rooms(sid)
        t = time.time()
        try:
            lay = plan_layout(sid, rooms, None, brief)
        except Exception as e:  # keep going: one odd scan shouldn't hide the rest
            print(f"{mid:12} planner failed: {type(e).__name__}: {e}")
            continue
        sec = time.time() - t
        floor_m2, fur_m2, empty = empty_share(lay, rooms)
        ok = validate_layout(lay, rooms).passed
        n_ok += ok
        tot_empty.append(empty)
        print(f"{mid:12} {floor_m2:8.0f} {len(lay.items):5d} {lay.seat_count:5d} {fur_m2 / floor_m2 * 100:7.1f} {empty * 100:8.1f} {'ok' if ok else 'FAIL':>6} {sec:5.1f}")
        if args.png:
            draw_png(lay, rooms, args.png / f"{mid}.png")
    if tot_empty:
        print(f"average empty {sum(tot_empty) / len(tot_empty) * 100:.1f} %, valid {n_ok}/{len(tot_empty)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
