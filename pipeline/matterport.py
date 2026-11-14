"""Matterport Model API (GraphQL) client.

Auth: HTTP Basic with MATTERPORT_API_TOKEN_ID / MATTERPORT_API_TOKEN_SECRET.
Endpoint: MATTERPORT_GRAPH_URL (default https://api.matterport.com/api/models/graph).

The schema varies by account/extension, so we introspect it once and only ask for
fields that exist (G4: `python -m pipeline.gates g4` prints what's available).
"""

from __future__ import annotations

import os
import random
import time
from functools import cached_property

import httpx

GRAPH_URL = os.getenv("MATTERPORT_GRAPH_URL", "https://api.matterport.com/api/models/graph")
SKYBOX_RESOLUTION = os.getenv("MATTERPORT_SKYBOX_RES", "2k")
# Order of SkyboxPanorama.children. Verify on one pano: 'up' should show the ceiling.
SKYBOX_FACE_ORDER = os.getenv("MATTERPORT_FACE_ORDER", "up,front,right,back,left,down").split(",")

WANTED = {
    "Dimension": ["areaFloor", "areaCeiling", "height", "width", "depth", "length", "units", "volume"],
    "SkyboxPanorama": ["status", "format", "children", "urlTemplate", "resolution"],
    "ModelRoom": ["id", "label", "tags", "classifications", "dimensions", "floor", "panoLocations", "bounds", "boundary", "outline"],
    "PanoramicImageLocation": ["id", "label", "variant", "position", "rotation", "skybox", "anchor", "placement", "source"],
}


class MatterportError(RuntimeError):
    pass


