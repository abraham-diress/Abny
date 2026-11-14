"""Project 3D points (Matterport model space) into a panorama image.

Camera convention, CALIBRATED at gate G4 on 5 real scans (118 panorama faces): of all 48 ways
to read the pose, this one put each room's floor outline on the visible floor/wall edges
(score 0.47-0.77; the next best 0.33), and its four faces form a consistent cube.
* PanoRef.rotation_quat (x, y, z, w) rotates the camera's local frame into model space (y-up).
* The camera's local frame is Matterport-native: +z is up, the "front" face looks along +x,
  "left" along +y, "back" along -x, "right" along -y.
* Each face is a 90-degree pinhole image: forward = the face direction, image-up = local +z.
* An equirect image maps longitude across the width (center = front) and latitude down the height.
Re-check with the calibration in eval/g4_camera_check.py if the data pipeline changes.
"""

from __future__ import annotations

import math

import numpy as np

from shared.schemas import PanoRef

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


LOCAL_UP = np.array([0.0, 0.0, 1.0])
# Face -> view direction in the camera's local frame.
FACE_FORWARD = {
    "front": np.array([1.0, 0.0, 0.0]),
    "back": np.array([-1.0, 0.0, 0.0]),
    "left": np.array([0.0, 1.0, 0.0]),
    "right": np.array([0.0, -1.0, 0.0]),
    "up": np.array([0.0, 0.0, 1.0]),
    "down": np.array([0.0, 0.0, -1.0]),
    "equirect": np.array([1.0, 0.0, 0.0]),
}


def face_matrix(face: str) -> np.ndarray:
    """Rows: the face image's right, up and backward (-forward) axes in the camera's local frame."""
    fwd = FACE_FORWARD.get(face, FACE_FORWARD["front"])
    up = LOCAL_UP if abs(fwd @ LOCAL_UP) < 0.9 else np.array([-1.0, 0.0, 0.0]) * np.sign(fwd @ LOCAL_UP)
    right = np.cross(fwd, up)
    return np.stack([right, up, -fwd])


class PanoCamera:
    def __init__(self, pano: PanoRef) -> None:
        self.pano = pano
        self.center = np.array(pano.position_m, dtype=float)
        # world -> camera-local (R^T) -> face image axes (x right, y up, looking down -z)
        self.world_to_cam = face_matrix(pano.face) @ quat_to_matrix(pano.rotation_quat).T
        self.w, self.h = pano.width_px, pano.height_px
        self.f = (self.w / 2) / math.tan(math.radians(pano.fov_deg) / 2)

    def to_camera(self, pts: np.ndarray) -> np.ndarray:
        return (pts - self.center) @ self.world_to_cam.T

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
