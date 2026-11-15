"""Generate simple, correctly sized GLB models for every item in assets/catalog.json.

    python assets/build_assets.py

Every model:
* is in meters, with its footprint exactly width_m x depth_m and height height_m;
* has its origin at the center of the footprint on the floor (y = 0);
* faces +z (its "front": doors, glass, the customer side).
So the frontend places it at (x_m, floor_y, z_m) and rotates it by rotation_deg about +y.

Realistic models come from two free sources, downloaded to the gitignored data/ folder:
* Sketchfab (CC-BY, credits in assets/CREDITS.md): chairs, desks, laptops, monitors, counters, the
  pastry case, espresso machine, fridge, sink, mixer, meeting table, sofa, plants.
  `python assets/fetch_sketchfab.py` (needs SKETCHFAB_API_TOKEN in .env).
* Poly Haven (CC0): café table, bench, cash register, cabinets, shelves. `python assets/fetch_cc0.py`.
Chair styles are mixed on purpose: each kind of table or desk gets its own chair. Without the
sources, items fall back to Poly Haven only, then to simple box geometry. The ovens, condiment
station and phone booth stay simple shapes (no realistic free model found).
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
    m.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, (1, 0, 0)))  # trimesh builds it along z: stand it up
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


OAK = (206, 168, 120, 255)  # light oak desk tops
WALNUT = (112, 78, 56, 255)
TEAL = (58, 134, 140, 255)  # accent: screens, upholstery, bars
CORAL = (226, 112, 86, 255)  # accent: reception front
MUSTARD = (222, 170, 70, 255)
TERRACOTTA = (176, 98, 68, 255)
SOIL = (60, 45, 35, 255)
LEAF = (95, 150, 80, 255)
LAMP_SHADE = (240, 228, 200, 255)


def sphere(r, x=0.0, y=0.0, z=0.0, color=(70, 120, 70, 255)) -> trimesh.Trimesh:
    """Ball of radius r centered at (x, y, z): foliage."""
    m = trimesh.creation.icosphere(subdivisions=2, radius=r)
    m.apply_translation((x, y, z))
    m.visual.vertex_colors = np.tile(np.array(color, dtype=np.uint8), (len(m.vertices), 1))
    return m


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
    parts = [box(w, 0.03, d, x, 0.72, z, OAK)]
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
        parts = [box(w * 0.98, 0.35, 0.03, y=0.75, color=TEAL)]
        for side in (-1, 1):
            for dx in (-w / 4, w / 4):
                parts += office_desk(w / 2 - 0.04, 0.7, dx, side * 0.36, monitor_side=-side)
                parts += task_chair(dx, side * (0.7 + 0.45), facing_z=-side)
    elif t == "single_desk":
        # Desk against the wall (-z), chair in front of it (+z side).
        parts = office_desk(w - 0.04, 0.7, 0, -d / 2 + 0.36, monitor_side=-1) + task_chair(0, -d / 2 + 0.7 + 0.42, facing_z=-1)
    elif t == "meeting_table":
        parts = [box(2.0, 0.04, 1.1, y=0.72, color=WALNUT)]
        parts += [box(0.08, 0.72, 0.8, x=sx, color=DARK_STEEL) for sx in (-0.75, 0.75)]
        for dx in (-0.7, 0.0, 0.7):
            parts += task_chair(dx, -0.95, facing_z=+1) + task_chair(dx, 0.95, facing_z=-1)
        parts += [box(0.5, 0.05, 0.5, x=sx, y=0.44, color=CHARCOAL) for sx in (-1.03, 1.03)]
        parts += [box(0.05, 0.5, 0.48, x=sx + 0.22 * (1 if sx > 0 else -1), y=0.5, color=CHARCOAL) for sx in (-1.03, 1.03)]
        parts += [cylinder(0.03, 0.42, x=sx, y=0.02, color=DARK_STEEL) for sx in (-1.03, 1.03)]
    elif t == "reception_desk":
        # Visitors on +z; a raised top facing them; staff chair behind (-z, against the wall).
        parts = [box(w, 1.05, 0.6, z=d / 2 - 0.3, color=CORAL), box(w, 0.04, 0.35, y=1.05, z=d / 2 - 0.18, color=PLASTIC_WHITE),
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
        parts += [box(0.6, 0.03, 0.35, y=1.0, z=-d / 2 + 0.2, color=WOOD), box(0.4, 0.45, 0.4, color=TEAL)]
    elif t == "storage_cabinet":
        parts = [box(w, h, d, color=PLASTIC_WHITE)]
        parts += [box(0.02, h * 0.9, 0.01, x=0, y=h * 0.05, z=d / 2, color=CHARCOAL)]
        parts += [box(0.03, 0.25, 0.03, x=sx, y=h * 0.45, z=d / 2 + 0.01, color=DARK_STEEL) for sx in (-0.08, 0.08)]
    elif t == "kitchenette_counter":
        parts = [box(w, 0.88, d, color=PLASTIC_WHITE), box(w, 0.04, d, y=0.88, color=DARK_WOOD),
                 box(0.5, 0.03, 0.4, x=-w / 4, y=0.91, color=STEEL),
                 box(w, 0.7, 0.35, y=1.5, z=-d / 2 + 0.175, color=PLASTIC_WHITE),
                 box(0.55, 0.85, 0.55, x=w / 2 - 0.3, y=0.92, z=-0.02, color=DARK_STEEL)]  # fridge/coffee
    elif t == "lounge_set":
        # Sofa against the back (-z), coffee table in front of it, an armchair on each side facing the table.
        parts = [box(2.0, 0.42, 0.9, z=-d / 2 + 0.45, color=UPHOLSTERY), box(2.0, 0.43, 0.2, y=0.42, z=-d / 2 + 0.1, color=UPHOLSTERY)]
        parts += [box(0.18, 0.2, 0.9, x=sx, y=0.42, z=-d / 2 + 0.45, color=UPHOLSTERY) for sx in (-0.91, 0.91)]
        parts += [box(1.0, 0.04, 0.55, y=0.38, z=0.1, color=WOOD), box(0.06, 0.38, 0.06, x=-0.4, z=0.1, color=BLACK), box(0.06, 0.38, 0.06, x=0.4, z=0.1, color=BLACK)]
        for sx, face in ((-1.08, 1), (1.08, -1)):  # armchair seat 0.75, back on the outer side
            parts += [box(0.75, 0.4, 0.75, x=sx, z=0.1, color=FABRIC), box(0.2, 0.4, 0.75, x=sx - 0.275 * face, y=0.4, z=0.1, color=FABRIC)]
    elif t == "huddle_table":
        parts = [cylinder(0.55, 0.04, y=0.72, color=WOOD), cylinder(0.05, 0.72, color=BLACK), cylinder(0.3, 0.03, color=BLACK)]
        parts += chair(0, -0.64, +1) + chair(0, 0.64, -1) + chair_x(-0.64, 0, +1) + chair_x(0.64, 0, -1)
    elif t == "coffee_bar":
        parts = [box(w, h - 0.06, d, color=TEAL), box(w + 0.04, 0.06, d + 0.04, y=h - 0.06, color=OAK),
                 box(0.55, 0.45, 0.4, x=-w * 0.25, y=h, z=-d * 0.15, color=STEEL), box(0.3, 0.3, 0.3, x=w * 0.2, y=h, z=-d * 0.15, color=BLACK),
                 box(0.6, 0.12, 0.4, x=w * 0.3, y=h, z=d * 0.1, color=PLASTIC_WHITE)]
    elif t == "bookshelf":
        parts = [box(w, h, 0.03, z=-d / 2 + 0.015, color=WOOD)]
        parts += [box(0.03, h, d, x=sx, color=WOOD) for sx in (-w / 2 + 0.015, w / 2 - 0.015)]
        parts += [box(w, 0.03, d, y=k * (h - 0.03) / 5, color=WOOD) for k in range(6)]
        shades = [(150, 70, 60, 255), (70, 100, 150, 255), (90, 130, 90, 255), (200, 170, 90, 255), PLASTIC_WHITE]
        for row in range(1, 5):  # books: narrow boxes of varying height on four shelves
            x = -w / 2 + 0.08
            k = 0
            while x < w / 2 - 0.12:
                bw = 0.04 + 0.02 * (k % 3)
                parts.append(box(bw, 0.2 + 0.05 * ((k + row) % 3), d * 0.75, x + bw / 2, row * (h - 0.03) / 5 + 0.03, 0.0, shades[(k + row) % len(shades)]))
                x += bw + 0.005
                k += 1
    elif t == "printer_station":
        parts = [box(w, 0.8, d, color=PLASTIC_WHITE), box(0.6, 0.3, 0.5, y=0.8, color=CHARCOAL), box(0.5, 0.02, 0.3, y=1.1, z=0.0, color=WHITE),
                 box(0.02, 0.5, 0.01, y=0.15, z=d / 2, color=CHARCOAL)]
    elif t == "whiteboard":
        parts = [box(w, 1.0, 0.03, y=0.9, z=-d / 2 + 0.2, color=PLASTIC_WHITE), box(w + 0.04, 0.03, 0.05, y=0.88, z=-d / 2 + 0.2, color=DARK_STEEL),
                 box(w + 0.04, 0.03, 0.05, y=1.9 - 0.03, z=-d / 2 + 0.2, color=DARK_STEEL)]
        parts += [box(0.04, 0.9, 0.04, x=sx, z=-d / 2 + 0.2, color=DARK_STEEL) for sx in (-w / 2 + 0.1, w / 2 - 0.1)]
        parts += [box(0.05, 0.04, 0.4, x=sx, z=-d / 2 + 0.2, color=DARK_STEEL) for sx in (-w / 2 + 0.1, w / 2 - 0.1)]
        parts += [box(0.35, 0.02, 0.07, x=0.0, y=0.88, z=-d / 2 + 0.25, color=CHARCOAL)]
    elif t == "plant_large":
        parts = [cylinder(0.22, 0.4, color=TERRACOTTA), cylinder(0.21, 0.02, y=0.4, color=SOIL), cylinder(0.025, 0.5, y=0.4, color=DARK_WOOD)]
        parts += [sphere(0.27, 0.0, 1.05, 0.0, PLANT), sphere(0.2, 0.09, 1.3, 0.06, LEAF), sphere(0.2, -0.09, 0.88, -0.05, LEAF),
                  sphere(0.17, -0.05, 1.42, 0.1, PLANT), sphere(0.17, 0.11, 0.82, 0.1, PLANT)]
    elif t == "planter_divider":
        parts = [box(w, 0.45, d, color=CHARCOAL), box(w - 0.06, 0.02, d - 0.06, y=0.45, color=SOIL)]
        parts += [sphere(0.24, x, 0.78, 0.0, PLANT) for x in np.linspace(-w / 2 + 0.3, w / 2 - 0.3, 4)]
        parts += [sphere(0.18, x, 1.0, 0.0, LEAF) for x in np.linspace(-w / 2 + 0.5, w / 2 - 0.5, 3)]
    elif t.startswith("rug_"):
        base = {"rug_lounge": (46, 111, 121, 255), "rug_huddle": (196, 106, 75, 255), "rug_meeting": (72, 92, 128, 255)}.get(t, (120, 120, 130, 255))
        edge = tuple(min(255, int(c * 1.25)) for c in base[:3]) + (255,)
        parts = [box(w, 0.012, d, color=base), box(w - 0.3, 0.008, d - 0.3, y=0.012, color=edge), box(w - 0.55, 0.008, d - 0.55, y=0.02, color=base)]
    elif t == "floor_lamp":
        parts = [cylinder(0.2, 0.03, color=BLACK), cylinder(0.015, 1.35, y=0.03, color=DARK_STEEL), cylinder(0.2, 0.32, y=1.38, color=MUSTARD)]
    else:
        parts = [box(w, h, d)]
    mesh = trimesh.util.concatenate(parts)
    return mesh


def bake_materials(scene: trimesh.Scene) -> trimesh.Scene:
    """Give every vertex-coloured mesh a real material per colour (and drop the vertex colours).
    Viewers that ignore COLOR_0 (the Matterport scene one included) draw vertex-coloured parts black;
    a plain PBR material with a base colour looks the same everywhere."""
    for gname in list(scene.geometry):
        g = scene.geometry[gname]
        if not (isinstance(g, trimesh.Trimesh) and isinstance(g.visual, trimesh.visual.ColorVisuals) and g.visual.kind == "vertex"):
            continue
        nodes = [(n, scene.graph[n][0]) for n in scene.graph.nodes_geometry if scene.graph[n][1] == gname]
        vc = np.asarray(g.visual.vertex_colors)
        face_colors = vc[g.faces[:, 0]]
        pieces = []
        for color in np.unique(face_colors, axis=0):
            idx = np.nonzero((face_colors == color).all(axis=1))[0]
            sub = g.submesh([idx], append=True)
            sub.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
                baseColorFactor=[int(c) for c in color], metallicFactor=0.0, roughnessFactor=0.8, doubleSided=True))
            pieces.append(sub)
        scene.delete_geometry(gname)
        for node, matrix in nodes:
            for k, piece in enumerate(pieces):
                scene.add_geometry(piece, node_name=f"{node}_c{k}", geom_name=f"{gname}_c{k}", transform=matrix)
    return scene


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
SKETCHFAB_DIR = ROOT.parent / "data" / "sketchfab"  # see fetch_sketchfab.py
# Sketchfab models come in their authors' units and orientation. Each is turned (yaw, degrees about
# +y) so its front faces +z like every other model here; sizes are set where it is used (fit()).
# "src" reuses another download; "keep"/"drop" pick parts by node name (the desk comes with a chair).
SKETCHFAB_FIX = {
    "office_chair_mesh": {"yaw": 90.0},
    "leather_office_chair": {"yaw": 0.0},
    "bentwood_chair": {"yaw": 0.0},
    "bistro_chair": {"yaw": -90.0},
    "tolix_chair": {"yaw": 0.0},
    "cafe_table": {"yaw": 0.0},
    "pastry_case": {"yaw": 0.0},  # curved glass toward the customer
    "bar_counter": {"yaw": 0.0},  # panelled side toward the customer
    "espresso_machine": {"yaw": 0.0},  # group heads toward +z (turned to the barista when placed)
    "commercial_fridge": {"yaw": 0.0},
    "steel_table": {"yaw": 90.0},  # long side along x
    "commercial_sink": {"yaw": 0.0},
    "dough_mixer": {"yaw": 0.0},
    "wood_desk": {"yaw": 0.0, "drop": ("Office-Chair",)},  # the user sits on the +z side
    "wood_desk_chair": {"src": "wood_desk", "yaw": 180.0, "keep": ("Office-Chair",)},
    "dual_monitors": {"yaw": 0.0},
    "laptop": {"yaw": 0.0},  # keyboard toward +z
    "glass_meeting_table": {"yaw": 0.0},  # table with six chrome chairs
    "modern_sofa": {"yaw": 0.0},
    "table_tennis": {"yaw": 0.0},  # long side along x
    "foosball": {"yaw": 0.0},  # goal to goal along x, handles toward +z/-z
    "koi": {"yaw": 0.0},
    "office_printer": {"yaw": 0.0},  # control panel toward +z
    "mobile_whiteboard": {"yaw": 0.0},
    "floor_lamp_classic": {"yaw": 0.0},
    "persian_rug": {"yaw": 90.0},  # long side along x
    "old_persian_carpet": {"yaw": 90.0},
    "monstera": {"yaw": 0.0},
    "pothos": {"yaw": 0.0},
}
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
    fix = SKETCHFAB_FIX.get(mid)
    path = SKETCHFAB_DIR / fix.get("src", mid) / "model.glb" if fix else CC0_DIR / mid / f"{mid}.gltf"
    if not path.exists():
        return None
    if fix:
        scene = trimesh.load(path, force="scene")
        keep, drop = fix.get("keep"), fix.get("drop", ())
        meshes = []
        for node in scene.graph.nodes_geometry:
            if (keep and not any(k in node for k in keep)) or any(k in node for k in drop):
                continue
            transform, geom = scene.graph[node]
            m = scene.geometry[geom]
            if isinstance(m, trimesh.Trimesh):
                m = m.copy()
                m.apply_transform(transform)
                meshes.append(m)
        t = trimesh.transformations.rotation_matrix(math.radians(fix["yaw"]), (0, 1, 0))
        for m in meshes:
            m.apply_transform(t)
    else:
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


def size_of(mid: str) -> np.ndarray:
    v = np.vstack([m.vertices for m in cc0(mid)])
    return v.max(axis=0) - v.min(axis=0)


def fit(mid: str, w: float | None = None, h: float | None = None, d: float | None = None, stretch: bool = False):
    """Scale for put(): the model's width/height/depth (its own x/y/z, front = +z) brought to the given
    meters. Uniform (the smallest ratio, so it fits) unless stretch=True; a missing axis then takes
    the average of the others."""
    ex, ey, ez = size_of(mid)
    r = [w / ex if w else None, h / ey if h else None, d / ez if d else None]
    given = [v for v in r if v]
    if not stretch:
        s = min(given)
        return (s, s, s)
    avg = sum(given) / len(given)
    return tuple(v or avg for v in r)


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


def ellipsoid(rx, ry, rz, x=0.0, y=0.0, z=0.0, color=(230, 120, 40, 255)) -> trimesh.Trimesh:
    m = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
    m.apply_scale([rx, ry, rz])
    m.apply_translation((x, y, z))
    m.visual.vertex_colors = np.tile(np.array(color, dtype=np.uint8), (len(m.vertices), 1))
    return m


def water(w, h, d, x=0.0, y=0.0, z=0.0) -> trimesh.Trimesh:
    """Blue see-through water surface (alpha-blended material)."""
    m = trimesh.creation.box(extents=(w, h, d))
    m.apply_translation((x, y + h / 2, z))
    mat = trimesh.visual.material.PBRMaterial(baseColorFactor=[0.16, 0.47, 0.62, 0.55], metallicFactor=0.0,
                                              roughnessFactor=0.05, alphaMode="BLEND", doubleSided=True)
    m.visual = trimesh.visual.TextureVisuals(material=mat)
    return m


CAFE_CHAIR, MODERN_CHAIR = "painted_wooden_chair_01", "dining_chair_02"


def turned(facing: tuple[float, float], deg: float) -> tuple[float, float]:
    """`facing` swiveled by a few degrees, so rows of chairs don't look machine-placed."""
    a = math.radians(deg)
    return (facing[0] * math.cos(a) + facing[1] * math.sin(a), -facing[0] * math.sin(a) + facing[1] * math.cos(a))


