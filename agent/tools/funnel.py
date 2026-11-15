"""The funnel stages, as plain functions over a RunContext.

Both orchestrators use these: the LLM Deep Agent (agent/agent.py wraps them as tools that
subagents choose to call) and the scripted fallback (agent/pipeline.py calls them in order).

Every contract-function call goes through `safe_call`: a timeout, a tool_call/tool_result
event pair, and a caught exception (turned into a message) instead of a crash. One bad
space marks that space failed; the run carries on with the rest.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Callable, TypeVar

from agent import config
from agent import providers as P
from agent.context import RunContext
from agent.ranking import score_space
from agent.tools.inspector import inspect_space
from shared import conventions as C
from shared.schemas import CandidateResult

log = logging.getLogger(__name__)
T = TypeVar("T")

_POOL = ThreadPoolExecutor(max_workers=32, thread_name_prefix="hestia-tool")


class ToolError(Exception):
    pass


def safe_call(ctx: RunContext, agent: str, tool: str, fn: Callable[..., T], *args: Any,
              timeout: float | None = None, summary: Callable[[T], str] | None = None,
              quiet: bool = False, **kwargs: Any) -> T:
    """Run one contract function with a timeout and events. Raises ToolError with a readable message."""
    arg_view = {k: v for k, v in kwargs.items()} | ({"space_id": args[0]} if args and isinstance(args[0], str) else {})
    if not quiet:
        ctx.emit("tool_call", agent=agent, message=tool, tool=tool, args=arg_view)
    fut = _POOL.submit(fn, *args, **kwargs)
    try:
        out = fut.result(timeout=timeout or config.TOOL_TIMEOUT_S)
    except FutureTimeout:
        msg = f"{tool} timed out after {timeout or config.TOOL_TIMEOUT_S:.0f}s"
        ctx.emit("tool_result", agent=agent, message=msg, tool=tool, summary=msg, ok=False)
        raise ToolError(msg) from None
    except Exception as e:  # noqa: BLE001
        msg = f"{tool} failed: {type(e).__name__}: {e}"[:400]
        log.exception("tool %s failed", tool)
        ctx.emit("tool_result", agent=agent, message=msg, tool=tool, summary=msg, ok=False)
        raise ToolError(msg) from e
    if not quiet:
        s = summary(out) if summary else "ok"
        ctx.emit("tool_result", agent=agent, message=s, tool=tool, summary=s, ok=True)
    return out


def pmap(fn: Callable[[str], T], ids: list[str]) -> dict[str, T | ToolError]:
    """Run fn over ids in parallel; exceptions are returned, not raised."""
    out: dict[str, T | ToolError] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(config.MAX_WORKERS, len(ids)))) as ex:
        futs = {i: ex.submit(fn, i) for i in ids}
        for i, f in futs.items():
            try:
                out[i] = f.result()
            except ToolError as e:
                out[i] = e
            except Exception as e:  # noqa: BLE001
                out[i] = ToolError(f"{type(e).__name__}: {e}")
    return out


def _cdir(space_id: str) -> str:
    return C.AGENT_CANDIDATE_DIR.format(space_id=space_id)


def _fail(ctx: RunContext, space_id: str, err: Exception | str) -> None:
    ctx.failures[space_id] = str(err)


# --------------------------------------------------------------------------- #
# Brief
# --------------------------------------------------------------------------- #


def brief_markdown(ctx: RunContext) -> str:
    b = ctx.brief
    lines = ["# Brief", "", f"> {b.raw_text}" if b.raw_text else "", ""]
    for k, v in b.model_dump(exclude={"raw_text", "feedback_history"}).items():
        if v not in (None, [], ""):
            lines.append(f"- **{k}**: {v}")
    if b.feedback_history:
        lines += ["", "## Feedback so far"] + [f"{i + 1}. ({f.kind}) {f.text}" for i, f in enumerate(b.feedback_history)]
    if ctx.rejected:
        lines += ["", f"Rejected spaces: {', '.join(sorted(ctx.rejected))}"]
    return "\n".join(lines) + "\n"


def write_brief(ctx: RunContext, agent: str = "orchestrator") -> str:
    md = brief_markdown(ctx)
    ctx.write_file(C.AGENT_BRIEF, md, agent=agent)
    return md


# --------------------------------------------------------------------------- #
# Scout: filter + neighborhood rank
# --------------------------------------------------------------------------- #


def search_spaces(ctx: RunContext, agent: str = "scout") -> list[str]:
    spaces = safe_call(ctx, agent, "query_spaces", P.query_spaces, ctx.brief, limit=config.FUNNEL_FILTER_LIMIT,
                       summary=lambda s: f"{len(s)} spaces match the hard filters")
    for s in spaces:
        ctx.spaces[s.space_id] = s
    ctx.filtered = ctx.active_ids([s.space_id for s in spaces])
    ctx.update_funnel(total=P.total_space_count(len(spaces)), filtered=len(ctx.filtered),
                      ranked=0, inspected=0, fitted=0)
    return ctx.filtered


def rank_neighborhoods(ctx: RunContext, top_n: int | None = None, agent: str = "scout") -> list[str]:
    top_n = top_n or config.FUNNEL_INSPECT_TOP
    ids = ctx.active_ids(ctx.filtered)
    todo = [i for i in ids if i not in ctx.neighborhoods]
    ctx.emit("tool_call", agent=agent, message="neighborhood_profile", tool="neighborhood_profile",
             args={"spaces": len(todo), "cached": len(ids) - len(todo)})

    kw = {"business_type": ctx.brief.business_type} if P.accepts(P.neighborhood_profile, "business_type") else {}

    def one(sid: str):
        return safe_call(ctx, agent, "neighborhood_profile", P.neighborhood_profile, sid, quiet=True, **kw)

    for sid, res in pmap(one, todo).items():
        if isinstance(res, ToolError):
            _fail(ctx, sid, res)
        else:
            ctx.neighborhoods[sid] = res
    ok = sum(1 for i in ids if i in ctx.neighborhoods)
    ctx.emit("tool_result", agent=agent, message=f"profiled {ok}/{len(ids)} neighborhoods", tool="neighborhood_profile",
             summary=f"profiled {ok}/{len(ids)} neighborhoods", ok=ok > 0)

    scored = sorted(((score_space(ctx.brief, ctx.space(i), ctx.neighborhoods.get(i))[0], i) for i in ids), reverse=True)
    ctx.shortlist = [i for _, i in scored[:top_n]]
    ctx.update_funnel(ranked=len(ctx.shortlist))

    rows = ["# Shortlist (ranked by neighborhood, budget and size)", "",
            "| # | space_id | address | rent/mo | sqft | score |", "|---|---|---|---|---|---|"]
    for n, (sc, i) in enumerate(scored[:top_n], start=1):
        s = ctx.space(i)
        rows.append(f"| {n} | {i} | {s.address} | {s.asking_rent_month or '?'} | {s.sqft or '?'} | {sc:.2f} |")
    ctx.write_file(C.AGENT_SHORTLIST, "\n".join(rows) + "\n", agent=agent)
    return ctx.shortlist


# --------------------------------------------------------------------------- #
# Inspector
# --------------------------------------------------------------------------- #


def inspect_spaces(ctx: RunContext, space_ids: list[str], agent: str = "inspector") -> dict[str, str]:
    ids = ctx.active_ids(space_ids)

    def one(sid: str):
        if sid in ctx.inspections:
            return ctx.inspections[sid]
        return safe_call(ctx, agent, "inspect_space", inspect_space, sid, ctx.brief.business_type,
                         summary=lambda i: _insp_line(i, ctx.brief.business_type))

    out: dict[str, str] = {}
    for sid, res in pmap(one, ids).items():
        if isinstance(res, ToolError):
            _fail(ctx, sid, res)
            out[sid] = f"FAILED: {res}"
            continue
        ctx.inspections[sid] = res
        out[sid] = _insp_line(res, ctx.brief.business_type)
        md = [f"# Inspection: {sid}", "", f"- confidence: {res.confidence:.2f}", f"- panoramas: {', '.join(res.pano_ids) or 'none'}"]
        for f in ("storefront_glass", "existing_kitchen", "existing_restroom", "vent_hood", "natural_light",
                  "existing_build_out", "ceiling_height_m"):
            v = getattr(res, f)
            md.append(f"- {f}: {'unverified' if f in res.unverified_fields and v is None else v}")
        md += [f"- note: {n}" for n in res.notes]
        ctx.write_file(_cdir(sid) + "inspection.md", "\n".join(md) + "\n", agent=agent)
    ctx.update_funnel(inspected=sum(1 for i in ctx.active_ids(ctx.shortlist) if i in ctx.inspections))
    return out


def _insp_line(i, business_type: str = "bakery") -> str:
    tail = f"ceiling {i.ceiling_height_m or '?'} m; confidence {i.confidence:.2f}"
    if business_type == "office":
        light = "?" if i.natural_light is None else f"{i.natural_light:.2f}"
        return (f"daylight {light}; built as {i.existing_build_out or 'unknown'}; "
                f"restroom {'yes' if i.existing_restroom else 'no' if i.existing_restroom is False else '?'}; {tail}")
    yes = [f for f in ("storefront_glass", "existing_kitchen", "existing_restroom", "vent_hood") if getattr(i, f)]
    return f"has {', '.join(yes) or 'none of the checklist'}; {tail}"


def has_photos(space_id: str) -> bool:
    """True if at least one of the space's scan photos is on disk (vision, staging and the tour need them)."""
    from agent.tools.inspector import _local_path

    try:
        return any(_local_path(p).is_file() for p in P.get_panoramas(space_id))
    except Exception:  # noqa: BLE001
        return False


