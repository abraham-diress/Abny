"""Step 1 + 2: CoStar dump (JSON/CSV/Parquet) + Matterport join CSVs -> DuckDB.

    python -m pipeline.ingest_costar                 # load raw + build normalized tables
    python -m pipeline.ingest_costar --show-mapping  # print detected datasets/columns, then exit
    python -m pipeline.ingest_costar --mode broker   # G1 failed: vacant scanned properties instead of listings
    python -m pipeline.ingest_costar --skip-raw      # rebuild normalized tables from existing raw_* tables

Reads every file under COSTAR_DATA_DIR (default data/costar_raw). Each file becomes a
``raw_<name>`` table; nested JSON objects are flattened to ``parent__child`` columns.
Then builds ``spaces``, ``candidates``, ``tenants`` and ``residential`` (see pipeline/tables.py).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from shared.conventions import DATA_DIR, REPO_ROOT

from pipeline import colmap
from pipeline.db import METRO_RADIUS_M, METROS, connect, rows
from pipeline.tables import ensure_tables

RAW_EXTS = {".json", ".jsonl", ".ndjson", ".csv", ".parquet", ".geojson"}
FLAT_DIR = DATA_DIR / "_flat"

# Property types we keep as candidates for food/retail businesses.
RETAILISH = ["retail", "restaurant", "storefront", "shop", "flex", "mixed", "general", "strip", "freestanding", "food", "commercial"]


# --------------------------------------------------------------------------- #
# Raw load
# --------------------------------------------------------------------------- #


def raw_dir() -> Path:
    d = os.getenv("COSTAR_DATA_DIR") or str(DATA_DIR / "costar_raw")
    p = Path(d)
    return p if p.is_absolute() else REPO_ROOT / p


def table_name_for(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("").as_posix()
    return "raw_" + re.sub(r"[^a-z0-9]+", "_", rel.lower()).strip("_")


def _flatten(obj: dict, prefix: str = "", out: dict | None = None) -> dict:
    out = {} if out is None else out
    for k, v in obj.items():
        key = f"{prefix}__{k}" if prefix else str(k)
        if isinstance(v, dict):
            _flatten(v, key, out)
        elif isinstance(v, list):
            # GeoJSON-style coordinates or lists of records: keep as JSON text.
            out[key] = json.dumps(v)
        else:
            out[key] = v
    return out


def _records_from_json(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix in {".jsonl", ".ndjson"}:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:  # NDJSON with a .json extension
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if data.get("type") == "FeatureCollection":
            return [{**(f.get("properties") or {}), "geometry": f.get("geometry")} for f in data.get("features", [])]
        lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if lists:
            return max(lists, key=len)
        return [data]
    return []


def load_raw(con, root: Path) -> list[str]:
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in RAW_EXTS)
    if not files:
        sys.exit(f"No CoStar files found under {root}. Set COSTAR_DATA_DIR in .env.")
    FLAT_DIR.mkdir(parents=True, exist_ok=True)
    loaded = []
    for f in files:
        name = table_name_for(f, root)
        try:
            if f.suffix.lower() == ".csv":
                con.execute(
                    f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_csv_auto(?, sample_size=-1, ignore_errors=true)",
                    [str(f)],
                )
            elif f.suffix.lower() == ".parquet":
                con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_parquet(?)", [str(f)])
            else:
                recs = [_flatten(r) for r in _records_from_json(f) if isinstance(r, dict)]
                if not recs:
                    print(f"  ! {f.name}: no records, skipped")
                    continue
                flat = FLAT_DIR / f"{name}.ndjson"
                with flat.open("w", encoding="utf-8") as fh:
                    for r in recs:
                        fh.write(json.dumps(r, default=str) + "\n")
                con.execute(
                    f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_json_auto(?, format='newline_delimited', "
                    "union_by_name=true, sample_size=-1, maximum_object_size=100000000)",
                    [str(flat)],
                )
            n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            print(f"  {name:<50} {n:>8} rows   <- {f.relative_to(root)}")
            loaded.append(name)
        except Exception as e:  # keep going; one bad file shouldn't stop ingest
            print(f"  ! {f.name}: {e}")
    return loaded


# --------------------------------------------------------------------------- #
# Mapping
# --------------------------------------------------------------------------- #


def raw_tables(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'raw_%' ORDER BY table_name"
    ).fetchall()]


def columns_of(con, table: str) -> list[str]:
    return [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]


def build_mapping(con) -> dict[str, dict]:
    """role -> {'tables': [...], 'cols': {table: {field: column}}}"""
    ov = colmap.load_overrides()
    forced = ov.get("datasets", {})
    roles: dict[str, dict] = {}
    for t in raw_tables(con):
        role = next((r for r, tbl in forced.items() if tbl == t or (isinstance(tbl, list) and t in tbl)), None)
        role = role or colmap.detect_role(t)
        if role is None:
            continue
        cols = columns_of(con, t)
        entry = roles.setdefault(role, {"tables": [], "cols": {}})
        entry["tables"].append(t)
        entry["cols"][t] = colmap.resolve_columns(role, cols, ov)
    return roles


def print_mapping(mapping: dict[str, dict]) -> None:
    for role, e in mapping.items():
        print(f"\n[{role}]")
        for t in e["tables"]:
            print(f"  {t}")
            for field, col in e["cols"][t].items():
                print(f"      {field:<16} -> {col if col else '-- not found --'}")


# --------------------------------------------------------------------------- #
# SQL helpers over dynamic columns
# --------------------------------------------------------------------------- #


def q(col: str | None, alias: str = "") -> str:
    if not col:
        return "NULL"
    return f'{alias + "." if alias else ""}"{col}"'


def num(expr: str) -> str:
    """Parse '$1,234.50/SF/YR' -> 1234.5 (first number), NULL if none."""
    if expr == "NULL":
        return "CAST(NULL AS DOUBLE)"
    return f"TRY_CAST(regexp_extract(replace(CAST({expr} AS VARCHAR), ',', ''), '-?[0-9]+(\\.[0-9]+)?', 0) AS DOUBLE)"


def txt(expr: str) -> str:
    return "CAST(NULL AS VARCHAR)" if expr == "NULL" else f"NULLIF(trim(CAST({expr} AS VARCHAR)), '')"


def union_role(mapping: dict, role: str, fields: list[str]) -> str | None:
    """SELECT of the given logical fields across all tables of a role, as one UNION ALL."""
    e = mapping.get(role)
    if not e:
        return None
    parts = []
    for t in e["tables"]:
        c = e["cols"][t]
        sel = ", ".join(f"{q(c.get(f))} AS {f}" if c.get(f) else f"NULL AS {f}" for f in fields)
        parts.append(f"SELECT {sel}, '{t}' AS _table FROM {t}")
    return " UNION ALL BY NAME ".join(parts)


def city_sql(city_expr: str, lat: str, lon: str) -> str:
    """CASE mapping raw city text / coordinates to 'Houston' | 'Los Angeles' | NULL."""
    dist = lambda c: (  # noqa: E731  equirectangular distance in meters, fine at metro scale
        f"(111320 * sqrt(power({lat} - {c[0]}, 2) + power(({lon} - ({c[1]})) * cos(radians({c[0]})), 2)))"
    )
    h, la = METROS["Houston"], METROS["Los Angeles"]
    return f"""CASE
        WHEN lower(CAST({city_expr} AS VARCHAR)) LIKE '%houston%' THEN 'Houston'
        WHEN lower(CAST({city_expr} AS VARCHAR)) LIKE '%los angeles%' THEN 'Los Angeles'
        WHEN {lat} IS NOT NULL AND {dist(h)} < {METRO_RADIUS_M} THEN 'Houston'
        WHEN {lat} IS NOT NULL AND {dist(la)} < {METRO_RADIUS_M} THEN 'Los Angeles'
        ELSE NULL END"""


# --------------------------------------------------------------------------- #
# Normalized tables
# --------------------------------------------------------------------------- #


def build_property_view(con, mapping: dict) -> bool:
    fields = ["property_id", "lat", "lon", "address", "city", "state", "property_type", "sqft", "year_built",
              "parking_ratio", "parking_spaces", "vacant_sf", "vacancy_pct"]
    sql = union_role(mapping, "commercial_property", fields)
    if not sql:
        con.execute("""CREATE OR REPLACE TEMP VIEW prop AS SELECT NULL::VARCHAR AS pid, NULL::DOUBLE AS lat,
            NULL::DOUBLE AS lon, NULL::VARCHAR AS address, NULL::VARCHAR AS city, NULL::VARCHAR AS state,
            NULL::VARCHAR AS property_type, NULL::DOUBLE AS sqft, NULL::INTEGER AS year_built,
            NULL::DOUBLE AS parking_ratio, NULL::INTEGER AS parking_spaces, NULL::DOUBLE AS vacant_sf,
            NULL::DOUBLE AS vacancy_pct, NULL::VARCHAR AS _table WHERE false""")
        return False
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW prop AS
        SELECT CAST(property_id AS VARCHAR) AS pid,
               {num('lat')} AS lat, {num('lon')} AS lon,
               {txt('address')} AS address, {txt('city')} AS city, {txt('state')} AS state,
               {txt('property_type')} AS property_type, {num('sqft')} AS sqft,
               CAST({num('year_built')} AS INTEGER) AS year_built,
               {num('parking_ratio')} AS parking_ratio, CAST({num('parking_spaces')} AS INTEGER) AS parking_spaces,
               {num('vacant_sf')} AS vacant_sf, {num('vacancy_pct')} AS vacancy_pct,
               _table
        FROM ({sql})
        WHERE property_id IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY CAST(property_id AS VARCHAR) ORDER BY _table) = 1
    """)
    return True


