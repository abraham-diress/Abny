"""Kickoff checks G1 (scan coverage) and G4 (Matterport room fields). Paste the output in chat.

    python -m pipeline.gates g1          # needs ingest done; retail/restaurant and office counted separately
    python -m pipeline.gates g1-classify # drop scans that are apartment units (calls Matterport, ~1-3 min)
    python -m pipeline.gates g4          # needs Matterport keys; uses the first scanned candidate
    python -m pipeline.gates g4 --model <matterport_model_id>
    python -m pipeline.gates             # both
"""

from __future__ import annotations

import argparse
import json
import re

from pipeline.db import connect, rows

G1_THRESHOLD = 30


# Space groups the gates count separately (business_type -> which spaces it can use).
GROUPS = {"retail/restaurant": "RETAIL_SPACES_SQL", "office": "OFFICE_SPACES_SQL"}


def _group_sql() -> dict[str, str]:
    from pipeline import queries
    return {g: getattr(queries, attr) for g, attr in GROUPS.items()}


def g1() -> None:
    """Scanned listings in Houston + LA, counted separately for retail/restaurant and office."""
    with connect() as con:
        total = con.execute("SELECT count(*) FROM spaces").fetchone()[0]
        print(f"G1 coverage: {total} spaces in DB")
        print(f"  {'group':<18}{'city':<14}{'listings':>9}{'scanned':>9}{'own scan':>10}{'+rent':>7}")
        for group, cond in _group_sql().items():
            res = rows(con, f"""
                SELECT COALESCE(city, '(other)') AS city, count(*) AS listings,
                       count(*) FILTER (WHERE has_scan) AS scanned,
                       count(*) FILTER (WHERE scan_level IN ('space', 'listing')) AS own_scan,
                       count(*) FILTER (WHERE has_scan AND asking_rent_month IS NOT NULL) AS scanned_with_rent
                FROM spaces WHERE {cond} GROUP BY 1 ORDER BY 1""")
            for r in res:
                print(f"  {group:<18}{r['city']:<14}{r['listings']:>9}{r['scanned']:>9}{r['own_scan']:>10}{r['scanned_with_rent']:>7}")
            n = sum(r["scanned"] for r in res if r["city"] != "(other)")
            verdict = "listings mode OK" if n >= G1_THRESHOLD else "BROKER MODE: python -m pipeline.ingest_costar --skip-raw --mode broker"
            print(f"  RESULT {group}: {n} scanned listings in Houston+LA -> {verdict}")
    print("  ('own scan' = a scan of the suite or attached to the listing; the rest are some scan of the building.")
    print("   Run `python -m pipeline.gates g1-classify` to drop scans that are apartment units.)")


RESIDENTIAL_ROOMS = {"bedroom", "master bedroom", "primary bedroom", "nursery", "laundry room"}


