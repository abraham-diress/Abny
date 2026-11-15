"""Brief parsing (contract: parse_brief) and feedback handling for the re-plan loop.

parse_brief(text) -> Brief
    LLM structured output when credentials exist; a deterministic regex parser otherwise
    (and as a fallback if the LLM call fails). Both return a schema-valid Brief.

apply_feedback(brief, feedback) -> (new_brief, restart_stage)
    Appends to feedback_history, updates the structured fields, and says where the
    funnel must restart: "scout" (location/rent/size changed) or "designer" (seats/style).
"""

from __future__ import annotations

import logging
import re
from typing import Literal, get_args

from pydantic import BaseModel, Field

from shared.schemas import Brief, BusinessType, City, Feedback

log = logging.getLogger(__name__)

SQFT_PER_M2 = 10.7639
Stage = Literal["scout", "inspector", "designer", "stager", "analyst"]

# Fields whose change invalidates the search itself vs. only the fit-out.
_SCOUT_FIELDS = ("business_type", "city", "area_hint", "sqft_min", "sqft_max", "max_rent_month", "must_haves", "nice_to_haves")
_DESIGN_FIELDS = ("seats_wanted", "style")


class _BriefFields(BaseModel):
    """What the LLM fills in (Brief minus bookkeeping fields)."""

    business_type: BusinessType = Field("bakery", description="Kind of business")
    city: City | None = Field(None, description="Only Houston or Los Angeles; null if not stated")
    area_hint: str | None = Field(None, description="Neighborhood or location preference, e.g. 'near downtown', 'close to transit'")
    seats_wanted: int | None = Field(None, description="Customer seats for food businesses; for offices the headcount (= desks)")
    sqft_min: float | None = Field(None, description="Minimum size in square feet (convert m² to sqft)")
    sqft_max: float | None = Field(None, description="Maximum size in square feet")
    max_rent_month: float | None = Field(None, description="Maximum rent in USD per month (convert yearly or per-sqft rent)")
    must_haves: list[str] = Field(default_factory=list, description="Hard requirements as short lowercase phrases, e.g. 'parking', 'existing kitchen'")
    nice_to_haves: list[str] = Field(default_factory=list, description="Soft preferences as short lowercase phrases")
    style: str | None = Field(None, description="Look and feel, e.g. 'warm artisan, wood and white tile'")


_SYSTEM = (
    "You turn a small-business owner's request for a commercial space into structured fields. "
    "Only fill what the owner actually said or clearly implied; leave everything else null/empty. "
    "Money is USD per month (convert '$72k/year' to 6000). Sizes are square feet (1 m² = 10.7639 sqft). "
    "Cities: only 'Houston' or 'Los Angeles' (LA, L.A. -> 'Los Angeles'); anything else -> null. "
    "Requirements like 'needs parking', 'near transit' or 'with natural light' go in must_haves; "
    "'ideally'/'would be nice' go in nice_to_haves. area_hint is only a neighborhood or street name "
    "(e.g. 'Montrose', 'downtown'), never a feature like transit or parking. "
    "Offices (a team, employees, desks, headquarters, workspace) -> business_type 'office' and the headcount "
    "('25-person team', 'team of 25') goes in seats_wanted."
)


def parse_brief(text: str) -> Brief:
    """Free text from the business owner -> structured Brief (raw_text always set)."""
    from agent.llm import llm_available

    if llm_available():
        try:
            return _parse_llm(text)
        except Exception as e:  # noqa: BLE001 - never block a run on the parser
            log.warning("LLM brief parse failed, using rules: %r", e)
    return parse_brief_rules(text)


