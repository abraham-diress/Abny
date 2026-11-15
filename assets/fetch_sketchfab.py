"""Download the CC-BY furniture models used by build_assets.py from Sketchfab.

    # .env: SKETCHFAB_API_TOKEN=...   (sketchfab.com -> Settings -> Password & API)
    python assets/fetch_sketchfab.py   # -> data/sketchfab/<id>/model.glb (gitignored); then: python assets/build_assets.py

Only the final GLBs in assets/glb/ are committed. These models are CC-BY 4.0: their authors are
credited in assets/CREDITS.md, which must stay with the GLBs. Without the sources (or the token),
build_assets.py falls back to the Poly Haven chairs.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "sketchfab"
UA = "hestia-asset-fetch"

# our id -> (Sketchfab uid, title, author). All CC-BY 4.0; credited in assets/CREDITS.md.
MODELS = {
    # chairs (a mix: each furniture group gets its own style)
    "office_chair_mesh": ("db03012c3c484314a480b4137da8eb30", "Office Chair", "FangedAnteater"),
    "leather_office_chair": ("675f34f7304e4d92812a41e9750539aa", "Office Chair Modern", "thethieme"),
    "bentwood_chair": ("e76cb526238a493c90255ad4a900f83d", "Bentwood chair", "ValeGoG"),
    "bistro_chair": ("6b0a51cfa9784a60ae82e05db38f9ec0", "Free 3D French Bistro Chair", "deltahedra"),
    "tolix_chair": ("f2423b51fe2141e8857d3f1fa26b33ec", "Tolix Style Bistro Dining Chairs Red", "allenbranch"),
    # café / bakery
    "cafe_table": ("4517652104744f4981defb6d4d18e481", "Bar Table", "commonspence"),
    "pastry_case": ("867570f94d654385bb9750248849892b", "Canarian Cafe - cake display", "lanzaboy"),
    "bar_counter": ("47e1be52888640f89ab6dd8eeb008b35", "Counter", "gorzi90"),
    "espresso_machine": ("bab05bc7805d4b0dbc2cdcbb48441956", "Commercial Coffee Machine", "mreslan"),
    "commercial_fridge": ("144cf5c6902c45cbb1fd5fde56f068a5", "52\" Commercial Refrigerator", "allenbranch"),
    "steel_table": ("b6ba50f7cece4721bfb2d47947865d1e", "Old 3 Tier Stainless Steel Table", "Ykc"),
    "commercial_sink": ("2d0cade455614fd989b2e81878fd7764", "Low poly commercial sink", "christiangadelha1"),
    "dough_mixer": ("2e8fa1bb607a43c08a61dce49d026a1e", "Electric Industrial Dough Mixer", "nokillnando"),
    # office
    "wood_desk": ("f26030d09d73422f8ff270425c7c63e0", "Desk Set", "renviros"),  # desk + its own chair
    "dual_monitors": ("58a2dba70e4f4752962ee98a9d6827be", "Basic PC Monitors", "sousinho"),
    "laptop": ("7d870e900889481395b4a575b9fa8c3e", "Laptop", "Aullwen"),
    "glass_meeting_table": ("c41a27d7a1b24dc484bc603e1bc2d0ef", "Dining Table Glass", "topfrank2013"),
    "modern_sofa": ("ac92f6e97eaa43c4ad6cb8f7c65ac43f", "Modern Sofa", "3dimentionalben"),
    "monstera": ("1ab9bf841df04c07b1819be596327629", "Monstera Deliciosa Potted Mid-Century plant", "ChubbyPanda"),
    # office extras
    "table_tennis": ("378b91cbefb741cd9fa4aeae5639359f", "Table Tennis", "appsnation.co"),
    "foosball": ("1303a318d4584639acef729b9fd296fc", "Foosball Table", "owestgate"),
    "koi": ("3e1b80c3653f43349252aab3b4fb1d86", "Koi Fish", "sdpm"),
    "office_printer": ("d55f6fca7c3d45c883bbff770672970d", "MFP Office Printer", "nokillnando"),
    "mobile_whiteboard": ("858a2d94034f48ebbbbbd1f07494cea0", "Whiteboard", "arlinetjandra"),
    "floor_lamp_classic": ("33eb258d9873435690254cfbb0ea46ec", "Floor Lamp", "bilgehan.korkmaz"),
    "persian_rug": ("fe13eecfc9b8405dab1fe76c5dd28a4c", "Persian Rug", "nrecord"),
    "old_persian_carpet": ("08fee343183d4287a9ac8269ec4e97c5", "Old Persian Carpet_14_MB", "ahmagh2e"),
    "pothos": ("e9832f38484f4f85b3f9081b51fa3799", "Pothos Potted Plant - Money Plant", "AllQuad"),
    # bread (pastry case, bread shelf, prep table)
    "boule": ("809fab32f5c94cc5916fbd00b7d9f659", "Homemade Bread (Game Ready / 2K PBR)", "meerschaumdigital"),
    "bread_loaf": ("daf4801f72ae4f9eba9c338afbbb2926", "(Game Ready Free) Bread Loaf", "Igrodev"),
    "bread_roll": ("2a75ccc1c53348efb7e82eeb86f82173", "Bread Roll (Game Ready / 2K PBR)", "meerschaumdigital"),
    "sf_croissant": ("c512d041ead447f091eeb31982558d80", "Croissant (Game Ready / 2K PBR)", "meerschaumdigital"),
    "baguette": ("b6c483995db04698bf5041c9cef369c0", "French baguette", "encoded01"),
    "bread_platter": ("5cc69d0b0ae244b1a7c5b26dfc2ca721", "Bakery Products collection", "vertexgrocer"),
    "wicker_basket": ("d0153e62dfbb4659b0cb55d5bf51a9d1", "Wicker basket 01", "koss2712"),
}


def _token() -> str:
    tok = os.environ.get("SKETCHFAB_API_TOKEN")
    env = ROOT / ".env"
    if not tok and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("SKETCHFAB_API_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip("\"'")
    if not tok:
        sys.exit("Set SKETCHFAB_API_TOKEN in .env (sketchfab.com -> Settings -> Password & API).")
    return tok


def main() -> int:
    tok = _token()
    for mid, (uid, title, author) in MODELS.items():
        dest = DEST / mid / "model.glb"
        if dest.exists():
            print("have", mid)
            continue
        req = urllib.request.Request(f"https://api.sketchfab.com/v3/models/{uid}/download",
                                     headers={"Authorization": f"Token {tok}", "User-Agent": UA})
        info = json.load(urllib.request.urlopen(req))
        if "glb" not in info:
            print("no GLB download for", mid, "- skipped")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(urllib.request.urlopen(urllib.request.Request(info["glb"]["url"], headers={"User-Agent": UA})).read())
        print("ok", mid, f'"{title}" by {author}')
        time.sleep(4)  # Sketchfab rate-limits downloads (HTTP 429)
    return 0


if __name__ == "__main__":
    sys.exit(main())
