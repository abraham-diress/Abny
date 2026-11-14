import pytest

from agent.brief import apply_feedback, parse_brief_rules, restart_stage
from shared.schemas import Feedback

CASES = [
    ("Second bakery location in Houston, ~20 seats, under $6k/month, needs parking",
     dict(business_type="bakery", city="Houston", seats_wanted=20, max_rent_month=6000), ["parking"]),
    ("bakery in Houston, 20 seats, under $6k",
     dict(business_type="bakery", city="Houston", seats_wanted=20, max_rent_month=6000), []),
    ("Cozy café in LA near Echo Park, 1,000-1,400 sqft, budget $72k/year, ideally near transit",
     dict(business_type="cafe", city="Los Angeles", sqft_min=1000, sqft_max=1400, max_rent_month=6000), []),
    ("I want to open a salon in Houston with at least 900 sq ft and max $4,500 a month, street-facing storefront",
     dict(business_type="salon", city="Houston", sqft_min=900, max_rent_month=4500), ["storefront glass"]),
    ("Restaurant with an existing kitchen and vent hood in Houston, 40 seats, up to $9,000/mo, warm industrial look",
     dict(business_type="restaurant", city="Houston", seats_wanted=40, max_rent_month=9000), ["existing kitchen", "vent hood"]),
    # Offices: headcount -> seats_wanted (= desks)
    ("Office for a 25-person team in downtown LA, near transit, under $20k/month",
     dict(business_type="office", city="Los Angeles", seats_wanted=25, max_rent_month=20000), ["near transit"]),
    ("We need a workspace in Houston for a team of 12, open plan, lots of natural light, budget $9,000/mo",
     dict(business_type="office", city="Houston", seats_wanted=12, max_rent_month=9000), ["open plan", "natural light"]),
]


@pytest.mark.parametrize("text,expected,must", CASES)
def test_rule_parser(text, expected, must):
    b = parse_brief_rules(text)
    assert b.raw_text == text
    for k, v in expected.items():
        assert getattr(b, k) == pytest.approx(v) if isinstance(v, float | int) else getattr(b, k) == v, k
    assert b.must_haves == must


def test_nice_to_have_goes_soft():
    b = parse_brief_rules(CASES[2][0])
    assert "near transit" in b.nice_to_haves and "near transit" not in b.must_haves


def test_feedback_fewer_seats_closer_to_transit(monkeypatch):
    monkeypatch.setattr("agent.llm.llm_available", lambda: False)
    b = parse_brief_rules("bakery in Houston, 20 seats, under $6k")
    new, stage = apply_feedback(b, Feedback(text="fewer seats, closer to transit"))
    assert new.seats_wanted == 15
    assert "near transit" in new.must_haves
    assert stage == "scout"  # location changed -> restart the search
    assert len(new.feedback_history) == 1 and b.feedback_history == []


def test_restart_stage_seats_only():
    a = parse_brief_rules("bakery in Houston, 20 seats")
    b = a.model_copy(update={"seats_wanted": 12})
    assert restart_stage(a, b) == "designer"
    assert restart_stage(a, a) is None


def test_office_near_restaurants_stays_office():
    b = parse_brief_rules("Office for 30 employees in Houston near restaurants and gyms")
    assert b.business_type == "office" and b.seats_wanted == 30
    assert "existing kitchen" not in b.must_haves


def test_office_feedback_fewer_desks(monkeypatch):
    monkeypatch.setattr("agent.llm.llm_available", lambda: False)
    b = parse_brief_rules(CASES[5][0])
    new, stage = apply_feedback(b, Feedback(text="fewer desks"))
    assert new.business_type == "office" and new.seats_wanted == 19 and stage == "designer"