def _parse_llm(text: str) -> Brief:
    from agent.llm import get_chat_model

    model = get_chat_model(fast=True, max_tokens=1024).with_structured_output(_BriefFields)
    fields: _BriefFields = model.invoke([("system", _SYSTEM), ("human", text)])  # type: ignore[assignment]
    b = Brief(raw_text=text, **fields.model_dump())
    # Cheap sanity merge: the rule parser is good at numbers, trust it when the LLM left a gap.
    rules = parse_brief_rules(text)
    for f in ("seats_wanted", "max_rent_month", "sqft_min", "sqft_max", "city"):
        if getattr(b, f) is None and getattr(rules, f) is not None:
            setattr(b, f, getattr(rules, f))
    # Requirements: the rule parser's names are the canonical ones the ranker scores, so they win;
    # anything extra the LLM understood is kept.
    for name in rules.must_haves:
        if name in b.nice_to_haves:
            b.nice_to_haves.remove(name)
        if name not in b.must_haves:
            b.must_haves.append(name)
    for name in rules.nice_to_haves:
        if name not in b.must_haves and name not in b.nice_to_haves:
            b.nice_to_haves.append(name)
    if b.area_hint and any(re.search(rx, b.area_hint, re.I) for rx in _FEATURES.values()):
        b.area_hint = rules.area_hint  # the LLM mistook a feature ("near transit") for a place
    return b


# --------------------------------------------------------------------------- #
# Deterministic parser (no network). Good enough for the demo prompts.
# --------------------------------------------------------------------------- #

_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(k|K|thousand)?"
_FEATURES = {
    "parking": r"\bparking\b",
    "near transit": r"\b(transit|metro|light rail|bus stop|subway|train)\b",
    "existing kitchen": r"\b(existing|built[- ]out|second[- ]generation|2nd[- ]gen)\s+(kitchen|restaurant)\b|\bkitchen\b",
    "vent hood": r"\b(vent|hood|exhaust)\b",
    "storefront glass": r"\b(storefront|street[- ]facing|big windows|window frontage)\b",
    "natural light": r"\b(natural light|daylight|lots of light|bright|lots of windows)\b",
    "open plan": r"\bopen[- ](plan|layout|floor)\b",
    "meeting room": r"\b(meeting|conference) rooms?\b",
    "private offices": r"\bprivate offices?\b",
    "kitchenette": r"\b(kitchenette|break ?room)\b",
    "amenities nearby": r"\b(amenities|lunch spots|places to eat|restaurants nearby|cafes nearby|gyms? nearby)\b",
    "restroom": r"\b(restroom|bathroom)\b",
    "outdoor seating": r"\b(patio|outdoor seating|sidewalk seating)\b",
    "foot traffic": r"\b(foot traffic|walkable|busy street)\b",
}
# Features that only make sense for food businesses (ignored in office briefs) and vice versa.
_FOOD_ONLY = {"existing kitchen", "vent hood", "storefront glass", "outdoor seating"}
_OFFICE_ONLY = {"open plan", "meeting room", "private offices", "kitchenette", "amenities nearby"}
_OFFICE = r"\b(office|offices|workspace|work space|headquarters|hq|coworking|desks?|employees|staff|team)\b"
_FOOD = r"\b(bakery|bakeries|cafe|café|coffee|restaurant|patisserie|pastry|diner|bar)\b"
_SOFT = r"\b(ideally|prefer|preferably|nice to have|would be nice|bonus|if possible)\b"


def _num(m: re.Match[str]) -> float:
    v = float(m.group(1).replace(",", ""))
    return v * 1000 if m.group(2) else v


def _business_type(t: str) -> str:
    # Offices first: "office near restaurants and gyms" must not become a restaurant.
    explicit_office = re.search(r"\boffices?\b|\bworkspace\b|\bheadquarters\b|\bhq\b|\bcoworking\b", t)
    if re.search(_OFFICE, t) and (explicit_office or not re.search(_FOOD, t)):
        return "office"
    for bt in get_args(BusinessType):
        if bt not in ("other", "office") and re.search(rf"\b{bt}s?\b", t):
            return bt
    aliases = {"café": "cafe", "coffee": "cafe", "patisserie": "bakery", "pastry": "bakery", "boutique": "retail",
               "shop": "retail", "store": "retail", "barber": "salon", "fitness": "gym"}
    return next((v for k, v in aliases.items() if k in t), "bakery")


