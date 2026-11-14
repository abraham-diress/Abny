"""Analyst contract functions (owner: Natnael): estimate_costs, draft_broker_email.

    from agent.analyst.costs import estimate_costs, draft_broker_email

Pure arithmetic over the Space/Layout/Inspection/Brief plus benchmarks in
agent/analyst/benchmarks.py; every input becomes an `Assumption` or a `Citation`.
Ranges: *_low = pessimistic revenue / cheap fit-out, *_high = optimistic revenue / expensive fit-out.
Break-even: low = best case (cheap fit-out, strong sales), high = worst case; None = never at that end.
Offices (brief.business_type == "office"): no revenue or break-even; cost per desk per month
(cost_per_seat_month_*) and a comparison with nearby office listings instead.
"""

from __future__ import annotations

import math

from shared.schemas import Assumption, Brief, Citation, Inspection, Layout, Numbers, Space

from agent.analyst import benchmarks as B

FOOD = {"bakery", "cafe", "restaurant"}


def _bt(brief: Brief, table: dict) -> str:
    return brief.business_type if brief.business_type in table else "other"


def _rent(space: Space, assumptions: list[Assumption], cites: list[Citation], sqft: float) -> float | None:
    if space.asking_rent_month:
        cites.extend(c for c in space.citations if c.field in ("asking_rent_month", "rent_per_sqft_year"))
        return space.asking_rent_month
    if space.rent_per_sqft_year:
        cites.extend(c for c in space.citations if c.field == "rent_per_sqft_year")
        return space.rent_per_sqft_year * sqft / 12
    try:  # no asking rent (broker mode): CoStar market median for the city/type
        from pipeline.queries import market_rent_psf_year
        m = market_rent_psf_year(space.city, space.property_type)
    except Exception:
        m = None
    if m:
        psf, n = m
        assumptions.append(Assumption(name="market_rent_psf_year", value=round(psf, 2), unit="$/sqft/yr", source="costar",
                                      note=f"No asking rent on this listing; median of {n} CoStar listings in {space.city or 'market'}"))
        return psf * sqft / 12
    return None


def _fitout(space: Space, layout: Layout | None, inspection: Inspection | None, brief: Brief, sqft: float,
            assumptions: list[Assumption], cites: list[Citation]) -> tuple[float, float]:
    bt = _bt(brief, B.FITOUT_PSF)
    kitchen = inspection.existing_kitchen if inspection else None
    if kitchen is True:
        lo_psf, hi_psf = B.FITOUT_PSF[bt]["second_gen"]
        basis = "existing kitchen seen in panoramas (second-generation space)"
        cites.extend(c for c in (inspection.citations if inspection else []) if c.field in (None, "existing_kitchen"))
    elif kitchen is False:
        lo_psf, hi_psf = B.FITOUT_PSF[bt]["raw"]
        basis = "no existing kitchen seen: full build-out"
    else:  # unknown: span both
        lo_psf, hi_psf = B.FITOUT_PSF[bt]["second_gen"][0], B.FITOUT_PSF[bt]["raw"][1]
        basis = "kitchen not verified: range spans second-gen to full build-out"
    if brief.business_type not in FOOD:
        basis = "standard tenant improvement"
    assumptions.append(Assumption(name="fitout_psf_low", value=lo_psf, unit="$/sqft", note=f"{basis}. {B.FITOUT_NOTE}"))
    assumptions.append(Assumption(name="fitout_psf_high", value=hi_psf, unit="$/sqft", note=basis))
    build_lo, build_hi = lo_psf * sqft, hi_psf * sqft

    # Equipment: from the layout's items if we have one, else a starter package.
    if layout and layout.items:
        eq_lo = eq_hi = 0.0
        counts: dict[str, int] = {}
        for it in layout.items:
            lo, hi = B.ITEM_COST.get(it.item_type, B.DEFAULT_ITEM_COST)
            eq_lo += lo
            eq_hi += hi
            counts[it.item_type] = counts.get(it.item_type, 0) + 1
        summary = ", ".join(f"{n}× {t}" for t, n in sorted(counts.items()))
        assumptions.append(Assumption(name="equipment_from_layout", value=f"${eq_lo:,.0f}–${eq_hi:,.0f}", unit="USD",
                                      source="model", note=f"{summary}. {B.EQUIPMENT_NOTE}"))
    else:
        eq_lo, eq_hi = B.EQUIPMENT_PACKAGE.get(brief.business_type, B.EQUIPMENT_PACKAGE["other"])
        assumptions.append(Assumption(name="equipment_package", value=f"${eq_lo:,.0f}–${eq_hi:,.0f}", unit="USD",
                                      note=f"No layout yet: typical starter package. {B.EQUIPMENT_NOTE}"))

    hood_lo = hood_hi = 0.0
    # Second-gen $/sqft already assumes the hood is reused, so only credit a hood when there's no full kitchen.
    if brief.business_type in FOOD and inspection and inspection.vent_hood is True and kitchen is not True:
        hood_lo, hood_hi = B.VENT_HOOD_COST
        assumptions.append(Assumption(name="vent_hood_savings", value=f"${hood_lo:,.0f}–${hood_hi:,.0f}", unit="USD",
                                      source="model", note="Existing hood seen in panoramas; install cost avoided"))

    pct = B.CONTINGENCY_PCT + B.SOFT_COSTS_PCT
    assumptions.append(Assumption(name="contingency_and_soft_costs", value=pct, unit="share of hard costs",
                                  note="10% contingency + 8% design/permits"))
    low = max(0.0, (build_lo + eq_lo) * (1 + pct) - hood_hi)
    high = max(low, (build_hi + eq_hi) * (1 + pct) - hood_lo)
    return round(low, -2), round(high, -2)


