"""Vexcel API 2.0 client, following the hackathon quickstart (vexcel_quickstart.py).

Auth: long-life key in the X-API-KEY header (VEXCEL_API_KEY).
Endpoints used (base https://api.vexcelgroup.com/v2):
    GET  property/extract        parcel polygon + flat dotted attributes + structures[]
    POST ortho/extract           top-down JPEG clipped to a WKT
    GET  oriented/collections    which oblique directions exist here (404 = none)
    POST oriented/extract        oblique JPEG (product-type oblique-north|south|east|west)
    POST elements/detect         open-vocabulary detection ("car", "parking lot") -> parking score
    POST embedding/extract       semantic tile search (not used per space; see search_tiles)
Coordinates: WKT is POINT(lon lat). 429 -> exponential backoff.
"""

from __future__ import annotations

import math
import os
import random
import time

import httpx

BASE = os.getenv("VEXCEL_BASE_URL", "https://api.vexcelgroup.com/v2").rstrip("/")
LAYERS = os.getenv("VEXCEL_LAYERS", "urban,urban-r,wide-area,urban-g")  # API picks the best available
OBLIQUE_LAYER = "urban"  # only layer with obliques
OBLIQUE_DIRECTIONS = ["oblique-north", "oblique-south", "oblique-east", "oblique-west"]
NO_PARCEL_HALF_M = 40


class VexcelError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


def point_wkt(lat: float, lon: float) -> str:
    return f"POINT({lon} {lat})"


def square_wkt(lat: float, lon: float, half_m: float) -> str:
    dlat = half_m / 111_320
    dlon = half_m / (111_320 * max(0.1, math.cos(math.radians(lat))))
    w, e, s, n = lon - dlon, lon + dlon, lat - dlat, lat + dlat
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


def to_wkt(geometry) -> str | None:
    if geometry is None:
        return None
    from shapely import wkt as swkt
    from shapely.geometry import shape

    if isinstance(geometry, str):
        return swkt.loads(geometry).wkt
    return shape(geometry).wkt


def wkt_area_m2(w: str) -> float:
    """Approximate area of a lon/lat WKT polygon in m^2."""
    from shapely import wkt as swkt

    g = swkt.loads(w)
    lat = g.centroid.y
    return g.area * 111_320 ** 2 * math.cos(math.radians(lat))


