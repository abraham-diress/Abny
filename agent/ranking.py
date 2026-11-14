"""Ranking: one 0-1 score per space plus human-readable reasons (every reason names its source).

Food businesses (bakery, cafe, ...) - weights sum to 1:
    neighborhood 0.30 · budget 0.25 · size/seats 0.15 · building (kitchen, glass) 0.15 · fit-out 0.15
Offices (score_office) - weights sum to 1:
    transit 0.20 · budget 0.20 · neighborhood 0.15 · amenities 0.10 · size/desk 0.10 · daylight+build-out 0.15 · fit/cost per desk 0.10
Must-haves add or subtract on top (parking, transit, kitchen, ...), then the score is clamped to 0..1.
Stages that haven't run yet count as neutral (0.5) so early and late rankings are comparable.
"""

from __future__ import annotations

from shared.schemas import Brief, Inspection, Layout, NeighborhoodProfile, Numbers, Space, ValidationReport

SQFT_PER_SEAT = 30.0  # rough front-of-house + back-of-house need for a bakery/cafe
SQFT_PER_DESK = 150.0  # typical open-plan office including circulation, meeting and support space
TRANSIT_NEAR_M = 500
AMENITY_WALK_M = 400


def _money(v: float) -> str:
    return f"${v:,.0f}"


def wants(brief: Brief, *words: str) -> bool:
    text = " ".join(brief.must_haves + brief.nice_to_haves + [brief.area_hint or ""]).lower()
    return any(w in text for w in words)


def score_space(
    brief: Brief,
    space: Space,
    nb: NeighborhoodProfile | None = None,
    insp: Inspection | None = None,
    layout: Layout | None = None,
    validation: ValidationReport | None = None,
    numbers: Numbers | None = None,
) -> tuple[float, list[str]]:
    if brief.business_type == "office":
        return score_office(brief, space, nb, insp, layout, validation, numbers)
    reasons: list[tuple[float, str]] = []  # (impact, text) -> sorted by impact for display

    # Neighborhood (Data Engine's 0-1 score)
    s_nb = nb.score if nb else 0.5
    if nb:
        txt = f"Neighborhood fit {nb.score:.2f}: {nb.nearby_tenant_count} businesses and {nb.nearby_residential_units:,} homes nearby (CoStar)"
        if nb.competitors:
            close = min(c.distance_m for c in nb.competitors)
            txt += f"; {len(nb.competitors)} competitor(s), closest {close:.0f} m"
        reasons.append((abs(nb.score - 0.5), txt))

    s_budget = _budget(brief, space, numbers, reasons)

    # Size / seats
    s_size = 0.5
    if space.sqft:
        lo = brief.sqft_min or (brief.seats_wanted * SQFT_PER_SEAT if brief.seats_wanted else None)
        hi = brief.sqft_max
        if lo and space.sqft < lo:
            s_size = max(0.0, space.sqft / lo)
            reasons.append((0.25, f"{space.sqft:,.0f} sqft may be tight (you need about {lo:,.0f})"))
        elif hi and space.sqft > hi:
            s_size = max(0.0, 1 - (space.sqft - hi) / hi)
            reasons.append((0.15, f"{space.sqft:,.0f} sqft is larger than you asked for"))
        else:
            s_size = 1.0
            reasons.append((0.1, f"{space.sqft:,.0f} sqft fits your size needs"))

    # Building (inspection)
    s_bld = 0.5
    if insp:
        pts, found = 0.5, []
        if insp.existing_kitchen:
            pts += 0.25
            found.append("an existing kitchen (cuts fit-out cost)")
        if insp.vent_hood:
            pts += 0.1
            found.append("a vent hood")
        if insp.storefront_glass:
            pts += 0.1
            found.append("storefront glass")
        if insp.existing_restroom:
            pts += 0.05
            found.append("a restroom")
        if insp.storefront_glass is False:
            pts -= 0.15
        s_bld = min(1.0, pts)
        if found:
            reasons.append((pts - 0.5, "3D scan shows " + ", ".join(found) + " (Matterport)"))

    # Fit-out (layout + validation + image)
    s_fit = 0.5
    if layout:
        want = brief.seats_wanted or layout.seat_count or 1
        s_fit = min(1.0, layout.seat_count / want) if want else 1.0
        if validation and not validation.passed:
            s_fit *= 0.4
            reasons.append((0.3, f"Layout has {len(validation.violations)} problem(s) to fix"))
        else:
            reasons.append((0.2, f"Fits {layout.seat_count} of {want} seats in a layout that passes all checks"))

    # 0.85 leaves headroom so must-have bonuses still separate the top spaces.
    score = 0.85 * (0.30 * s_nb + 0.25 * s_budget + 0.15 * s_size + 0.15 * s_bld + 0.15 * s_fit)

    # Must-haves / nice-to-haves.
    weight = {True: 0.08, False: 0.04}
    if nb and wants(brief, "parking"):
        hard = "parking" in " ".join(brief.must_haves)
        if nb.parking_score is not None:
            delta = (nb.parking_score - 0.5) * 2 * weight[hard]
            score += delta
            reasons.append((abs(delta) + 0.1, f"Parking score {nb.parking_score:.2f}"
                            + (f": {nb.parking_notes}" if nb.parking_notes else "") + " (Vexcel aerial)"))
    if nb and wants(brief, "transit", "metro", "rail", "bus"):
        hard = any(w in " ".join(brief.must_haves) for w in ("transit", "metro"))
        near = [t for t in nb.transit if t.distance_m <= TRANSIT_NEAR_M]
        if near:
            score += weight[hard] + 0.04  # feedback demo: "closer to transit" visibly re-ranks
            t = min(near, key=lambda t: t.distance_m)
            reasons.append((0.5, f"{t.name} is {t.distance_m:.0f} m away (transit)"))
        else:
            score -= weight[hard]
            reasons.append((0.35, f"No transit stop within {TRANSIT_NEAR_M} m"))
    if insp and wants(brief, "kitchen") and insp.existing_kitchen is False:
        score -= 0.08
    score += _area_bonus(brief, space, reasons)
    if numbers and numbers.breakeven_months_low is not None:
        hi = numbers.breakeven_months_high
        span = f"{numbers.breakeven_months_low:.0f}-{hi:.0f}" if hi is not None else f"{numbers.breakeven_months_low:.0f}+"
        reasons.append((0.15, f"Break-even in about {span} months (estimate, see assumptions)"))

    return _finish(score, reasons)


