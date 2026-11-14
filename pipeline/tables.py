"""DDL for the normalized tables that pipeline/queries.py reads.

Raw sponsor files land in ``raw_*`` tables (any columns). The ingest/fetch scripts
turn them into these fixed tables, so queries never depend on raw column names.
"""

from __future__ import annotations

import duckdb

DDL: dict[str, str] = {
    # One row per candidate space (a listing, or a vacant property in broker mode).
    "spaces": """
        CREATE TABLE IF NOT EXISTS spaces (
            space_id VARCHAR PRIMARY KEY,
            costar_property_id VARCHAR,
            listing_id VARCHAR,
            matterport_model_id VARCHAR,
            address VARCHAR,
            city VARCHAR,
            lat DOUBLE,
            lon DOUBLE,
            property_type VARCHAR,
            sqft DOUBLE,
            asking_rent_month DOUBLE,
            rent_per_sqft_year DOUBLE,
            rent_note VARCHAR,
            year_built INTEGER,
            has_scan BOOLEAN,
            parking_ratio DOUBLE,      -- spaces per 1,000 sqft (CoStar)
            parking_spaces INTEGER,
            broker_name VARCHAR,
            broker_company VARCHAR,
            broker_email VARCHAR,
            broker_phone VARCHAR,
            src_dataset VARCHAR,       -- raw dataset the row came from
            src_record_id VARCHAR,
            is_sample BOOLEAN DEFAULT FALSE,
            scan_level VARCHAR,        -- 'space' (scan of this suite) | 'listing' | 'property' (some scan of the building)
            space_use VARCHAR,         -- CoStar SpaceUse: Retail, Office, OfficeRetail, ...
            service_type VARCHAR       -- rent basis: TripleNet, FullService, ModifiedGross, ...
        )""",
    # The subset we fetch Matterport/Vexcel media for (step 2 of the indexing order).
    "candidates": """
        CREATE TABLE IF NOT EXISTS candidates (
            space_id VARCHAR PRIMARY KEY,
            priority INTEGER DEFAULT 100,   -- 0 = demo space, fetched first
            note VARCHAR
        )""",
    # Businesses at nearby locations (occupancy + company detail).
    "tenants": """
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id VARCHAR,
            name VARCHAR,
            category VARCHAR,
            lat DOUBLE,
            lon DOUBLE,
            employees INTEGER,
            dataset VARCHAR,
            record_id VARCHAR
        )""",
    # Apartment buildings (units) and residential listings (1 unit each).
    "residential": """
        CREATE TABLE IF NOT EXISTS residential (
            record_id VARCHAR,
            dataset VARCHAR,
            lat DOUBLE,
            lon DOUBLE,
            units INTEGER
        )""",
    "mp_rooms": """
        CREATE TABLE IF NOT EXISTS mp_rooms (
            space_id VARCHAR,
            model_id VARCHAR,
            room_id VARCHAR,
            label VARCHAR,
            room_type VARCHAR,
            floor_index INTEGER,
            polygon_json VARCHAR,       -- [[x, z], ...] meters, y-up model coords
            polygon_source VARCHAR,     -- 'api' | 'approx_rect'
            floor_y_m DOUBLE,
            ceiling_m DOUBLE,
            area_m2 DOUBLE,
            openings_json VARCHAR       -- [{kind, a: [x, z], b: [x, z]}]
        )""",
    "mp_panos": """
        CREATE TABLE IF NOT EXISTS mp_panos (
            pano_id VARCHAR PRIMARY KEY,
            space_id VARCHAR,
            model_id VARCHAR,
            scan_id VARCHAR,
            room_id VARCHAR,
            face VARCHAR,
            path VARCHAR,               -- URL path media/panos/...
            defurnished BOOLEAN,
            px DOUBLE, py DOUBLE, pz DOUBLE,
            qx DOUBLE, qy DOUBLE, qz DOUBLE, qw DOUBLE,
            fov_deg DOUBLE,
            width_px INTEGER,
            height_px INTEGER
        )""",
    # All scan poses (even ones whose images we did not download).
    "mp_scans": """
        CREATE TABLE IF NOT EXISTS mp_scans (
            model_id VARCHAR,
            scan_id VARCHAR,
            room_id VARCHAR,
            variant VARCHAR,
            px DOUBLE, py DOUBLE, pz DOUBLE,
            qx DOUBLE, qy DOUBLE, qz DOUBLE, qw DOUBLE
        )""",
    "mp_fetch_log": """
        CREATE TABLE IF NOT EXISTS mp_fetch_log (
            model_id VARCHAR PRIMARY KEY,
            status VARCHAR,
            error VARCHAR,
            raw_json VARCHAR,
            fetched_at TIMESTAMP DEFAULT current_timestamp
        )""",
    "vx_props": """
        CREATE TABLE IF NOT EXISTS vx_props (
            space_id VARCHAR PRIMARY KEY,
            footprint_wkt VARCHAR,
            parcel_wkt VARCHAR,
            attrs_json VARCHAR,
            parking_score DOUBLE,
            parking_notes VARCHAR,
            ortho_path VARCHAR,
            oblique_path VARCHAR,
            status VARCHAR,
            error VARCHAR,
            fetched_at TIMESTAMP DEFAULT current_timestamp
        )""",
    "transit": """
        CREATE TABLE IF NOT EXISTS transit (
            stop_id VARCHAR PRIMARY KEY,
            name VARCHAR,
            kind VARCHAR,               -- rail | bus | tram
            lat DOUBLE,
            lon DOUBLE
        )""",
}


def ensure_tables(con: duckdb.DuckDBPyConnection, names: list[str] | None = None) -> None:
    for name, ddl in DDL.items():
        if names is None or name in names:
            con.execute(ddl)
