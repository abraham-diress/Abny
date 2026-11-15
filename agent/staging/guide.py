"""render_guide: draw a layout onto a real panorama so the image model (and people) can see the plan.

Writes three files under media/guides/:
  <layout_id>__<pano_id>.png       the panorama with color-coded item boxes (the "guide")
  <layout_id>__<pano_id>_mask.png  white where items go, black elsewhere (for inpainting)
and render_floorplan writes <layout_id>_plan.png, a top-down plan (UI fallback, README, Devpost).
"""

from __future__ import annotations

import math
import os
import re

import cv2
import numpy as np

from agent.layout.geometry import is_void, item_footprint, room_polygon
from agent.staging.camera import PanoCamera, box_corners
from agent.staging.files import ensure_dirs, mask_url_for, to_path, to_url
from shared.conventions import GUIDES_DIR
from shared.schemas import Layout, PanoRef, Room

# BGR colors per zone (OpenCV order)
ZONE_COLORS = {
    "service": (40, 160, 235),  # amber
    "back_of_house": (180, 120, 60),  # steel blue
    "seating": (90, 170, 70),  # green
    "front_of_house": (170, 90, 160),  # purple
    "entrance": (60, 60, 220),  # red
    None: (150, 150, 150),
}
CAMERA_HEIGHT_M = float(os.environ.get("PANO_CAMERA_HEIGHT_M", "1.55"))


