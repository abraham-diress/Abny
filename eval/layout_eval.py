"""Layout eval: how often does the planner produce a valid layout, and how many of the requested seats fit?

    python eval/layout_eval.py                    # 200 synthetic floor plans (rectangles, L-shapes, front+kitchen)
    python eval/layout_eval.py --n 500 --seed 3
    python eval/layout_eval.py --spaces ID1 ID2   # real spaces (needs pipeline.queries.get_rooms)

Writes data/eval/layout_eval.json and prints a summary you can quote in the pitch.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.layout.planner import plan_layout  # noqa: E402
from agent.layout.validator import validate_layout  # noqa: E402
from shared.conventions import DATA_DIR  # noqa: E402
from shared.schemas import Brief, Opening, Room  # noqa: E402


def _rot(points, deg, off):
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    return [(round(x * c - z * s + off[0], 4), round(x * s + z * c + off[1], 4)) for x, z in points]


def synthetic_space(rng: random.Random, i: int) -> tuple[str, list[Room]]:
    kind = rng.choice(["rect", "rect", "L", "front+kitchen"])
    w = rng.uniform(6, 14)
    d = rng.uniform(7, 16)
    deg = rng.uniform(0, 360)
    off = (rng.uniform(-50, 50), rng.uniform(-50, 50))
    sid = f"SYN{i:04d}"
    door_u = rng.uniform(1.0, w - 2.0)
    door = Opening(kind="door", a=_rot([(door_u, 0)], deg, off)[0], b=_rot([(door_u + 1.0, 0)], deg, off)[0])
    windows = []
    if door_u > 1.6:
        windows.append(Opening(kind="window", a=_rot([(0.3, 0)], deg, off)[0], b=_rot([(door_u - 0.3, 0)], deg, off)[0]))
    if kind == "rect":
        shape = [(0, 0), (w, 0), (w, d), (0, d)]
        return sid, [Room(room_id=f"{sid}-R1", space_id=sid, polygon_m=_rot(shape, deg, off), area_m2=w * d, openings=[door, *windows])]
    if kind == "L":
        cut_w, cut_d = rng.uniform(0.3, 0.5) * w, rng.uniform(0.3, 0.5) * d
        shape = [(0, 0), (w, 0), (w, d - cut_d), (w - cut_w, d - cut_d), (w - cut_w, d), (0, d)]
        return sid, [Room(room_id=f"{sid}-R1", space_id=sid, polygon_m=_rot(shape, deg, off), area_m2=w * d - cut_w * cut_d, openings=[door, *windows])]
    k = rng.uniform(3.5, 5.5)
    front = [(0, 0), (w, 0), (w, d), (0, d)]
    kitchen = [(0, d), (w, d), (w, d + k), (0, d + k)]
    gap_u = rng.uniform(0.5, w - 1.5)
    opening = Opening(kind="opening", a=_rot([(gap_u, d)], deg, off)[0], b=_rot([(gap_u + 1.0, d)], deg, off)[0])
    return sid, [
        Room(room_id=f"{sid}-F", space_id=sid, polygon_m=_rot(front, deg, off), area_m2=w * d, openings=[door, *windows, opening]),
        Room(room_id=f"{sid}-K", space_id=sid, room_type="kitchen", polygon_m=_rot(kitchen, deg, off), area_m2=w * k),
    ]


def evaluate(spaces: list[tuple[str, list[Room]]], briefs: list[Brief]) -> dict:
    rows = []
    for (sid, rooms), brief in zip(spaces, briefs):
        t0 = time.perf_counter()
        try:
            lay = plan_layout(sid, rooms, None, brief)
            rep = validate_layout(lay, rooms)
            rows.append({
                "space_id": sid, "ok": True, "valid": rep.passed, "seats": lay.seat_count, "wanted": brief.seats_wanted,
                "min_aisle_m": rep.min_aisle_m, "strategy": lay.strategy, "seconds": round(time.perf_counter() - t0, 3),
                "violations": [v.kind for v in rep.violations],
            })
        except Exception as exc:  # noqa: BLE001 - an eval records failures instead of stopping
            rows.append({"space_id": sid, "ok": False, "error": f"{type(exc).__name__}: {exc}", "seconds": round(time.perf_counter() - t0, 3)})
    done = [r for r in rows if r["ok"]]
    valid = [r for r in done if r["valid"]]
    ratios = [min(1.0, r["seats"] / r["wanted"]) for r in valid if r["wanted"]]
    summary = {
        "spaces": len(rows),
        "crashed": len(rows) - len(done),
        "valid_pct": round(100 * len(valid) / max(1, len(rows)), 1),
        "full_seats_pct": round(100 * sum(1 for x in ratios if x >= 1.0) / max(1, len(ratios)), 1),
        "avg_seat_fill_pct": round(100 * statistics.mean(ratios), 1) if ratios else None,
        "median_min_aisle_m": statistics.median([r["min_aisle_m"] for r in valid if r["min_aisle_m"] is not None]) if valid else None,
        "median_seconds": statistics.median([r["seconds"] for r in rows]) if rows else None,
        "strategies": {s: sum(1 for r in done if r.get("strategy") == s) for s in {r.get("strategy") for r in done}},
    }
    return {"summary": summary, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--spaces", nargs="*", help="real space ids (uses pipeline.queries.get_rooms)")
    ap.add_argument("--business", default="bakery")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    if args.spaces:
        from pipeline.queries import get_rooms

        spaces = [(sid, get_rooms(sid)) for sid in args.spaces]
    else:
        spaces = [synthetic_space(rng, i) for i in range(args.n)]
    briefs = [Brief(business_type=args.business, seats_wanted=rng.choice([8, 12, 16, 20, 24, 30])) for _ in spaces]

    result = evaluate(spaces, briefs)
    out = DATA_DIR / "eval" / "layout_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    s = result["summary"]
    print(json.dumps(s, indent=2))
    print(f"\nPitch line: {s['valid_pct']}% of {s['spaces']} floor plans got a valid layout; "
          f"{s['full_seats_pct']}% fit every requested seat; median {s['median_seconds']} s per layout.")
    for r in result["rows"]:
        if not r["ok"] or not r["valid"]:
            print("  problem:", r)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