_AREA_STOP = {"in", "near", "close", "to", "closer", "the", "around", "by", "area", "transit", "amenities", "a", "of"}


def _area_bonus(brief: Brief, space: Space, reasons: list[tuple[float, str]]) -> float:
    """'near downtown' / 'in Montrose': small bonus when the space's address names that area."""
    words = [w for w in (brief.area_hint or "").lower().replace(",", " ").split() if w not in _AREA_STOP]
    if words and all(w in space.address.lower() for w in words):
        reasons.append((0.3, f"In {' '.join(words).title()}, the area you asked for (CoStar address)"))
        return 0.06
    return 0.0


def _finish(score: float, reasons: list[tuple[float, str]]) -> tuple[float, list[str]]:
    reasons.sort(key=lambda r: -r[0])
    return round(max(0.0, min(1.0, score)), 3), [r for _, r in reasons[:6]]


def _budget(brief: Brief, space: Space, numbers: Numbers | None, reasons: list[tuple[float, str]]) -> float:
    rent = (numbers.rent_month if numbers and numbers.rent_month else None) or space.asking_rent_month
    if rent and brief.max_rent_month:
        diff = brief.max_rent_month - rent
        if diff >= 0:
            reasons.append((0.3, f"Rent {_money(rent)}/mo is {_money(diff)} under your {_money(brief.max_rent_month)} budget (CoStar listing)"))
            return 1.0
        reasons.append((0.4, f"Rent {_money(rent)}/mo is {_money(-diff)} over budget (CoStar listing)"))
        return max(0.0, 1 + 2 * diff / brief.max_rent_month)
    if rent:
        reasons.append((0.05, f"Asking rent {_money(rent)}/mo (CoStar listing)"))
    return 0.5