def _revenue(layout: Layout | None, brief: Brief, assumptions: list[Assumption]) -> tuple[float, float, int]:
    bt = _bt(brief, B.REVENUE)
    r = B.REVENUE[bt]
    seats = (layout.seat_count if layout and layout.seat_count else None) or brief.seats_wanted or 0
    seat_src = "layout" if layout and layout.seat_count else ("brief" if brief.seats_wanted else "none")
    (t_lo, t_hi), (s_lo, s_hi), (c_lo, c_hi), days = r["ticket"], r["turns_per_seat"], r["counter_tx"], r["days"]
    assumptions += [
        Assumption(name="seats", value=seats, source="model" if seat_src == "layout" else "user",
                   note=f"from the {seat_src}" if seat_src != "none" else "no seats planned"),
        Assumption(name="avg_ticket", value=f"${t_lo}–${t_hi}", unit="USD", note=B.REVENUE_NOTE),
        Assumption(name="seat_turns_per_day", value=f"{s_lo}–{s_hi}"),
        Assumption(name="counter_transactions_per_day", value=f"{c_lo}–{c_hi}", note="takeout / walk-in, no seat"),
        Assumption(name="open_days_per_month", value=days),
    ]
    # Combine traffic and ticket uncertainty root-sum-square instead of stacking all-worst x all-worst.
    tx_lo, tx_hi = seats * s_lo + c_lo, seats * s_hi + c_hi
    tx_mid, t_mid = (tx_lo + tx_hi) / 2, (t_lo + t_hi) / 2
    rel = math.hypot((tx_hi - tx_lo) / (2 * tx_mid) if tx_mid else 0, (t_hi - t_lo) / (2 * t_mid))
    mid = tx_mid * t_mid * days
    assumptions.append(Assumption(name="revenue_month_base", value=round(mid, -2), unit="USD/month", source="model",
                                  note=f"{tx_mid:.0f} transactions/day × ${t_mid:.2f} × {days} days; "
                                       f"range ±{rel:.0%} combines traffic and ticket uncertainty"))
    return round(mid * (1 - rel), -2), round(mid * (1 + rel), -2), mid


