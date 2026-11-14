"""Data contract functions (owner: Natnael). See shared/contracts.py for the specs.

    from pipeline.queries import query_spaces, get_space, get_rooms, get_panoramas, neighborhood_profile

All reads are local DuckDB (no live API calls), so they're safe during the demo.
Extra helpers for the agent (not contracts): ``score_for_brief``, ``market_rent_psf_year``,
``broker_contact``, ``target_sqft``.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import get_args

from shared.schemas import POI, Brief, Citation, NeighborhoodProfile, Opening, PanoRef, Room, Source, Space

from pipeline.db import bbox, connect, haversine_m, rows, table_exists

REQUIRE_SCAN = os.getenv("HESTIA_REQUIRE_SCAN", "1") != "0"

TENANT_RADIUS_M = 400
COMPETITOR_RADIUS_M = 800
RESIDENTIAL_RADIUS_M = 800
TRANSIT_RADIUS_M = 800

# Slack so the agent can reason about trade-offs (contract: keep slightly-over-budget spaces).
RENT_SLACK = 1.15
SIZE_SLACK = 0.15

COMPETITOR_KEYWORDS: dict[str, list[str]] = {
    "bakery": ["bakery", "bakeries", "bake", "pastry", "pastries", "patisserie", "boulangerie", "panaderia", "donut", "doughnut", "kolache", "cupcake", "cake", "bread", "croissant"],
    "cafe": ["cafe", "café", "coffee", "espresso", "tea house", "teahouse", "starbucks", "dunkin", "roaster"],
    "restaurant": ["restaurant", "grill", "kitchen", "diner", "bistro", "eatery", "taqueria", "pizza", "sushi", "bbq", "cantina"],
    "retail": ["boutique", "apparel", "clothing", "gift shop", "retail"],
    "salon": ["salon", "barber", "beauty", "nail", "spa"],
    "gym": ["fitness", "gym", "yoga", "pilates", "crossfit"],
    "clinic": ["clinic", "medical", "dental", "dentist", "urgent care", "physician"],
}

# Offices: places to eat, grab coffee or work out within a short walk (POI kind "amenity").
AMENITY_RADIUS_M = 500
AMENITY_KEYWORDS = ["restaurant", "cafe", "café", "coffee", "espresso", "bakery", "deli", "grill", "kitchen", "diner",
                    "bistro", "eatery", "pizza", "taco", "taqueria", "sushi", "ramen", "pho", "burger", "sandwich",
                    "salad", "juice", "food", "starbucks", "gym", "fitness", "yoga", "pilates", "crossfit",
                    "accommodation and food"]  # CoStar IndustryType "Accommodation And Food Services"

# Rough space need per business type, for briefs that give seats (desks for offices) but not sqft.
SQFT_PER_SEAT = {"bakery": 18, "cafe": 18, "restaurant": 22, "office": 175}  # office: ~150–200 sqft per person
SQFT_BASE = {"bakery": 700, "cafe": 450, "restaurant": 1200, "retail": 1200, "salon": 900, "gym": 2500, "clinic": 1500, "office": 400, "other": 1200}

FOOD = {"bakery", "cafe", "restaurant"}
OFFICE = "office"
TRANSIT_SOURCE: str = "osm" if "osm" in get_args(Source) else "assumption"

# Which listed spaces each business type may use. `space_use` is CoStar's SpaceUse; rows from other
# loaders may only have `property_type`, so fall back to it.
OFFICE_SPACES_SQL = ("(space_use IN ('Office', 'Office Retail') OR (space_use IS NULL AND "
                     "regexp_matches(lower(COALESCE(property_type, '')), 'office')))")
RETAIL_SPACES_SQL = ("(space_use IN ('Retail', 'Office Retail') OR (space_use IS NULL AND NOT "
                     "regexp_matches(lower(COALESCE(property_type, '')), "
                     "'office|industrial|warehouse|land|hospitality|health care|multi-family|multifamily')))")


def is_office(business_type: str | None) -> bool:
    return business_type == OFFICE


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _dataset(src: str | None) -> str | None:
    return src.removeprefix("raw_") if src else None


def _space_from_row(r: dict) -> Space:
    ds = _dataset(r.get("src_dataset"))
    rid = r.get("src_record_id")
    sample = bool(r.get("is_sample"))
    note = "SAMPLE DATA (synthetic)" if sample else None
    cites = [Citation(source="costar", dataset=ds, record_id=rid, field="address", value=r["address"], note=note)]
    if r.get("sqft") is not None:
        cites.append(Citation(source="costar", dataset=ds, record_id=rid, field="sqft", value=r["sqft"], note=note))
    if r.get("asking_rent_month") is not None:
        cites.append(Citation(source="costar", dataset=ds, record_id=rid, field="asking_rent_month",
                              value=round(r["asking_rent_month"], 2), note=r.get("rent_note") or note))
    if r.get("rent_per_sqft_year") is not None:
        cites.append(Citation(source="costar", dataset=ds, record_id=rid, field="rent_per_sqft_year",
                              value=round(r["rent_per_sqft_year"], 2), note=r.get("rent_note") or note))
    if r.get("matterport_model_id"):
        level = {"space": "scan of this suite", "listing": "scan attached to this listing",
                 "property": "scan of this building (may be a different suite)"}.get(r.get("scan_level") or "")
        cites.append(Citation(source="matterport", dataset="model", record_id=r["matterport_model_id"],
                              field="has_scan", value=True, note=note or level))
    return Space(
        space_id=r["space_id"],
        costar_property_id=r.get("costar_property_id"),
        listing_id=r.get("listing_id"),
        matterport_model_id=r.get("matterport_model_id"),
        address=r.get("address") or "Address not listed",
        city=r.get("city") if r.get("city") in ("Houston", "Los Angeles") else None,
        lat=r["lat"],
        lon=r["lon"],
        property_type=r.get("property_type"),
        sqft=r.get("sqft"),
        asking_rent_month=r.get("asking_rent_month"),
        rent_per_sqft_year=r.get("rent_per_sqft_year"),
        year_built=r.get("year_built"),
        has_scan=bool(r.get("has_scan")),
        citations=cites,
    )


def target_sqft(brief: Brief) -> tuple[float | None, float | None, float | None]:
    """(min, max, ideal) sqft for the brief. Uses seats when no size is given."""
    lo, hi = brief.sqft_min, brief.sqft_max
    ideal = None
    if lo or hi:
        ideal = ((lo or hi) + (hi or lo)) / 2
    elif brief.seats_wanted:
        bt = brief.business_type
        ideal = SQFT_BASE.get(bt, 1200) + SQFT_PER_SEAT.get(bt, 15) * brief.seats_wanted
        lo, hi = ideal * 0.6, ideal * 2.0
    return lo, hi, ideal


def _model_id(con, space_id: str) -> str | None:
    r = con.execute("SELECT matterport_model_id FROM spaces WHERE space_id = ?", [space_id]).fetchone()
    if r is None:
        raise KeyError(f"unknown space_id {space_id!r}")
    return r[0]


# --------------------------------------------------------------------------- #
# Contract functions
# --------------------------------------------------------------------------- #


def query_spaces(brief: Brief, limit: int = 200) -> list[Space]:
    """Cheap SQL filter: city, size range, rent (with slack), has_scan, space type. Best fits first.

    Space type follows brief.business_type: office -> office spaces; everything else -> retail/restaurant.
    For offices, seats_wanted is the desk count (sized at ~175 sqft per desk).
    """
    where, params = ["lat IS NOT NULL", "lon IS NOT NULL"], []
    if REQUIRE_SCAN:
        where.append("has_scan")
    with connect() as con:  # scans that turned out to be apartment units can't show a storefront
        if table_exists(con, "mp_model_info"):
            where.append("matterport_model_id NOT IN (SELECT model_id FROM mp_model_info WHERE is_residential)")
    if brief.city:
        where.append("city = ?")
        params.append(brief.city)
    lo, hi, ideal = target_sqft(brief)
    if lo:
        where.append("(sqft IS NULL OR sqft >= ?)")
        params.append(lo * (1 - SIZE_SLACK))
    if hi:
        where.append("(sqft IS NULL OR sqft <= ?)")
        params.append(hi * (1 + SIZE_SLACK))
    if brief.max_rent_month:
        where.append("(asking_rent_month IS NULL OR asking_rent_month <= ?)")
        params.append(brief.max_rent_month * RENT_SLACK)
    where.append(OFFICE_SPACES_SQL if is_office(brief.business_type) else RETAIL_SPACES_SQL)

    # Lower = better: size distance from ideal, over-budget penalty, unknown rent penalty, space-type bonus.
    order_terms = []
    if ideal:
        order_terms.append(f"COALESCE(abs(sqft - {ideal}) / {ideal}, 0.5)")
    if brief.max_rent_month:
        b = brief.max_rent_month
        order_terms.append(f"COALESCE(greatest(asking_rent_month - {b}, 0) / {b} * 3, 0.4)")
    else:
        order_terms.append("CASE WHEN asking_rent_month IS NULL THEN 0.3 ELSE 0 END")
    if is_office(brief.business_type):
        order_terms.append("CASE WHEN space_use = 'Office' THEN 0 ELSE 0.15 END")
    else:
        order_terms.append("CASE WHEN space_use = 'Retail' THEN 0 "
                           "WHEN regexp_matches(lower(COALESCE(property_type,'')), 'restaurant|retail|food') THEN 0.15 ELSE 0.4 END")
    order_terms.append("CASE scan_level WHEN 'space' THEN 0 WHEN 'listing' THEN 0.05 ELSE 0.15 END")
    order = " + ".join(order_terms) or "0"

    sql = f"SELECT * FROM spaces WHERE {' AND '.join(where)} ORDER BY ({order}), space_id LIMIT {int(limit)}"
    with connect() as con:
        return [_space_from_row(r) for r in rows(con, sql, params)]


def get_space(space_id: str) -> Space:
    with connect() as con:
        r = rows(con, "SELECT * FROM spaces WHERE space_id = ?", [space_id])
    if not r:
        raise KeyError(f"unknown space_id {space_id!r}")
    return _space_from_row(r[0])


def get_rooms(space_id: str) -> list[Room]:
    """Matterport rooms. Polygons are approximate rectangles unless polygon_source='api' (see G4)."""
    with connect() as con:
        mid = _model_id(con, space_id)
        if not mid:
            return []
        recs = rows(con, "SELECT * FROM mp_rooms WHERE model_id = ? ORDER BY area_m2 DESC", [mid])
    out = []
    for r in recs:
        openings = [Opening(kind=o.get("kind", "unknown"), a=tuple(o["a"]), b=tuple(o["b"]))
                    for o in json.loads(r.get("openings_json") or "[]")]
        out.append(Room(
            room_id=r["room_id"], space_id=space_id, label=r.get("label"), room_type=r.get("room_type"),
            floor_index=r.get("floor_index") or 0,
            polygon_m=[tuple(p) for p in json.loads(r["polygon_json"])],
            floor_y_m=r.get("floor_y_m") or 0.0, ceiling_m=r.get("ceiling_m"),
            area_m2=r["area_m2"], openings=openings,
        ))
    return out


FACE_ORDER = {"front": 0, "right": 1, "back": 2, "left": 3, "equirect": 4, "up": 5, "down": 6}


def get_panoramas(space_id: str) -> list[PanoRef]:
    """Cached faces with camera pose; furniture-free first, then by scan and face."""
    with connect() as con:
        mid = _model_id(con, space_id)
        if not mid:
            return []
        recs = rows(con, "SELECT * FROM mp_panos WHERE model_id = ?", [mid])
    recs.sort(key=lambda r: (not r.get("defurnished"), r["scan_id"], FACE_ORDER.get(r["face"], 9)))
    out = []
    for r in recs:
        q = (r["qx"], r["qy"], r["qz"], r["qw"])
        out.append(PanoRef(
            pano_id=r["pano_id"], space_id=space_id, scan_id=r["scan_id"], room_id=r.get("room_id"),
            face=r["face"], path=r["path"], defurnished=bool(r.get("defurnished")),
            position_m=(r["px"], r["py"], r["pz"]),
            rotation_quat=q if all(v is not None for v in q) else None,
            fov_deg=r.get("fov_deg") or 90.0, width_px=r["width_px"], height_px=r["height_px"],
        ))
    return out


def neighborhood_profile(space_id: str, business_type: str = "bakery") -> NeighborhoodProfile:
    """Nearby tenants, residents, competitors or amenities, transit, parking + a 0–1 score.

    `business_type` (optional, default bakery). Pass the brief's business type:
      - bakery / cafe / retail / ...: `competitors` (same-business tenants within 800 m), `amenities` empty.
      - office: `competitors` empty, `amenities` (food, cafés, gyms within 500 m), transit weighted higher.
    For a brief-aware score with reasons, use `score_for_brief(profile, brief, space)`.
    """
    return _neighborhood_cached(space_id, business_type).model_copy(deep=True)


@lru_cache(maxsize=4096)
def _neighborhood_cached(space_id: str, business_type: str) -> NeighborhoodProfile:
    office = is_office(business_type)
    with connect() as con:
        s = rows(con, "SELECT * FROM spaces WHERE space_id = ?", [space_id])
        if not s:
            raise KeyError(f"unknown space_id {space_id!r}")
        s = s[0]
        lat, lon = s["lat"], s["lon"]
        sample_note = "SAMPLE DATA (synthetic)" if s.get("is_sample") else None
        cites: list[Citation] = []

        def near(table: str, radius: float, cols: str, extra: str = "", params: list | None = None) -> list[dict]:
            if not table_exists(con, table):
                return []
            a, b, c, d = bbox(lat, lon, radius)
            got = rows(con, f"SELECT {cols} FROM {table} WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? {extra}",
                       [a, b, c, d, *(params or [])])
            for g in got:
                g["distance_m"] = haversine_m(lat, lon, g["lat"], g["lon"])
            return [g for g in got if g["distance_m"] <= radius]

        def tenant_pois(kind: str, keywords: list[str], radius: float) -> list[POI]:
            pattern = "|".join(re.escape(k) for k in keywords)
            hits = near("tenants", radius, "name, category, lat, lon, dataset, record_id",
                        "AND regexp_matches(lower(COALESCE(name,'') || ' ' || COALESCE(category,'')), ?)", [pattern])
            hits.sort(key=lambda c: c["distance_m"])
            return [POI(name=c["name"], kind=kind, lat=c["lat"], lon=c["lon"], distance_m=round(c["distance_m"], 1),
                        citation=Citation(source="costar", dataset=_dataset(c["dataset"]), record_id=c.get("record_id"),
                                          field="tenant_name", value=c["name"], note=sample_note))
                    for c in hits[:25]]

        # Tenants within 400 m (foot traffic proxy; for offices, how established the business district is).
        tenants = near("tenants", TENANT_RADIUS_M, "name, category, lat, lon, employees, dataset, record_id")
        emp = [t["employees"] for t in tenants if t.get("employees")]
        if tenants:
            cites.append(Citation(source="costar", dataset=_dataset(tenants[0]["dataset"]), field="tenants_within_400m",
                                  value=len(tenants), note=sample_note or f"count of tenant records within {TENANT_RADIUS_M} m"))
        if emp:
            cites.append(Citation(source="costar", dataset=_dataset(tenants[0]["dataset"]), field="employees_within_400m",
                                  value=sum(emp), note=sample_note or f"sum over {len(emp)} tenants with employee counts"))

        # Bakery etc.: competitors within 800 m by name/category. Offices: amenities within 500 m instead.
        competitors: list[POI] = []
        amenities: list[POI] = []
        if office:
            amenities = tenant_pois("amenity", AMENITY_KEYWORDS, AMENITY_RADIUS_M)
            if amenities:
                cites.append(Citation(source="costar", dataset=amenities[0].citation.dataset, field="amenities_within_500m",
                                      value=len(amenities), note=sample_note or "restaurants, cafés and gyms among nearby tenants"))
        elif COMPETITOR_KEYWORDS.get(business_type):
            competitors = tenant_pois("competitor", COMPETITOR_KEYWORDS[business_type], COMPETITOR_RADIUS_M)

        # Residents within 800 m.
        res = near("residential", RESIDENTIAL_RADIUS_M, "units, lat, lon, dataset")
        units = int(sum(r["units"] or 0 for r in res))
        if res:
            cites.append(Citation(source="costar", dataset=",".join(sorted({_dataset(r["dataset"]) for r in res})),
                                  field="residential_units_within_800m", value=units, note=sample_note))

        # Transit within 800 m (rail first).
        stops = near("transit", TRANSIT_RADIUS_M, "stop_id, name, kind, lat, lon")
        stops.sort(key=lambda t: (t["kind"] != "rail", t["distance_m"]))
        transit = [POI(name=f"{t['name']} ({t['kind']})", kind="transit", lat=t["lat"], lon=t["lon"],
                       distance_m=round(t["distance_m"], 1),
                       citation=Citation(source=TRANSIT_SOURCE, dataset="openstreetmap", record_id=t["stop_id"],
                                         field="transit_stop", value=t["name"], note="© OpenStreetMap contributors"))
                   for t in stops[:10]]

        # Parking: Vexcel attribute if any, else CoStar parking ratio / count.
        vx = rows(con, "SELECT * FROM vx_props WHERE space_id = ?", [space_id]) if table_exists(con, "vx_props") else []
        vx = vx[0] if vx else {}
        parking_score, parking_notes = vx.get("parking_score"), vx.get("parking_notes")
        if parking_score is not None:
            cites.append(Citation(source="vexcel", dataset="property/extract", record_id=space_id, field="parking",
                                  value=parking_score, note=parking_notes))
        elif s.get("parking_ratio"):
            parking_score = round(min(1.0, s["parking_ratio"] / 5.0), 2)
            parking_notes = f"{s['parking_ratio']:.1f} spaces per 1,000 sf (CoStar)"
            cites.append(Citation(source="costar", dataset="commercial_property", record_id=s.get("costar_property_id"),
                                  field="parking_ratio", value=s["parking_ratio"], note=sample_note))
        elif s.get("parking_spaces"):
            parking_score = round(min(1.0, s["parking_spaces"] / 40.0), 2)
            parking_notes = f"{s['parking_spaces']} parking spaces (CoStar)"
            cites.append(Citation(source="costar", dataset="commercial_property", record_id=s.get("costar_property_id"),
                                  field="parking_spaces", value=s["parking_spaces"], note=sample_note))
        if vx.get("footprint_wkt"):
            cites.append(Citation(source="vexcel", dataset="property/extract", record_id=space_id, field="footprint"))

    prof = NeighborhoodProfile(
        space_id=space_id,
        nearby_tenant_count=len(tenants),
        nearby_employees_est=sum(emp) if emp else None,
        nearby_residential_units=units,
        competitors=competitors,
        amenities=amenities,
        transit=transit,
        parking_score=parking_score,
        parking_notes=parking_notes,
        footprint_wkt=vx.get("footprint_wkt"),
        parcel_wkt=vx.get("parcel_wkt"),
        aerial_ortho_path=vx.get("ortho_path"),
        aerial_oblique_path=vx.get("oblique_path"),
        citations=cites,
    )
    prof.score = _generic_score(prof, business_type)
    return prof


# --------------------------------------------------------------------------- #
# Scoring (for the scout / ranking)
# --------------------------------------------------------------------------- #


def _parts(p: NeighborhoodProfile) -> dict[str, float]:
    close_comp = sum(1 for c in p.competitors if c.distance_m <= TENANT_RADIUS_M)
    rail = [t for t in p.transit if "(rail)" in t.name]
    near_stops = [t for t in p.transit if t.distance_m <= 400]
    transit = 1.0 if (rail and rail[0].distance_m <= 600) else min(1.0, len(near_stops) / 4)
    return {
        "foot_traffic": min(1.0, p.nearby_tenant_count / 60) * 0.65 + min(1.0, (p.nearby_employees_est or 0) / 1500) * 0.35,
        "residents": min(1.0, p.nearby_residential_units / 1500),
        "transit": transit,
        "parking": p.parking_score if p.parking_score is not None else 0.5,
        "low_competition": 1.0 - min(1.0, close_comp / 4),
        "amenities": min(1.0, len(p.amenities) / 10),
    }


# Bakery (and the other customer-facing types): foot traffic, residents, competition matter.
BASE_WEIGHTS = {"foot_traffic": 0.30, "residents": 0.20, "transit": 0.15, "parking": 0.15, "low_competition": 0.20}
# Offices: commute and lunch options matter; there are no competitors.
OFFICE_WEIGHTS = {"transit": 0.35, "amenities": 0.25, "foot_traffic": 0.15, "parking": 0.15, "residents": 0.10}


def weights_for(business_type: str | None) -> dict[str, float]:
    return dict(OFFICE_WEIGHTS if is_office(business_type) else BASE_WEIGHTS)


def _generic_score(p: NeighborhoodProfile, business_type: str | None = None) -> float:
    w, parts = weights_for(business_type), _parts(p)
    return round(sum(w[k] * parts[k] for k in w), 3)


def _brief_text(brief: Brief) -> str:
    return " ".join([brief.area_hint or "", *brief.must_haves, *brief.nice_to_haves, *(f.text for f in brief.feedback_history)]).lower()


def score_for_brief(profile: NeighborhoodProfile, brief: Brief, space: Space | None = None) -> tuple[float, list[str]]:
    """Brief-aware 0–1 score + human-readable reasons (for CandidateResult.rank_reasons).

    Base weights follow brief.business_type (offices: transit + amenities; bakery: foot traffic,
    residents, competition) and shift with the brief: 'transit' in area_hint/feedback, 'parking'
    in must-haves, etc. Rent and size fit are included when `space` is given.
    For offices, pass a profile built with neighborhood_profile(space_id, "office").
    """
    office = is_office(brief.business_type)
    text = _brief_text(brief)
    w = weights_for(brief.business_type)
    if "transit" in text or "metro" in text or "train" in text or "bus" in text:
        w["transit"] += 0.30
    if "parking" in text:
        w["parking"] += 0.25
    if "foot traffic" in text or "busy" in text or "walk" in text:
        w["foot_traffic"] += 0.20
    if "competit" in text and "low_competition" in w:
        w["low_competition"] += 0.15
    if office and any(k in text for k in ("lunch", "food", "restaurant", "amenit", "gym", "coffee")):
        w["amenities"] += 0.20
    parts = _parts(profile)
    reasons: list[str] = []

    fit_w = 0.0
    fit = 0.0
    if space is not None:
        if brief.max_rent_month and space.asking_rent_month:
            over = space.asking_rent_month / brief.max_rent_month
            rent_fit = 1.0 if over <= 1 else max(0.0, 1 - (over - 1) * 4)
            fit += 0.35 * rent_fit
            fit_w += 0.35
            reasons.append(f"Rent ${space.asking_rent_month:,.0f}/mo vs budget ${brief.max_rent_month:,.0f}"
                           + ("" if over <= 1 else f" ({(over - 1) * 100:.0f}% over)"))
        lo, hi, ideal = target_sqft(brief)
        if ideal and space.sqft:
            size_fit = max(0.0, 1 - abs(space.sqft - ideal) / ideal)
            fit += 0.25 * size_fit
            fit_w += 0.25
            if office and brief.seats_wanted:
                reasons.append(f"{space.sqft:,.0f} sqft for {brief.seats_wanted} desks "
                               f"(~{space.sqft / brief.seats_wanted:,.0f} sqft/desk; target ~{SQFT_PER_SEAT[OFFICE]})")
            else:
                reasons.append(f"{space.sqft:,.0f} sqft (target ~{ideal:,.0f})")

    total_w = sum(w.values())
    neigh = sum(w[k] * parts[k] for k in w) / total_w
    score = (neigh * 1.0 + fit) / (1.0 + fit_w)

    if profile.transit:
        t = profile.transit[0]
        reasons.append(f"{t.name} {t.distance_m:.0f} m away")
    elif office or w["transit"] > BASE_WEIGHTS["transit"]:
        reasons.append(f"No transit stop within {TRANSIT_RADIUS_M} m")
    if office:
        if profile.amenities:
            names = ", ".join(a.name for a in profile.amenities[:3])
            reasons.append(f"{len(profile.amenities)} places to eat or work out within {AMENITY_RADIUS_M} m (e.g. {names})")
        else:
            reasons.append(f"No restaurants, cafés or gyms found within {AMENITY_RADIUS_M} m")
    elif profile.competitors:
        close = [c for c in profile.competitors if c.distance_m <= TENANT_RADIUS_M]
        reasons.append(f"{len(profile.competitors)} competitor(s) within {COMPETITOR_RADIUS_M} m"
                       + (f", nearest {profile.competitors[0].name} at {profile.competitors[0].distance_m:.0f} m" if close else ""))
    else:
        reasons.append(f"No direct competitors within {COMPETITOR_RADIUS_M} m")
    reasons.append(f"{profile.nearby_tenant_count} businesses within {TENANT_RADIUS_M} m")
    if profile.nearby_residential_units and not office:
        reasons.append(f"{profile.nearby_residential_units:,} residential units within {RESIDENTIAL_RADIUS_M} m")
    if profile.parking_notes:
        reasons.append(f"Parking: {profile.parking_notes}")
    return round(min(1.0, max(0.0, score)), 3), reasons


# --------------------------------------------------------------------------- #
# Extra data helpers for the analyst
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=64)
def market_rent_psf_year(city: str | None, property_type: str | None = None) -> tuple[float, int] | None:
    """Median asking $/sf/yr across listings (same city, same type if enough), and the sample size."""
    with connect() as con:
        for use_type in (True, False):
            where, params = ["rent_per_sqft_year BETWEEN 5 AND 300"], []
            if city:
                where.append("city = ?")
                params.append(city)
            if use_type and property_type:
                where.append("property_type = ?")
                params.append(property_type)
            r = con.execute(f"SELECT median(rent_per_sqft_year), count(*) FROM spaces WHERE {' AND '.join(where)}", params).fetchone()
            if r and r[1] >= 10:
                return float(r[0]), int(r[1])
    return None


def broker_contact(space_id: str) -> dict:
    with connect() as con:
        r = rows(con, "SELECT broker_name, broker_company, broker_email, broker_phone FROM spaces WHERE space_id = ?", [space_id])
    return r[0] if r else {}


def count_spaces(business_type: str | None = None) -> int:
    """Size of the searchable set: the funnel's starting "total" (e.g. 3,000 -> 200 -> 20 -> 5).

    Same base filters as query_spaces (coordinates, Houston/LA, has a scan, scan isn't an apartment),
    without the brief's size/rent limits. Pass a business type to count only the spaces that type can
    use (office -> office spaces, anything else -> retail/restaurant); with no argument, counts both.
    """
    where = ["lat IS NOT NULL", "lon IS NOT NULL", "city IS NOT NULL"]
    if REQUIRE_SCAN:
        where.append("has_scan")
    if business_type is not None:
        where.append(OFFICE_SPACES_SQL if is_office(business_type) else RETAIL_SPACES_SQL)
    else:
        where.append(f"({OFFICE_SPACES_SQL} OR {RETAIL_SPACES_SQL})")
    with connect() as con:
        if table_exists(con, "mp_model_info"):
            where.append("(matterport_model_id IS NULL OR matterport_model_id NOT IN "
                         "(SELECT model_id FROM mp_model_info WHERE is_residential))")
        return int(con.execute(f"SELECT count(*) FROM spaces WHERE {' AND '.join(where)}").fetchone()[0])


def listing_details(space_id: str) -> dict:
    """Broker contact + rent basis for a space (columns not on the Space schema)."""
    with connect() as con:
        r = rows(con, "SELECT * FROM spaces WHERE space_id = ?", [space_id])
    if not r:
        return {}
    keep = ("broker_name", "broker_company", "broker_email", "broker_phone", "service_type", "space_use", "rent_note")
    return {k: r[0].get(k) for k in keep}


def rent_comps(space_id: str, radius_m: float = 1500, k: int = 5) -> list[dict]:
    """Other listings of the same kind (office vs retail) nearby with an asking rent, nearest first.

    Falls back to the whole city when fewer than 3 are within `radius_m`. One comp per listing.
    Each dict: space_id, address, rent_per_sqft_year, distance_m, scope, src_dataset, src_record_id, service_type.
    """
    with connect() as con:
        s = rows(con, "SELECT * FROM spaces WHERE space_id = ?", [space_id])
        if not s:
            raise KeyError(f"unknown space_id {space_id!r}")
        s = s[0]
        office = s.get("space_use") in ("Office", "Office Retail") or (
            s.get("space_use") is None and "office" in (s.get("property_type") or "").lower())
        kind = OFFICE_SPACES_SQL if office else RETAIL_SPACES_SQL
        base = ("SELECT space_id, address, rent_per_sqft_year, lat, lon, src_dataset, src_record_id, service_type "
                f"FROM spaces WHERE {kind} AND rent_per_sqft_year BETWEEN 5 AND 300 "
                "AND space_id <> ? AND COALESCE(listing_id, '') <> COALESCE(?, '#')")
        params = [space_id, s.get("listing_id")]
        a, b, c, d = bbox(s["lat"], s["lon"], radius_m)
        got = rows(con, base + " AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", params + [a, b, c, d])
        scope = f"within {radius_m / 1000:g} km"
        if len(got) < 3 and s.get("city"):
            got = rows(con, base + " AND city = ?", params + [s["city"]])
            scope = f"in {s['city']}"
    for g in got:
        g["distance_m"] = round(haversine_m(s["lat"], s["lon"], g["lat"], g["lon"]), 1)
        g["scope"] = scope
    got.sort(key=lambda g: g["distance_m"])
    seen, out = set(), []  # one comp per listing (a listing can have many suites at the same rate)
    for g in got:
        key = (g["src_record_id"] or g["space_id"]).split("/")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out[:k]