def parse_brief_rules(text: str) -> Brief:
    t = text.lower()
    b = Brief(raw_text=text)

    # Offices first: "office near restaurants and gyms" must not become a restaurant.
    b.business_type = _business_type(t)  # type: ignore[assignment]

    if re.search(r"\bhouston\b|\bhtx\b", t):
        b.city = "Houston"
    elif re.search(r"\blos angeles\b|\bl\.?a\.?\b", t):
        b.city = "Los Angeles"

    # Seats, or headcount for offices: "20 seats", "25-person team", "team of 25", "30 desks", "12 employees".
    if m := re.search(r"(\d+)\s*(?:-\s*\d+\s*)?[- ]?(?:seats?|covers|people|persons?|guests|seater|desks?|employees|"
                      r"staff|workers|members|headcount)\b", t) or re.search(r"\b(?:team|staff|crew|group) of (\d+)", t):
        b.seats_wanted = int(m.group(1))

    # Rent: "under $6k/month", "max 6000 a month", "$72k/yr", "budget 5,500".
    for m in re.finditer(r"(?:under|below|less than|max(?:imum)?|up to|budget(?: of| is)?|<|at most)?\s*\$\s*" + _NUM
                         + r"\s*(/|per|a)?\s*(month|mo|year|yr)?", t):
        v = _num(m)
        if v < 200:  # "$6" is noise, "$40/sqft" handled below
            continue
        if m.group(4) in {"year", "yr"}:
            v /= 12
        b.max_rent_month = round(v, 2)
        break
    if b.max_rent_month is None and (m := re.search(r"(?:budget|rent)[^\d$]{0,20}" + _NUM, t)):
        b.max_rent_month = _num(m)

    # Size: "1,200-1,800 sqft", "at least 1000 sq ft", "120 m2".
    unit = r"\s*(sq\.?\s*ft|sqft|square feet|sf|m2|m²|sqm|square meters)"
    if m := re.search(_NUM + r"\s*(?:-|to)\s*" + _NUM + unit, t):
        lo, hi = float(m.group(1).replace(",", "")), float(m.group(3).replace(",", ""))
        k = SQFT_PER_M2 if m.group(5).startswith(("m", "sqm", "square m")) else 1
        b.sqft_min, b.sqft_max = lo * k, hi * k
    elif m := re.search(r"(at least|min(?:imum)?|over|more than|under|max(?:imum)?|less than|up to|around|about|~)?\s*" + _NUM + unit, t):
        v = float(m.group(2).replace(",", "")) * (1000 if m.group(3) else 1)
        v *= SQFT_PER_M2 if m.group(4).startswith(("m", "sqm", "square m")) else 1
        q = m.group(1) or "around"
        if q in {"under", "max", "maximum", "less than", "up to"}:
            b.sqft_max = v
        elif q in {"at least", "min", "minimum", "over", "more than"}:
            b.sqft_min = v
        else:
            b.sqft_min, b.sqft_max = v * 0.8, v * 1.25

    # Requirements: split into clauses so "ideally near transit" lands in nice_to_haves.
    for clause in re.split(r"[,;.]|\band\b|\bbut\b", t):
        soft = bool(re.search(_SOFT, clause))
        for name, pat in _FEATURES.items():
            if name in (_FOOD_ONLY if b.business_type == "office" else _OFFICE_ONLY):
                continue
            if re.search(pat, clause):
                target = b.nice_to_haves if soft else b.must_haves
                if name not in b.must_haves and name not in b.nice_to_haves:
                    target.append(name)

    if m := re.search(r"\b(?:near|close to|in|around)\s+(downtown|midtown|the heights|heights|montrose|east end|"
                      r"upper kirby|washington|echo park|highland park|boyle heights|transit|the university)\b", t):
        b.area_hint = m.group(0)

    if m := re.search(r"\b(?:style|vibe|feel|look)\b[^,.;]*|\b(?:warm|cozy|minimal|modern|rustic|industrial|"
                      r"scandinavian|french|artisan|bright)\b[^,.;]*", t):
        style = re.split(r"\s(?:in|near|with|for|at|under|around)\s|\$|\d", m.group(0))[0]
        style = re.sub(r"\b(?:bakery|cafe|café|coffee shop|restaurant|salon|shop|store|place)\b", "", style)
        style = re.sub(r"\s+", " ", style).strip(" -")
        b.style = style or None
    return b


# --------------------------------------------------------------------------- #
# Feedback -> updated brief + restart stage
# --------------------------------------------------------------------------- #


class _FeedbackUpdate(BaseModel):
    updated: _BriefFields
    reason: str = Field("", description="One short sentence: what changed and why")