def select_for_fitout(ctx: RunContext, top_n: int | None = None) -> list[str]:
    """Re-rank the shortlist with inspections and pick the spaces worth the expensive fit-out."""
    top_n = top_n or config.FUNNEL_FIT_TOP
    ids = [i for i in ctx.active_ids(ctx.shortlist) if i not in ctx.failures]
    scored = sorted(((has_photos(i) if config.PREFER_PHOTOS else True,
                      score_space(ctx.brief, ctx.space(i), ctx.neighborhoods.get(i), ctx.inspections.get(i))[0], i)
                     for i in ids), reverse=True)
    ctx.fit_list = [i for *_, i in scored[:top_n]]
    return ctx.fit_list


# --------------------------------------------------------------------------- #
# Designer / stager / analyst
# --------------------------------------------------------------------------- #

FALLBACK_STRATEGIES = ("fewer_tables", "compact")


def design_layouts(ctx: RunContext, space_ids: list[str], strategy: str | None = None,
                   agent: str = "designer") -> dict[str, str]:
    b = ctx.brief

    def one(sid: str) -> str:
        rooms = safe_call(ctx, agent, "get_rooms", P.get_rooms, sid, summary=lambda r: f"{len(r)} rooms")
        tries = [strategy] + [s for s in FALLBACK_STRATEGIES if s != strategy]
        last = None
        for strat in tries[:2]:  # the requested strategy, then one fallback
            key = (sid, b.business_type, b.seats_wanted, strat)
            if key in ctx.layout_cache:
                lay, rep = ctx.layout_cache[key]
            else:
                lay = safe_call(ctx, agent, "plan_layout", P.plan_layout, sid, rooms, ctx.inspections.get(sid), b,
                                strategy=strat, summary=lambda l: f"{l.seat_count} seats, {len(l.items)} items")
                rep = safe_call(ctx, agent, "validate_layout", P.validate_layout, lay, rooms,
                                summary=lambda r: "valid" if r.passed else f"{len(r.violations)} violations")
                ctx.layout_cache[key] = (lay, rep)
            last = (lay, rep)
            if rep.passed:
                break
        lay, rep = last  # type: ignore[misc]
        ctx.layouts[sid], ctx.validations[sid] = lay, rep
        ctx.write_file(_cdir(sid) + "layout.json", lay.model_dump_json(indent=1), agent=agent)
        status = "valid" if rep.passed else "INVALID: " + "; ".join(v.message for v in rep.violations[:3])
        unit = "desks" if b.business_type == "office" else "seats"
        return f"{lay.seat_count} {unit}, {len(lay.items)} items, {status}"

    return _collect(ctx, pmap(one, ctx.active_ids(space_ids)))