def classify_models(limit: int | None = None) -> None:
    """Look up the Matterport model behind each retail and office listing: commercial interior or an apartment?

    Writes mp_model_info(model_id, name, n_rooms, room_labels, is_residential). Resumable.
    """
    from pipeline.matterport import Matterport, MatterportError

    groups = _group_sql()
    any_group = " OR ".join(f"({c})" for c in groups.values())
    q = "query($id: ID!){ model(id:$id){ id name rooms { classifications { label } } } }"
    with connect(read_only=False) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS mp_model_info (model_id VARCHAR PRIMARY KEY, name VARCHAR,
                       n_rooms INTEGER, room_labels VARCHAR, is_residential BOOLEAN, error VARCHAR)""")
        todo = [r[0] for r in con.execute(f"""
            SELECT DISTINCT matterport_model_id FROM spaces
            WHERE has_scan AND ({any_group})
              AND matterport_model_id NOT IN (SELECT model_id FROM mp_model_info)""").fetchall()]
    todo = todo[:limit] if limit else todo
    mp = Matterport(min_interval_s=0.1)
    print(f"classifying {len(todo)} models")
    out = []
    for i, mid in enumerate(todo, 1):
        try:
            m = (mp.gql(q, {"id": mid}).get("data") or {}).get("model") or {}
            labels = [c["label"] for r in m.get("rooms") or [] for c in (r.get("classifications") or [])[:1]]
            name = m.get("name") or ""
            resid = bool(RESIDENTIAL_ROOMS & {x.lower() for x in labels}) or bool(re.search(r"\b\d\s*(BR|bed)", name, re.I))
            out.append((mid, name, len(m.get("rooms") or []), ", ".join(sorted(set(labels))), resid, None))
        except MatterportError as e:
            out.append((mid, None, None, None, None, str(e)[:300]))
        if i % 50 == 0 or i == len(todo):
            with connect(read_only=False) as con:
                con.executemany("INSERT OR REPLACE INTO mp_model_info VALUES (?, ?, ?, ?, ?, ?)", out)
            out = []
            print(f"  {i}/{len(todo)}")
    with connect() as con:
        for group, cond in groups.items():
            res = rows(con, f"""
                SELECT s.city, s.scan_level, count(*) AS spaces,
                       count(*) FILTER (WHERE NOT i.is_residential) AS commercial_scan,
                       count(*) FILTER (WHERE i.is_residential) AS apartment_scan,
                       count(*) FILTER (WHERE NOT i.is_residential AND s.asking_rent_month IS NOT NULL) AS commercial_with_rent
                FROM spaces s JOIN mp_model_info i ON i.model_id = s.matterport_model_id
                WHERE {cond.replace('space_use', 's.space_use').replace('property_type', 's.property_type')}
                GROUP BY ALL ORDER BY 1, 2""")
            print(f"  [{group}]")
            for r in res:
                print(f"    {r}")
            n = sum(r["commercial_scan"] for r in res)
            print(f"  RESULT {group}: {n} spaces whose scan is a commercial interior "
                  f"({'listings mode OK' if n >= G1_THRESHOLD else 'BROKER MODE'})")


def g4(model_id: str | None) -> None:
    from pipeline.fetch_matterport import _dim, detect_up_axis
    from pipeline.matterport import Matterport, face_urls

    mp = Matterport()
    if not model_id:
        with connect() as con:
            r = con.execute("""SELECT s.matterport_model_id FROM candidates c JOIN spaces s USING (space_id)
                               WHERE s.matterport_model_id IS NOT NULL ORDER BY c.priority LIMIT 1""").fetchone()
        if not r:
            raise SystemExit("No scanned candidate in DB; pass --model <id>")
        model_id = r[0]
    print(f"G4 room data, model {model_id}")
    for t in ["ModelRoom", "Dimension", "PanoramicImageLocation", "SkyboxPanorama"]:
        f = mp.schema.get(t) or {}
        print(f"  schema {t}: {', '.join(sorted(f)) if f else '(introspection unavailable)'}")
    try:
        types = mp.gql("{ __schema { types { name } } }")["data"]["__schema"]["types"]
        hits = sorted(t["name"] for t in types if any(k in t["name"].lower() for k in ("door", "window", "opening", "wall", "floorplan", "boundary")))
        print(f"  door/window/wall-like types in schema: {hits or 'none'}")
    except Exception as e:
        print(f"  (schema type list unavailable: {e})")

    m = mp.model(model_id)
    rooms, panos = m.get("rooms") or [], m.get("panoLocations") or []
    dims = [_dim(r) for r in rooms]
    have = lambda k: sum(1 for d in dims if d.get(k) is not None)  # noqa: E731
    variants = sorted({str(p.get("variant")) for p in panos})
    sky = next((p.get("skybox") for p in panos if p.get("skybox")), None)
    print(f"  rooms: {len(rooms)}; labels: {[r.get('label') for r in rooms][:10]}")
    print(f"  tags/classes: {[r.get('tags') or r.get('classifications') for r in rooms][:5]}")
    print(f"  dimension fields present (rooms with value): areaFloor {have('areaFloor')}, height(ceiling) {have('height')}, "
          f"width {have('width')}, depth {have('depth')}; units={dims[0].get('units') if dims else None}")
    print(f"  scans: {len(panos)}; variants: {variants}; up axis detected: {detect_up_axis(panos)}")
    print(f"  skybox faces available: {sorted(face_urls(sky)) if sky else 'none'}; status={sky.get('status') if sky else None}")
    print("  polygons: Model API gives no room outline -> approx rectangles from dimensions (polygon_source='approx_rect')")
    print("  RESULT: missing fields get defaults; tell Yared which of ceiling/doors/windows are missing (unverified_fields).")
    print("  sample room JSON:", json.dumps(rooms[0])[:600] if rooms else None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", nargs="?", choices=["g1", "g1-classify", "g4", "all"], default="all")
    ap.add_argument("--model")
    a = ap.parse_args()
    if a.which in ("g1", "all"):
        g1()
    if a.which == "g1-classify":
        classify_models()
    if a.which in ("g4", "all"):
        print()
        g4(a.model)


if __name__ == "__main__":
    main()