SWIVEL = (-9.0, 6.0, -4.0, 11.0, 3.0, -7.0, 8.0, -12.0)  # fixed, so builds are reproducible


DESK_TOP = 0.76  # m
WOOD_DESK_TOP_SHARE = 816 / 1296  # the desk model's top sits at this share of its height (lamp included)


def _desk(w: float, d: float, x=0.0, z=0.0, facing=(0.0, 1.0)) -> list:
    """The wood desk (tablet, frames, lamp and books on it) at DESK_TOP height, user on its `facing` side."""
    return put("wood_desk", x=x, z=z, facing=facing, scale=fit("wood_desk", w=w, h=DESK_TOP / WOOD_DESK_TOP_SHARE, d=d, stretch=True))


def build_sketchfab(item: dict) -> list | None:
    """The item from Sketchfab models (CC-BY, assets/CREDITS.md), or None when the sources are missing.
    Chairs are mixed on purpose: each kind of table or desk gets its own chair style."""
    t, w, d, h = item["item_type"], item["width_m"], item["depth_m"], item["height_m"]
    if t == "table_2" and have("cafe_table", "bistro_chair"):
        parts = put("cafe_table", scale=fit("cafe_table", h=0.75))
        chair = fit("bistro_chair", h=0.86)
        parts += put("bistro_chair", z=-d / 2 + 0.26, facing=turned((0, 1), SWIVEL[0]), scale=chair)
        return parts + put("bistro_chair", z=d / 2 - 0.26, facing=turned((0, -1), SWIVEL[3]), scale=chair)
    if t == "table_4" and have("round_wooden_table_02", "bentwood_chair"):
        parts = put("round_wooden_table_02")
        for k, (fx, fz) in enumerate(((0, 1), (0, -1), (1, 0), (-1, 0))):
            parts += put("bentwood_chair", x=-fx * (w / 2 - 0.28), z=-fz * (d / 2 - 0.28), facing=turned((fx, fz), SWIVEL[k] * 0.6))
        return parts
    if t == "bench_table_4" and have("painted_wooden_bench", "wooden_table_02", "tolix_chair"):
        parts = put("painted_wooden_bench", z=-d / 2 + 0.26, scale=(w / 1.2, 1, 1))
        parts += put("wooden_table_02", z=-d / 2 + 0.52 + 0.36, scale=(w / 1.2, 1, 1))
        chair = fit("tolix_chair", h=0.86)
        return parts + [p for k, sx in enumerate((-w / 4, w / 4)) for p in put("tolix_chair", x=sx, z=d / 2 - 0.27, facing=turned((0, -1), SWIVEL[k + 4]), scale=chair)]
    if t == "display_case" and have("pastry_case"):
        return put("pastry_case", scale=fit("pastry_case", w=w, h=h, d=d, stretch=True))
    if t in ("service_counter", "espresso_bar") and have("bar_counter"):
        parts = put("bar_counter", scale=fit("bar_counter", w=w, h=1.0, d=d, stretch=True))
        if t == "service_counter" and have("CashRegister_01"):
            parts += put("CashRegister_01", x=w * 0.25, z=-0.05, y=1.0, scale=(0.6, 0.6, 0.6), facing=(0, -1))
        if t == "espresso_bar" and have("espresso_machine"):
            parts += put("espresso_machine", x=-w * 0.15, z=-0.05, y=1.0, facing=(0, -1), scale=fit("espresso_machine", h=0.5))
        return parts
    if t in ("reach_in_fridge", "proofing_cabinet") and have("commercial_fridge"):
        return put("commercial_fridge", scale=fit("commercial_fridge", w=w, h=h, d=d, stretch=True))
    if t == "prep_table" and have("steel_table"):
        return put("steel_table", scale=fit("steel_table", w=w, h=h, d=d, stretch=True))
    if t == "three_comp_sink" and have("commercial_sink"):
        return put("commercial_sink", scale=fit("commercial_sink", w=w, h=h, d=d, stretch=True))
    if t == "spiral_mixer" and have("steel_table", "dough_mixer"):
        top = 0.8
        parts = put("steel_table", scale=fit("steel_table", w=w, h=top, d=d, stretch=True))
        return parts + put("dough_mixer", y=top, scale=fit("dough_mixer", w=w * 0.95, d=d * 0.95))
    if t == "desk_pod" and have("wood_desk", "office_chair_mesh", "laptop"):
        parts = [box(w * 0.98, 0.35, 0.03, y=DESK_TOP, color=FABRIC)]  # low screen between the facing desks
        k = 0
        for side in (-1, 1):
            for dx in (-w / 4, w / 4):
                parts += _desk(w / 2 - 0.04, 0.7, x=dx, z=side * 0.36, facing=(0, side))
                parts += put("laptop", x=dx + 0.1, z=side * 0.45, y=DESK_TOP, facing=(0, side), scale=fit("laptop", w=0.34))
                parts += put("office_chair_mesh", x=dx, z=side * (d / 2 - 0.34), facing=turned((0, -side), SWIVEL[k]),
                             scale=fit("office_chair_mesh", h=0.98))
                k += 1
        return parts
    if t == "single_desk" and have("wood_desk", "wood_desk_chair"):
        parts = _desk(w - 0.04, 0.7, z=-d / 2 + 0.36)
        return parts + put("wood_desk_chair", z=-d / 2 + 0.7 + 0.32, facing=turned((0, -1), SWIVEL[2]), scale=fit("wood_desk_chair", h=0.95))
    if t == "meeting_table" and have("glass_meeting_table"):
        return put("glass_meeting_table", facing=(1, 0), scale=fit("glass_meeting_table", w=w - 0.1, h=h, d=d - 0.1))
    if t == "reception_desk" and have("bar_counter", "leather_office_chair", "dual_monitors", "pothos"):
        front_z = d / 2 - 0.3
        parts = put("bar_counter", z=front_z, scale=fit("bar_counter", w=w, h=1.05, d=0.6, stretch=True))
        parts += put("dual_monitors", z=front_z - 0.12, y=1.05, facing=(0, -1), scale=fit("dual_monitors", w=0.9))
        parts += put("pothos", x=w / 2 - 0.25, z=front_z, y=1.05, scale=fit("pothos", h=0.35))
        return parts + put("leather_office_chair", z=-d / 2 + 0.36, facing=(0, 1), scale=fit("leather_office_chair", h=1.0))
    if t == "sofa" and have("modern_sofa", "monstera"):
        parts = put("modern_sofa", x=-0.22, scale=fit("modern_sofa", w=w - 0.46, h=0.72, d=d - 0.04, stretch=True))
        return parts + put("monstera", x=w / 2 - 0.22, z=-0.1, scale=fit("monstera", w=0.44))
    if t == "kitchenette_counter" and have("modern_wooden_cabinet", "espresso_machine"):
        parts = put("modern_wooden_cabinet", scale=fit("modern_wooden_cabinet", w=w, h=0.88, d=d - 0.05, stretch=True))
        parts += [box(w + 0.02, 0.04, d, y=0.88, color=PLASTIC_WHITE)]  # worktop
        parts += put("modern_wooden_cabinet", y=1.45, z=-d / 2 + 0.18, scale=fit("modern_wooden_cabinet", w=w, h=0.7, d=0.35, stretch=True))
        return parts + put("espresso_machine", x=-w / 4, y=0.92, scale=fit("espresso_machine", h=0.38))
    if t == "huddle_table" and have("round_wooden_table_02", "tolix_chair"):
        parts = put("round_wooden_table_02", scale=(1.25, 1.1, 1.25))
        chair = fit("tolix_chair", h=0.86)
        for k, (fx, fz) in enumerate(((0, 1), (0, -1), (1, 0), (-1, 0))):
            parts += put("tolix_chair", x=-fx * (w / 2 - 0.3), z=-fz * (d / 2 - 0.3), facing=turned((fx, fz), SWIVEL[k + 2] * 0.6), scale=chair)
        return parts
    if t == "table_tennis" and have("table_tennis"):
        return put("table_tennis", scale=fit("table_tennis", w=w, h=0.8, d=d, stretch=True))
    if t == "foosball_table" and have("foosball"):
        return put("foosball", scale=fit("foosball", w=w, h=h, d=d, stretch=True))
    if t == "printer_station" and have("office_printer"):
        return put("office_printer", scale=fit("office_printer", w=w, h=h, d=d))
    if t == "whiteboard" and have("mobile_whiteboard"):
        return put("mobile_whiteboard", scale=fit("mobile_whiteboard", w=w, h=h, d=d, stretch=True))
    if t == "floor_lamp" and have("floor_lamp_classic"):
        return put("floor_lamp_classic", scale=fit("floor_lamp_classic", w=w, h=h, d=d))
    if t.startswith("rug_") and have("persian_rug", "old_persian_carpet"):
        mid = "old_persian_carpet" if t == "rug_huddle" else "persian_rug"  # two patterns, so rooms differ
        return put(mid, scale=fit(mid, w=w, h=0.02, d=d, stretch=True))
    if t == "coffee_bar" and have("bar_counter", "espresso_machine", "pothos"):
        parts = put("bar_counter", scale=fit("bar_counter", w=w, h=1.0, d=d, stretch=True))
        parts += put("espresso_machine", x=-w * 0.2, y=1.0, scale=fit("espresso_machine", h=0.45))  # faces the people using it
        return parts + put("pothos", x=w / 2 - 0.25, y=1.0, scale=fit("pothos", h=0.35))
    if t == "fish_pond" and have("koi"):  # Biniyam's stone pond with real koi under the water
        stone, rim = (150, 150, 142, 255), 0.22
        parts = [box(w, h, rim, z=-d / 2 + rim / 2, color=stone), box(w, h, rim, z=d / 2 - rim / 2, color=stone),
                 box(rim, h, d - 2 * rim, x=-w / 2 + rim / 2, color=stone), box(rim, h, d - 2 * rim, x=w / 2 - rim / 2, color=stone),
                 box(w - 2 * rim, 0.28, d - 2 * rim, color=(34, 70, 84, 255))]
        koi = fit("koi", w=0.46)
        for x, z, f in ((-0.7, 0.1, (1, 0.3)), (0.2, -0.3, (-1, 0.2)), (0.8, 0.25, (0.4, -1)), (-0.1, 0.35, (1, -0.5)), (0.5, -0.1, (-0.6, 1))):
            parts += put("koi", x=x, z=z, y=0.32, facing=f, scale=koi)
        parts += [cylinder(0.17, 0.012, -0.35, 0.42, -0.2, color=(70, 130, 70, 255)), cylinder(0.14, 0.012, 0.9, 0.42, 0.1, color=(70, 130, 70, 255))]
        parts += [sphere(0.12, -w / 2 + rim + 0.18, 0.5, -d / 2 + rim + 0.15, (120, 120, 118, 255)), sphere(0.09, -w / 2 + rim + 0.34, 0.5, -d / 2 + rim + 0.12, (135, 135, 130, 255))]
        if have("pothos"):
            parts += put("pothos", x=w / 2 - 0.25, y=h, z=d / 2 - 0.2, scale=fit("pothos", w=0.3, d=0.36))
        parts.append(water(w - 2 * rim, 0.01, d - 2 * rim, y=0.42))
        return parts
    if t == "plant_large" and have("monstera"):
        return [box(0.36, 0.4, 0.36, color=WHITE)] + put("monstera", y=0.4, scale=fit("monstera", w=w, h=h - 0.4, d=d))
    if t == "planter_divider" and have("pothos"):
        parts = [box(w, 0.45, d, color=CHARCOAL)]
        for x in np.linspace(-w / 2 + 0.3, w / 2 - 0.3, 3):
            parts += put("pothos", x=float(x), y=0.45, scale=fit("pothos", w=0.56, h=h - 0.45, d=d))
        return parts
    return None


