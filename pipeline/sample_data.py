"""Synthetic sample database so the team can build on the real query functions at M0.

    python -m pipeline.sample_data            # writes data/sample.duckdb + placeholder panos
    HESTIA_DB_PATH=data/sample.duckdb python -c "from pipeline.queries import *; ..."

Everything here is FAKE: ids start with 'sample-', addresses are on 'Sample St', and
every citation says 'SAMPLE DATA (synthetic)'. Never demo from it.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

from shared.conventions import PANOS_DIR

from pipeline.db import SAMPLE_DB_PATH, connect, media_url
from pipeline.tables import ensure_tables

# (city, neighborhood center) — real areas so map views look sensible.
SITES = [
    ("Houston", "Montrose", 29.7449, -95.3907),
    ("Houston", "Heights", 29.7984, -95.3989),
    ("Houston", "Midtown", 29.7408, -95.3772),
    ("Houston", "EaDo", 29.7518, -95.3507),
    ("Houston", "Rice Village", 29.7163, -95.4144),
    ("Houston", "Upper Kirby", 29.7366, -95.4183),
    ("Los Angeles", "Silver Lake", 34.0869, -118.2702),
    ("Los Angeles", "Echo Park", 34.0782, -118.2606),
    ("Los Angeles", "Highland Park", 34.1115, -118.1923),
    ("Los Angeles", "Koreatown", 34.0618, -118.3004),
    ("Los Angeles", "Arts District", 34.0403, -118.2352),
    ("Los Angeles", "Larchmont", 34.0748, -118.3239),
]
# Office samples (business_type="office"), appended so the retail samples above keep their values.
OFFICE_SITES = [
    ("Houston", "Downtown", 29.7589, -95.3677),
    ("Houston", "Galleria", 29.7390, -95.4634),
    ("Los Angeles", "Downtown", 34.0500, -118.2550),
    ("Los Angeles", "Century City", 34.0560, -118.4170),
]

TENANT_NAMES = ["Sunrise Bakery", "Golden Crust Bakery", "Daily Grind Coffee", "Corner Cafe", "Pho House", "Taqueria Sol",
                "Bright Smiles Dental", "FitLab Gym", "Bloom Florist", "City Hardware", "Main St Books", "Nail Studio",
                "Green Leaf Market", "Urban Cuts Barber", "Pizza Place", "Law Office", "Insurance Agency", "Yoga Loft"]
CATEGORIES = {"Bakery": "Bakery", "Coffee": "Coffee Shop", "Cafe": "Cafe", "Pho": "Restaurant", "Taqueria": "Restaurant",
              "Dental": "Dentist", "Gym": "Fitness", "Florist": "Retail", "Hardware": "Retail", "Books": "Retail",
              "Nail": "Salon", "Market": "Grocery", "Barber": "Salon", "Pizza": "Restaurant", "Law": "Office",
              "Insurance": "Office", "Yoga": "Fitness"}

NOTE = "SAMPLE DATA (synthetic)"


def _jitter(rng: random.Random, lat: float, lon: float, max_m: float) -> tuple[float, float]:
    r = max_m * math.sqrt(rng.random())
    t = rng.random() * 2 * math.pi
    return lat + r * math.cos(t) / 111_320, lon + r * math.sin(t) / (111_320 * math.cos(math.radians(lat)))


def _placeholder_pano(path: Path, label: str, face: str, seed: int) -> tuple[int, int]:
    """Simple one-point-perspective 'empty room' so image code has something to draw on."""
    w = h = 1024
    rng = random.Random(seed)
    wall = tuple(rng.randint(200, 235) for _ in range(3))
    im = Image.new("RGB", (w, h), wall)
    d = ImageDraw.Draw(im)
    m = 300  # back wall inset
    d.polygon([(0, h), (w, h), (w - m, h - m), (m, h - m)], fill=(165, 140, 110))  # floor
    d.polygon([(0, 0), (w, 0), (w - m, m), (m, m)], fill=(240, 240, 240))  # ceiling
    d.rectangle([m, m, w - m, h - m], outline=(120, 120, 120), width=3)
    for a, b in [((0, 0), (m, m)), ((w, 0), (w - m, m)), ((0, h), (m, h - m)), ((w, h), (w - m, h - m))]:
        d.line([a, b], fill=(120, 120, 120), width=3)
    if face == "front":  # storefront window on the back wall
        d.rectangle([m + 40, m + 60, w - m - 40, h - m - 80], fill=(180, 210, 230), outline=(80, 80, 80), width=4)
    d.text((20, 20), f"SAMPLE PANO  {label}  face={face}", fill=(60, 60, 60))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=85)
    return w, h


def build(path: Path = SAMPLE_DB_PATH, images: bool = True) -> Path:
    rng = random.Random(42)
    if path.exists():
        path.unlink()
    with connect(read_only=False, path=path) as con:
        ensure_tables(con)
        tenant_i = 0
        sites = [(*x, "retail") for x in SITES] + [(*x, "office") for x in OFFICE_SITES]
        for i, (city, hood, lat, lon, kind) in enumerate(sites, 1):
            office = kind == "office"
            sid = f"sample-{'hou' if city == 'Houston' else 'la'}-{'office-' if office else ''}{i:02d}"
            mid = f"sample-model-{i:02d}"
            if office:
                sqft = rng.choice([2500, 3500, 4800, 6000])
                psf = rng.uniform(26, 38) if city == "Houston" else rng.uniform(40, 58)
                ptype, use, service = "Office space in Office building", "Office", "Full Service"
            else:
                sqft = rng.choice([900, 1200, 1400, 1600, 1800, 2200, 2600])
                psf = rng.uniform(26, 42) if city == "Houston" else rng.uniform(36, 60)
                ptype = rng.choice(["Retail", "Retail", "Restaurant", "Retail (Storefront)", "Flex"])
                use, service = "Retail", "TripleNet"
            rent = psf * sqft / 12
            con.execute("INSERT INTO spaces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                sid, f"sample-prop-{i:02d}", f"sample-listing-{i:02d}", mid,
                f"{100 + i * 11} Sample St ({hood})", city, lat, lon, ptype, sqft, round(rent, 2), round(psf, 2),
                "rent quoted $/sf/year", rng.choice([1962, 1978, 1985, 2004, 2015]), True,
                round(rng.uniform(1.0, 5.0), 1), None, "Alex Rivera", "Sample Realty", "broker@example.com", "555-0100",
                "raw_sample_commercial_listing", f"sample-listing-{i:02d}", True, "space", use, service,
            ])
            con.execute("INSERT INTO candidates VALUES (?, ?, ?)", [sid, 0 if i in (1, 2, 7, 13, 15) else 150, "sample"])

            # Rooms: front of house, kitchen, restroom (rectangles in model coords, meters).
            total_m2 = sqft / 10.7639
            fw = math.sqrt(total_m2 * 0.65 * 1.4)
            fd = total_m2 * 0.65 / fw
            kd = total_m2 * 0.3 / fw
            if office:  # open-plan floor, conference room, kitchenette
                rooms = [
                    ("r1", "Open office", "office", [(0, 0), (fw, 0), (fw, fd), (0, fd)], [{"kind": "door", "a": [0.5, 0], "b": [1.5, 0]},
                                                                                               {"kind": "window", "a": [fw, 0.5], "b": [fw, fd - 0.5]}]),
                    ("r2", "Conference room", "conference room", [(0, fd), (fw * 0.6, fd), (fw * 0.6, fd + kd), (0, fd + kd)], [{"kind": "door", "a": [1, fd], "b": [2, fd]}]),
                    ("r3", "Kitchenette", "kitchen", [(fw * 0.6, fd), (fw, fd), (fw, fd + kd), (fw * 0.6, fd + kd)], [{"kind": "opening", "a": [fw * 0.7, fd], "b": [fw * 0.7 + 1, fd]}]),
                ]
            else:
                rooms = [
                    ("r1", "Front room", "retail", [(0, 0), (fw, 0), (fw, fd), (0, fd)], [{"kind": "door", "a": [fw / 2 - 0.5, 0], "b": [fw / 2 + 0.5, 0]},
                                                                                             {"kind": "window", "a": [0.5, 0], "b": [fw / 2 - 1, 0]}]),
                    ("r2", "Kitchen", "kitchen", [(0, fd), (fw * 0.75, fd), (fw * 0.75, fd + kd), (0, fd + kd)], [{"kind": "opening", "a": [1, fd], "b": [2, fd]}]),
                    ("r3", "Restroom", "bathroom", [(fw * 0.75, fd), (fw, fd), (fw, fd + kd), (fw * 0.75, fd + kd)], [{"kind": "door", "a": [fw * 0.8, fd], "b": [fw * 0.8 + 0.9, fd]}]),
                ]
            ceiling = rng.choice([3.0, 3.4, 3.7, 4.3])
            for rid, label, rtype, poly, openings in rooms:
                xs, zs = [p[0] for p in poly], [p[1] for p in poly]
                area = (max(xs) - min(xs)) * (max(zs) - min(zs))
                con.execute("INSERT INTO mp_rooms VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
                    sid, mid, f"{mid}-{rid}", label, rtype, 0, json.dumps(poly), "api", 0.0, ceiling, area, json.dumps(openings)])

            # Two scans in the front room, one in the kitchen.
            scan_spots = [("s1", f"{mid}-r1", (fw * 0.33, 1.55, fd * 0.5)), ("s2", f"{mid}-r1", (fw * 0.66, 1.55, fd * 0.5)),
                          ("s3", f"{mid}-r2", (fw * 0.35, 1.55, fd + kd / 2))]
            for scan, rid, (x, y, z) in scan_spots:
                con.execute("INSERT INTO mp_scans VALUES (?,?,?,?,?,?,?,?,?,?,?)", [mid, scan, rid, "default", x, y, z, 0, 0, 0, 1])
                faces = ["front", "right", "back", "left"] if scan != "s3" else ["front"]
                for face in faces:
                    p = PANOS_DIR / mid / f"{scan}_{face}.jpg"
                    w, h = _placeholder_pano(p, f"{sid}/{scan}", face, rng.randint(0, 65535)) if images else (1024, 1024)
                    yaw = {"front": 0, "right": -90, "back": 180, "left": 90}[face]
                    qy, qw = math.sin(math.radians(yaw) / 2), math.cos(math.radians(yaw) / 2)
                    con.execute("INSERT INTO mp_panos VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                        f"{mid}:{scan}:{face}", sid, mid, scan, rid, face, media_url(p), scan == "s1",
                        x, y, z, 0.0, qy, 0.0, qw, 90.0, w, h])
            con.execute("INSERT INTO mp_fetch_log (model_id, status) VALUES (?, 'ok')", [mid])

            # Neighborhood: tenants, residents, transit, Vexcel-ish parking.
            for _ in range(rng.randint(15, 70)):
                tlat, tlon = _jitter(rng, lat, lon, 700)
                name = rng.choice(TENANT_NAMES)
                cat = next((v for k, v in CATEGORIES.items() if k in name), "Retail")
                tenant_i += 1
                con.execute("INSERT INTO tenants VALUES (?,?,?,?,?,?,?,?)", [
                    f"sample-co-{tenant_i}", name, cat, tlat, tlon, rng.randint(2, 60), "raw_sample_location_occupancy", f"sample-occ-{tenant_i}"])
            for j in range(rng.randint(3, 15)):
                rlat, rlon = _jitter(rng, lat, lon, 900)
                con.execute("INSERT INTO residential VALUES (?,?,?,?,?)", [f"sample-apt-{i}-{j}", "raw_sample_apartment_listings", rlat, rlon, rng.randint(20, 320)])
            for j in range(rng.randint(1, 6)):
                slat, slon = _jitter(rng, lat, lon, 900)
                kind = "rail" if j == 0 and rng.random() < 0.5 else "bus"
                con.execute("INSERT OR IGNORE INTO transit VALUES (?,?,?,?,?)", [f"sample-stop-{i}-{j}", f"{hood} Stop {j + 1}", kind, slat, slon])
            pk = round(rng.uniform(0.1, 0.9), 2)
            con.execute("INSERT INTO vx_props (space_id, parking_score, parking_notes, status) VALUES (?, ?, ?, 'ok')",
                        [sid, pk, f"{NOTE}: ~{int(pk * 40)} parking spaces on parcel"])
    return path


def main() -> None:
    p = build()
    print(f"Wrote {p} ({len(SITES)} retail + {len(OFFICE_SITES)} office sample spaces).")
    print("Use it with:  HESTIA_DB_PATH=data/sample.duckdb   (PowerShell: $env:HESTIA_DB_PATH='data/sample.duckdb')")


if __name__ == "__main__":
    main()
