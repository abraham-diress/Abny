"""fetch_matterport on a fake API response (z-up coordinates, imperial units, a defurnished variant)."""

from __future__ import annotations

import json

import pytest
from PIL import Image


class FakeMP:
    def __init__(self, model):
        self._m = model
        self.downloads = []

    def model(self, model_id):
        return self._m

    def download(self, url, dest):
        self.downloads.append(url)
        Image.new("RGB", (64, 64)).save(dest)


def _model():
    sky = {"status": "ok", "children": [f"https://x/{i}.jpg" for i in range(6)]}
    # z-up: camera height 1.6 on z, room spread on x/y
    panos = [
        {"id": "p1", "variant": "default", "position": {"x": 1.0, "y": 2.0, "z": 1.6}, "rotation": {"x": 0, "y": 0, "z": 0, "w": 1}, "skybox": sky},
        {"id": "p1e", "variant": "defurnished", "position": {"x": 1.0, "y": 2.0, "z": 1.6}, "rotation": {"x": 0, "y": 0, "z": 0, "w": 1}, "skybox": sky},
        {"id": "p2", "variant": "default", "position": {"x": 6.0, "y": 3.0, "z": 1.6}, "rotation": {"x": 0, "y": 0, "z": 0, "w": 1}, "skybox": sky},
        {"id": "p3", "variant": "default", "position": {"x": 3.0, "y": 9.0, "z": 1.61}, "rotation": {"x": 0, "y": 0, "z": 0, "w": 1}, "skybox": sky},
    ]
    rooms = [
        {"id": "r1", "label": "Main", "tags": ["retail"], "floor": {"sequence": 0},
         "dimensions": [{"areaFloor": 400.0, "height": 12.0, "width": 25.0, "depth": 16.0, "units": "imperial"}],
         "panoLocations": [{"id": "p1"}, {"id": "p1e"}, {"id": "p2"}]},
        {"id": "r2", "label": "Back", "floor": {"sequence": 0}, "dimensions": [{"areaFloor": 10.0, "height": 3.0, "units": "metric"}],
         "panoLocations": [{"id": "p3"}]},
    ]
    return {"id": "M1", "rooms": rooms, "panoLocations": panos}


def test_fetch_model(tmp_path, monkeypatch):
    from pipeline import fetch_matterport as fm

    monkeypatch.setattr(fm, "PANOS_DIR", tmp_path / "panos")
    monkeypatch.setattr(fm, "media_url", lambda p: "media/panos/" + p.parent.name + "/" + p.name)
    mp = FakeMP(_model())
    res = fm.fetch_model(mp, "S1", "M1", n_scans=2, faces=["front", "right"], images=True)

    assert res["up"] == "z"
    rooms = {r["room_id"]: r for r in res["rooms"]}
    main = rooms["r1"]
    assert main["area_m2"] == pytest.approx(400 * 0.092903)
    assert main["ceiling_m"] == pytest.approx(12 * 0.3048)
    poly = json.loads(main["polygon_json"])
    assert len(poly) == 4
    # z-up (x, y, z) -> y-up (x, z, -y): room center z ~ -mean(y of scans)
    cz = sum(p[1] for p in poly) / 4
    assert cz == pytest.approx(-(2 + 2 + 3) / 3)
    assert main["floor_y_m"] == pytest.approx(1.6 - fm.CAMERA_HEIGHT_M)
    # one scan per room, defurnished preferred in the big room
    scans = {p["scan_id"] for p in res["panos"]}
    assert scans == {"p1e", "p3"}
    assert all(p["defurnished"] for p in res["panos"] if p["scan_id"] == "p1e")
    assert len(res["panos"]) == 4 and len(mp.downloads) == 4
    # quaternion was rotated into y-up (identity -> -90 deg about x)
    q = res["panos"][0]
    assert q["qx"] == pytest.approx(-(0.5 ** 0.5)) and q["qw"] == pytest.approx(0.5 ** 0.5)


def test_boundary_polygon_and_openings():
    """Real-format room boundary (z-up Point2D edges) -> y-up polygon + door segment."""
    from pipeline import fetch_matterport as fm

    sq = [(0, 0), (4, 0), (4, -3), (0, -3)]  # API x/y; y-up z = -y -> 0..3
    edges = []
    for i in range(4):
        a, b = sq[i], sq[(i + 1) % 4]
        e = {"type": "wall", "vertices": [{"position": {"x": a[0], "y": a[1]}}, {"position": {"x": b[0], "y": b[1]}}], "openings": []}
        if i == 0:
            e["openings"] = [{"type": "doorway", "width": 1.0, "relativeCenter": 0.5, "lowerElevation": 0.02, "height": 2.1}]
        edges.append(e)
    room = {"id": "r", "classifications": [{"label": "Retail", "confidence": 0.9}], "dimensions": [{"areaFloor": 12.0, "units": "metric"}],
            "ceiling": {"minHeight": 3.2, "maxHeight": 3.4}, "boundary": {"edges": edges}}
    rows = fm.room_rows("S", {"id": "M", "rooms": [room]}, "z", {})
    assert len(rows) == 1
    r = rows[0]
    assert r["polygon_source"] == "api" and r["room_type"] == "Retail" and r["ceiling_m"] == 3.4
    poly = json.loads(r["polygon_json"])
    assert {round(x) for x, _ in poly} == {0, 4} and {round(z) for _, z in poly} == {0, 3}
    door = json.loads(r["openings_json"])[0]
    assert door["kind"] == "door" and door["a"] == [1.5, 0.0] and door["b"] == [2.5, 0.0]
    assert r["floor_y_m"] == pytest.approx(0.02)
