"""Generate simple, correctly sized GLB models for every item in assets/catalog.json.

    python assets/build_assets.py

Every model:
* is in meters, with its footprint exactly width_m x depth_m and height height_m;
* has its origin at the center of the footprint on the floor (y = 0);
* faces +z (its "front": doors, glass, the customer side).
So the frontend places it at (x_m, floor_y, z_m) and rotates it by rotation_deg about +y.

Realistic parts (chairs, café tables, bench, sofa, cabinet, shelves, cash register, pastries,
plants) come from CC0 Poly Haven models: run `python assets/fetch_cc0.py` first (downloads to the
gitignored data/cc0/). Without them every item falls back to simple box geometry. Kitchen
equipment, desks and counters stay simple shapes (there are no good CC0 models for them).
"""

from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "catalog.json"
OUT = ROOT / "glb"

WOOD = (150, 105, 70, 255)
DARK_WOOD = (95, 65, 45, 255)
STEEL = (190, 195, 200, 255)
DARK_STEEL = (110, 115, 120, 255)
GLASS = (185, 220, 235, 255)
WHITE = (240, 240, 236, 255)
BLACK = (40, 40, 42, 255)
FABRIC = (120, 140, 120, 255)


def box(w, h, d, x=0.0, y=0.0, z=0.0, color=WOOD) -> trimesh.Trimesh:
    """Axis-aligned box: x/z are the center, y is the bottom."""
    m = trimesh.creation.box(extents=(w, h, d))
    m.apply_translation((x, y + h / 2, z))
    m.visual.vertex_colors = np.tile(np.array(color, dtype=np.uint8), (len(m.vertices), 1))
    return m


def cylinder(r, h, x=0.0, y=0.0, z=0.0, color=STEEL) -> trimesh.Trimesh:
    m = trimesh.creation.cylinder(radius=r, height=h, sections=24)
    m.apply_translation((x, y + h / 2, z))
    m.visual.vertex_colors = np.tile(np.array(color, dtype=np.uint8), (len(m.vertices), 1))
    return m


def chair(x, z, facing_z: float) -> list[trimesh.Trimesh]:
    """Seat 0.42 x 0.42 at height 0.45 with a back on the side away from `facing_z` (+1 or -1)."""
    back_z = z - 0.19 * facing_z
    parts = [box(0.42, 0.04, 0.42, x, 0.43, z, DARK_WOOD), box(0.42, 0.45, 0.04, x, 0.47, back_z, DARK_WOOD)]
    for dx in (-0.18, 0.18):
        for dz in (-0.18, 0.18):
            parts.append(box(0.03, 0.43, 0.03, x + dx, 0, z + dz, BLACK))
    return parts


def chair_x(x, z, facing_x: float) -> list[trimesh.Trimesh]:
    back_x = x - 0.19 * facing_x
    parts = [box(0.42, 0.04, 0.42, x, 0.43, z, DARK_WOOD), box(0.04, 0.45, 0.42, back_x, 0.47, z, DARK_WOOD)]
    for dx in (-0.18, 0.18):
        for dz in (-0.18, 0.18):
            parts.append(box(0.03, 0.43, 0.03, x + dx, 0, z + dz, BLACK))
    return parts


def table_top(w, d, x=0.0, z=0.0) -> list[trimesh.Trimesh]:
    return [box(w, 0.04, d, x, 0.72, z, WOOD), box(0.06, 0.72, 0.06, x, 0, z, BLACK), box(0.45, 0.03, 0.45, x, 0, z, BLACK)]


PLASTIC_WHITE = (232, 232, 228, 255)
CHARCOAL = (60, 62, 66, 255)
SCREEN = (25, 28, 32, 255)
UPHOLSTERY = (85, 110, 140, 255)
PLANT = (70, 120, 70, 255)


