"""Step 3 + 5: Matterport rooms, scan poses and panorama faces for candidate spaces.

    python -m pipeline.fetch_matterport                       # all candidates, demo (priority 0) first
    python -m pipeline.fetch_matterport --space-ids a,b,c     # just these
    python -m pipeline.fetch_matterport --scans 2 --faces front,right,back,left
    python -m pipeline.fetch_matterport --scans all           # every scan (use for demo spaces)
    python -m pipeline.fetch_matterport --no-images           # rooms + poses only (fast, all candidates)
    python -m pipeline.fetch_matterport --force               # refetch even if cached

Resumable: models with status 'ok' in mp_fetch_log are skipped; existing images aren't re-downloaded.
Writes mp_rooms, mp_scans, mp_panos and data/media/panos/<model>/<scan>_<face>.jpg.

Coordinates: everything stored is y-up (our convention). The API's up axis is detected
from scan positions (cameras on one floor share a height) unless MATTERPORT_UP_AXIS=y|z.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import traceback
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from shared.conventions import PANOS_DIR

from pipeline.db import connect, media_url, rows
from pipeline.matterport import Matterport, MatterportError, face_urls
from pipeline.tables import ensure_tables

CAMERA_HEIGHT_M = float(os.getenv("MATTERPORT_CAMERA_HEIGHT_M", "1.25"))  # observed ~1.25 m above the floor
UP_AXIS = os.getenv("MATTERPORT_UP_AXIS", "auto")  # auto | y | z
DEFURNISHED_HINTS = ("defurn", "empty", "unfurn", "vacant", "clear")


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #


def detect_up_axis(panos: list[dict]) -> str:
    if UP_AXIS in ("y", "z"):
        return UP_AXIS
    pts = [p["position"] for p in panos if p.get("position")]
    if len(pts) < 3:
        return "y"
    var_y = statistics.pvariance([p["y"] for p in pts])
    var_z = statistics.pvariance([p["z"] for p in pts])
    return "y" if var_y <= var_z else "z"


def to_yup(pos: dict, up: str) -> tuple[float, float, float]:
    x, y, z = pos["x"], pos["y"], pos["z"]
    return (x, y, z) if up == "y" else (x, z, -y)


def quat_to_yup(q: dict | None, up: str) -> tuple[float, float, float, float] | None:
    if not q:
        return None
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    if up == "y":
        return (x, y, z, w)
    # r = -90 deg about x (maps z-up to y-up); result = r * q
    s = math.sqrt(0.5)
    rx, ry, rz, rw = -s, 0.0, 0.0, s
    return (
        rw * x + rx * w + ry * z - rz * y,
        rw * y - rx * z + ry * w + rz * x,
        rw * z + rx * y - ry * x + rz * w,
        rw * w - rx * x - ry * y - rz * z,
    )


def _dim(room: dict) -> dict:
    d = room.get("dimensions")
    if isinstance(d, list):
        d = next((x for x in d if x), None)
    return d or {}


def _metric(d: dict, key: str, area: bool = False) -> float | None:
    v = d.get(key)
    if v is None:
        return None
    imperial = str(d.get("units", "")).lower().startswith("imp")
    return float(v) * ((0.092903 if area else 0.3048) if imperial else 1.0)


OPENING_KIND = {"doorway": "door", "window": "window", "opening": "opening", "divider": "opening"}


def plan_xz(pt: dict, up: str) -> tuple[float, float]:
    """Floor-plan Point2D (same x/y frame as the API's 3D points) -> our y-up (x, z)."""
    return (pt["x"], -pt["y"]) if up == "z" else (pt["x"], pt["y"])


def boundary_geometry(room: dict, up: str):
    """Room outline polygon (shapely, x/z meters) + openings from boundary edges, or (None, [])."""
    from shapely.geometry import LineString, MultiPoint
    from shapely.ops import polygonize, unary_union

    edges = ((room.get("boundary") or {}).get("edges")) or []
    segs, openings = [], []
    for e in edges:
        vs = [plan_xz(v["position"], up) for v in e.get("vertices") or [] if v.get("position")]
        if len(vs) < 2:
            continue
        a, b = vs[0], vs[-1]
        segs.append(LineString([a, b]))
        length = math.dist(a, b)
        for o in e.get("openings") or []:
            if not length or o.get("width") is None or o.get("relativeCenter") is None:
                continue
            c, h = o["relativeCenter"], o["width"] / 2 / length
            t0, t1 = max(0.0, c - h), min(1.0, c + h)
            pa = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
            pb = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            openings.append({"kind": OPENING_KIND.get(o.get("type"), "unknown"), "a": list(pa), "b": list(pb),
                             "lower_m": o.get("lowerElevation"), "type": o.get("type")})
    if len(segs) < 3:
        return None, openings
    polys = list(polygonize(unary_union(segs)))
    poly = max(polys, key=lambda p: p.area) if polys else MultiPoint([c for s in segs for c in s.coords]).convex_hull
    if poly.geom_type != "Polygon" or poly.area < 0.5:
        return None, openings
    return poly, openings


def room_rows(space_id: str, model: dict, up: str, scans_by_room: dict[str, list[tuple]]) -> list[dict]:
    out = []
    for r in model.get("rooms") or []:
        rid = r["id"]
        d = _dim(r)
        pts = scans_by_room.get(rid, [])
        poly, openings = boundary_geometry(r, up)
        area = _metric(d, "areaFloor", area=True)
        if poly is not None:
            coords = [list(c) for c in list(poly.exterior.coords)[:-1]]
            source = "api"
            area = area or poly.area
        else:  # no outline: rectangle from dimensions, centered on the room's scans
            width = _metric(d, "width") or _metric(d, "length")
            depth = _metric(d, "depth")
            if area is None and width and depth:
                area = width * depth
            if not pts and area is None:
                continue
            if not (width and depth):
                width = depth = math.sqrt(area) if area else 4.0
            area = area or width * depth
            cx = statistics.fmean(p[0] for p in pts) if pts else 0.0
            cz = statistics.fmean(p[2] for p in pts) if pts else 0.0
            hw, hd = width / 2, depth / 2
            coords = [[cx - hw, cz - hd], [cx + hw, cz - hd], [cx + hw, cz + hd], [cx - hw, cz + hd]]
            source = "approx_rect"
        # Floor height: doors sit on the floor; else camera height below the scans.
        door_lows = [o["lower_m"] for o in openings if o["type"] == "doorway" and o.get("lower_m") is not None]
        if door_lows:
            floor_y = statistics.median(door_lows)
        elif pts:
            floor_y = statistics.median(p[1] for p in pts) - CAMERA_HEIGHT_M
        else:
            floor_y = 0.0
        ceil = r.get("ceiling") or {}
        cls = [c for c in r.get("classifications") or [] if isinstance(c, dict)]
        tags = r.get("tags") or []
        room_type = (cls[0].get("label") if cls else None) or (tags[0] if tags else None)
        out.append({
            "space_id": space_id,
            "model_id": model["id"],
            "room_id": rid,
            "label": r.get("label") or room_type,
            "room_type": room_type,
            "floor_index": ((r.get("floor") or {}).get("sequence")) or 0,
            "polygon_json": json.dumps(coords),
            "polygon_source": source,
            "floor_y_m": floor_y,
            "ceiling_m": ceil.get("maxHeight") or ceil.get("minHeight") or _metric(d, "height"),
            "area_m2": area,
            "openings_json": json.dumps([{k: o[k] for k in ("kind", "a", "b")} for o in openings]),
        })
    return out


# --------------------------------------------------------------------------- #
# Fetch one model
# --------------------------------------------------------------------------- #


def pick_scans(model: dict, rooms: list[dict], room_of: dict[str, str], n: int | None, poses: dict) -> list[dict]:
    """Up to n scans: one per room, biggest rooms first, the scan nearest each room's center.
    A furniture-free variant at the same spot is preferred when the account has one."""
    panos = model.get("panoLocations") or []
    def is_defurn(p):
        return any(h in str(p.get("variant", "")).lower() for h in DEFURNISHED_HINTS)

    chosen: list[dict] = []
    for room in sorted(rooms, key=lambda r: -(r["area_m2"] or 0)):
        in_room = [p for p in panos if room_of.get(p["id"]) == room["room_id"] and p.get("skybox")]
        if not in_room:
            continue
        poly = json.loads(room["polygon_json"])
        cx = sum(p[0] for p in poly) / len(poly)
        cz = sum(p[1] for p in poly) / len(poly)
        in_room.sort(key=lambda p: (not is_defurn(p), math.dist((poses[p["id"]][0], poses[p["id"]][2]), (cx, cz))))
        chosen.append(in_room[0])
        if n is not None and len(chosen) >= n:
            return chosen
    if n is None:  # 'all': every scan, defurnished first
        rest = [p for p in panos if p not in chosen and p.get("skybox")]
        chosen += sorted(rest, key=lambda p: not is_defurn(p))
    elif not chosen:
        chosen = [p for p in panos if p.get("skybox")][:n]
    return chosen


def fetch_model(mp: Matterport, space_id: str, model_id: str, n_scans: int | None, faces: list[str], images: bool) -> dict:
    model = mp.model(model_id)
    panos = model.get("panoLocations") or []
    up = detect_up_axis(panos)
    poses = {p["id"]: to_yup(p["position"], up) for p in panos if p.get("position")}
    quats = {p["id"]: quat_to_yup(p.get("rotation"), up) for p in panos}

    room_of: dict[str, str] = {}
    for r in model.get("rooms") or []:
        for pl in r.get("panoLocations") or []:
            room_of[pl["id"]] = r["id"]
    scans_by_room: dict[str, list[tuple]] = {}
    for pid, rid in room_of.items():
        if pid in poses:
            scans_by_room.setdefault(rid, []).append(poses[pid])

    rooms = room_rows(space_id, model, up, scans_by_room)
    scans = [{
        "model_id": model_id, "scan_id": p["id"], "room_id": room_of.get(p["id"]), "variant": p.get("variant"),
        **dict(zip(["px", "py", "pz"], poses.get(p["id"], (None, None, None)))),
        **dict(zip(["qx", "qy", "qz", "qw"], quats.get(p["id"]) or (None, None, None, None))),
    } for p in panos]

    pano_rows = []
    if images:
        out_dir = PANOS_DIR / model_id
        out_dir.mkdir(parents=True, exist_ok=True)
        jobs = []
        for p in pick_scans(model, rooms, room_of, n_scans, poses):
            urls = face_urls(p.get("skybox"))
            defurn = any(h in str(p.get("variant", "")).lower() for h in DEFURNISHED_HINTS)
            for face in faces:
                if face not in urls:
                    continue
                dest = out_dir / f"{p['id']}_{face}.jpg"
                jobs.append((p, face, urls[face], dest, defurn))
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(lambda j: j[3].exists() or mp.download(j[2], j[3]), jobs))
        for p, face, _, dest, defurn in jobs:
            if not dest.exists():
                continue
            with Image.open(dest) as im:
                w, h = im.size
            pos = poses.get(p["id"], (0.0, 0.0, 0.0))
            q = quats.get(p["id"]) or (None, None, None, None)
            pano_rows.append({
                "pano_id": f"{model_id}:{p['id']}:{face}", "space_id": space_id, "model_id": model_id,
                "scan_id": p["id"], "room_id": room_of.get(p["id"]), "face": face, "path": media_url(dest),
                "defurnished": defurn, "px": pos[0], "py": pos[1], "pz": pos[2],
                "qx": q[0], "qy": q[1], "qz": q[2], "qw": q[3], "fov_deg": 90.0, "width_px": w, "height_px": h,
            })
    return {"model": model, "up": up, "rooms": rooms, "scans": scans, "panos": pano_rows}


