"""Transit stops from OpenStreetMap (Overpass API), one query per city bounding box.

    python -m pipeline.fetch_transit

Needed for "closer to transit" feedback. Free, no key. The bbox comes from the extent
of our spaces (plus a margin), so we don't download whole metros. Writes `transit`.
OSM data is (c) OpenStreetMap contributors, ODbL: credit it on the Devpost page.
"""

from __future__ import annotations

import time

import httpx

from pipeline.db import connect
from pipeline.tables import ensure_tables

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MARGIN_DEG = 0.02


def query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    b = f"({s},{w},{n},{e})"
    return f"""[out:json][timeout:180];
(
  node["railway"~"^(station|halt|tram_stop)$"]{b};
  node["public_transport"="station"]{b};
  node["highway"="bus_stop"]{b};
);
out body;"""


def kind_of(tags: dict) -> str:
    if tags.get("railway") == "tram_stop" or tags.get("tram") == "yes":
        return "tram"
    if tags.get("railway") in ("station", "halt") or tags.get("train") == "yes" or tags.get("subway") == "yes" or tags.get("light_rail") == "yes":
        return "rail"
    return "bus"


def main() -> None:
    with connect(read_only=False) as con:
        ensure_tables(con, ["transit"])
        boxes = con.execute(
            "SELECT city, min(lat), min(lon), max(lat), max(lon) FROM spaces WHERE city IS NOT NULL GROUP BY city"
        ).fetchall()
    http = httpx.Client(timeout=240, headers={"User-Agent": "hestia-hackathon/0.1"})
    for city, s, w, n, e in boxes:
        bbox = (s - MARGIN_DEG, w - MARGIN_DEG, n + MARGIN_DEG, e + MARGIN_DEG)
        for attempt in range(3):
            r = http.post(OVERPASS_URL, data={"data": query(bbox)})
            if r.status_code == 200:
                break
            print(f"{city}: HTTP {r.status_code}, retrying")
            time.sleep(10 * (attempt + 1))
        else:
            print(f"{city}: failed")
            continue
        els = r.json().get("elements", [])
        recs = [(f"osm:{el['id']}", (el.get("tags") or {}).get("name") or "Unnamed stop", kind_of(el.get("tags") or {}),
                 el["lat"], el["lon"]) for el in els if "lat" in el]
        with connect(read_only=False) as con:
            con.executemany("INSERT OR REPLACE INTO transit VALUES (?, ?, ?, ?, ?)", recs)
        print(f"{city}: {len(recs)} stops ({sum(1 for x in recs if x[2] == 'rail')} rail)")


if __name__ == "__main__":
    main()
