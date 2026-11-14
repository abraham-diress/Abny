"""Map raw CoStar tables/columns to the logical fields the pipeline needs.

We don't know the dump's exact column names ahead of time, so each logical field has
a list of candidate names (compared case/punctuation-insensitively, also matching the
last part of a flattened nested key like ``location__latitude``).

If auto-detection picks the wrong thing, override it in ``pipeline/colmap.json``
(column names only, no data, so it's safe to commit)::

    {
      "datasets": {"commercial_listing": "raw_listings_houston"},
      "columns":  {"commercial_listing": {"rent_psf": "AskingRentPerSFPerYear"}}
    }

`python -m pipeline.ingest_costar --show-mapping` prints what was resolved.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

OVERRIDES_PATH = Path(__file__).with_name("colmap.json")

# Dataset role -> keywords in the file/table name (checked in this order).
DATASET_KEYWORDS: list[tuple[str, list[str]]] = [
    ("mp_join", ["matterport", "mp_join", "model_join", "join"]),
    ("listing_features", ["feature"]),
    ("apartment_listings", ["apartment", "multifamily"]),
    ("residential_listings", ["residential", "homes", "forsale"]),
    ("sale_comps", ["salecomp", "sale_comp", "sales_comp", "comps", "sale"]),
    ("company_detail", ["company"]),
    ("location_occupancy", ["occupancy", "occupan", "tenant"]),
    ("commercial_listing", ["listing", "forlease", "lease"]),
    ("commercial_property", ["property", "properties", "building"]),
]

# Logical field -> candidate column names.
COMMON = {
    "property_id": ["property_id", "propertyid", "costar_property_id", "prop_id", "propid", "pid", "property_key"],
    "lat": ["latitude", "lat", "y_coord"],
    "lon": ["longitude", "lon", "lng", "long", "x_coord"],
    "address": ["address", "street_address", "address1", "address_line1", "full_address", "property_address", "building_address", "street"],
    "city": ["city", "city_name", "market", "submarket_city"],
    "state": ["state", "state_code", "province"],
    "zip": ["zip", "zipcode", "zip_code", "postal_code"],
}

FIELDS: dict[str, dict[str, list[str]]] = {
    "commercial_listing": {
        **COMMON,
        "listing_id": ["listing_id", "listingid", "costar_listing_id", "id", "listing_key", "space_id"],
        "property_type": ["property_type", "propertytype", "space_use", "spaceuse", "use_type", "primary_type", "listing_type", "type"],
        "sqft": ["available_sf", "space_available", "sf_available", "available_sqft", "sqft", "square_feet", "size_sf", "rba", "area_sf", "space_size", "size"],
        "rent_month": ["asking_rent_month", "monthly_rent", "rent_monthly", "rent_per_month", "monthly_asking_rent"],
        "rent_psf": ["asking_rent_psf", "asking_rent_per_sf", "asking_rent", "rent_per_sf", "rent_psf", "asking_rate", "rental_rate", "rate", "rent"],
        "rent_unit": ["rent_unit", "rate_type", "asking_rent_unit", "rent_basis", "rent_type", "rate_unit", "lease_rate_units"],
        "for_lease": ["for_lease", "listing_status", "status", "transaction_type", "deal_type"],
        "broker_name": ["broker_name", "contact_name", "agent_name", "leasing_contact", "listing_agent", "broker_contact_name", "contact"],
        "broker_company": ["broker_company", "brokerage", "company_name", "agency", "listing_company", "broker_firm"],
        "broker_email": ["broker_email", "contact_email", "agent_email", "email"],
        "broker_phone": ["broker_phone", "contact_phone", "agent_phone", "phone"],
    },
    "commercial_property": {
        **COMMON,
        "property_type": ["property_type", "propertytype", "primary_type", "building_type", "type"],
        "sqft": ["rba", "building_sf", "building_size", "total_sf", "sqft", "square_feet", "gross_sf"],
        "year_built": ["year_built", "yearbuilt", "built_year", "year_constructed"],
        "parking_ratio": ["parking_ratio", "parkingratio", "parking_per_1000", "parking_ratio_per_1000_sf"],
        "parking_spaces": ["parking_spaces", "number_of_parking_spaces", "num_parking_spaces", "parking_count", "parking"],
        "vacant_sf": ["vacant_sf", "total_vacant_sf", "vacancy_sf", "available_sf", "total_available_sf"],
        "vacancy_pct": ["vacancy_rate", "percent_vacant", "vacancy_pct", "vacancy"],
    },
    "location_occupancy": {
        **COMMON,
        "tenant_name": ["tenant_name", "tenant", "occupant_name", "occupant", "business_name", "company_name", "name"],
        "company_id": ["company_id", "companyid", "tenant_id", "occupant_id"],
        "category": ["industry", "industry_type", "sic_description", "naics_description", "category", "tenant_industry", "business_type", "use"],
        "employees": ["employees", "employee_count", "num_employees", "number_of_employees", "headcount"],
        "occupancy_status": ["occupancy_status", "status", "occupied", "is_vacant", "vacant"],
    },
    "company_detail": {
        **COMMON,
        "company_id": ["company_id", "companyid", "id", "tenant_id"],
        "tenant_name": ["company_name", "name", "business_name", "tenant_name"],
        "category": ["industry", "industry_type", "sic_description", "naics_description", "category", "primary_industry"],
        "employees": ["employees", "employee_count", "num_employees", "number_of_employees", "headcount"],
    },
    "apartment_listings": {
        **COMMON,
        "record_id": ["listing_id", "property_id", "id"],
        "units": ["units", "number_of_units", "num_units", "unit_count", "total_units"],
    },
    "residential_listings": {
        **COMMON,
        "record_id": ["listing_id", "id", "mls_id"],
        "units": ["units", "number_of_units", "num_units"],
    },
    "mp_join": {
        "property_id": COMMON["property_id"],
        "listing_id": ["listing_id", "listingid", "costar_listing_id"],
        "model_id": ["matterport_model_id", "model_id", "modelid", "matterport_id", "mp_model_id", "matterport_sid", "sid", "showcase_id", "model_sid", "space_sid"],
        "model_url": ["matterport_url", "url", "tour_url", "showcase_url", "model_url", "link"],
    },
    "listing_features": {
        "listing_id": ["listing_id", "listingid", "costar_listing_id", "id"],
        "feature": ["feature", "feature_name", "amenity", "name", "description"],
    },
    "sale_comps": {**COMMON},
}


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def load_overrides() -> dict:
    if OVERRIDES_PATH.exists():
        return json.loads(OVERRIDES_PATH.read_text())
    return {}


def detect_role(table_name: str) -> str | None:
    n = table_name.lower().removeprefix("raw_")
    flat = norm(n)
    for role, kws in DATASET_KEYWORDS:
        if any(norm(k) in flat for k in kws):
            return role
    return None


def resolve_columns(role: str, columns: list[str], overrides: dict | None = None) -> dict[str, str | None]:
    """logical field -> actual column name (or None)."""
    overrides = (overrides or {}).get("columns", {}).get(role, {})
    by_norm = {norm(c): c for c in columns}
    by_tail = {}
    for c in columns:  # flattened nested keys: 'location__latitude' -> 'latitude'
        tail = norm(c.split("__")[-1])
        by_tail.setdefault(tail, c)
    out: dict[str, str | None] = {}
    used: set[str] = set()
    for field, cands in FIELDS.get(role, {}).items():
        if field in overrides:
            out[field] = overrides[field] if overrides[field] in columns else None
            continue
        hit = None
        for cand in cands:
            k = norm(cand)
            c = by_norm.get(k) or by_tail.get(k)
            if c and c not in used:
                hit = c
                break
        if hit is None:  # substring fallback for long names ('asking_rent_per_sf_per_year')
            for cand in cands[:3]:
                k = norm(cand)
                if len(k) < 5:
                    continue
                for c in columns:
                    if k in norm(c) and c not in used:
                        hit = c
                        break
                if hit:
                    break
        out[field] = hit
        if hit:
            used.add(hit)
    return out
