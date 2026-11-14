"""Data Engine tests: contract functions on the sample DB, and ingest on a fake CoStar dump."""

from __future__ import annotations

import csv
import json

import pytest

from shared.schemas import Brief, Inspection, Layout, LayoutItem, NeighborhoodProfile, Numbers, PanoRef, Room, Space


@pytest.fixture()
def sample_db(tmp_path, monkeypatch):
    from pipeline import queries, sample_data

    db = tmp_path / "sample.duckdb"
    sample_data.build(db, images=False)
    monkeypatch.setenv("HESTIA_DB_PATH", str(db))
    queries._neighborhood_cached.cache_clear()
    queries.market_rent_psf_year.cache_clear()
    yield db
    queries._neighborhood_cached.cache_clear()
    queries.market_rent_psf_year.cache_clear()


BRIEF = Brief(raw_text="bakery in Houston, 20 seats, under $6k", city="Houston", seats_wanted=20, max_rent_month=6000)


def test_query_spaces_filters(sample_db):
    from pipeline.queries import query_spaces

    spaces = query_spaces(BRIEF)
    assert spaces and all(isinstance(s, Space) for s in spaces)
    assert all(s.city == "Houston" and s.has_scan for s in spaces)
    assert all(s.asking_rent_month is None or s.asking_rent_month <= 6000 * 1.15 for s in spaces)
    assert all(any(c.field == "asking_rent_month" for c in s.citations) for s in spaces)
    assert len(query_spaces(Brief(), limit=3)) == 3


def test_space_rooms_panos(sample_db):
    from pipeline.queries import get_panoramas, get_rooms, get_space

    s = get_space("sample-hou-01")
    rooms = get_rooms(s.space_id)
    panos = get_panoramas(s.space_id)
    assert rooms and all(isinstance(r, Room) and r.area_m2 > 0 and len(r.polygon_m) >= 3 for r in rooms)
    assert panos and all(isinstance(p, PanoRef) and p.path.startswith("media/panos/") for p in panos)
    assert panos[0].defurnished  # furniture-free first
    with pytest.raises(KeyError):
        get_space("nope")


def test_neighborhood(sample_db):
    from pipeline.queries import neighborhood_profile, score_for_brief, get_space

    p = neighborhood_profile("sample-la-07")
    assert isinstance(p, NeighborhoodProfile) and 0 <= p.score <= 1
    assert p.citations and all(c.citation for c in p.competitors)
    score, reasons = score_for_brief(p, BRIEF.model_copy(update={"area_hint": "close to transit"}), get_space("sample-la-07"))
    assert 0 <= score <= 1 and reasons


def _layout(space_id: str) -> Layout:
    types = ["deck_oven", "display_case", "service_counter", "prep_table", "sink"] + ["table_2"] * 9 + ["chair"] * 18
    items = [LayoutItem(item_id=str(i), item_type=t, glb_asset="assets/glb/x.glb", room_id="r", x_m=0, z_m=0,
                        width_m=1, depth_m=1, height_m=1, seats=1 if t == "chair" else 0) for i, t in enumerate(types)]
    return Layout(layout_id="l1", space_id=space_id, business_type="bakery", items=items, seat_count=18)


def test_estimate_costs(sample_db):
    from agent.analyst.costs import draft_broker_email, estimate_costs
    from pipeline.queries import get_space

    s = get_space("sample-hou-01")
    raw = estimate_costs(s, _layout(s.space_id), Inspection(space_id=s.space_id, existing_kitchen=False), BRIEF)
    second = estimate_costs(s, _layout(s.space_id), Inspection(space_id=s.space_id, existing_kitchen=True), BRIEF)
    none = estimate_costs(s, None, None, BRIEF)
    for n in (raw, second, none):
        assert isinstance(n, Numbers) and n.fitout_cost_low <= n.fitout_cost_high
        assert n.revenue_month_low <= n.revenue_month_high and n.assumptions
        assert n.rent_month == pytest.approx(s.asking_rent_month, rel=1e-3)
    assert second.fitout_cost_high < raw.fitout_cost_high  # existing kitchen is cheaper
    if raw.breakeven_months_low and raw.breakeven_months_high:
        assert raw.breakeven_months_low <= raw.breakeven_months_high
    email = draft_broker_email(s, BRIEF)
    assert s.address in email and "bakery" in email


