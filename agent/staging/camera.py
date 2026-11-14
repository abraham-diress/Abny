"""Project 3D points (Matterport model space) into a panorama image.

Assumed camera convention (three.js / Matterport SDK style, VERIFY at gate G4 on a real scan):
* PanoRef.rotation_quat (x, y, z, w) rotates camera-local vectors into model space.
* In camera-local space the camera looks down -z, +y is up, +x is right.
* Cube faces are views from the same point: front looks -z, right +x, left -x,
  back +z, up +y, down -y (all in camera-local space).
* An equirect image maps longitude across the width (center = front) and latitude down the height.

If a real scan shows boxes in the wrong place, flip FLIP_X / FLIP_Z or swap the face table
below; nothing else depends on these choices.
"""

from __future__ import annotations

import math

import numpy as np

from shared.schemas import PanoRef

FLIP_X = False
FLIP_Z = False


def quat_to_matrix(q: tuple[float, float, float, float] | None) -> np.ndarray:
    if q is None:
        return np.eye(3)
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _rot_y(deg: float) -> np.ndarray:
    t = math.radians(deg)
    return np.array([[math.cos(t), 0, math.sin(t)], [0, 1, 0], [-math.sin(t), 0, math.cos(t)]])


def _rot_x(deg: float) -> np.ndarray:
    t = math.radians(deg)
    return np.array([[1, 0, 0], [0, math.cos(t), -math.sin(t)], [0, math.sin(t), math.cos(t)]])


# face-local -> camera-local
FACE_ROTATION = {
    "front": np.eye(3),
    "right": _rot_y(-90),
    "left": _rot_y(90),
    "back": _rot_y(180),
    "up": _rot_x(90),
    "down": _rot_x(-90),
    "equirect": np.eye(3),
}


class PanoCamera:
    def __init__(self, pano: PanoRef) -> None:
        self.pano = pano
        self.center = np.array(pano.position_m, dtype=float)
        r = quat_to_matrix(pano.rotation_quat) @ FACE_ROTATION.get(pano.face, np.eye(3))
        self.world_to_cam = r.T
        self.w, self.h = pano.width_px, pano.height_px
        self.f = (self.w / 2) / math.tan(math.radians(pano.fov_deg) / 2)

    def to_camera(self, pts: np.ndarray) -> np.ndarray:
        cam = (pts - self.center) @ self.world_to_cam.T
        if FLIP_X:
            cam[:, 0] *= -1
        if FLIP_Z:
            cam[:, 2] *= -1
        return cam

    def project(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Nx3 model-space points -> (Nx2 pixel coords, N bool 'in front of camera')."""
        cam = self.to_camera(np.asarray(pts, dtype=float))
        if self.pano.face == "equirect":
            d = cam / np.linalg.norm(cam, axis=1, keepdims=True)
            lon = np.arctan2(d[:, 0], -d[:, 2])
            lat = np.arcsin(np.clip(d[:, 1], -1, 1))
            u = (lon / (2 * math.pi) + 0.5) * self.w
            v = (0.5 - lat / math.pi) * self.h
            return np.stack([u, v], axis=1), np.ones(len(cam), dtype=bool)
        depth = -cam[:, 2]
        ok = depth > 0.05
        safe = np.where(ok, depth, 1.0)
        u = self.w / 2 + self.f * cam[:, 0] / safe
        v = self.h / 2 - self.f * cam[:, 1] / safe
        return np.stack([u, v], axis=1), ok

    def distance(self, p: np.ndarray) -> float:
        return float(np.linalg.norm(np.asarray(p) - self.center))


def box_corners(x: float, z: float, width: float, depth: float, height: float, rotation_deg: float, floor_y: float) -> np.ndarray:
    """8 corners of an item's bounding box in model space (same footprint math as the planner)."""
    t = math.radians(rotation_deg)
    pts = []
    for y in (floor_y, floor_y + height):
        for lx, lz in ((-width / 2, -depth / 2), (width / 2, -depth / 2), (width / 2, depth / 2), (-width / 2, depth / 2)):
            pts.append((x + lx * math.cos(t) + lz * math.sin(t), y, z - lx * math.sin(t) + lz * math.cos(t)))
    return np.array(pts)
