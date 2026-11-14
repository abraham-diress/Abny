"""Step 4: Vexcel parcel data, ortho + oblique crops and a parking score per candidate.

    python -m pipeline.fetch_vexcel                    # all candidates, demo first
    python -m pipeline.fetch_vexcel --space-ids a,b    # just these
    python -m pipeline.fetch_vexcel --no-images        # parcel data only
    python -m pipeline.fetch_vexcel --no-detect        # skip car/parking-lot detection (faster)
    python -m pipeline.fetch_vexcel --force

Resumable (skips spaces with status 'ok'). Writes vx_props and
data/media/aerial/<space_id>_ortho.jpg / <space_id>_oblique.jpg.
"""

from __future__ import annotations

import argparse
import json

from shared.conventions import AERIAL_DIR

from pipeline.db import connect, media_url, rows
from pipeline.tables import ensure_tables
from pipeline.vexcel import (NO_PARCEL_HALF_M, Vexcel, VexcelError, footprint_wkt, parcel_and_attrs,
                             parking_from_detections, square_wkt)


def targets(space_ids: list[str] | None, force: bool, limit: int | None) -> list[dict]:
    cond = "TRUE" if force else "v.status IS DISTINCT FROM 'ok'"
    with connect() as con:
        if space_ids:
            return rows(con, f"""SELECT s.space_id, s.lat, s.lon FROM spaces s LEFT JOIN vx_props v USING (space_id)
                                 WHERE s.space_id IN ({', '.join('?' * len(space_ids))}) AND {cond}""", space_ids)
        return rows(con, f"""SELECT s.space_id, s.lat, s.lon FROM candidates c JOIN spaces s USING (space_id)
                             LEFT JOIN vx_props v USING (space_id) WHERE {cond}
                             ORDER BY c.priority, s.space_id {f'LIMIT {int(limit)}' if limit else ''}""")


def fetch_one(vx: Vexcel, t: dict, images: bool, detect: bool) -> dict:
    sid, lat, lon = t["space_id"], t["lat"], t["lon"]
    rec = {"space_id": sid, "footprint_wkt": None, "parcel_wkt": None, "attrs_json": None, "parking_score": None,
           "parking_notes": None, "ortho_path": None, "oblique_path": None, "status": "ok", "error": None}
    errors: list[str] = []

    try:
        prop = vx.property(lat, lon)
        parcel, attrs = parcel_and_attrs(prop)
        rec["parcel_wkt"] = parcel
        rec["footprint_wkt"] = footprint_wkt(attrs)
        rec["attrs_json"] = json.dumps(attrs)[:500_000] if attrs else None
    except VexcelError as e:
        parcel = None
        errors.append(str(e))
    area = rec["parcel_wkt"] or square_wkt(lat, lon, NO_PARCEL_HALF_M)

    if images:
        AERIAL_DIR.mkdir(parents=True, exist_ok=True)
        ortho = AERIAL_DIR / f"{sid}_ortho.jpg"
        try:
            if not ortho.exists():
                ortho.write_bytes(vx.ortho(area))
            rec["ortho_path"] = media_url(ortho)
        except VexcelError as e:
            errors.append(str(e))
        obl = AERIAL_DIR / f"{sid}_oblique.jpg"
        try:
            if not obl.exists():
                dirs = vx.oblique_directions(area)
                if dirs:
                    obl.write_bytes(vx.oblique(area, dirs[0]))
            if obl.exists():
                rec["oblique_path"] = media_url(obl)
        except VexcelError as e:
            errors.append(str(e))

    if detect:
        try:
            dets = vx.detect(area, ["parking lot", "car"])
            rec["parking_score"], rec["parking_notes"] = parking_from_detections(dets)
        except VexcelError as e:
            errors.append(str(e))

    if errors:
        rec["error"] = " | ".join(errors)[:1000]
        rec["status"] = "partial" if (rec["parcel_wkt"] or rec["ortho_path"] or rec["parking_score"] is not None) else "error"
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space-ids")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--no-detect", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    with connect(read_only=False) as con:
        ensure_tables(con)
    vx = Vexcel()
    todo = targets(a.space_ids.split(",") if a.space_ids else None, a.force, a.limit)
    print(f"{len(todo)} spaces to fetch")
    for i, t in enumerate(todo, 1):
        rec = fetch_one(vx, t, not a.no_images, not a.no_detect)
        cols = list(rec)
        with connect(read_only=False) as con:
            con.execute(f"INSERT OR REPLACE INTO vx_props ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [rec[c] for c in cols])
        print(f"[{i}/{len(todo)}] {t['space_id']}: {rec['status']} parking={rec['parking_score']}"
              + (f" ({rec['error'][:120]})" if rec["error"] else ""))


if __name__ == "__main__":
    main()