def build_join_view(con, mapping: dict) -> bool:
    sql = union_role(mapping, "mp_join", ["property_id", "listing_id", "model_id", "model_url"])
    if not sql:
        con.execute("CREATE OR REPLACE TEMP VIEW mpj AS SELECT NULL::VARCHAR AS pid, NULL::VARCHAR AS lid, NULL::VARCHAR AS model_id WHERE false")
        return False
    # If only a tour URL is given, pull the model id out of '...show/?m=<id>'.
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW mpj AS
        SELECT CAST(property_id AS VARCHAR) AS pid, CAST(listing_id AS VARCHAR) AS lid,
               COALESCE({txt('model_id')}, NULLIF(regexp_extract(CAST(model_url AS VARCHAR), '[?&]m=([A-Za-z0-9]+)', 1), '')) AS model_id
        FROM ({sql})
    """)
    return True


def build_spaces(con, mapping: dict, mode: str) -> int:
    con.execute("DROP TABLE IF EXISTS spaces")
    ensure_tables(con, ["spaces"])
    has_prop = build_property_view(con, mapping)
    build_join_view(con, mapping)
    mp_by_lid = "(SELECT lid, any_value(model_id) AS model_id FROM mpj WHERE model_id IS NOT NULL AND lid IS NOT NULL GROUP BY lid)"
    mp_by_pid = "(SELECT pid, any_value(model_id) AS model_id FROM mpj WHERE model_id IS NOT NULL AND pid IS NOT NULL GROUP BY pid)"

    if mode == "listings":
        fields = ["listing_id", "property_id", "lat", "lon", "address", "city", "property_type", "sqft", "rent_month",
                  "rent_psf", "rent_unit", "broker_name", "broker_company", "broker_email", "broker_phone"]
        sql = union_role(mapping, "commercial_listing", fields)
        if not sql:
            sys.exit("No commercial_listing table detected. Fix pipeline/colmap.json or use --mode broker.")
        # rent_unit falls back to the rent text itself ('$32/SF/YR'); <8 $/sf is almost surely monthly.
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW lst AS
            WITH l AS (
                SELECT CAST(listing_id AS VARCHAR) AS lid, CAST(property_id AS VARCHAR) AS pid,
                       {num('lat')} AS lat, {num('lon')} AS lon, {txt('address')} AS address, {txt('city')} AS city,
                       {txt('property_type')} AS property_type, {num('sqft')} AS sqft,
                       {num('rent_month')} AS rent_month, {num('rent_psf')} AS rent_psf,
                       lower(COALESCE(CAST(rent_unit AS VARCHAR), CAST(rent_psf AS VARCHAR), '')) AS unit_txt,
                       {txt('broker_name')} AS broker_name, {txt('broker_company')} AS broker_company,
                       {txt('broker_email')} AS broker_email, {txt('broker_phone')} AS broker_phone, _table
                FROM ({sql})
                WHERE listing_id IS NOT NULL
            )
            SELECT *,
                CASE WHEN rent_psf IS NULL THEN NULL
                     WHEN unit_txt LIKE '%mo%' THEN rent_psf * 12
                     WHEN unit_txt LIKE '%yr%' OR unit_txt LIKE '%year%' OR unit_txt LIKE '%ann%' THEN rent_psf
                     WHEN rent_psf < 8 THEN rent_psf * 12
                     ELSE rent_psf END AS psf_year,
                CASE WHEN rent_psf IS NULL THEN NULL
                     WHEN unit_txt LIKE '%mo%' THEN 'rent quoted $/sf/month'
                     WHEN unit_txt LIKE '%yr%' OR unit_txt LIKE '%year%' OR unit_txt LIKE '%ann%' THEN 'rent quoted $/sf/year'
                     WHEN rent_psf < 8 THEN 'unit not given; < $8/sf assumed monthly'
                     ELSE 'unit not given; assumed $/sf/year' END AS rent_note
            FROM l
            QUALIFY row_number() OVER (PARTITION BY lid ORDER BY _table) = 1
        """)
        p = "p" if has_prop else None
        pj = "LEFT JOIN prop p ON p.pid = l.pid" if has_prop else ""
        lat = f"COALESCE(l.lat, {p}.lat)" if p else "l.lat"
        lon = f"COALESCE(l.lon, {p}.lon)" if p else "l.lon"
        con.execute(f"""
            INSERT INTO spaces
            SELECT 'cs-l-' || l.lid, l.pid, l.lid, COALESCE(ml.model_id, mp.model_id),
                   COALESCE(l.address, {'p.address' if p else 'NULL'}, 'Address not listed'),
                   {city_sql('COALESCE(l.city, ' + ('p.city' if p else 'NULL') + ')', lat, lon)},
                   {lat}, {lon},
                   COALESCE(l.property_type, {'p.property_type' if p else 'NULL'}),
                   l.sqft,
                   COALESCE(l.rent_month, l.psf_year * l.sqft / 12),
                   COALESCE(l.psf_year, CASE WHEN l.sqft > 0 THEN l.rent_month * 12 / l.sqft END),
                   CASE WHEN l.rent_month IS NOT NULL THEN 'monthly rent from listing' ELSE l.rent_note END,
                   {'p.year_built' if p else 'NULL'},
                   COALESCE(ml.model_id, mp.model_id) IS NOT NULL,
                   {'p.parking_ratio' if p else 'NULL'}, {'p.parking_spaces' if p else 'NULL'},
                   l.broker_name, l.broker_company, l.broker_email, l.broker_phone,
                   l._table, l.lid, FALSE, 'property', NULL, NULL
            FROM lst l {pj}
            LEFT JOIN {mp_by_lid} ml ON ml.lid = l.lid
            LEFT JOIN {mp_by_pid} mp ON mp.pid = l.pid
            WHERE {lat} IS NOT NULL AND {lon} IS NOT NULL
        """)
    else:  # broker mode: vacant (or any) scanned properties
        if not has_prop:
            sys.exit("Broker mode needs a commercial_property table.")
        con.execute(f"""
            INSERT INTO spaces
            SELECT 'cs-p-' || p.pid, p.pid, NULL, mp.model_id,
                   COALESCE(p.address, 'Address not listed'),
                   {city_sql('p.city', 'p.lat', 'p.lon')},
                   p.lat, p.lon, p.property_type, COALESCE(p.vacant_sf, p.sqft), NULL, NULL,
                   'broker mode: no asking rent; market estimate used', p.year_built, TRUE,
                   p.parking_ratio, p.parking_spaces, NULL, NULL, NULL, NULL, p._table, p.pid, FALSE, 'property', NULL, NULL
            FROM prop p JOIN {mp_by_pid} mp ON mp.pid = p.pid
            WHERE p.lat IS NOT NULL AND p.lon IS NOT NULL
              AND (p.vacant_sf IS NULL OR p.vacant_sf > 0)
        """)
    return con.execute("SELECT count(*) FROM spaces").fetchone()[0]