def score_office(
    brief: Brief,
    space: Space,
    nb: NeighborhoodProfile | None = None,
    insp: Inspection | None = None,
    layout: Layout | None = None,
    validation: ValidationReport | None = None,
    numbers: Numbers | None = None,
) -> tuple[float, list[str]]:
    """Offices: transit, amenities, daylight and cost per desk matter; competitors don't."""
    reasons: list[tuple[float, str]] = []

    s_nb = nb.score if nb else 0.5
    s_transit = s_amen = 0.5
    if nb:
        if nb.transit:
            t = min(nb.transit, key=lambda t: t.distance_m)
            s_transit = max(0.0, min(1.0, (1000 - t.distance_m) / 700))  # 1 at <=300 m, 0 at 1 km
            reasons.append((0.25 + s_transit * 0.2, f"{t.name} is {t.distance_m:.0f} m away (transit)"))
        else:
            s_transit = 0.0
            reasons.append((0.4, "No transit stop nearby"))
        near = [a for a in nb.amenities if a.distance_m <= AMENITY_WALK_M]
        s_amen = min(1.0, len(near) / 4)
        if near:
            reasons.append((0.2, f"{len(near)} lunch/coffee/gym spots within a 5-minute walk, e.g. {near[0].name} (CoStar)"))
        if nb.nearby_employees_est:
            reasons.append((0.05, f"About {nb.nearby_employees_est:,} people work nearby (CoStar)"))

    s_budget = _budget(brief, space, numbers, reasons)

    s_size = 0.5
    desks = brief.seats_wanted
    if space.sqft and desks:
        per = space.sqft / desks
        if per < SQFT_PER_DESK * 0.8:
            s_size = max(0.0, per / SQFT_PER_DESK)
            reasons.append((0.3, f"{space.sqft:,.0f} sqft is tight for {desks} people ({per:.0f} sqft/person)"))
        elif per > SQFT_PER_DESK * 2:
            s_size = max(0.0, 1 - (per - SQFT_PER_DESK * 2) / (SQFT_PER_DESK * 2))
            reasons.append((0.15, f"{space.sqft:,.0f} sqft is roomy for {desks} people (room to grow)"))
        else:
            s_size = 1.0
            reasons.append((0.1, f"{space.sqft:,.0f} sqft fits {desks} people ({per:.0f} sqft/person)"))

    s_bld = 0.5
    if insp:
        light = insp.natural_light if insp.natural_light is not None else 0.5
        build = {"open plan": 1.0, "mixed offices": 0.7, "private offices": 0.55, "shell": 0.4}.get(
            insp.existing_build_out or "", 0.5)
        s_bld = 0.6 * light + 0.4 * build
        if insp.natural_light is not None:
            word = "lots of" if light >= 0.7 else "some" if light >= 0.4 else "little"
            reasons.append((abs(light - 0.5) + 0.1, f"3D scan shows {word} daylight ({light:.2f}) (Matterport)"))
        if insp.existing_build_out:
            reasons.append((0.15, f"Already built as {insp.existing_build_out} (Matterport)"))
        if insp.existing_restroom is False:
            s_bld -= 0.1

    s_fit = 0.5
    if layout:
        want = desks or layout.seat_count or 1
        s_fit = min(1.0, layout.seat_count / want)
        if validation and not validation.passed:
            s_fit *= 0.4
            reasons.append((0.3, f"Layout has {len(validation.violations)} problem(s) to fix"))
        else:
            reasons.append((0.2, f"Fits {layout.seat_count} of {want} desks in a layout that passes all checks"))
    if numbers and numbers.cost_per_seat_month_low is not None and numbers.cost_per_seat_month_high is not None:
        reasons.append((0.35, f"About {_money(numbers.cost_per_seat_month_low)}-{_money(numbers.cost_per_seat_month_high)} "
                              f"per desk per month incl. fit-out (estimate, see assumptions)"))

    score = 0.85 * (0.20 * s_transit + 0.20 * s_budget + 0.15 * s_nb + 0.10 * s_amen + 0.10 * s_size
                    + 0.15 * s_bld + 0.10 * s_fit)
    if nb and wants(brief, "parking") and nb.parking_score is not None:
        score += (nb.parking_score - 0.5) * 0.1
        reasons.append((0.15, f"Parking score {nb.parking_score:.2f}" + (f": {nb.parking_notes}" if nb.parking_notes else "")))
    if wants(brief, "transit", "metro") and s_transit >= 0.7:
        score += 0.06
    if wants(brief, "amenit") and s_amen >= 0.5:
        score += 0.04
    if insp and wants(brief, "light", "daylight") and (insp.natural_light or 0) >= 0.7:
        score += 0.04
    score += _area_bonus(brief, space, reasons)
    return _finish(score, reasons)