def task_chair(x, z, facing_z: float) -> list[trimesh.Trimesh]:
    """Office chair (0.55 wide) facing +z (facing_z=+1) or -z (-1): seat, back, post and base."""
    back_z = z - 0.24 * facing_z
    return [
        box(0.5, 0.06, 0.5, x, 0.44, z, CHARCOAL),
        box(0.48, 0.55, 0.05, x, 0.55, back_z, CHARCOAL),
        cylinder(0.03, 0.4, x, 0.04, z, color=DARK_STEEL),
        box(0.55, 0.04, 0.08, x, 0.0, z, BLACK),
        box(0.08, 0.04, 0.55, x, 0.0, z, BLACK),
    ]


def office_desk(w, d, x, z, monitor_side: float) -> list[trimesh.Trimesh]:
    """Desk top w x d at 0.74 m, two legs, a monitor at the `monitor_side` (+1/-1 along z) edge."""
    parts = [box(w, 0.03, d, x, 0.72, z, PLASTIC_WHITE)]
    parts += [box(0.04, 0.72, d * 0.9, x + sx, 0, z, DARK_STEEL) for sx in (-w / 2 + 0.03, w / 2 - 0.03)]
    mz = z + monitor_side * (d / 2 - 0.12)
    parts += [box(0.6, 0.36, 0.03, x, 0.9, mz, SCREEN), box(0.06, 0.16, 0.06, x, 0.75, mz, DARK_STEEL)]
    return parts


