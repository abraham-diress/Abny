"""CoStar hackathon kit -> DuckDB (the real data format; see data/costar_kit/kit/index.md).

    python -m pipeline.ingest_kit                       # uses COSTAR_DATA_DIR (default data/costar_kit/kit)
    python -m pipeline.ingest_kit --include-inactive    # also listings that are not Active

Kit layout: data/<dataset>.jsonl (8 datasets), commercial-properties.csv (PropertyId -> MatterportModelId),
schemas/enums.json (integer enums -> names).

Builds:
  spaces       one row per leasable space (forLeaseSummary.spaces[]) on an active lease listing,
               rent normalised to $/sf/yr, broker from listingContacts, best Matterport model:
               scan_level 'space'    the suite's own scan (spaces[].floorPlan.videoKey)
                          'listing'  a scan attached to the listing
                          'property' some scan of the building (commercial-properties.csv)
  tenants      current tenancies (toDate null) joined to company-detail (name, industry, employees)
  residential  apartment communities (units) + residential listings (1 each)
  candidates   scanned spaces in Houston/LA: retail (bakery) and office spaces, suite-level scans first
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from pathlib import Path

from shared.conventions import DATA_DIR, REPO_ROOT

from pipeline.db import connect, nearest_metro
from pipeline.tables import ensure_tables

FLAT_DIR = DATA_DIR / "_flat"
LEASE_LISTING_TYPES = {14, 16, 17, 19, 20}  # direct, building-park, shopping-center, sublease, assignment
MATTERPORT_REF_TYPES = {36, 234}            # MatterportScan, MatterportStreamingKey
RETAIL_USES = {"Retail", "Office Retail"}
RETAIL_PROPERTY_TYPES = {"General Retail", "Mixed Use", "Flex", "Specialty"}


def kit_dir() -> Path:
    d = Path(os.getenv("COSTAR_DATA_DIR") or DATA_DIR / "costar_kit" / "kit")
    return d if d.is_absolute() else REPO_ROOT / d


def is_kit(d: Path) -> bool:
    return (d / "data" / "commercial-property.jsonl").exists() and (d / "commercial-properties.csv").exists()


def jsonl(d: Path, name: str):
    with (d / "data" / f"{name}.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def pretty(name: str | None) -> str | None:
    """'GeneralRetail' -> 'General Retail'."""
    if not name:
        return None
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


class Enums:
    def __init__(self, d: Path):
        self.e = json.loads((d / "schemas" / "enums.json").read_text(encoding="utf-8"))

    def __call__(self, enum: str, value) -> str | None:
        if value is None:
            return None
        v = self.e.get(enum, {}).get(str(value))
        return None if v in (None, "Unknown") else pretty(v)


def fmt_address(a: dict | None) -> str | None:
    if not a:
        return None
    street = " ".join(str(x) for x in [a.get("streetNumber"), a.get("streetDirection"), a.get("streetName"),
                                       a.get("streetType"), a.get("streetSuffix")] if x)
    parts = [p for p in [street, a.get("city")] if p]
    return ", ".join(parts) or None


def bulk_insert(con, table: str, recs: list[dict]) -> int:
    """Fast insert via a temp NDJSON file (DuckDB executemany is slow for 50k+ rows)."""
    if not recs:
        return 0
    FLAT_DIR.mkdir(parents=True, exist_ok=True)
    path = FLAT_DIR / f"{table}.ndjson"
    cols = list(recs[0].keys())
    with path.open("w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps({c: r.get(c) for c in cols}, default=str) + "\n")
    types = dict(con.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?", [table]).fetchall())
    spec = "{" + ", ".join(f"'{c}': '{types[c]}'" for c in cols) + "}"
    con.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM "
                f"read_json(?, format='newline_delimited', columns={spec})", [str(path)])
    return len(recs)


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #


def load_models(d: Path) -> dict[str, list[str]]:
    by_prop: dict[str, list[str]] = defaultdict(list)
    with (d / "commercial-properties.csv").open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("MatterportModelId"):
                by_prop[str(row["PropertyId"])].append(row["MatterportModelId"])
    return by_prop


def load_properties(d: Path, en: Enums) -> dict[str, dict]:
    props = {}
    for p in jsonl(d, "commercial-property"):
        a = p.get("primaryAddress") or {}
        built = [e.get("year") for e in p.get("constructionEvents") or [] if e.get("eventType") == 2 and e.get("year")]
        spaces = sum((x.get("totalSpaces") or 0) for x in p.get("parking") or [])
        props[str(p["id"])] = {
            "lat": a.get("latitude"), "lon": a.get("longitude"), "address": fmt_address(a), "city": a.get("city"),
            "property_type": en("PropertyType", p.get("propertyType")),
            "rba": p.get("rentableBuildingAreaSquareFeet"),
            "year_built": max(built) if built else None,
            "parking_ratio": p.get("parkingRatio"), "parking_spaces": spaces or None,
        }
    return props


def _video_keys(attachments) -> list[str]:
    out = []
    for a in attachments or []:
        if a and a.get("videoKey") and a.get("videoExternalReferenceType") in MATTERPORT_REF_TYPES:
            out.append(a["videoKey"])
    return out


def _broker(listing: dict) -> dict:
    contacts = listing.get("listingContacts") or []
    contacts = sorted(contacts, key=lambda c: c.get("contactRole") != 11)  # ListingBroker first
    c = contacts[0] if contacts else {}
    name = " ".join(x for x in [c.get("firstName"), c.get("lastName")] if x) or None
    return {"broker_name": name, "broker_company": listing.get("brokerageCompanyName"),
            "broker_email": c.get("emailAddress"), "broker_phone": c.get("phoneNumber")}


def build_spaces(d: Path, en: Enums, props: dict, models: dict, include_inactive: bool) -> tuple[list[dict], dict]:
    out, stats = [], defaultdict(int)
    for L in jsonl(d, "commercial-listing-summary"):
        stats["listings"] += 1
        if L.get("listingType") not in LEASE_LISTING_TYPES:
            continue
        stats["lease_listings"] += 1
        if not include_inactive and L.get("listingStatus") != 1:
            continue
        stats["active_lease_listings"] += 1
        fl = L.get("forLeaseSummary") or {}
        listing_keys = _video_keys(L.get("attachments"))
        broker = _broker(L)
        for s in fl.get("spaces") or []:
            if s.get("dateOffMarket"):
                continue
            stats["spaces"] += 1
            pid = str(s.get("propertyId") or L.get("propertyId") or "")
            prop = props.get(pid, {})
            addr = s.get("marketingAddress") or L.get("address") or {}
            lat = addr.get("latitude") or prop.get("lat")
            lon = addr.get("longitude") or prop.get("lon")
            if lat is None or lon is None:
                continue
            city_txt = addr.get("city") or prop.get("city") or ""
            city = "Houston" if "houston" in city_txt.lower() else "Los Angeles" if "los angeles" in city_txt.lower() else nearest_metro(lat, lon)

            # Rent: space rate (0 = none) else listing range; basis 1 = monthly, 2 = yearly; per SF.
            rate = s.get("rateLow") or s.get("rateHigh") or 0
            basis = s.get("rateBasis")
            if not rate and fl.get("askingRateMeasurementType") in (1, None):
                rate = fl.get("askingRateLow") or fl.get("askingRateHigh") or 0
                basis = fl.get("askingRateBasis")
            psf_year = (rate * 12 if basis == 1 else rate) if rate else None
            sqft = s.get("squareFeetMax") or s.get("squareFeetMin")
            service = en("ServiceType", s.get("serviceType") or fl.get("serviceType"))
            note = None
            if rate:
                note = f"asking ${rate:g}/sf/{'mo' if basis == 1 else 'yr'}" + (f", {service}" if service else "")
                if s.get("isLeasePending"):
                    note += ", lease pending"

            # Best Matterport model: the suite's own scan, then the listing's, then any scan of the building.
            prop_models = models.get(pid, [])
            space_keys = _video_keys([s.get("floorPlan")])
            model, level = None, None
            if space_keys:
                model, level = space_keys[0], "space"
            elif [k for k in listing_keys if k in prop_models] or listing_keys:
                model, level = ([k for k in listing_keys if k in prop_models] or listing_keys)[0], "listing"
            elif prop_models:
                model, level = prop_models[0], "property"
            stats[f"scan_{level or 'none'}"] += 1

            use = en("SpaceUse", s.get("spaceUse"))
            ptype = prop.get("property_type") or en("PropertyType", L.get("propertyType"))
            suite = s.get("suite")
            address = fmt_address(addr) or prop.get("address") or "Address not listed"
            if suite:
                address = f"{address.split(',')[0]}, Suite {suite}" + (", " + address.split(", ", 1)[1] if ", " in address else "")
            out.append({
                "space_id": f"cs-{L['id']}-{s.get('id')}",
                "costar_property_id": pid or None, "listing_id": str(L["id"]), "matterport_model_id": model,
                "address": address, "city": city, "lat": lat, "lon": lon,
                "property_type": (f"{use} space" if use else "Space") + (f" in {ptype} building" if ptype else ""),
                "sqft": sqft, "asking_rent_month": psf_year * sqft / 12 if (psf_year and sqft) else None,
                "rent_per_sqft_year": psf_year, "rent_note": note, "year_built": prop.get("year_built"),
                "has_scan": model is not None,
                "parking_ratio": prop.get("parking_ratio"), "parking_spaces": prop.get("parking_spaces"),
                **broker,
                "src_dataset": "commercial-listing-summary", "src_record_id": f"{L['id']}/space/{s.get('id')}",
                "is_sample": False, "scan_level": level, "space_use": use, "service_type": service,
            })
    return out, stats


def build_tenants(d: Path, en: Enums, props: dict) -> list[dict]:
    current: dict[int, str] = {}
    for o in jsonl(d, "location-occupancy"):
        if o.get("toDate") is None and o.get("tenantLocationId"):
            current[o["tenantLocationId"]] = str(o.get("propertyId"))
    out = []
    for c in jsonl(d, "company-detail"):
        if c["id"] not in current:
            continue
        a = c.get("address") or {}
        prop = props.get(current[c["id"]], {})
        lat = a.get("latitude") or c.get("latitude") or prop.get("lat")
        lon = a.get("longitude") or c.get("longitude") or prop.get("lon")
        if lat is None or lon is None:
            continue
        prof = c.get("profile") or {}
        brands = " ".join(b.get("locationName") or "" for b in c.get("brandProfiles") or [])
        out.append({
            "tenant_id": str(c["id"]), "name": c.get("name"),
            "category": " ".join(x for x in [en("IndustryType", prof.get("industryType")), brands] if x) or None,
            "lat": lat, "lon": lon, "employees": c.get("numEmployees"),
            "dataset": "company-detail", "record_id": str(c["id"]),
        })
    return out


def build_residential(d: Path) -> list[dict]:
    out = []
    for a in jsonl(d, "apartment-listing"):
        ad = a.get("address") or {}
        if ad.get("latitude") is not None:
            out.append({"record_id": str(a["id"]), "dataset": "apartment-listing", "lat": ad["latitude"],
                        "lon": ad.get("longitude"), "units": a.get("totalNumUnits") or 1})
    for r in jsonl(d, "residential-listings"):
        ad = ((r.get("property") or {}).get("address")) or {}
        if ad.get("latitude") is not None:
            out.append({"record_id": str(r["id"]), "dataset": "residential-listings", "lat": ad["latitude"],
                        "lon": ad.get("longitude"), "units": 1})
    return out


def build_candidates(con, limit: int = 2000) -> int:
    con.execute("DELETE FROM candidates WHERE priority >= 100")
    con.execute(f"""
        INSERT INTO candidates
        SELECT space_id,
               100 + (CASE scan_level WHEN 'space' THEN 0 WHEN 'listing' THEN 10 ELSE 30 END)
                   + (CASE WHEN space_use IN ('Retail', 'Office Retail', 'Office') THEN 0 ELSE 40 END),  -- bakery + office
               'auto'
        FROM spaces
        WHERE has_scan AND city IS NOT NULL AND space_id NOT IN (SELECT space_id FROM candidates)
        ORDER BY 2, asking_rent_month IS NULL, space_id
        LIMIT {int(limit)}
    """)
    return con.execute("SELECT count(*) FROM candidates").fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--include-inactive", action="store_true")
    ap.add_argument("--candidates", type=int, default=2000)
    a = ap.parse_args()
    d = kit_dir()
    if not is_kit(d):
        raise SystemExit(f"{d} doesn't look like the CoStar kit (needs data/commercial-property.jsonl). Set COSTAR_DATA_DIR.")
    en = Enums(d)
    print(f"Reading kit at {d}")
    models = load_models(d)
    props = load_properties(d, en)
    print(f"  properties {len(props)}, with Matterport models {len(models)}")
    spaces, stats = build_spaces(d, en, props, models, a.include_inactive)
    print("  " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    tenants = build_tenants(d, en, props)
    residential = build_residential(d)

    with connect(read_only=False) as con:
        for t in ("spaces", "tenants", "residential"):
            con.execute(f"DROP TABLE IF EXISTS {t}")
        ensure_tables(con)
        print(f"spaces: {bulk_insert(con, 'spaces', spaces)}")
        print(f"tenants (current, with location): {bulk_insert(con, 'tenants', tenants)}")
        print(f"residential: {bulk_insert(con, 'residential', residential)}")
        print(f"candidates: {build_candidates(con, a.candidates)}")


if __name__ == "__main__":
    main()