def test_estimate_costs_without_db():
    """Works on a bare Space with no database (e.g. hand-made sample objects)."""
    from agent.analyst.costs import estimate_costs

    s = Space(space_id="x", address="1 Test St", lat=0, lon=0, sqft=1200, asking_rent_month=4000)
    n = estimate_costs(s, None, None, Brief(seats_wanted=16))
    assert n.rent_month == 4000 and n.fitout_cost_high > 0


def test_ingest_fake_dump(tmp_path, monkeypatch):
    """Odd column names, nested JSON, rent strings with units, tour URLs instead of model ids."""
    from pipeline import ingest_costar as ing
    from pipeline.db import connect

    raw = tmp_path / "costar"
    raw.mkdir()
    listings = {"data": [
        {"ListingID": 1, "PropertyID": 10, "SpaceUse": "Retail", "AvailableSF": "1,400",
         "AskingRent": "$32.50/SF/YR", "Contact": {"Name": "Pat Lee", "Email": "pat@example.com"},
         "Location": {"Latitude": 29.75, "Longitude": -95.39}, "City": "Houston"},
        {"ListingID": 2, "PropertyID": 11, "SpaceUse": "Restaurant", "AvailableSF": 2000, "AskingRent": 4.1,
         "Location": {"Latitude": 34.05, "Longitude": -118.25}, "City": "Los Angeles"},
        {"ListingID": 3, "PropertyID": 12, "SpaceUse": "Retail", "AvailableSF": 900, "AskingRent": 40,
         "Location": {"Latitude": 29.80, "Longitude": -95.40}, "City": "Bellaire"},  # suburb -> nearest metro
    ]}
    (raw / "commercial_listing.json").write_text(json.dumps(listings))
    (raw / "commercial_property.json").write_text(json.dumps([
        {"PropertyID": 10, "YearBuilt": 1990, "ParkingRatio": 3.5, "Latitude": 29.75, "Longitude": -95.39},
        {"PropertyID": 11, "YearBuilt": 2005, "Latitude": 34.05, "Longitude": -118.25},
    ]))
    (raw / "location_occupancy.json").write_text(json.dumps([
        {"PropertyID": 10, "TenantName": "Sunrise Bakery", "Industry": "Bakery", "Employees": 8},
    ]))
    with (raw / "matterport_join.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["property_id", "matterport_url"])
        w.writerow([10, "https://my.matterport.com/show/?m=AbC123xyz"])
        w.writerow([11, "https://my.matterport.com/show/?m=Zz9"])

    monkeypatch.setenv("HESTIA_DB_PATH", str(tmp_path / "t.duckdb"))
    monkeypatch.setattr(ing, "FLAT_DIR", tmp_path / "_flat")
    with connect(read_only=False) as con:
        ing.load_raw(con, raw)
        m = ing.build_mapping(con)
        assert {"commercial_listing", "commercial_property", "location_occupancy", "mp_join"} <= set(m)
        assert ing.build_spaces(con, m, "listings") == 3
        assert ing.build_tenants(con, m) == 1
        ing.build_residential(con, m)
        got = {r[0]: r for r in con.execute(
            "SELECT space_id, city, sqft, rent_per_sqft_year, asking_rent_month, matterport_model_id, broker_email, parking_ratio FROM spaces").fetchall()}
    a, b, c = got["cs-l-1"], got["cs-l-2"], got["cs-l-3"]
    assert a[1] == "Houston" and a[2] == 1400 and a[3] == 32.5 and a[5] == "AbC123xyz" and a[6] == "pat@example.com" and a[7] == 3.5
    assert a[4] == pytest.approx(32.5 * 1400 / 12)
    assert b[1] == "Los Angeles" and b[3] == pytest.approx(4.1 * 12) and b[5] == "Zz9"  # < $8 -> monthly
    assert c[1] == "Houston" and c[5] is None


# --------------------------------------------------------------------------- #
# Offices (business_type="office")
# --------------------------------------------------------------------------- #

OFFICE_BRIEF = Brief(raw_text="office for a 25-person team in downtown LA, near transit, under $20k/month",
                     business_type="office", city="Los Angeles", seats_wanted=25, max_rent_month=20000,
                     area_hint="near transit")


def test_query_spaces_office_vs_bakery(sample_db):
    from pipeline.db import connect
    from pipeline.queries import query_spaces

    offices = query_spaces(OFFICE_BRIEF.model_copy(update={"city": None, "max_rent_month": None, "seats_wanted": None}))
    bakeries = query_spaces(Brief(business_type="bakery"))
    with connect() as con:
        use = dict(con.execute("SELECT space_id, space_use FROM spaces").fetchall())
    assert offices and all(use[s.space_id] == "Office" for s in offices)
    assert bakeries and all(use[s.space_id] == "Retail" for s in bakeries)
    # 25 desks -> ~4,775 sqft target; the LA office samples are found
    la = query_spaces(OFFICE_BRIEF.model_copy(update={"max_rent_month": None}))
    assert la and all(s.city == "Los Angeles" for s in la)


def test_neighborhood_office(sample_db):
    from pipeline.queries import get_space, neighborhood_profile, score_for_brief

    sid = "sample-la-office-15"
    office = neighborhood_profile(sid, "office")
    bakery = neighborhood_profile(sid, "bakery")
    assert office.competitors == [] and office.amenities
    assert all(a.kind == "amenity" and a.citation for a in office.amenities)
    assert bakery.amenities == []
    assert any(c.field == "amenities_within_500m" for c in office.citations)
    score, reasons = score_for_brief(office, OFFICE_BRIEF, get_space(sid))
    assert 0 <= score <= 1
    assert any("places to eat" in r for r in reasons) and any("desks" in r for r in reasons)
    assert not any("competitor" in r for r in reasons)


def test_estimate_costs_office(sample_db):
    from agent.analyst.costs import draft_broker_email, estimate_costs
    from pipeline.queries import get_space

    s = get_space("sample-la-office-15")
    open_plan = estimate_costs(s, None, Inspection(space_id=s.space_id, existing_build_out="open plan"), OFFICE_BRIEF)
    shell = estimate_costs(s, None, Inspection(space_id=s.space_id, existing_build_out="shell"), OFFICE_BRIEF)
    unknown = estimate_costs(s, None, None, OFFICE_BRIEF)
    for n in (open_plan, shell, unknown):
        assert n.revenue_month_low == 0 and n.revenue_month_high == 0
        assert n.breakeven_months_low is None and n.breakeven_months_high is None
        assert n.cost_per_seat_month_low and n.cost_per_seat_month_high
        assert n.cost_per_seat_month_low <= n.cost_per_seat_month_high
        assert any(a.name == "desks" and a.value == 25 for a in n.assumptions)
    # open plan is cheaper at both ends (ranges overlap because furniture costs the same)
    assert open_plan.fitout_cost_low < shell.fitout_cost_low and open_plan.fitout_cost_high < shell.fitout_cost_high
    assert open_plan.cost_per_seat_month_high < shell.cost_per_seat_month_high
    # rent compared with nearby office listings, each one cited
    comp = next(a for a in unknown.assumptions if a.name == "nearby_office_rent_median")
    assert comp.source == "costar"
    assert sum(1 for c in unknown.citations if "comparable office listing" in (c.note or "")) >= 1  # 2 LA office samples
    # full-service sample rent: nothing added on top
    assert next(a for a in unknown.assumptions if a.name == "opex_on_top_of_rent").value == "$0–$0"
    email = draft_broker_email(s, OFFICE_BRIEF)
    assert "team of 25" in email and "grease trap" not in email and "full-service" in email


def test_office_layout_desks_override_brief(sample_db):
    from agent.analyst.costs import estimate_costs
    from pipeline.queries import get_space

    s = get_space("sample-la-office-15")
    items = [LayoutItem(item_id=str(i), item_type=t, glb_asset="assets/glb/x.glb", room_id="r", x_m=0, z_m=0,
                        width_m=1, depth_m=1, height_m=1, seats=1 if t == "single_desk" else 0)
             for i, t in enumerate(["reception_desk", "meeting_table", "kitchenette_counter"] + ["single_desk"] * 20)]
    lay = Layout(layout_id="o1", space_id=s.space_id, business_type="office", items=items, seat_count=20)
    n = estimate_costs(s, lay, None, OFFICE_BRIEF)
    assert any(a.name == "desks" and a.value == 20 for a in n.assumptions)
    assert any(a.name == "furniture_from_layout" for a in n.assumptions)
