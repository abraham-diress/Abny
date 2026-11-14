"""What's cached per space: rooms, panos (files on disk), Vexcel, aerials. Use it for D7 (demo cache).

    python -m pipeline.cache_status                  # demo spaces (priority 0) + summary
    python -m pipeline.cache_status --space-ids a,b
    python -m pipeline.cache_status --set-demo a,b,c,d,e   # mark these as the 5 demo spaces (fetched first)
"""

from __future__ import annotations

import argparse

from shared.conventions import REPO_ROOT

from pipeline.db import connect, rows
from pipeline.tables import ensure_tables


def file_ok(url_path: str | None) -> bool:
    return bool(url_path) and (REPO_ROOT / "data" / url_path).exists()


def status(space_ids: list[str]) -> list[dict]:
    out = []
    with connect() as con:
        for sid in space_ids:
            s = rows(con, "SELECT space_id, address, matterport_model_id AS mid, asking_rent_month FROM spaces WHERE space_id = ?", [sid])
            if not s:
                out.append({"space_id": sid, "error": "not in spaces"})
                continue
            s = s[0]
            mid = s["mid"]
            n_rooms, room_m2 = con.execute("SELECT count(*), sum(area_m2) FROM mp_rooms WHERE model_id = ?", [mid]).fetchone() if mid else (0, None)
            sqft = con.execute("SELECT sqft FROM spaces WHERE space_id = ?", [sid]).fetchone()[0]
            panos = rows(con, "SELECT path FROM mp_panos WHERE model_id = ?", [mid]) if mid else []
            vx = rows(con, "SELECT status, ortho_path, oblique_path, parking_score FROM vx_props WHERE space_id = ?", [sid])
            vx = vx[0] if vx else {}
            out.append({
                "space_id": sid, "address": s["address"], "rent": s["asking_rent_month"] is not None,
                "rooms": n_rooms,
                # ~1.0 = the scan covers about the listed suite; >> 1 = a scan of the whole building
                "scan_vs_listing_area": round(room_m2 * 10.7639 / sqft, 1) if (room_m2 and sqft) else None,
                "panos": sum(file_ok(p["path"]) for p in panos), "panos_missing": sum(not file_ok(p["path"]) for p in panos),
                "vexcel": vx.get("status"), "ortho": file_ok(vx.get("ortho_path")), "oblique": file_ok(vx.get("oblique_path")),
                "parking": vx.get("parking_score") is not None,
            })
    for r in out:
        r["complete"] = bool(r.get("rooms") and r.get("panos", 0) >= 4 and r.get("ortho") and r.get("rent"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space-ids")
    ap.add_argument("--set-demo")
    a = ap.parse_args()
    if a.set_demo:
        ids = a.set_demo.split(",")
        with connect(read_only=False) as con:
            ensure_tables(con, ["candidates"])
            for sid in ids:
                con.execute("INSERT OR REPLACE INTO candidates VALUES (?, 0, 'demo')", [sid])
        print(f"marked {len(ids)} demo spaces; now run fetch_matterport --space-ids ... --scans all and fetch_vexcel --space-ids ...")
        return
    with connect() as con:
        ids = a.space_ids.split(",") if a.space_ids else [r[0] for r in con.execute("SELECT space_id FROM candidates WHERE priority = 0").fetchall()]
        summary = con.execute("""SELECT (SELECT count(*) FROM candidates), (SELECT count(DISTINCT model_id) FROM mp_rooms),
                                        (SELECT count(*) FROM mp_panos), (SELECT count(*) FROM vx_props WHERE status='ok'),
                                        (SELECT count(*) FROM mp_fetch_log WHERE status <> 'ok')""").fetchone()
    print(f"candidates {summary[0]} | models with rooms {summary[1]} | pano faces {summary[2]} | vexcel ok {summary[3]} | matterport failures {summary[4]}")
    for r in status(ids):
        flag = "OK  " if r.get("complete") else "TODO"
        print(f"{flag} {r}")


if __name__ == "__main__":
    main()
