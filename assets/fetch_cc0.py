"""Download the CC0 source models used by build_assets.py (from Poly Haven, public domain / CC0).

    python assets/fetch_cc0.py        # -> data/cc0/<id>/ (gitignored); then: python assets/build_assets.py

Only the final GLBs in assets/glb/ are committed. Without these sources, build_assets.py still
works and falls back to simple box models.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "cc0"
UA = {"User-Agent": "hestia-asset-fetch"}

MODELS = [
    "painted_wooden_chair_01",  # café chairs
    "round_wooden_table_02",  # café tables
    "wooden_table_02",  # bench table
    "painted_wooden_bench",
    "dining_chair_02",  # modern leather chair: desks and meeting table
    "sofa_02",
    "drawer_cabinet",  # storage cabinet
    "modern_wooden_cabinet",  # kitchenette base
    "wooden_display_shelves_01",  # retail shelf
    "CashRegister_01",
    "croissant",
    "carrot_cake",
    "strawberry_chocolate_cake",
    "hamburger_buns",
    "potted_plant_02",
]


def _get(url: str, dest: Path) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA)) as r:
        dest.write_bytes(r.read())


def main() -> int:
    for mid in MODELS:
        files = json.load(urllib.request.urlopen(urllib.request.Request(f"https://api.polyhaven.com/files/{mid}", headers=UA)))
        g = files["gltf"]["1k"]["gltf"]
        _get(g["url"], DEST / mid / f"{mid}.gltf")
        for rel, v in g.get("include", {}).items():
            _get(v["url"], DEST / mid / rel)
        print("ok", mid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