class Matterport:
    def __init__(self, token_id: str | None = None, token_secret: str | None = None, min_interval_s: float = 0.25):
        tid = token_id or os.getenv("MATTERPORT_API_TOKEN_ID")
        sec = token_secret or os.getenv("MATTERPORT_API_TOKEN_SECRET")
        if not tid or not sec:
            raise MatterportError("Set MATTERPORT_API_TOKEN_ID and MATTERPORT_API_TOKEN_SECRET in .env")
        self.http = httpx.Client(auth=(tid, sec), timeout=60, headers={"Content-Type": "application/json"})
        self.min_interval_s = min_interval_s
        self._last = 0.0

    # ------------------------------------------------------------------ transport
    def gql(self, query: str, variables: dict | None = None, retries: int = 5) -> dict:
        for attempt in range(retries):
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.http.post(GRAPH_URL, json={"query": query, "variables": variables or {}})
            except httpx.HTTPError as e:
                err = str(e)
            else:
                if r.status_code == 200:
                    body = r.json()
                    if body.get("errors") and not body.get("data"):
                        raise MatterportError(str(body["errors"])[:800])
                    return body
                err = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code in (400, 401, 403, 404):
                    raise MatterportError(err)
            time.sleep(min(30, 2 ** attempt + random.random()))
        raise MatterportError(f"gave up after {retries} attempts: {err}")

    # ------------------------------------------------------------------ schema
    def type_fields(self, name: str) -> dict[str, dict]:
        q = """query($n: String!) { __type(name: $n) { name fields { name args { name } type { name kind ofType { name kind ofType { name kind } } } } } }"""
        try:
            t = self.gql(q, {"n": name})["data"]["__type"]
        except MatterportError:
            return {}
        if not t:
            return {}
        out = {}
        for f in t.get("fields") or []:
            ty = f["type"]
            while ty.get("ofType"):
                ty = ty["ofType"]
            out[f["name"]] = {"type": ty.get("name"), "kind": ty.get("kind"), "args": [a["name"] for a in f.get("args", [])]}
        return out

    def enum_values(self, name: str) -> list[str]:
        try:
            t = self.gql("query($n: String!) { __type(name: $n) { enumValues { name } } }", {"n": name})["data"]["__type"]
        except MatterportError:
            return []
        return [v["name"] for v in (t or {}).get("enumValues") or []]

    @cached_property
    def schema(self) -> dict[str, dict[str, dict]]:
        names = ["Model", "ModelRoom", "ModelFloor", "PanoramicImageLocation", "SkyboxPanorama", "Dimension", "Point", "Quaternion"]
        return {n: self.type_fields(n) for n in names}

    def _has(self, type_name: str, field: str) -> bool:
        fields = self.schema.get(type_name) or {}
        return not fields or field in fields  # introspection disabled -> assume yes

    def _sel(self, type_name: str, wanted: list[str]) -> str:
        fields = self.schema.get(type_name) or {}
        return " ".join(f for f in wanted if not fields or f in fields)

    # ------------------------------------------------------------------ query
    def model_query(self) -> str:
        units = self.enum_values("Units")
        metric = next((u for u in units if u.lower() == "metric"), None)
        dim_arg = f"(units: {metric})" if metric else ""
        dims = self._sel("Dimension", WANTED["Dimension"])
        sky = self._sel("SkyboxPanorama", WANTED["SkyboxPanorama"])
        room = self.schema.get("ModelRoom") or {}
        room_parts = ["id", "label"]
        if self._has("ModelRoom", "tags"):
            room_parts.append("tags")
        if "classifications" in room:
            room_parts.append("classifications { label confidence }")
        if self._has("ModelRoom", "floor"):
            room_parts.append("floor { id sequence }")
        if dims and self._has("ModelRoom", "dimensions"):
            room_parts.append(f"dimensions{dim_arg} {{ {dims} }}")
        if "ceiling" in room:
            room_parts.append(f"ceiling{dim_arg} {{ minHeight maxHeight }}")
        if "boundary" in room:  # real outline: wall edges with doors/windows
            room_parts.append("boundary { edges { type vertices { position { x y } } "
                              "openings { type width height relativeCenter lowerElevation } } }")
        if self._has("ModelRoom", "panoLocations"):
            room_parts.append("panoLocations { id }")
        pano_parts = ["id", "label", "position { x y z }", "rotation { x y z w }"]
        if self._has("PanoramicImageLocation", "variant"):
            pano_parts.append("variant")
        if sky:
            pano_parts.append(f'skybox(resolution: "{SKYBOX_RESOLUTION}") {{ {sky} }}')
        geo = "geocoordinates { latitude longitude } address { address }" if "geocoordinates" in (self.schema.get("Model") or {}) else ""
        return f"""query Model($id: ID!) {{
  model(id: $id) {{
    id name {geo}
    floors {{ id sequence label }}
    rooms {{ {" ".join(room_parts)} }}
    panoLocations {{ {" ".join(pano_parts)} }}
  }}
}}"""

    def model(self, model_id: str) -> dict:
        body = self.gql(self.model_query(), {"id": model_id})
        m = (body.get("data") or {}).get("model")
        if not m:
            raise MatterportError(f"model {model_id} not found or not accessible: {str(body.get('errors'))[:300]}")
        return m

    def download(self, url: str, dest, retries: int = 4) -> None:
        for attempt in range(retries):
            try:
                with httpx.stream("GET", url, timeout=60, follow_redirects=True) as r:
                    r.raise_for_status()
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with tmp.open("wb") as fh:
                        for chunk in r.iter_bytes():
                            fh.write(chunk)
                    tmp.replace(dest)
                    return
            except httpx.HTTPError:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)


def face_urls(skybox: dict | None) -> dict[str, str]:
    """SkyboxPanorama -> {face: url}."""
    if not skybox:
        return {}
    children = skybox.get("children") or []
    if children:
        return {SKYBOX_FACE_ORDER[i]: u for i, u in enumerate(children[:6])}
    tpl = skybox.get("urlTemplate")
    if tpl:
        out = {}
        for i, face in enumerate(SKYBOX_FACE_ORDER):
            out[face] = tpl.replace("<face>", str(i)).replace("{face}", str(i))
        return out
    return {}