def apply_feedback(brief: Brief, fb: Feedback) -> tuple[Brief, Stage | None]:
    """Return (new brief, stage to restart at). Stage None = nothing changed beyond the history."""
    from agent.llm import llm_available

    new = brief.model_copy(deep=True)
    new.feedback_history.append(fb)

    updated: Brief | None = None
    if fb.kind != "reject" and llm_available():
        try:
            updated = _feedback_llm(brief, fb)
        except Exception as e:  # noqa: BLE001
            log.warning("LLM feedback parse failed, using rules: %r", e)
    if updated is None and fb.kind != "reject":
        updated = _feedback_rules(brief, fb.text)
    if updated is not None:
        for f in _SCOUT_FIELDS + _DESIGN_FIELDS:
            setattr(new, f, getattr(updated, f))

    stage = restart_stage(brief, new)
    if fb.kind == "reject" and stage is None:
        stage = "scout"  # re-rank without the rejected space; caches make this cheap
    return new, stage


def restart_stage(old: Brief, new: Brief) -> Stage | None:
    if any(getattr(old, f) != getattr(new, f) for f in _SCOUT_FIELDS):
        return "scout"
    if any(getattr(old, f) != getattr(new, f) for f in _DESIGN_FIELDS):
        return "designer"
    return None


def _feedback_llm(brief: Brief, fb: Feedback) -> Brief:
    from agent.llm import get_chat_model

    current = brief.model_dump(include=set(_SCOUT_FIELDS + _DESIGN_FIELDS))
    model = get_chat_model(fast=True, max_tokens=1024).with_structured_output(_FeedbackUpdate)
    out: _FeedbackUpdate = model.invoke([  # type: ignore[assignment]
        ("system", _SYSTEM + " You are UPDATING an existing brief with the owner's feedback. Keep every field "
         "the feedback doesn't touch exactly as it is. Relative changes ('fewer seats') mean about 25% less."),
        ("human", f"Current brief: {current}\n\nFeedback: {fb.text}"),
    ])
    return Brief(raw_text=brief.raw_text, **out.updated.model_dump())


def _feedback_rules(brief: Brief, text: str) -> Brief:
    t = text.lower()
    b = brief.model_copy(deep=True)
    parsed = parse_brief_rules(text)
    # Absolute values in the feedback win.
    for f in ("city", "seats_wanted", "max_rent_month", "sqft_min", "sqft_max", "style"):
        if getattr(parsed, f) is not None:
            setattr(b, f, getattr(parsed, f))
    if re.search(r"\b(bakery|cafe|café|coffee|restaurant|retail|salon|clinic)\b", t) and not re.search(r"\bnear|close to\b", t):
        b.business_type = parsed.business_type
    elif re.search(r"\b(office|workspace|headquarters)\b", t):
        b.business_type = "office"
    # Relative changes.
    seats = b.seats_wanted or 20
    if parsed.seats_wanted is None:
        if re.search(r"\b(fewer|less|smaller|reduce)\b.*\b(seats?|desks?|people|team)\b|\bfewer\b|\bsmaller team\b", t):
            b.seats_wanted = max(2, round(seats * 0.75))
        elif re.search(r"\b(more|extra|bigger)\b.*\b(seats?|desks?|people|team)\b|\bteam is growing\b", t):
            b.seats_wanted = round(seats * 1.25)
    if parsed.max_rent_month is None and re.search(r"\b(cheaper|lower rent|less expensive|too expensive)\b", t):
        b.max_rent_month = round((b.max_rent_month or 6000) * 0.85)
    if re.search(r"\b(bigger|larger|more space)\b", t) and "seat" not in t:
        b.sqft_min = round((b.sqft_min or 1200) * 1.2)
    for name in parsed.must_haves:
        if name not in b.must_haves:
            b.must_haves.append(name)
    for name in parsed.nice_to_haves:
        if name not in b.nice_to_haves and name not in b.must_haves:
            b.nice_to_haves.append(name)
    if m := re.search(r"\b(?:closer to|near|close to|in)\s+([a-z ]+?)(?:$|[,.;]|\band\b)", t):
        b.area_hint = m.group(0).strip(" ,.;")
    return b