class Vexcel:
    def __init__(self, max_retries: int = 5):
        key = os.getenv("VEXCEL_API_KEY")
        if not key:
            raise VexcelError("Set VEXCEL_API_KEY in .env")
        self.http = httpx.Client(timeout=300, headers={"X-API-KEY": key}, follow_redirects=True)
        self.max_retries = max_retries

    def send(self, method: str, path: str, **kw) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                r = self.http.request(method, f"{BASE}/{path}", **kw)
            except httpx.HTTPError as e:
                if attempt == self.max_retries:
                    raise VexcelError(f"{path}: {e}")
                time.sleep(2 ** attempt)
                continue
            if r.status_code not in (429, 502, 503, 504) or attempt == self.max_retries:
                return r
            time.sleep(min(2 ** attempt, 30) + random.random())
        raise AssertionError("unreachable")

    def _ok(self, r: httpx.Response, path: str) -> httpx.Response:
        if not r.is_success:
            raise VexcelError(f"{path} failed ({r.status_code}): {r.text[:300]}", r.status_code)
        return r

    # ------------------------------------------------------------------ calls
    def property(self, lat: float, lon: float) -> dict | None:
        """Parcel at the point (GeoJSON FeatureCollection) or None if no parcel there (404)."""
        params = {"wkt": point_wkt(lat, lon), "srid": 4326, "layer": LAYERS, "latest": "true",
                  "include": "precomputed", "unit-system": "metric"}
        r = self.send("GET", "property/extract", params=params)
        if r.status_code == 404:  # point on a road etc.: retry with a small buffer
            r = self.send("GET", "property/extract", params={**params, "buffer-meter": 30})
            if r.status_code == 404:
                return None
        return self._ok(r, "property/extract").json()

    def ortho(self, area_wkt: str, buffer_m: int = 15) -> bytes:
        body = {"wkt": area_wkt, "srid": 4326, "layer": LAYERS, "buffer-meter": buffer_m,
                "crop": "bounding_box", "image-format": "jpeg",
                "drawing": [{"wkt": area_wkt, "outline-width": 4, "outline-color": "rgb(255,204,0)"}]}
        return self._ok(self.send("POST", "ortho/extract", json=body), "ortho/extract").content

    def oblique_directions(self, area_wkt: str) -> list[str]:
        r = self.send("GET", "oriented/collections", params={
            "wkt": area_wkt, "srid": 4326, "layer": OBLIQUE_LAYER, "product-type": "oblique",
            "include": "product-type,collection,last-capture-date"})
        if r.status_code == 404:
            return []
        feats = self._ok(r, "oriented/collections").json().get("features", [])
        newest = max((f["properties"].get("last-capture-date") for f in feats), default=None)
        avail = {f["properties"].get("product-type") for f in feats if f["properties"].get("last-capture-date") == newest}
        return [d for d in OBLIQUE_DIRECTIONS if d in avail]

    def oblique(self, area_wkt: str, direction: str, buffer_m: int = 15) -> bytes:
        body = {"wkt": area_wkt, "srid": 4326, "layer": OBLIQUE_LAYER, "product-type": direction,
                "rotation": "natural", "buffer-meter": buffer_m, "crop": "bbox", "image-format": "jpeg/png",
                "drawing": [{"wkt": area_wkt, "outline-width": 4, "outline-color": "255,204,0",
                             "fill-color": "255,204,0", "transparency": 0}]}
        return self._ok(self.send("POST", "oriented/extract", json=body), "oriented/extract").content

    def detect(self, area_wkt: str, labels: list[str], buffer_m: int = 30, threshold: float = 0.4) -> list[dict]:
        """Open-vocabulary detection on the ortho -> [{label, confidence, bbox_wkt}]."""
        body = {"wkt": area_wkt, "srid": 4326, "buffer-meter": buffer_m,
                "images": [{"endpoint": "ortho/extract",
                            "request": {"layer": LAYERS, "srid": 4326, "wkt": area_wkt, "crop": "bounding_box"}}],
                "model-input": {"elements": [{"label": l, "model": "sam3", "detection-threshold": threshold} for l in labels],
                                "include": ["bbox", "confidence"]}}
        res = self._ok(self.send("POST", "elements/detect", json=body), "elements/detect").json()
        out = []
        for f in res.get("features", []):
            label = f["properties"].get("label")
            for d in f["properties"].get("detections", []):
                out.append({"label": label, "confidence": d.get("confidence"), "bbox_wkt": d.get("bbox")})
        return out

    def search_tiles(self, area_wkt: str, text: str, k: int = 10) -> list[dict]:
        """Semantic search ('parking lot', 'bus stop') over embedding tiles in an area."""
        body = {"wkt": area_wkt, "srid": 4326, "search-text": text, "include": "score,geometry,collection",
                "total-records": k, "page-size": k}
        return self._ok(self.send("POST", "embedding/extract", json=body), "embedding/extract").json().get("features", [])


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #


def parcel_and_attrs(prop: dict | None) -> tuple[str | None, dict]:
    if not prop or not prop.get("features"):
        return None, {}
    f = prop["features"][0]
    return to_wkt(f.get("geometry")), f.get("properties") or {}


def footprint_wkt(attrs: dict) -> str | None:
    """Primary structure footprint, if the response carries one (as WKT or GeoJSON)."""
    structs = attrs.get("structures") or []
    structs = sorted(structs, key=lambda s: not s.get("primary-structure"))
    for s in structs:
        for k, v in s.items():
            if "footprint" in k and ("wkt" in k or "geometry" in k) and v:
                try:
                    return to_wkt(v)
                except Exception:
                    continue
    return None


def parking_from_detections(dets: list[dict]) -> tuple[float | None, str | None]:
    """Score parking from detected lots (area) and cars on/around the parcel."""
    lots = [d for d in dets if "parking" in (d["label"] or "") and d.get("bbox_wkt")]
    cars = [d for d in dets if d["label"] == "car"]
    lot_m2 = sum(wkt_area_m2(d["bbox_wkt"]) for d in lots)
    if not lots and not cars:
        return 0.1, "No parking lot or parked cars detected on/around the parcel (Vexcel elements/detect)"
    # ~25 m^2 per stall: 1,000 m^2 of lot ~ 40 stalls -> full score
    score = min(1.0, max(lot_m2 / 1000.0, len(cars) / 25.0))
    note = f"Vexcel aerial detection: {len(lots)} parking area(s) ~{lot_m2:,.0f} m², {len(cars)} cars within 30 m of the parcel"
    return round(score, 2), note