def stage_heroes(ctx: RunContext, space_ids: list[str], style: str | None = None, agent: str = "stager") -> dict[str, str]:
    style = style or ctx.brief.style

    def one(sid: str) -> str:
        lay = ctx.layouts.get(sid)
        if not lay:
            raise ToolError("no layout yet: run the designer first")
        key = (lay.layout_id, style)
        hero = ctx.hero_cache.get(key) or safe_call(
            ctx, agent, "render_hero", P.render_hero, sid, lay, style=style, timeout=config.HERO_TIMEOUT_S,
            summary=lambda h: f"image {'passed' if h.score and h.score.passed else 'not verified'} ({h.model})")
        ctx.hero_cache[key] = hero
        ctx.heroes[sid] = hero
        ctx.write_file(_cdir(sid) + "hero.json", hero.model_dump_json(indent=1), agent=agent)
        sc = hero.score
        return f"hero {hero.path}" + (f", realism {sc.realism_1to5:.1f}/5, passed={sc.passed}" if sc else "")

    return _collect(ctx, pmap(one, ctx.active_ids(space_ids)), fatal=False)


def compute_numbers(ctx: RunContext, space_ids: list[str], agent: str = "analyst") -> dict[str, str]:
    def one(sid: str) -> str:
        sp = ctx.space(sid)
        n = safe_call(ctx, agent, "estimate_costs", P.estimate_costs, sp, ctx.layouts.get(sid), ctx.inspections.get(sid),
                      ctx.brief, summary=lambda n: f"fit-out ${n.fitout_cost_low:,.0f}-{n.fitout_cost_high:,.0f}")
        ctx.numbers[sid] = n
        try:
            ctx.emails[sid] = safe_call(ctx, agent, "draft_broker_email", P.draft_broker_email, sp, ctx.brief,
                                        summary=lambda e: "drafted")
        except ToolError:
            pass  # the email is optional
        md = [f"# Numbers: {sid}", ""] + [f"- {line}" for line in numbers_lines(n, ctx.brief.business_type)]
        md += ["", "## Assumptions"] + [f"- {a.name}: {a.value} {a.unit or ''} ({a.source})" for a in n.assumptions]
        ctx.write_file(_cdir(sid) + "numbers.md", "\n".join(md) + "\n", agent=agent)
        return ", ".join(numbers_lines(n, ctx.brief.business_type))

    return _collect(ctx, pmap(one, ctx.active_ids(space_ids)), fatal=False)