def render_guide(layout: Layout, pano: PanoRef) -> str:
    """Draw the layout's item boxes onto a panorama face. Returns the guide's URL path."""
    ensure_dirs()
    img = cv2.imread(str(to_path(pano.path)), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Panorama not found: {pano.path}")
    if img.shape[1] != pano.width_px or img.shape[0] != pano.height_px:
        pano = pano.model_copy(update={"width_px": img.shape[1], "height_px": img.shape[0]})

    guide, mask, _ = draw_items(img, layout, pano, floor_y=_floor_y(layout, pano))
    name = f"{_safe(layout.layout_id)}__{_safe(pano.pano_id)}.png"
    out = GUIDES_DIR / name
    cv2.imwrite(str(out), guide)
    cv2.imwrite(str(to_path(mask_url_for(to_url(out)))), mask)
    return to_url(out)


def draw_items(img: np.ndarray, layout: Layout, pano: PanoRef, floor_y: float) -> tuple[np.ndarray, np.ndarray, int]:
    """Returns (guide image, mask, number of items visible)."""
    cam = PanoCamera(pano)
    h, w = img.shape[:2]
    overlay = img.copy()
    mask = np.zeros((h, w), dtype=np.uint8)
    drawn = []
    for item in _in_camera_room(layout, pano):
        corners = box_corners(item.x_m, item.z_m, item.width_m, item.depth_m, item.height_m, item.rotation_deg, floor_y)
        px, ok = cam.project(corners)
        if not ok.all():
            continue
        hull = cv2.convexHull(px.astype(np.float32)).astype(np.int32)
        x0, y0, bw, bh = cv2.boundingRect(hull)
        if x0 > w or y0 > h or x0 + bw < 0 or y0 + bh < 0:
            continue
        if pano.face == "equirect" and bw > w / 2:  # wraps around the seam
            continue
        drawn.append((cam.distance(corners.mean(axis=0)), item, hull, px))
    # Far to near so near items paint over far ones.
    for _, item, hull, px in sorted(drawn, key=lambda d: -d[0]):
        color = ZONE_COLORS.get(item.zone, ZONE_COLORS[None])
        cv2.fillConvexPoly(overlay, hull, color)
        cv2.fillConvexPoly(mask, hull, 255)
    guide = cv2.addWeighted(overlay, 0.45, img, 0.55, 0)
    for _, item, hull, px in sorted(drawn, key=lambda d: -d[0]):
        color = ZONE_COLORS.get(item.zone, ZONE_COLORS[None])
        _draw_box_edges(guide, px, color)
    mask = cv2.dilate(mask, np.ones((9, 9), np.uint8))
    return guide, mask, len(drawn)


def _in_camera_room(layout: Layout, pano: PanoRef) -> list:
    """Items the camera can actually see: those in its own room (walls hide the rest).
    Panoramas without a room id see everything."""
    if not pano.room_id:
        return list(layout.items)
    return [i for i in layout.items if i.room_id == pano.room_id]


def view_score(layout: Layout, pano: PanoRef, floor_y: float | None = None) -> float:
    """How good this face is as the hero view: items fully in frame at a readable size count most;
    an item filling the foreground (camera right next to it) counts against the view."""
    cam = PanoCamera(pano)
    fy = _floor_y(layout, pano) if floor_y is None else floor_y
    w, h = pano.width_px, pano.height_px
    score = 0.0
    for item in _in_camera_room(layout, pano):
        corners = box_corners(item.x_m, item.z_m, item.width_m, item.depth_m, item.height_m, item.rotation_deg, fy)
        px, ok = cam.project(corners)
        if not ok.all():
            continue
        inside = (px[:, 0] >= 0) & (px[:, 0] < w) & (px[:, 1] >= 0) & (px[:, 1] < h)
        hull = cv2.convexHull(px.astype(np.float32))
        frac = cv2.contourArea(hull) / float(w * h)
        if frac > 0.3:
            score -= 1.0  # blocks the view
        elif inside.all() and frac >= 0.003:
            score += 1.0 + 0.5 * min(frac, 0.05) / 0.05
        elif inside.any():
            score += 0.3
    return score


def visible_items(layout: Layout, pano: PanoRef, floor_y: float | None = None) -> list:
    """The layout items this panorama face shows at least partly (camera's room only)."""
    cam = PanoCamera(pano)
    fy = _floor_y(layout, pano) if floor_y is None else floor_y
    out = []
    for item in _in_camera_room(layout, pano):
        corners = box_corners(item.x_m, item.z_m, item.width_m, item.depth_m, item.height_m, item.rotation_deg, fy)
        px, ok = cam.project(corners)
        if ok.all() and ((px[:, 0] >= 0) & (px[:, 0] < pano.width_px) & (px[:, 1] >= 0) & (px[:, 1] < pano.height_px)).any():
            out.append(item)
    return out


def count_visible(layout: Layout, pano: PanoRef, floor_y: float | None = None) -> int:
    """How many of the layout's items this panorama face shows (center in frame, camera's room only)."""
    cam = PanoCamera(pano)
    fy = _floor_y(layout, pano) if floor_y is None else floor_y
    n = 0
    for item in _in_camera_room(layout, pano):
        corners = box_corners(item.x_m, item.z_m, item.width_m, item.depth_m, item.height_m, item.rotation_deg, fy)
        px, ok = cam.project(corners)
        if ok.all():
            u, v = px[:, 0].mean(), px[:, 1].mean()
            if 0 <= u < pano.width_px and 0 <= v < pano.height_px:
                n += 1
    return n


def render_floorplan(layout: Layout, rooms: list[Room], px_per_m: int = 60) -> str:
    """Top-down plan of the rooms and the layout. Returns its URL path."""
    ensure_dirs()
    polys = [room_polygon(r) for r in rooms]
    xs = [x for p in polys for x, _ in p.exterior.coords]
    zs = [z for p in polys for _, z in p.exterior.coords]
    pad = 0.8
    x0, z0 = min(xs) - pad, min(zs) - pad
    W = int((max(xs) - x0 + pad) * px_per_m)
    H = int((max(zs) - z0 + pad) * px_per_m)
    img = np.full((H, W, 3), 250, np.uint8)

    def P(x: float, z: float) -> tuple[int, int]:
        return int((x - x0) * px_per_m), int((z - z0) * px_per_m)

    used = {i.room_id for i in layout.items}
    labels = []
    for r, p in zip(rooms, polys):
        pts = np.array([P(x, z) for x, z in p.exterior.coords], np.int32)
        void = is_void(r)
        # Rooms the plan uses are gray; unused rooms (restrooms, halls, spare rooms) stay pale and labeled.
        cv2.fillPoly(img, [pts], (205, 205, 205) if void else (236, 236, 236) if r.room_id in used else (247, 246, 243))
        cv2.polylines(img, [pts], True, (60, 60, 60), 3)
        if r.room_id not in used and p.area >= 2.0:
            name = (r.label or r.room_type or "").strip()
            name = "void" if void else (name if name and name.lower() not in ("other", "unknown") else "unused")
            c = p.representative_point()
            labels.append((name.lower(), P(c.x, c.y)))
    for r in rooms:
        for o in r.openings:
            color = {"door": (60, 60, 220), "window": (220, 170, 60)}.get(o.kind, (160, 160, 160))
            cv2.line(img, P(*o.a), P(*o.b), color, 6)
    for item in layout.items:
        fp = item_footprint(item)
        pts = np.array([P(x, z) for x, z in fp.exterior.coords], np.int32)
        color = ZONE_COLORS.get(item.zone, ZONE_COLORS[None])
        cv2.fillPoly(img, [pts], color)
        cv2.polylines(img, [pts], True, (40, 40, 40), 1)
        # Front marker: a short line from the center toward the item's front.
        t = math.radians(item.rotation_deg)
        cx, cz = item.x_m, item.z_m
        fx, fz = cx + math.sin(t) * item.depth_m / 2, cz + math.cos(t) * item.depth_m / 2
        cv2.line(img, P(cx, cz), P(fx, fz), (255, 255, 255), 2)
    if layout.entrance_xz:
        cv2.circle(img, P(*layout.entrance_xz), 10, (60, 60, 220), -1)
    # Plans are drawn with +z down the image; flip so the entrance usually sits at the bottom.
    img = cv2.flip(img, 0)
    for text, (lx, ly) in labels:
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(img, text, (lx - tw // 2, H - 1 - ly + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1, cv2.LINE_AA)
    unit = "desks" if layout.business_type == "office" else "seats"
    label = f"{layout.business_type} | {layout.seat_count} {unit} | {layout.strategy or ''}"
    cv2.putText(img, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 40, 40), 2, cv2.LINE_AA)
    out = GUIDES_DIR / f"{_safe(layout.layout_id)}_plan.png"
    cv2.imwrite(str(out), img)
    return to_url(out)


def _draw_box_edges(img: np.ndarray, px: np.ndarray, color) -> None:
    p = px.astype(np.int32)
    for a, b in [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]:
        cv2.line(img, tuple(p[a]), tuple(p[b]), color, 2, cv2.LINE_AA)


def _floor_y(layout: Layout, pano: PanoRef) -> float:
    """Floor height for the layout's rooms: from the data pipeline if it looks real, else camera height.

    A room floor left at the default 0.0 while the camera says otherwise (> 0.5 m apart) is treated
    as "not set" and the camera estimate wins.
    """
    camera_floor = pano.position_m[1] - CAMERA_HEIGHT_M
    try:
        from pipeline.queries import get_rooms  # Natnael's module; optional at this point

        rooms = {r.room_id: r for r in get_rooms(layout.space_id)}
        ys = [rooms[i.room_id].floor_y_m for i in layout.items if i.room_id in rooms]
        if ys:
            y = float(np.median(ys))
            if not (y == 0.0 and abs(camera_floor) > 0.5):
                return y
    except Exception:  # noqa: BLE001 - fall back to the camera estimate
        pass
    return camera_floor


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


__all__ = ["render_guide", "render_floorplan", "draw_items", "count_visible"]
