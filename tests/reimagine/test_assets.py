"""Every model must look the same in every viewer. Parts that only carry vertex colours (COLOR_0, no
material) are drawn black by the Matterport scene viewer, so each mesh needs a real material."""

from __future__ import annotations

import json
import struct

from shared.conventions import REPO_ROOT
from agent.layout.catalog import load_catalog


def _gltf(path) -> dict:
    data = path.read_bytes()
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n])


def test_every_model_part_has_a_real_material():
    bad = []
    for item in load_catalog().values():
        doc = _gltf(REPO_ROOT / item.glb_asset)
        for mesh in doc["meshes"]:
            for prim in mesh["primitives"]:
                if prim.get("material") is None or "COLOR_0" in prim["attributes"]:
                    bad.append(item.item_type)
    assert not bad, f"vertex-colour-only parts (black in the Matterport viewer): {sorted(set(bad))}"


def test_rugs_are_flat_and_everything_else_is_not():
    from agent.layout.geometry import FLAT_MAX_HEIGHT_M

    cat = load_catalog()
    rugs = {t for t in cat if t.startswith("rug_")}
    assert rugs, "no rugs in the catalog"
    assert all(cat[t].height_m <= FLAT_MAX_HEIGHT_M for t in rugs)
    assert all(c.height_m > FLAT_MAX_HEIGHT_M for t, c in cat.items() if t not in rugs)