def build_real(item: dict) -> list[trimesh.Trimesh] | None:
    """Realistic version of an item, or None to use the simple one."""
    parts = build_sketchfab(item)
    if parts is not None:
        return parts
    t, w, d, h = item["item_type"], item["width_m"], item["depth_m"], item["height_m"]
    # Fallback when the Sketchfab sources are missing: Poly Haven chairs only.
    CAFE_CHAIR, DESK_CHAIR, MEETING_CHAIR = "painted_wooden_chair_01", "dining_chair_02", "dining_chair_02"
    if t == "table_tennis":  # long side along x; net across the middle
        parts = [box(w, 0.03, d, y=0.73, color=(28, 78, 140, 255)), box(w - 0.04, 0.004, 0.02, y=0.76, color=WHITE), box(0.02, 0.004, d - 0.04, x=0.0, y=0.76, color=WHITE),
                 box(0.02, 0.15, d, y=0.76, color=WHITE), box(w - 0.04, 0.004, 0.02, y=0.76, z=d / 2 - 0.02, color=WHITE)]
        parts += [box(0.05, 0.73, 0.05, x=sx, z=sz, color=CHARCOAL) for sx in (-w / 2 + 0.2, w / 2 - 0.2) for sz in (-d / 2 + 0.15, d / 2 - 0.15)]
        parts += [box(0.16, 0.012, 0.18, x=-w / 2 + 0.5, y=0.76, z=0.25, color=(190, 40, 40, 255)), box(0.16, 0.012, 0.18, x=w / 2 - 0.5, y=0.76, z=-0.25, color=(30, 30, 30, 255)),
                  sphere(0.02, 0.4, 0.78, 0.1, (250, 250, 240, 255))]
        return parts
    if t == "foosball_table":
        green = (46, 125, 70, 255)
        parts = [box(w, 0.05, d, y=0.78, color=WALNUT), box(w - 0.1, 0.02, d - 0.1, y=0.83, color=green)]
        parts += [box(w, 0.1, 0.05, y=0.83, z=sz, color=WALNUT) for sz in (-d / 2 + 0.025, d / 2 - 0.025)] + [box(0.05, 0.1, d, x=sx, y=0.83, color=WALNUT) for sx in (-w / 2 + 0.025, w / 2 - 0.025)]
        parts += [box(0.06, 0.78, 0.06, x=sx, z=sz, color=CHARCOAL) for sx in (-w / 2 + 0.08, w / 2 - 0.08) for sz in (-d / 2 + 0.08, d / 2 - 0.08)]
        for k, x in enumerate((-0.45, -0.15, 0.15, 0.45)):  # rods across the table with a red or blue row of players
            parts.append(box(0.015, 0.015, d, x=x, y=0.92, color=STEEL))
            parts += [box(0.04, 0.1, 0.03, x=x, y=0.84, z=zz, color=(200, 50, 50, 255) if k % 2 == 0 else (50, 90, 200, 255)) for zz in (-0.18, 0.0, 0.18)]
        return parts
    if t == "fish_pond":
        stone, rim = (150, 150, 142, 255), 0.22
        parts = [box(w, h, rim, z=-d / 2 + rim / 2, color=stone), box(w, h, rim, z=d / 2 - rim / 2, color=stone),
                 box(rim, h, d - 2 * rim, x=-w / 2 + rim / 2, color=stone), box(rim, h, d - 2 * rim, x=w / 2 - rim / 2, color=stone),
                 box(w - 2 * rim, 0.28, d - 2 * rim, color=(34, 70, 84, 255))]
        parts += [ellipsoid(0.16, 0.05, 0.06, x, 0.33, z, (232, 118, 40, 255)) for k, (x, z) in enumerate([(-0.7, 0.1), (0.2, -0.3), (0.8, 0.25), (-0.1, 0.35)])]
        parts += [ellipsoid(0.12, 0.04, 0.05, 0.5, 0.31, -0.1, (245, 240, 230, 255)), cylinder(0.17, 0.012, -0.35, 0.42, -0.2, color=(70, 130, 70, 255)), cylinder(0.14, 0.012, 0.9, 0.42, 0.1, color=(70, 130, 70, 255))]
        parts += [sphere(0.12, -w / 2 + rim + 0.18, 0.5, -d / 2 + rim + 0.15, (120, 120, 118, 255)), sphere(0.09, -w / 2 + rim + 0.34, 0.5, -d / 2 + rim + 0.12, (135, 135, 130, 255)), sphere(0.2, w / 2 - rim - 0.3, 0.62, d / 2 - rim - 0.25, PLANT)]
        parts.append(water(w - 2 * rim, 0.01, d - 2 * rim, y=0.42))
        return parts
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
    if t == "desk_pod" and have(DESK_CHAIR):
        parts = [box(w * 0.98, 0.35, 0.03, y=0.75, color=TEAL)]
        k = 0
        for side in (-1, 1):
            for dx in (-w / 4, w / 4):
                parts += office_desk(w / 2 - 0.04, 0.7, dx, side * 0.36, monitor_side=-side)
                parts += put(DESK_CHAIR, x=dx, z=side * (d / 2 - 0.34), facing=turned((0, -side), SWIVEL[k]))
                k += 1
        return parts
    if t == "single_desk" and have(DESK_CHAIR):
        return office_desk(w - 0.04, 0.7, 0, -d / 2 + 0.36, monitor_side=-1) + put(DESK_CHAIR, z=d / 2 - 0.34, facing=turned((0, -1), SWIVEL[1]))
    if t == "meeting_table" and have(MEETING_CHAIR):
        parts = [box(2.0, 0.04, 1.1, y=0.72, color=WALNUT)]
        parts += [box(0.08, 0.72, 0.8, x=sx, color=DARK_STEEL) for sx in (-0.75, 0.75)]
        k = 0
        for dx in (-0.65, 0.0, 0.65):
            parts += put(MEETING_CHAIR, x=dx, z=-(d / 2 - 0.32), facing=turned((0, 1), SWIVEL[k] * 0.5))
            parts += put(MEETING_CHAIR, x=dx, z=d / 2 - 0.32, facing=turned((0, -1), SWIVEL[k + 3] * 0.5))
            k += 1
        parts += put(MEETING_CHAIR, x=-(w / 2 - 0.32), facing=(1, 0)) + put(MEETING_CHAIR, x=w / 2 - 0.32, facing=(-1, 0))
        return parts
    if t == "reception_desk" and have(DESK_CHAIR):
        parts = [box(w, 1.05, 0.6, z=d / 2 - 0.3, color=CORAL), box(w, 0.04, 0.35, y=1.05, z=d / 2 - 0.18, color=PLASTIC_WHITE),
                 box(w * 0.9, 0.03, 0.6, y=0.72, z=d / 2 - 0.85, color=PLASTIC_WHITE), box(0.6, 0.36, 0.03, y=0.9, z=d / 2 - 0.68, color=SCREEN)]
        return parts + put(DESK_CHAIR, z=-d / 2 + 0.34, facing=(0, 1))
    if t == "lounge_set" and have("sofa_02", "modern_arm_chair_01", "modern_coffee_table_01"):
        parts = put("sofa_02", z=-d / 2 + 0.41, facing=(0, -1), scale=(2.0 / 1.81, 1, 1))
        parts += put("modern_coffee_table_01", z=0.2, facing=(1, 0), scale=(0.83, 0.83, 0.83))
        parts += put("modern_arm_chair_01", x=-(w / 2 - 0.47), z=0.42, facing=(1, 0), scale=(0.9, 0.9, 0.9))
        parts += put("modern_arm_chair_01", x=w / 2 - 0.47, z=0.42, facing=(-1, 0), scale=(0.9, 0.9, 0.9))
        return parts
    if t == "huddle_table" and have("round_wooden_table_02", MODERN_CHAIR):
        parts = put("round_wooden_table_02", scale=(1.25, 1.1, 1.25))
        for fx, fz in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            parts += put(MODERN_CHAIR, x=-fx * (w / 2 - 0.3), z=-fz * (d / 2 - 0.3), facing=(fx, fz))
        return parts
    if t == "bookshelf" and have("wooden_bookshelf_worn"):
        return put("wooden_bookshelf_worn", scale=(w / 1.37, h / 2.06, d / 0.58))
    if t == "plant_large" and have("potted_plant_02"):
        return [box(0.34, 0.7, 0.34, color=WHITE)] + put("potted_plant_02", y=0.7, scale=(0.85, 0.85, 0.85))
    if t == "planter_divider" and have("potted_plant_02"):
        parts = [box(w, 0.45, d, color=CHARCOAL)]
        for x in np.linspace(-w / 2 + 0.33, w / 2 - 0.33, 3):
            parts += put("potted_plant_02", x=float(x), y=0.45, scale=(0.6, 0.6, 0.6))
        return parts
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
    """Build every model, or only the named ones: `python assets/build_assets.py plant_large floor_lamp`.
    (Without data/cc0 a full rebuild turns the realistic CC0 models back into boxes, so build just what you added.)"""
    OUT.mkdir(parents=True, exist_ok=True)
    items = json.loads(CATALOG.read_text())
    only = set(sys.argv[1:])
    if only:
        items = [i for i in items if i["item_type"] in only]
        missing = only - {i["item_type"] for i in items}
        if missing:
            print(f"not in the catalog: {', '.join(sorted(missing))}")
            return 1
    real = 0
    for item in items:
        scene, mesh = build_any(item)
        real += build_real(item) is not None
        check(mesh, item)
        scene = bake_materials(scene)
        path = ROOT.parent / item["glb_asset"]
        path.parent.mkdir(parents=True, exist_ok=True)
        scene.export(path)
        print(f"{item['item_type']:20s} {path.stat().st_size / 1024:7.1f} KB  bounds {np.round(mesh.extents, 2)}")
    print(f"{real} of {len(items)} items use CC0 models" + ("" if real else " (run assets/fetch_cc0.py first)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