def build(item: dict) -> trimesh.Trimesh:
    t, w, d, h = item["item_type"], item["width_m"], item["depth_m"], item["height_m"]
    fz = d / 2  # front face z
    if t == "display_case":
        parts = [box(w, h * 0.55, d, color=DARK_WOOD), box(w * 0.98, h * 0.45, d * 0.96, y=h * 0.55, color=GLASS)]
        parts += [box(w * 0.9, 0.02, d * 0.8, y=h * 0.55 + k * h * 0.15, color=WHITE) for k in (1, 2)]
    elif t in ("service_counter", "espresso_bar"):
        parts = [box(w, h - 0.04, d, color=WOOD), box(w + 0.04, 0.04, d + 0.04, y=h - 0.04, color=WHITE)]
        if t == "service_counter":
            parts.append(box(0.35, 0.25, 0.3, x=w * 0.25, y=h, z=-d * 0.1, color=BLACK))  # register
        else:
            parts.append(box(0.7, 0.45, 0.5, x=-w * 0.15, y=h, z=-d * 0.1, color=STEEL))  # espresso machine
    elif t == "deck_oven":
        legs = 0.35
        deck = (h - legs) / 3
        parts = [box(w, legs, d * 0.9, color=DARK_STEEL)]
        for k in range(3):
            parts.append(box(w, deck - 0.02, d, y=legs + k * deck, color=STEEL))
            parts.append(box(w * 0.8, deck * 0.4, 0.02, y=legs + k * deck + deck * 0.3, z=fz - 0.01, color=BLACK))
    elif t == "convection_oven":
        parts = [box(w, 0.6, d * 0.9, color=DARK_STEEL), box(w, h - 0.6, d, y=0.6, color=STEEL),
                 box(w * 0.6, (h - 0.6) * 0.5, 0.02, y=0.6 + (h - 0.6) * 0.25, z=fz - 0.01, color=BLACK)]
    elif t in ("proofing_cabinet", "reach_in_fridge"):
        parts = [box(w, h, d, color=STEEL if t == "reach_in_fridge" else WHITE),
                 box(0.03, h * 0.3, 0.04, x=w * 0.38, y=h * 0.45, z=fz, color=BLACK)]
    elif t == "prep_table":
        parts = [box(w, 0.04, d, y=h - 0.04, color=STEEL), box(w * 0.95, 0.03, d * 0.9, y=0.18, color=STEEL)]
        for dx in (-w / 2 + 0.04, w / 2 - 0.04):
            for dz in (-d / 2 + 0.04, d / 2 - 0.04):
                parts.append(box(0.04, h - 0.04, 0.04, dx, 0, dz, DARK_STEEL))
    elif t == "spiral_mixer":
        parts = [box(w, 0.75, d, color=WHITE), cylinder(min(w, d) * 0.4, 0.4, y=0.75, color=STEEL),
                 box(w * 0.8, 0.15, d * 0.5, y=h - 0.15, z=-d * 0.2, color=WHITE)]
    elif t == "three_comp_sink":
        parts = [box(w, h - 0.05, d, color=STEEL)]
        parts += [box(w / 3 - 0.08, 0.06, d * 0.7, x=(k - 1) * w / 3, y=h - 0.08, color=DARK_STEEL) for k in range(3)]
        parts.append(box(w, 0.3, 0.05, y=h - 0.05, z=-d / 2 + 0.025, color=STEEL))  # backsplash
    elif t == "table_2":
        parts = table_top(0.7, 0.7) + chair(0, -d / 2 + 0.24, +1) + chair(0, d / 2 - 0.24, -1)
    elif t == "table_4":
        parts = table_top(0.8, 0.8) + chair(0, -d / 2 + 0.24, +1) + chair(0, d / 2 - 0.24, -1)
        parts += chair_x(-w / 2 + 0.24, 0, +1) + chair_x(w / 2 - 0.24, 0, -1)
    elif t == "bench_table_4":
        bench_z = -d / 2 + 0.25
        parts = [box(w, 0.45, 0.5, z=bench_z, color=FABRIC), box(w, 0.5, 0.08, y=0.45, z=-d / 2 + 0.04, color=FABRIC)]
        parts += table_top(w * 0.9, 0.6, z=0.05)
        parts += chair(-w / 4, d / 2 - 0.24, -1) + chair(w / 4, d / 2 - 0.24, -1)
    elif t == "condiment_station":
        parts = [box(w, h, d, color=DARK_WOOD), box(w * 0.9, 0.12, d * 0.6, y=h, color=STEEL)]
    elif t == "retail_shelf":
        parts = [box(w, h, 0.03, z=-d / 2 + 0.015, color=WOOD)]
        parts += [box(0.03, h, d, x=sx, color=WOOD) for sx in (-w / 2 + 0.015, w / 2 - 0.015)]
        parts += [box(w, 0.025, d, y=k * h / 5, color=WOOD) for k in range(1, 5)]
    elif t == "desk_pod":
        # Two desks per side, facing each other across a low screen; chairs on the outside.
        parts = [box(w * 0.98, 0.35, 0.03, y=0.75, color=FABRIC)]
        for side in (-1, 1):
            for dx in (-w / 4, w / 4):
                parts += office_desk(w / 2 - 0.04, 0.7, dx, side * 0.36, monitor_side=-side)
                parts += task_chair(dx, side * (0.7 + 0.45), facing_z=-side)
    elif t == "single_desk":
        # Desk against the wall (-z), chair in front of it (+z side).
        parts = office_desk(w - 0.04, 0.7, 0, -d / 2 + 0.36, monitor_side=-1) + task_chair(0, -d / 2 + 0.7 + 0.42, facing_z=-1)
    elif t == "meeting_table":
        parts = [box(2.0, 0.04, 1.1, y=0.72, color=WOOD)]
        parts += [box(0.08, 0.72, 0.8, x=sx, color=DARK_STEEL) for sx in (-0.75, 0.75)]
        for dx in (-0.7, 0.0, 0.7):
            parts += task_chair(dx, -0.95, facing_z=+1) + task_chair(dx, 0.95, facing_z=-1)
        parts += [box(0.5, 0.05, 0.5, x=sx, y=0.44, color=CHARCOAL) for sx in (-1.03, 1.03)]
        parts += [box(0.05, 0.5, 0.48, x=sx + 0.22 * (1 if sx > 0 else -1), y=0.5, color=CHARCOAL) for sx in (-1.03, 1.03)]
        parts += [cylinder(0.03, 0.42, x=sx, y=0.02, color=DARK_STEEL) for sx in (-1.03, 1.03)]
    elif t == "reception_desk":
        # Visitors on +z; a raised top facing them; staff chair behind (-z, against the wall).
        parts = [box(w, 1.05, 0.6, z=d / 2 - 0.3, color=WOOD), box(w, 0.04, 0.35, y=1.05, z=d / 2 - 0.18, color=PLASTIC_WHITE),
                 box(w * 0.9, 0.03, 0.6, y=0.72, z=d / 2 - 0.85, color=PLASTIC_WHITE)]
        parts += [box(0.6, 0.36, 0.03, y=0.9, z=d / 2 - 0.68, color=SCREEN)]
        parts += task_chair(0, -d / 2 + 0.3, facing_z=+1)
    elif t == "sofa":
        parts = [box(w, 0.42, d, color=UPHOLSTERY), box(w, 0.43, 0.2, y=0.42, z=-d / 2 + 0.1, color=UPHOLSTERY)]
        parts += [box(0.18, 0.2, d, x=sx, y=0.42, color=UPHOLSTERY) for sx in (-w / 2 + 0.09, w / 2 - 0.09)]
    elif t == "phone_booth":
        parts = [box(w, h, 0.05, z=-d / 2 + 0.025, color=CHARCOAL), box(w, 0.08, d, y=h - 0.08, color=CHARCOAL),
                 box(w, 0.05, d, color=CHARCOAL), box(w * 0.96, h - 0.15, 0.02, y=0.05, z=d / 2 - 0.01, color=GLASS)]
        parts += [box(0.05, h, d, x=sx, color=CHARCOAL) for sx in (-w / 2 + 0.025, w / 2 - 0.025)]
        parts += [box(0.6, 0.03, 0.35, y=1.0, z=-d / 2 + 0.2, color=WOOD), box(0.4, 0.45, 0.4, color=UPHOLSTERY)]
    elif t == "storage_cabinet":
        parts = [box(w, h, d, color=PLASTIC_WHITE)]
        parts += [box(0.02, h * 0.9, 0.01, x=0, y=h * 0.05, z=d / 2, color=CHARCOAL)]
        parts += [box(0.03, 0.25, 0.03, x=sx, y=h * 0.45, z=d / 2 + 0.01, color=DARK_STEEL) for sx in (-0.08, 0.08)]
    elif t == "kitchenette_counter":
        parts = [box(w, 0.88, d, color=PLASTIC_WHITE), box(w, 0.04, d, y=0.88, color=DARK_WOOD),
                 box(0.5, 0.03, 0.4, x=-w / 4, y=0.91, color=STEEL),
                 box(w, 0.7, 0.35, y=1.5, z=-d / 2 + 0.175, color=PLASTIC_WHITE),
                 box(0.55, 0.85, 0.55, x=w / 2 - 0.3, y=0.92, z=-0.02, color=DARK_STEEL)]  # fridge/coffee
    else:
        parts = [box(w, h, d)]
    mesh = trimesh.util.concatenate(parts)
    return mesh