def build_tenants(con, mapping: dict) -> int:
    con.execute("DROP TABLE IF EXISTS tenants")
    ensure_tables(con, ["tenants"])
    occ = union_role(mapping, "location_occupancy", ["property_id", "tenant_name", "company_id", "category", "employees", "lat", "lon", "occupancy_status"])
    comp = union_role(mapping, "company_detail", ["company_id", "tenant_name", "category", "employees", "lat", "lon"])
    if occ:
        comp_join = ""
        cat = "o.category"
        emp = f"CAST({num('o.employees')} AS INTEGER)"
        if comp:
            con.execute(f"""CREATE OR REPLACE TEMP VIEW comp AS
                SELECT CAST(company_id AS VARCHAR) AS cid, any_value({txt('category')}) AS category,
                       any_value(CAST({num('employees')} AS INTEGER)) AS employees
                FROM ({comp}) WHERE company_id IS NOT NULL GROUP BY 1""")
            comp_join = "LEFT JOIN comp c ON c.cid = CAST(o.company_id AS VARCHAR)"
            cat = "COALESCE(o.category, c.category)"
            emp = f"COALESCE(CAST({num('o.employees')} AS INTEGER), c.employees)"
        con.execute(f"""
            INSERT INTO tenants
            SELECT CAST(o.company_id AS VARCHAR), {txt('o.tenant_name')}, {txt(cat)},
                   COALESCE({num('o.lat')}, p.lat), COALESCE({num('o.lon')}, p.lon),
                   {emp}, o._table, CAST(o.property_id AS VARCHAR)
            FROM ({occ}) o
            LEFT JOIN prop p ON p.pid = CAST(o.property_id AS VARCHAR)
            {comp_join}
            WHERE o.tenant_name IS NOT NULL
              AND lower(COALESCE(CAST(o.occupancy_status AS VARCHAR), '')) NOT IN ('vacant', 'true', 'available')
        """)
    elif comp:  # no occupancy table: companies with their own coordinates
        con.execute(f"""
            INSERT INTO tenants
            SELECT CAST(company_id AS VARCHAR), {txt('tenant_name')}, {txt('category')},
                   {num('lat')}, {num('lon')}, CAST({num('employees')} AS INTEGER), _table, CAST(company_id AS VARCHAR)
            FROM ({comp}) WHERE tenant_name IS NOT NULL
        """)
    con.execute("DELETE FROM tenants WHERE lat IS NULL OR lon IS NULL")
    return con.execute("SELECT count(*) FROM tenants").fetchone()[0]