def numbers_lines(n, business_type: str) -> list[str]:
    """Bakery: revenue + break-even. Office: cost per desk (no revenue/break-even), per the README."""
    lines = [f"Rent: ${n.rent_month or 0:,.0f}/mo", f"Fit-out: ${n.fitout_cost_low:,.0f}-{n.fitout_cost_high:,.0f}"]
    if business_type == "office":
        if n.cost_per_seat_month_low is not None:
            lines.append(f"Cost per desk: {_range(n.cost_per_seat_month_low, n.cost_per_seat_month_high, '$')}/mo")
    else:
        lines.append(f"Revenue: ${n.revenue_month_low:,.0f}-{n.revenue_month_high:,.0f}/mo")
        if n.breakeven_months_low is not None:
            lines.append(f"Break-even: {_range(n.breakeven_months_low, n.breakeven_months_high)} months")
        else:
            lines.append("Break-even: not within the lease at these assumptions")
    return lines


def _range(lo: float, hi: float | None, unit: str = "") -> str:
    """'$660-756', or '24+' when the upper bound is unknown (e.g. it never breaks even in the worst case)."""
    if hi is None:
        return f"{unit}{lo:,.0f}+"
    return f"{unit}{lo:,.0f}-{hi:,.0f}"


def _collect(ctx: RunContext, res: dict[str, Any], fatal: bool = True) -> dict[str, str]:
    out = {}
    for sid, r in res.items():
        if isinstance(r, ToolError):
            if fatal:
                _fail(ctx, sid, r)
            out[sid] = f"FAILED: {r}"
        else:
            out[sid] = r
    return out


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