def _build_out_kind(inspection: Inspection | None) -> str:
    text = ((inspection.existing_build_out if inspection else None) or "").lower()
    if not text:
        return "unknown"
    if "open" in text:
        return "open_plan"
    if "private" in text or "offices" in text:
        return "private_offices"
    if "shell" in text or "raw" in text or "cold dark" in text or "gray" in text or "grey" in text:
        return "shell"
    return "other"


def _service_kind(space: Space) -> tuple[str, str | None]:
    """Rent basis from the listing: full_service | modified_gross | net | unknown (+ the raw label)."""
    try:
        from pipeline.queries import listing_details
        d = listing_details(space.space_id)
    except Exception:
        d = {}
    label = d.get("service_type") or ""
    note = " ".join(c.note or "" for c in space.citations if c.field == "asking_rent_month")
    t = f"{label} {note}".lower()
    if "full service" in t or "fullservice" in t or "gross" in t and "modified" not in t:
        return "full_service", label or None
    if "modified" in t or "plus electric" in t or "plus utilities" in t:
        return "modified_gross", label or None
    if "net" in t or "nnn" in t:
        return "net", label or None
    return "unknown", label or None


def _office_rent_comps(space: Space, rent_psf_year: float | None, assumptions: list[Assumption],
                       cites: list[Citation]) -> None:
    """Compare the asking rent with nearby office listings and cite each comp."""
    try:
        from pipeline.queries import rent_comps
        comps = rent_comps(space.space_id)
    except Exception:
        comps = []
    if not comps:
        return
    psfs = sorted(c["rent_per_sqft_year"] for c in comps)
    median = psfs[len(psfs) // 2] if len(psfs) % 2 else (psfs[len(psfs) // 2 - 1] + psfs[len(psfs) // 2]) / 2
    vs = ""
    if rent_psf_year:
        diff = (rent_psf_year - median) / median
        vs = f"this space ${rent_psf_year:,.2f} is {abs(diff):.0%} {'above' if diff > 0 else 'below'} the median; "
    assumptions.append(Assumption(
        name="nearby_office_rent_median", value=round(median, 2), unit="$/sqft/yr", source="costar",
        note=f"{vs}median of {len(comps)} office listings {comps[0]['scope']}. Service types differ (gross vs net), "
             "so treat this as a rough comparison"))
    for c in comps:
        cites.append(Citation(source="costar", dataset=c.get("src_dataset"), record_id=c.get("src_record_id"),
                              field="rent_per_sqft_year", value=round(c["rent_per_sqft_year"], 2),
                              note=f"comparable office listing: {c['address']}, {c['distance_m']:,.0f} m away"
                                   + (f", {c['service_type']}" if c.get("service_type") else "")))


def _estimate_office(space: Space, layout: Layout | None, inspection: Inspection | None, brief: Brief) -> Numbers:
    """Offices: fit-out, cost per desk per month, rent vs nearby office listings. No revenue / break-even."""
    assumptions: list[Assumption] = []
    cites: list[Citation] = []

    sqft = space.sqft
    if not sqft:
        sqft = brief.seats_wanted * B.SQFT_PER_DESK if brief.seats_wanted else B.DEFAULT_SQFT
        assumptions.append(Assumption(name="sqft", value=sqft, unit="sqft", note="Listing has no size; estimated from the desk count"))
    else:
        cites.extend(c for c in space.citations if c.field == "sqft")

    if layout and layout.seat_count:
        desks, desk_src = layout.seat_count, "model"
        desk_note = "desks placed in the layout"
    elif brief.seats_wanted:
        desks, desk_src = brief.seats_wanted, "user"
        desk_note = "headcount from the brief"
    else:
        desks, desk_src = max(1, round(sqft / B.SQFT_PER_DESK)), "assumption"
        desk_note = f"no headcount given: ~{B.SQFT_PER_DESK} sqft per desk"
    assumptions.append(Assumption(name="desks", value=desks, source=desk_src, note=desk_note))

    rent = _rent(space, assumptions, cites, sqft)

    # Fit-out: build-out by what's there today + furniture + IT, plus contingency/soft costs.
    kind = _build_out_kind(inspection)
    lo_psf, hi_psf = B.OFFICE_FITOUT_PSF[kind]
    seen = (inspection.existing_build_out if inspection else None) or "not verified"
    if inspection and inspection.existing_build_out:
        cites.extend(c for c in inspection.citations if c.field in (None, "existing_build_out"))
    assumptions.append(Assumption(name="fitout_psf_low", value=lo_psf, unit="$/sqft",
                                  note=f"existing build-out: {seen}. {B.OFFICE_FITOUT_NOTE}"))
    assumptions.append(Assumption(name="fitout_psf_high", value=hi_psf, unit="$/sqft", note=f"existing build-out: {seen}"))

    if layout and layout.items:
        f_lo = f_hi = 0.0
        counts: dict[str, int] = {}
        for it in layout.items:
            lo, hi = B.OFFICE_ITEM_COST.get(it.item_type) or B.ITEM_COST.get(it.item_type) or B.DEFAULT_ITEM_COST
            f_lo += lo
            f_hi += hi
            counts[it.item_type] = counts.get(it.item_type, 0) + 1
        summary = ", ".join(f"{n}× {t}" for t, n in sorted(counts.items()))
        assumptions.append(Assumption(name="furniture_from_layout", value=f"${f_lo:,.0f}–${f_hi:,.0f}", unit="USD",
                                      source="model", note=f"{summary}. {B.OFFICE_FURNITURE_NOTE}"))
    else:
        f_lo, f_hi = (desks * x for x in B.FURNITURE_PER_DESK)
        assumptions.append(Assumption(name="furniture_per_desk", value=f"${B.FURNITURE_PER_DESK[0]:,}–${B.FURNITURE_PER_DESK[1]:,}",
                                      unit="USD per desk", note=f"No layout yet. {B.OFFICE_FURNITURE_NOTE}"))
    it_lo, it_hi = (desks * x for x in B.IT_PER_DESK)
    assumptions.append(Assumption(name="it_per_desk", value=f"${B.IT_PER_DESK[0]:,}–${B.IT_PER_DESK[1]:,}",
                                  unit="USD per desk", note="network cabling, Wi-Fi, share of AV"))
    pct = B.CONTINGENCY_PCT + B.SOFT_COSTS_PCT
    assumptions.append(Assumption(name="contingency_and_soft_costs", value=pct, unit="share of hard costs",
                                  note="10% contingency + 8% design/permits; a landlord TI allowance would reduce this"))
    fit_lo = round((lo_psf * sqft + f_lo + it_lo) * (1 + pct), -2)
    fit_hi = round((hi_psf * sqft + f_hi + it_hi) * (1 + pct), -2)

    # Monthly occupancy: rent + operating costs not included in the rent.
    service, label = _service_kind(space)
    ox_lo, ox_hi = B.OFFICE_OPEX_PSF_YEAR[service]
    assumptions.append(Assumption(name="opex_on_top_of_rent", value=f"${ox_lo}–${ox_hi}", unit="$/sqft/yr",
                                  note=f"rent basis: {label or 'not stated'}; full-service rent already includes these"))
    term = B.OFFICE_LEASE_TERM_MONTHS
    assumptions.append(Assumption(name="lease_term_months", value=term, unit="months",
                                  note="fit-out cost is spread over a typical 5-year office lease"))

    per_lo = per_hi = None
    if rent is not None:
        occ_lo = rent + ox_lo * sqft / 12
        occ_hi = rent + ox_hi * sqft / 12
        per_lo = round((occ_lo + fit_lo / term) / desks, 2)
        per_hi = round((occ_hi + fit_hi / term) / desks, 2)
        assumptions.append(Assumption(name="monthly_occupancy_cost", value=f"${occ_lo:,.0f}–${occ_hi:,.0f}",
                                      unit="USD/month", source="model", note="rent + operating costs not included in rent"))
        assumptions.append(Assumption(name="cost_per_desk_month_base", value=round((per_lo + per_hi) / 2, 2),
                                      unit="USD per desk per month", source="model",
                                      note="(rent + opex + fit-out / lease term) / desks, midpoint"))
    else:
        assumptions.append(Assumption(name="rent", value="unknown", note="No rent on listing and no market data: cost per desk not computed"))

    psf_year = space.rent_per_sqft_year or ((rent * 12 / sqft) if rent and sqft else None)
    _office_rent_comps(space, psf_year, assumptions, cites)

    return Numbers(
        space_id=space.space_id,
        rent_month=round(rent, 2) if rent is not None else None,
        fitout_cost_low=fit_lo,
        fitout_cost_high=fit_hi,
        revenue_month_low=0.0,
        revenue_month_high=0.0,
        breakeven_months_low=None,
        breakeven_months_high=None,
        cost_per_seat_month_low=per_lo,
        cost_per_seat_month_high=per_hi,
        assumptions=assumptions,
        citations=cites,
    )


def estimate_costs(space: Space, layout: Layout | None, inspection: Inspection | None, brief: Brief) -> Numbers:
    """Rent, fit-out range, revenue range, break-even months. Every assumption listed.

    Offices (brief.business_type == "office"): fit-out, cost per desk per month
    (cost_per_seat_month_*), rent vs nearby office listings; revenue 0 and break-even None.
    """
    if brief.business_type == "office":
        return _estimate_office(space, layout, inspection, brief)
    assumptions: list[Assumption] = []
    cites: list[Citation] = []

    sqft = space.sqft
    if not sqft:
        sqft = B.DEFAULT_SQFT
        assumptions.append(Assumption(name="sqft", value=sqft, unit="sqft", note="Listing has no size; typical small storefront assumed"))
    else:
        cites.extend(c for c in space.citations if c.field == "sqft")

    rent = _rent(space, assumptions, cites, sqft)
    fit_lo, fit_hi = _fitout(space, layout, inspection, brief, sqft, assumptions, cites)
    rev_lo, rev_hi, rev_mid = _revenue(layout, brief, assumptions)

    bt_cost = brief.business_type if brief.business_type in B.COGS_PCT else "other"
    mid = lambda r: sum(r) / 2  # noqa: E731
    cogs, labor, opex = mid(B.COGS_PCT[bt_cost]), mid(B.LABOR_PCT[bt_cost]), mid(B.OTHER_OPEX_PCT)
    nnn = mid(B.NNN_PCT_OF_RENT)
    margin = 1 - cogs - labor - opex
    assumptions += [
        Assumption(name="cogs_pct", value=round(cogs, 3), unit="share of revenue", note=B.COST_NOTE),
        Assumption(name="labor_pct", value=round(labor, 3), unit="share of revenue", note=B.COST_NOTE),
        Assumption(name="other_opex_pct", value=round(opex, 3), unit="share of revenue",
                   note="utilities, insurance, marketing, card fees, repairs, supplies"),
        Assumption(name="nnn_cam_pct_of_rent", value=nnn, unit="share of base rent",
                   note="taxes/insurance/CAM on top of base rent; ask the broker if the rent is NNN or gross"),
    ]

    be_lo = be_hi = None
    if rent is not None:
        occupancy = rent * (1 + nnn)
        profit = {k: r * margin - occupancy for k, r in (("lo", rev_lo), ("mid", rev_mid), ("hi", rev_hi))}
        fit_mid = (fit_lo + fit_hi) / 2
        if profit["mid"] > 0:
            # base +/- combined (root-sum-square) uncertainty of fit-out and monthly profit,
            # never better than the true best case (cheapest build, strongest sales).
            base_be = fit_mid / profit["mid"]
            rel = math.hypot((fit_hi - fit_lo) / (2 * fit_mid), (profit["hi"] - profit["lo"]) / (2 * profit["mid"]))
            best = fit_lo / profit["hi"]
            be_lo = round(max(best, base_be * (1 - rel)), 1)
            be_hi = round(base_be * (1 + rel), 1) if rel < 1 else None
        elif profit["hi"] > 0:
            be_lo = round(fit_lo / profit["hi"], 1)
        assumptions.append(Assumption(name="monthly_profit_range", value=f"${profit['lo']:,.0f} to ${profit['hi']:,.0f}",
                                      unit="USD/month", source="model",
                                      note="after COGS, labor, opex, rent + NNN; before owner pay, debt service, taxes"))
        base = round(fit_mid / profit["mid"], 1) if profit["mid"] > 0 else None
        assumptions.append(Assumption(name="breakeven_months_base", value=base if base is not None else "not reached",
                                      unit="months", source="model", note="mid fit-out cost / base-case monthly profit"))
        if be_hi is None:
            assumptions.append(Assumption(name="breakeven_note", value="low-revenue case does not break even", source="model",
                                          note="at the low revenue end the space loses money each month"))
    else:
        assumptions.append(Assumption(name="rent", value="unknown", note="No rent on listing and no market data: break-even not computed"))

    return Numbers(
        space_id=space.space_id,
        rent_month=round(rent, 2) if rent is not None else None,
        fitout_cost_low=fit_lo,
        fitout_cost_high=fit_hi,
        revenue_month_low=rev_lo,
        revenue_month_high=rev_hi,
        breakeven_months_low=be_lo,
        breakeven_months_high=be_hi,
        assumptions=assumptions,
        citations=cites,
    )


def draft_broker_email(space: Space, brief: Brief) -> str:
    """Short, specific email to the listing broker asking to visit."""
    try:
        from pipeline.queries import broker_contact
        contact = broker_contact(space.space_id)
    except Exception:
        contact = {}
    name = (contact.get("broker_name") or "").strip()
    first = name.split()[0] if name else ""
    greeting = f"Hi {first}," if first else "Hello,"
    office = brief.business_type == "office"
    size = f"{space.sqft:,.0f} sqft " if space.sqft else ""
    rent_line = f" The listing shows about ${space.asking_rent_month:,.0f}/month." if space.asking_rent_month else ""
    if office:
        team = f" for a team of {brief.seats_wanted}" if brief.seats_wanted else ""
        want = f"office space{team}"
    else:
        bt = brief.business_type if brief.business_type != "other" else "small business"
        seats = f" with about {brief.seats_wanted} seats" if brief.seats_wanted else ""
        want = f"a space for a {bt}{seats}"

    if office:
        questions = ["Is the asking rent full-service gross, or are operating expenses and utilities billed separately?",
                     "What is built out today (open plan, private offices, conference rooms), and could any existing furniture stay?",
                     "Is the landlord offering a tenant-improvement allowance or free rent?",
                     "What lease term is the landlord looking for, and is there flexibility (shorter term, expansion or sublease rights)?",
                     "What are the building hours, and how do after-hours HVAC and access work?",
                     "Which internet/fiber providers serve the building?"]
    else:
        questions = ["Is the asking rent NNN or gross, and what are the current CAM/tax charges?",
                     "Is the landlord offering any tenant-improvement allowance or free rent?",
                     "What lease term and start date is the landlord looking for?"]
        if brief.business_type in FOOD:
            questions[1:1] = ["Was the space previously used for food service (grease trap, hood, gas line, 3-compartment sink)?",
                              "Does zoning allow a food-service use, and is there enough electrical capacity for ovens?"]
    if any("parking" in m.lower() for m in brief.must_haves):
        questions.append("How many parking spaces come with the lease, and what do monthly permits cost?" if office
                         else "How many parking spaces come with the unit, and is customer parking shared?")

    to = f"To: {contact['broker_email']}\n" if contact.get("broker_email") else ""
    sign = "[Your name]\n[Phone]"
    body = "\n".join(f"- {q}" for q in questions)
    return (
        f"{to}Subject: Tour request: {space.address}\n\n"
        f"{greeting}\n\n"
        f"I'm looking for {want}, and your {size}listing at {space.address} looks like a strong fit.{rent_line} "
        f"I'd love to schedule a walkthrough this week or next.\n\n"
        f"A few questions before we visit:\n{body}\n\n"
        f"Thank you, and I look forward to hearing from you.\n\n{sign}\n"
    )