def build_residential(con, mapping: dict) -> int:
    con.execute("DROP TABLE IF EXISTS residential")
    ensure_tables(con, ["residential"])
    for role, default_units in [("apartment_listings", 1), ("residential_listings", 1)]:
        sql = union_role(mapping, role, ["record_id", "property_id", "lat", "lon", "units"])
        if not sql:
            continue
        con.execute(f"""
            INSERT INTO residential
            SELECT CAST(COALESCE(record_id, property_id) AS VARCHAR), _table,
                   COALESCE({num('r.lat')}, p.lat), COALESCE({num('r.lon')}, p.lon),
                   COALESCE(CAST({num('r.units')} AS INTEGER), {default_units})
            FROM ({sql}) r LEFT JOIN prop p ON p.pid = CAST(r.property_id AS VARCHAR)
        """)
    con.execute("DELETE FROM residential WHERE lat IS NULL OR lon IS NULL")
    return con.execute("SELECT count(*) FROM residential").fetchone()[0]


def build_candidates(con, limit: int = 1500) -> int:
    """Scanned spaces in our two cities, retail/restaurant types first."""
    ensure_tables(con, ["candidates"])
    keep = rows(con, "SELECT space_id FROM candidates WHERE priority < 100")  # hand-picked demo spaces survive
    con.execute("DELETE FROM candidates WHERE priority >= 100")
    like = " OR ".join(f"lower(COALESCE(property_type,'')) LIKE '%{k}%'" for k in RETAILISH)
    con.execute(f"""
        INSERT INTO candidates
        SELECT space_id, CASE WHEN ({like}) THEN 50 ELSE 90 END + 100, 'auto' FROM spaces
        WHERE has_scan AND city IS NOT NULL
          AND space_id NOT IN (SELECT space_id FROM candidates)
        ORDER BY ({like}) DESC, asking_rent_month IS NULL, space_id
        LIMIT {limit}
    """)
    print(f"  kept {len(keep)} hand-picked demo candidates")
    return con.execute("SELECT count(*) FROM candidates").fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["listings", "broker"], default="listings")
    ap.add_argument("--show-mapping", action="store_true")
    ap.add_argument("--skip-raw", action="store_true")
    ap.add_argument("--candidates", type=int, default=1500)
    a = ap.parse_args()

    from pipeline.ingest_kit import is_kit
    if is_kit(raw_dir()) and not a.show_mapping:
        print("CoStar hackathon kit detected -> python -m pipeline.ingest_kit")
        import sys as _sys
        from pipeline import ingest_kit
        _sys.argv = [_sys.argv[0]]
        ingest_kit.main()
        return

    with connect(read_only=False) as con:
        if not a.skip_raw:
            root = raw_dir()
            print(f"Loading raw files from {root}")
            load_raw(con, root)
        mapping = build_mapping(con)
        if a.show_mapping:
            print_mapping(mapping)
            return
        missing = [r for r in ["commercial_listing", "commercial_property", "mp_join"] if r not in mapping]
        if missing:
            print(f"WARNING: no table detected for {missing}; set them in pipeline/colmap.json")
        print(f"\nspaces ({a.mode}): {build_spaces(con, mapping, a.mode)}")
        print(f"tenants: {build_tenants(con, mapping)}")
        print(f"residential: {build_residential(con, mapping)}")
        ensure_tables(con)  # Matterport/Vexcel/transit tables, empty until fetched
        print(f"candidates: {build_candidates(con, a.candidates)}")
        n_scan = con.execute("SELECT count(*) FROM spaces WHERE has_scan").fetchone()[0]
        by_city = con.execute("SELECT city, count(*), count(*) FILTER (WHERE has_scan) FROM spaces GROUP BY 1 ORDER BY 1").fetchall()
        print(f"\nSELECT count(*) FROM spaces WHERE has_scan -> {n_scan}")
        for city, n, s in by_city:
            print(f"  {str(city):<12} {n:>7} spaces, {s:>5} with scans")


if __name__ == "__main__":
    main()