def check(mesh: trimesh.Trimesh, item: dict) -> None:
    (x0, y0, z0), (x1, y1, z1) = mesh.bounds
    w, d, h = item["width_m"], item["depth_m"], item["height_m"]
    tol = 0.05
    assert abs(y0) < 1e-6, f"{item['item_type']}: bottom at {y0}"
    assert x1 - x0 <= w + tol and z1 - z0 <= d + tol, f"{item['item_type']}: footprint {x1-x0:.2f}x{z1-z0:.2f} > {w}x{d}"
    assert y1 <= h + 0.5, f"{item['item_type']}: height {y1:.2f} vs {h}"


# --------------------------------------------------------------------------- #
# Realistic parts from CC0 models (data/cc0/<id>/<id>.gltf, see fetch_cc0.py)
# --------------------------------------------------------------------------- #

CC0_DIR = ROOT.parent / "data" / "cc0"
TEX_MAX = 512  # texture side in pixels: keeps each GLB small enough for the browser


SMALL_PROPS = {"croissant", "carrot_cake", "strawberry_chocolate_cake", "hamburger_buns", "potted_plant_02", "CashRegister_01"}


def _shrink(img, side: int):
    """Resize to at most `side` pixels and re-encode as JPEG (PNG if it has transparency):
    trimesh writes images in their own format, and PNG textures made the files 5-10x bigger."""
    import io

    from PIL import Image

    if max(img.size) > side:
        k = side / max(img.size)
        img = img.resize((max(1, int(img.size[0] * k)), max(1, int(img.size[1] * k))))
    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img.save(buf, format="PNG", optimize=True)
    else:
        img.convert("RGB").save(buf, format="JPEG", quality=82)
    buf.seek(0)
    out = Image.open(buf)
    out.load()
    return out