def publish_results(ctx: RunContext, space_ids: list[str] | None = None, notes: dict[str, str] | None = None,
                    agent: str = "orchestrator") -> list[CandidateResult]:
    """Score, rank and publish every fitted space (plus inspected-only ones if fewer than FIT_TOP fitted)."""
    ids = ctx.active_ids(space_ids or ctx.fit_list or ctx.shortlist)
    ids = list(dict.fromkeys(ids))
    results: list[CandidateResult] = []
    for sid in ids:
        sp = ctx.space(sid)
        score, reasons = score_space(ctx.brief, sp, ctx.neighborhoods.get(sid), ctx.inspections.get(sid),
                                     ctx.layouts.get(sid), ctx.validations.get(sid), ctx.numbers.get(sid))
        if notes and notes.get(sid):
            reasons.insert(0, notes[sid])
        if sid in ctx.failures:
            status, reasons = "failed", reasons + [f"Not fully evaluated: {ctx.failures[sid][:160]}"]
            score *= 0.5
        elif sid in ctx.layouts:
            status = "fitted"
        elif sid in ctx.inspections:
            status = "inspected"
        else:
            status = "screened"
        results.append(CandidateResult(
            run_id=ctx.run_id, rank=0, rank_score=score, rank_reasons=reasons, status=status,  # type: ignore[arg-type]
            space=sp, neighborhood=ctx.neighborhoods.get(sid), inspection=ctx.inspections.get(sid),
            layout=ctx.layouts.get(sid), validation=ctx.validations.get(sid), hero=ctx.heroes.get(sid),
            numbers=ctx.numbers.get(sid), broker_email=ctx.emails.get(sid)))
    order = {"fitted": 0, "inspected": 1, "screened": 2, "failed": 3}
    photos = {r.space.space_id: (has_photos(r.space.space_id) if config.PREFER_PHOTOS else True) for r in results}
    results.sort(key=lambda r: (order[r.status], not photos[r.space.space_id], -r.rank_score))
    for n, r in enumerate(results, start=1):
        r.rank = n
    ctx.results = results
    ctx.update_funnel(fitted=sum(1 for r in results if r.status == "fitted"))
    for r in results:
        sid = r.space.space_id
        ctx.write_file(C.AGENT_MEMO.format(space_id=sid), memo_markdown(r, ctx.brief.business_type), agent=agent)
        ctx.emit("candidate_ready", agent=agent, message=f"#{r.rank} {r.space.address}", result=r)
    return results


def memo_markdown(r: CandidateResult, business_type: str = "bakery") -> str:
    s = r.space
    lines = [f"# #{r.rank} {s.address}", "", f"Score **{r.rank_score:.2f}** ({r.status})", "", "## Why"]
    lines += [f"- {x}" for x in r.rank_reasons]
    office = business_type == "office"
    if r.numbers:
        lines += ["", "## Numbers"] + [f"- {x}" for x in numbers_lines(r.numbers, "office" if office else "food")]
    if r.layout:
        lines += ["", "## Layout", f"- {r.layout.seat_count} {'desks' if office else 'seats'}, {len(r.layout.items)} items, "
                  f"{'valid' if r.validation and r.validation.passed else 'needs fixes'}"]
    return "\n".join(lines) + "\n"


def results_table(ctx: RunContext) -> str:
    return json.dumps([{"rank": r.rank, "space_id": r.space.space_id, "address": r.space.address,
                        "score": r.rank_score, "status": r.status} for r in ctx.results], indent=1)
