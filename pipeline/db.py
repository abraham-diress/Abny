"""DuckDB connection helpers and small shared utilities for the Data Engine.

The database path is ``shared.conventions.DB_PATH`` unless ``HESTIA_DB_PATH`` is set
(e.g. ``HESTIA_DB_PATH=data/sample.duckdb`` to use the synthetic sample database).
"""

from __future__ import annotations

import math
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb
from dotenv import load_dotenv

from shared.conventions import DB_PATH, MEDIA_DIR, REPO_ROOT

load_dotenv(REPO_ROOT / ".env")

SAMPLE_DB_PATH = DB_PATH.parent / "sample.duckdb"

# Metro centers, used to assign a City when the city column is missing or is a suburb.
METROS: dict[str, tuple[float, float]] = {
    "Houston": (29.7604, -95.3698),
    "Los Angeles": (34.0522, -118.2437),
}
METRO_RADIUS_M = 70_000


def db_path() -> Path:
    p = os.getenv("HESTIA_DB_PATH")
    if not p:
        return DB_PATH
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path


@contextmanager
def connect(read_only: bool = True, path: Path | None = None, retries: int = 20) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open a short-lived connection. Retries while another process holds the write lock."""
    path = path or db_path()
    if read_only and not path.exists():
        raise FileNotFoundError(
            f"No database at {path}. Run `python -m pipeline.ingest_costar` "
            "or `python -m pipeline.sample_data` and set HESTIA_DB_PATH=data/sample.duckdb."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for i in range(retries):
        try:
            con = duckdb.connect(str(path), read_only=read_only)
            break
        except duckdb.IOException as e:  # file locked by a writer
            last = e
            time.sleep(0.25 * (i + 1))
    else:
        raise RuntimeError(f"Could not open {path}: {last}")
    try:
        yield con
    finally:
        con.close()


def table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchone()[0]
    )


def rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bbox(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """(lat_min, lat_max, lon_min, lon_max) around a point; a cheap SQL prefilter."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.1, math.cos(math.radians(lat))))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def media_url(path: Path) -> str:
    """Filesystem path under data/media -> URL path 'media/...'."""
    return "media/" + path.resolve().relative_to(MEDIA_DIR.resolve()).as_posix()


def nearest_metro(lat: float | None, lon: float | None) -> str | None:
    if lat is None or lon is None:
        return None
    best = min(METROS.items(), key=lambda kv: haversine_m(lat, lon, *kv[1]))
    return best[0] if haversine_m(lat, lon, *best[1]) <= METRO_RADIUS_M else None