@lru_cache(maxsize=None)
def cc0(mid: str) -> tuple[trimesh.Trimesh, ...] | None:
    """The model's meshes in world units, centered on x/z with the bottom at y = 0, textures shrunk."""
    path = CC0_DIR / mid / f"{mid}.gltf"
    if not path.exists():
        return None
    meshes = [m for m in trimesh.load(path, force="scene").dump() if isinstance(m, trimesh.Trimesh)]
    allv = np.vstack([m.vertices for m in meshes])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    shift = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2])
    side = 256 if mid in SMALL_PROPS else TEX_MAX
    seen: dict[int, object] = {}
    for m in meshes:
        m.apply_translation(shift)
        mat = getattr(m.visual, "material", None)
        for attr in ("baseColorTexture", "metallicRoughnessTexture", "normalTexture", "occlusionTexture", "emissiveTexture"):
            img = getattr(mat, attr, None) if mat is not None else None
            if img is not None:
                if id(img) not in seen:
                    seen[id(img)] = _shrink(img, side)
                setattr(mat, attr, seen[id(img)])
    return tuple(meshes)


def have(*mids: str) -> bool:
    return all(cc0(m) is not None for m in mids)


class Instance:
    """One placement of a CC0 model: exported as a node pointing at the shared mesh (glTF instancing),
    so four identical chairs cost one chair, and the JPEG textures stay JPEG."""

    def __init__(self, mid: str, transform: np.ndarray) -> None:
        self.mid, self.transform = mid, transform

    def meshes(self) -> list[trimesh.Trimesh]:  # transformed copies, only for size checks
        out = []
        for m in cc0(self.mid):
            c = trimesh.Trimesh(vertices=m.vertices.copy(), faces=m.faces, process=False)
            c.apply_transform(self.transform)
            out.append(c)
        return out


def put(mid: str, x=0.0, z=0.0, y=0.0, facing=(0.0, 1.0), scale=(1.0, 1.0, 1.0)) -> list[Instance]:
    """A CC0 model scaled, turned to face `facing` (x, z) and placed with its base at (x, y, z).
    Models face +z as authored (chairs: seat front toward +z)."""
    angle = math.atan2(facing[0], facing[1])
    t = trimesh.transformations.rotation_matrix(angle, (0, 1, 0)) @ np.diag([scale[0], scale[1], scale[2], 1.0])
    t[:3, 3] = (x, y, z)
    return [Instance(mid, t)]


def glass(w, h, d, x=0.0, y=0.0, z=0.0) -> trimesh.Trimesh:
    """See-through glass panel/box (alpha-blended material)."""
    m = trimesh.creation.box(extents=(w, h, d))
    m.apply_translation((x, y + h / 2, z))
    mat = trimesh.visual.material.PBRMaterial(baseColorFactor=[0.85, 0.93, 0.97, 0.22], metallicFactor=0.0,
                                              roughnessFactor=0.05, alphaMode="BLEND", doubleSided=True)
    m.visual = trimesh.visual.TextureVisuals(material=mat)
    return m


CAFE_CHAIR, MODERN_CHAIR = "painted_wooden_chair_01", "dining_chair_02"


