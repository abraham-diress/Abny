"""Floor-plan geometry shared by the planner and the validator.

Conventions (shared/conventions.py): Matterport model coordinates, y up, floor plan in
(x, z) meters. An item's rotation_deg is about +y and 0 means its front faces +z.

Rotating a vector by theta about +y (right-handed, as in three.js):
    x' =  x cos(theta) + z sin(theta)
    z' = -x sin(theta) + z cos(theta)
so the item's front (0, 0, 1) points to (sin(theta), cos(theta)) in (x, z).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from shared.schemas import LayoutItem, Room

XZ = tuple[float, float]


def facing_rotation(dx: float, dz: float) -> float:
    """rotation_deg that makes an item's front face direction (dx, dz)."""
    return math.degrees(math.atan2(dx, dz)) % 360.0


def front_vector(rotation_deg: float) -> XZ:
    t = math.radians(rotation_deg)
    return (math.sin(t), math.cos(t))


def local_to_world(cx: float, cz: float, lx: float, lz: float, rotation_deg: float) -> XZ:
    t = math.radians(rotation_deg)
    return (cx + lx * math.cos(t) + lz * math.sin(t), cz - lx * math.sin(t) + lz * math.cos(t))


def footprint(cx: float, cz: float, width: float, depth: float, rotation_deg: float) -> Polygon:
    """Rectangle of an item: width along its local x, depth along its local z (front = +z)."""
    hw, hd = width / 2.0, depth / 2.0
    corners = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    return Polygon([local_to_world(cx, cz, lx, lz, rotation_deg) for lx, lz in corners])


def front_zone(cx: float, cz: float, width: float, depth: float, rotation_deg: float, clearance: float) -> Polygon | None:
    """Rectangle in front of an item that must stay clear (people stand/walk there)."""
    if clearance <= 0:
        return None
    hw, hd = width / 2.0, depth / 2.0
    corners = [(-hw, hd), (hw, hd), (hw, hd + clearance), (-hw, hd + clearance)]
    return Polygon([local_to_world(cx, cz, lx, lz, rotation_deg) for lx, lz in corners])


def item_footprint(item: LayoutItem) -> Polygon:
    return footprint(item.x_m, item.z_m, item.width_m, item.depth_m, item.rotation_deg)


def room_polygon(room: Room) -> Polygon:
    poly = Polygon(room.polygon_m)
    return poly if poly.is_valid else poly.buffer(0)


VOID_WORDS = ("void", "shaft", "column", "chase")


def is_void(room: Room) -> bool:
    """Matterport marks columns, shafts and open-to-below areas as 'Void': not floor you can use."""
    text = f"{room.room_type or ''} {room.label or ''}".lower()
    return any(w in text for w in VOID_WORDS)


def rooms_union(rooms: list[Room]):
    """Usable floor: all rooms joined, with void areas cut out.
    A tiny buffer closes hairline gaps between rooms that share a wall."""
    floor = unary_union([room_polygon(r).buffer(0.02) for r in rooms if not is_void(r)]).buffer(-0.02)
    voids = [room_polygon(r) for r in rooms if is_void(r)]
    return floor.difference(unary_union(voids)) if voids else floor


def unit(dx: float, dz: float) -> XZ:
    n = math.hypot(dx, dz)
    return (dx / n, dz / n) if n > 1e-9 else (0.0, 0.0)


def inward_normal(poly: Polygon, a: XZ, b: XZ) -> XZ:
    """Unit normal of edge a-b that points into the polygon."""
    tx, tz = unit(b[0] - a[0], b[1] - a[1])
    for nx, nz in ((-tz, tx), (tz, -tx)):
        mid = ((a[0] + b[0]) / 2 + nx * 0.05, (a[1] + b[1]) / 2 + nz * 0.05)
        if poly.contains(Point(mid)):
            return (nx, nz)
    return (-tz, tx)


def edges(poly: Polygon) -> list[tuple[XZ, XZ]]:
    coords = list(poly.exterior.coords)
    return [(coords[i], coords[i + 1]) for i in range(len(coords) - 1)]


def nearest_edge(poly: Polygon, p: XZ) -> tuple[XZ, XZ]:
    pt = Point(p)
    return min(edges(poly), key=lambda e: LineString(e).distance(pt))


@dataclass(frozen=True)
class Frame:
    """Local frame anchored at the entrance: u runs along the entrance wall, v points into the room."""

    origin: XZ
    t: XZ  # unit vector along the wall
    n: XZ  # unit vector into the room

    def to_world(self, u: float, v: float) -> XZ:
        return (self.origin[0] + u * self.t[0] + v * self.n[0], self.origin[1] + u * self.t[1] + v * self.n[1])

    def to_local(self, p: XZ) -> XZ:
        dx, dz = p[0] - self.origin[0], p[1] - self.origin[1]
        return (dx * self.t[0] + dz * self.t[1], dx * self.n[0] + dz * self.n[1])

    def band(self, poly: Polygon, v_min: float, v_max: float, margin: float = 100.0) -> Polygon:
        """Part of `poly` whose depth from the entrance wall is between v_min and v_max."""
        if v_max <= v_min:
            return Polygon()
        corners = [(-margin, v_min), (margin, v_min), (margin, v_max), (-margin, v_max)]
        strip = Polygon([self.to_world(u, v) for u, v in corners])
        return poly.intersection(strip)

    def depth_extent(self, poly: Polygon) -> tuple[float, float]:
        vs = [self.to_local(c)[1] for c in poly.exterior.coords]
        return min(vs), max(vs)
