"""D1: one test call per sponsor API, to confirm the keys in .env work.

    python scripts/smoke_apis.py              # all
    python scripts/smoke_apis.py matterport --model <id>
    python scripts/smoke_apis.py vexcel --lat 29.7449 --lon -95.3907

Prints status only (never the keys).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def costar() -> None:
    from pipeline.ingest_costar import RAW_EXTS, raw_dir
    from pipeline.ingest_kit import is_kit

    d = raw_dir()
    print(f"[costar] kit layout detected: {is_kit(d)}")
    files = [p for p in d.rglob("*") if p.suffix.lower() in RAW_EXTS] if d.exists() else []
    print(f"[costar] {d}: {'MISSING' if not d.exists() else f'{len(files)} data files'}")
    for f in files[:20]:
        print(f"    {f.relative_to(d)}  ({f.stat().st_size / 1e6:.1f} MB)")


def matterport(model: str | None) -> None:
    from pipeline.matterport import Matterport, MatterportError, face_urls

    try:
        mp = Matterport()
        fields = mp.schema.get("Model") or {}
        print(f"[matterport] auth OK; Model fields: {', '.join(sorted(fields))[:300] or '(introspection off)'}")
        if model:
            m = mp.model(model)
            sky = next((p.get("skybox") for p in m.get("panoLocations") or [] if p.get("skybox")), None)
            print(f"[matterport] model {model}: {len(m.get('rooms') or [])} rooms, {len(m.get('panoLocations') or [])} scans, "
                  f"faces {sorted(face_urls(sky))}")
    except MatterportError as e:
        print(f"[matterport] FAILED: {e}")


def vexcel(lat: float, lon: float) -> None:
    from pipeline import vexcel as v

    try:
        vx = v.Vexcel()
        prop = vx.property(lat, lon)
        parcel, attrs = v.parcel_and_attrs(prop)
        print(f"[vexcel] property OK: parcel={bool(parcel)}, {len(attrs)} attributes, footprint={bool(v.footprint_wkt(attrs))}")
        area = parcel or v.square_wkt(lat, lon, v.NO_PARCEL_HALF_M)
        print(f"[vexcel] ortho OK ({len(vx.ortho(area)) // 1024} KB)")
        dirs = vx.oblique_directions(area)
        print(f"[vexcel] oblique directions: {dirs}")
        print(f"[vexcel] parking: {v.parking_from_detections(vx.detect(area, ['parking lot', 'car']))}")
    except v.VexcelError as e:
        print(f"[vexcel] FAILED: {e}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", nargs="?", default="all", choices=["all", "costar", "matterport", "vexcel"])
    ap.add_argument("--model")
    ap.add_argument("--lat", type=float, default=29.7449)
    ap.add_argument("--lon", type=float, default=-95.3907)
    a = ap.parse_args()
    if a.which in ("all", "costar"):
        costar()
    if a.which in ("all", "matterport"):
        matterport(a.model)
    if a.which in ("all", "vexcel"):
        vexcel(a.lat, a.lon)


if __name__ == "__main__":
    main()