def build_real(item: dict) -> list[trimesh.Trimesh] | None:
    """Realistic version of an item, or None to use the simple one."""
    t, w, d, h = item["item_type"], item["width_m"], item["depth_m"], item["height_m"]
    if t == "table_2" and have("round_wooden_table_02", CAFE_CHAIR):
        r = 0.7 / 0.8
        return (put("round_wooden_table_02", scale=(r, 1, r)) + put(CAFE_CHAIR, z=-d / 2 + 0.28, facing=(0, 1))
                + put(CAFE_CHAIR, z=d / 2 - 0.28, facing=(0, -1)))
    if t == "table_4" and have("round_wooden_table_02", CAFE_CHAIR):
        parts = put("round_wooden_table_02")
        for fx, fz in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            parts += put(CAFE_CHAIR, x=-fx * (w / 2 - 0.28), z=-fz * (d / 2 - 0.28), facing=(fx, fz))
        return parts
    if t == "bench_table_4" and have("painted_wooden_bench", "wooden_table_02", CAFE_CHAIR):
        parts = put("painted_wooden_bench", z=-d / 2 + 0.26, scale=(w / 1.2, 1, 1))
        parts += put("wooden_table_02", z=-d / 2 + 0.52 + 0.36, scale=(w / 1.2, 1, 1))
        parts += [p for sx in (-w / 4, w / 4) for p in put(CAFE_CHAIR, x=sx, z=d / 2 - 0.28, facing=(0, -1))]
        return parts
    if t == "display_case" and have("croissant", "carrot_cake", "hamburger_buns"):
        base_h = h * 0.55
        parts = [box(w, base_h, d, color=DARK_WOOD), box(w + 0.02, 0.03, d + 0.02, y=base_h - 0.03, color=WHITE)]
        top = h - base_h
        parts += [glass(w, top, 0.01, y=base_h, z=d / 2 - 0.005), glass(w, 0.01, d, y=h - 0.01),
                  glass(0.01, top, d, x=-w / 2 + 0.005, y=base_h), glass(0.01, top, d, x=w / 2 - 0.005, y=base_h)]
        shelves = [base_h, base_h + top * 0.42]
        parts += [box(w * 0.94, 0.015, d * 0.8, y=shelves[1] - 0.015, color=WHITE)]
        foods = ["croissant", "carrot_cake", "hamburger_buns", "croissant"]
        for row, y in enumerate(shelves):
            xs = np.linspace(-w / 2 + 0.22, w / 2 - 0.22, 5)
            for k, x in enumerate(xs):
                food = foods[(k + row) % len(foods)]
                for dz in ((-0.12, 0.1) if food in ("croissant", "hamburger_buns") else (0.0,)):
                    parts += put(food, x=x, z=dz, y=y + 0.002, facing=(0.3 * (k - 2), 1))
        return parts
    if t == "service_counter" and have("CashRegister_01"):
        parts = [box(w, h - 0.04, d, color=WOOD), box(w + 0.04, 0.04, d + 0.04, y=h - 0.04, color=WHITE)]
        return parts + put("CashRegister_01", x=w * 0.25, z=-0.05, y=h, scale=(0.6, 0.6, 0.6), facing=(0, -1))
    if t == "retail_shelf" and have("wooden_display_shelves_01"):
        return put("wooden_display_shelves_01", z=0.0, facing=(1, 0), scale=(d / 0.4, h / 1.56, w / 1.1))
    if t == "desk_pod" and have(MODERN_CHAIR):
        parts = [box(w * 0.98, 0.35, 0.03, y=0.75, color=FABRIC)]
        for side in (-1, 1):
            for dx in (-w / 4, w / 4):
                parts += office_desk(w / 2 - 0.04, 0.7, dx, side * 0.36, monitor_side=-side)
                parts += put(MODERN_CHAIR, x=dx, z=side * (d / 2 - 0.3), facing=(0, -side))
        return parts
    if t == "single_desk" and have(MODERN_CHAIR):
        return office_desk(w - 0.04, 0.7, 0, -d / 2 + 0.36, monitor_side=-1) + put(MODERN_CHAIR, z=d / 2 - 0.3, facing=(0, -1))
    if t == "meeting_table" and have(MODERN_CHAIR):
        parts = [box(2.0, 0.04, 1.1, y=0.72, color=WOOD)]
        parts += [box(0.08, 0.72, 0.8, x=sx, color=DARK_STEEL) for sx in (-0.75, 0.75)]
        for dx in (-0.65, 0.0, 0.65):
            parts += put(MODERN_CHAIR, x=dx, z=-(d / 2 - 0.3), facing=(0, 1)) + put(MODERN_CHAIR, x=dx, z=d / 2 - 0.3, facing=(0, -1))
        parts += put(MODERN_CHAIR, x=-(w / 2 - 0.3), facing=(1, 0)) + put(MODERN_CHAIR, x=w / 2 - 0.3, facing=(-1, 0))
        return parts
    if t == "reception_desk" and have(MODERN_CHAIR):
        parts = [box(w, 1.05, 0.6, z=d / 2 - 0.3, color=WOOD), box(w, 0.04, 0.35, y=1.05, z=d / 2 - 0.18, color=PLASTIC_WHITE),
                 box(w * 0.9, 0.03, 0.6, y=0.72, z=d / 2 - 0.85, color=PLASTIC_WHITE), box(0.6, 0.36, 0.03, y=0.9, z=d / 2 - 0.68, color=SCREEN)]
        return parts + put(MODERN_CHAIR, z=-d / 2 + 0.3, facing=(0, 1))
    if t == "sofa" and have("sofa_02"):
        return put("sofa_02", facing=(0, -1), scale=(w / 1.85, 1, d / 0.85))
    if t == "storage_cabinet" and have("drawer_cabinet"):
        return put("drawer_cabinet", scale=(w / 1.16, h / 1.9, d / 0.5))
    return None


