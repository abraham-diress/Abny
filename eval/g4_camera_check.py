"""Gate G4: do layout boxes line up with the real panoramas? Checks the camera convention.

    python eval/g4_camera_check.py                      # every space with cached panoramas
    python eval/g4_camera_check.py --spaces ID1 ID2

For each panorama face it projects the camera's own room outline (at floor height) into the image
and measures how well it lands on visible edges (the floor/wall line), for all 48 ways of reading
the camera pose. The convention in agent/staging/camera.py should win for every face by a clear
margin. On the first 5 real demo spaces it scored 0.47-0.77 against at most 0.33 for any other.
If another convention wins, the data pipeline changed how it stores poses or face names.
"""

from __future__ import annotations

import argparse
import itertools
import math
import random
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.staging.camera import PanoCamera, quat_to_matrix  # noqa: E402
from agent.staging.files import to_path  # noqa: E402


def _rotations() -> list[np.ndarray]:
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            m = np.zeros((3, 3))
            for i, (p, s) in enumerate(zip(perm, signs)):
                m[i, p] = s
            if np.linalg.det(m) > 0:
                out.append(m)
    return out


def _outline(poly, y: float, step: float = 0.1) -> np.ndarray:
    pts = []
    for (ax, az), (bx, bz) in zip(poly, poly[1:] + poly[:1]):
        n = max(2, int(math.hypot(bx - ax, bz - az) / step))
        for t in np.linspace(0, 1, n, endpoint=False):
            pts.append((ax + (bx - ax) * t, y, az + (bz - az) * t))
    return np.array(pts)


def _fit(dist: np.ndarray, f: float, world_to_cam: np.ndarray, center: np.ndarray, pts: np.ndarray) -> float | None:
    """Share of projected floor-outline points sitting on an image edge (and below the horizon)."""
    h, w = dist.shape
    cam = (pts - center) @ world_to_cam.T
    depth = -cam[:, 2]
    ok = depth > 0.3
    if ok.sum() < 40:
        return None
    u = w / 2 + f * cam[ok, 0] / depth[ok]
    v = h / 2 - f * cam[ok, 1] / depth[ok]
    inside = (u >= 2) & (u < w - 2) & (v >= 2) & (v < h - 2)
    if inside.sum() < 40:
        return None
    d = dist[v[inside].astype(int), u[inside].astype(int)]
    return float(np.exp(-(d / 4.0) ** 2).mean()) * float((v[inside] > h / 2).mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spaces", nargs="*")
    ap.add_argument("--per-space", type=int, default=24, help="panorama faces sampled per space")
    args = ap.parse_args()

    from pipeline.db import connect, rows
    from pipeline.queries import get_panoramas, get_rooms

    spaces = args.spaces
    if not spaces:
        with connect() as con:
            spaces = [r["space_id"] for r in rows(con, "select distinct space_id from mp_panos")]
    rots = _rotations()
    random.seed(0)
    current: dict[str, list[float]] = {}
    best_other: dict[str, list[float]] = {}
    for sid in spaces:
        rooms = {r.room_id: r for r in get_rooms(sid)}
        panos = [p for p in get_panoramas(sid) if p.room_id in rooms and p.rotation_quat and p.face != "equirect"]
        random.shuffle(panos)
        for p in panos[: args.per_space]:
            img = cv2.imread(str(to_path(p.path)), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            s = 512 / img.shape[1]
            img = cv2.resize(img, (512, int(img.shape[0] * s)))
            edges = cv2.Canny(cv2.GaussianBlur(img, (5, 5), 0), 40, 120)
            dist = cv2.distanceTransform(255 - edges, cv2.DIST_L2, 3)
            f = (img.shape[1] / 2) / math.tan(math.radians(p.fov_deg) / 2)
            room = rooms[p.room_id]
            pts = _outline(list(map(tuple, room.polygon_m)), room.floor_y_m)
            center = np.array(p.position_m)
            ours = _fit(dist, f, PanoCamera(p).world_to_cam, center, pts)
            if ours is None:
                continue
            r = quat_to_matrix(p.rotation_quat)
            others = [_fit(dist, f, m @ (r if inv else r.T), center, pts) for m in rots for inv in (False, True)]
            others = [o for o in others if o is not None and abs(o - ours) > 1e-9]
            current.setdefault(p.face, []).append(ours)
            best_other.setdefault(p.face, []).append(max(others, default=0.0))
    if not current:
        print("No panoramas with room ids found. Fetch Matterport data first.")
        return 1
    ok = True
    for face in sorted(current):
        mine, other = float(np.mean(current[face])), float(np.mean(best_other[face]))
        verdict = "OK" if mine > other + 0.05 else "CHECK"
        ok &= verdict == "OK"
        print(f"{face:6s} faces={len(current[face]):3d}  our convention {mine:.3f}  best other per face {other:.3f}  {verdict}")
    print("Camera convention matches the photos." if ok else "Another convention fits some faces better: see the module docstring.")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