def _insert(con, table: str, recs: list[dict]) -> None:
    if not recs:
        return
    cols = list(recs[0].keys())
    con.executemany(
        f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        if table == "mp_panos" else
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        [[r[c] for c in cols] for r in recs],
    )


def save(space_id: str, model_id: str, res: dict | None, error: str | None) -> None:
    with connect(read_only=False) as con:
        ensure_tables(con)
        if res is not None:
            con.execute("DELETE FROM mp_rooms WHERE model_id = ?", [model_id])
            con.execute("DELETE FROM mp_scans WHERE model_id = ?", [model_id])
            _insert(con, "mp_rooms", res["rooms"])
            _insert(con, "mp_scans", res["scans"])
            _insert(con, "mp_panos", res["panos"])
        status = "ok" if res is not None and res["rooms"] else ("no_rooms" if res is not None else "error")
        raw = json.dumps(res["model"])[:2_000_000] if res is not None else None
        con.execute("INSERT OR REPLACE INTO mp_fetch_log (model_id, status, error, raw_json) VALUES (?, ?, ?, ?)",
                    [model_id, status, error, raw])


def targets(space_ids: list[str] | None, force: bool, limit: int | None) -> list[dict]:
    with connect() as con:
        ensure_ok = "TRUE" if force else "l.status IS DISTINCT FROM 'ok'"
        if space_ids:
            sql = f"""SELECT s.space_id, s.matterport_model_id FROM spaces s
                      LEFT JOIN mp_fetch_log l ON l.model_id = s.matterport_model_id
                      WHERE s.space_id IN ({', '.join('?' * len(space_ids))}) AND s.matterport_model_id IS NOT NULL AND {ensure_ok}"""
            return rows(con, sql, space_ids)
        sql = f"""SELECT s.space_id, s.matterport_model_id FROM candidates c JOIN spaces s USING (space_id)
                  LEFT JOIN mp_fetch_log l ON l.model_id = s.matterport_model_id
                  WHERE s.matterport_model_id IS NOT NULL AND {ensure_ok}
                  ORDER BY c.priority, s.space_id {f'LIMIT {int(limit)}' if limit else ''}"""
        return rows(con, sql)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space-ids", help="comma-separated space_ids")
    ap.add_argument("--scans", default="2", help="scans per model with images, or 'all'")
    ap.add_argument("--faces", default="front,right,back,left")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    with connect(read_only=False) as con:
        ensure_tables(con)
    mp = Matterport()
    todo = targets(a.space_ids.split(",") if a.space_ids else None, a.force, a.limit)
    n_scans = None if a.scans == "all" else int(a.scans)
    faces = a.faces.split(",")
    print(f"{len(todo)} models to fetch")
    seen_models: set[str] = set()
    for i, t in enumerate(todo, 1):
        sid, mid = t["space_id"], t["matterport_model_id"]
        if mid in seen_models:
            continue
        seen_models.add(mid)
        try:
            res = fetch_model(mp, sid, mid, n_scans, faces, not a.no_images)
            save(sid, mid, res, None)
            print(f"[{i}/{len(todo)}] {sid} {mid}: {len(res['rooms'])} rooms, {len(res['scans'])} scans, "
                  f"{len(res['panos'])} faces (up={res['up']})")
        except (MatterportError, Exception) as e:  # log and move on
            save(sid, mid, None, f"{type(e).__name__}: {e}"[:1000])
            print(f"[{i}/{len(todo)}] {sid} {mid}: FAILED {e}")
            if not isinstance(e, MatterportError):
                traceback.print_exc(limit=2)


if __name__ == "__main__":
    main()