def build_any(item: dict) -> tuple[trimesh.Scene, trimesh.Trimesh]:
    """(scene to export, all geometry merged for size checks). Realistic parts when the CC0 sources
    are present, simple shapes otherwise. Simple shapes are merged into one mesh; CC0 models are instanced."""
    parts = build_real(item)
    if parts is None:
        mesh = build(item)
        return trimesh.Scene([mesh]), mesh
    meshes = [p for p in parts if isinstance(p, trimesh.Trimesh)]
    simple = [m for m in meshes if isinstance(m.visual, trimesh.visual.ColorVisuals)]  # vertex-colored boxes
    textured = [m for m in meshes if not isinstance(m.visual, trimesh.visual.ColorVisuals)]  # e.g. glass
    insts = [p for p in parts if isinstance(p, Instance)]
    scene = trimesh.Scene()
    if simple:  # merging only same-kind meshes keeps their colors
        scene.add_geometry(trimesh.util.concatenate(simple), geom_name="simple", node_name="simple")
    for k, m in enumerate(textured):
        scene.add_geometry(m, geom_name=f"textured_{k}", node_name=f"textured_{k}")
    for k, inst in enumerate(insts):
        for i, m in enumerate(cc0(inst.mid)):
            name = f"{inst.mid}_{i}"
            if name not in scene.geometry:
                scene.geometry[name] = m
            scene.graph.update(frame_to=f"{name}_n{k}", frame_from=scene.graph.base_frame, matrix=inst.transform, geometry=name)
    plain = [trimesh.Trimesh(vertices=m.vertices, faces=m.faces, process=False) for m in meshes]
    check_mesh = trimesh.util.concatenate(plain + [m for inst in insts for m in inst.meshes()])
    return scene, check_mesh


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    items = json.loads(CATALOG.read_text())
    real = 0
    for item in items:
        scene, mesh = build_any(item)
        real += build_real(item) is not None
        check(mesh, item)
        path = ROOT.parent / item["glb_asset"]
        path.parent.mkdir(parents=True, exist_ok=True)
        scene.export(path)
        print(f"{item['item_type']:20s} {path.stat().st_size / 1024:7.1f} KB  bounds {np.round(mesh.extents, 2)}")
    print(f"{real} of {len(items)} items use CC0 models" + ("" if real else " (run assets/fetch_cc0.py first)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
