"""Agent funnel on Natnael's sample database with the teammates' real code (no LLM, no network)."""

import pytest

from agent import providers as P
from agent.brief import apply_feedback, parse_brief_rules
from agent.context import RunContext
from agent.runner import run_round
from shared import conventions as C
from shared.schemas import AgentEvent, Feedback


@pytest.fixture(autouse=True)
def _db(sample_db):  # tests/conftest.py: sample database + no LLM
    return sample_db


def _run(text="bakery in Houston, 20 seats, under $6k, needs parking"):
    events: list[AgentEvent] = []
    ctx = RunContext(brief=parse_brief_rules(text), sink=events.append)
    run_round(ctx, "scout", mode="scripted")
    return ctx, events


def test_full_round_writes_files_and_results():
    ctx, events = _run()
    assert 1 <= len(ctx.results) <= 5
    assert [r.rank for r in ctx.results] == list(range(1, len(ctx.results) + 1))
    assert all(r.rank_reasons for r in ctx.results)
    assert C.AGENT_BRIEF in ctx.fs and C.AGENT_SHORTLIST in ctx.fs
    sid = ctx.results[0].space.space_id
    for f in ("inspection.md", "layout.json", "hero.json", "numbers.md"):
        assert C.AGENT_CANDIDATE_DIR.format(space_id=sid) + f in ctx.fs
    types = [e.type for e in events]
    assert types[0] == "run_started" and types[-1] == "run_finished"
    for t in ("plan_update", "subagent_started", "tool_call", "funnel_update", "candidate_ready", "file_written"):
        assert t in types
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


def test_one_failing_tool_does_not_crash(monkeypatch):
    real = P.plan_layout
    bad = {}

    def flaky(space_id, *a, **kw):
        if not bad:
            bad["id"] = space_id
            raise RuntimeError("boom")
        return real(space_id, *a, **kw)

    monkeypatch.setattr(P, "plan_layout", flaky)
    ctx, events = _run()
    assert ctx.results and bad["id"] in ctx.failures
    assert any(e.type == "tool_result" and not e.payload["ok"] for e in events)
    assert ctx.results[-1].space.space_id == bad["id"] and ctx.results[-1].status == "failed"


def test_feedback_reranks_and_uses_cache(monkeypatch):
    ctx, _ = _run()
    before = {r.space.space_id: r.layout.layout_id for r in ctx.results if r.layout}
    calls = []
    monkeypatch.setattr("agent.tools.funnel.inspect_space", lambda *a: calls.append(a) or None)
    ctx.round += 1
    ctx.brief, stage = apply_feedback(ctx.brief, Feedback(text="fewer seats, closer to transit"))
    run_round(ctx, stage, mode="scripted")
    assert ctx.results and calls == []  # inspections came from the cache
    assert ctx.brief.seats_wanted == 15
    # Fewer seats -> the designer re-planned (new layouts), the inspections were reused.
    redone = [r for r in ctx.results if r.layout and r.space.space_id in before]
    assert redone and all(r.layout.layout_id != before[r.space.space_id] for r in redone)


def test_reject_removes_space():
    ctx, _ = _run()
    top = ctx.results[0].space.space_id
    ctx.rejected.add(top)
    ctx.round += 1
    run_round(ctx, "scout", mode="scripted")
    assert top not in {r.space.space_id for r in ctx.results}


def test_office_round():
    ctx, events = _run("Office for a 25-person team in downtown LA, near transit, under $20k/month")
    assert ctx.brief.business_type == "office" and ctx.results
    for r in ctx.results:
        assert "office" in (r.space.property_type or "").lower()
        assert r.neighborhood.competitors == [] and r.neighborhood.amenities
        assert r.inspection.natural_light is not None and r.inspection.existing_build_out
        assert r.numbers.revenue_month_high == 0 and r.numbers.breakeven_months_low is None
        assert r.numbers.cost_per_seat_month_low and r.numbers.cost_per_seat_month_low > 0
        assert r.layout and r.layout.seat_count > 0  # office layouts themselves are Yared's planner (R10)
    top = ctx.results[0]
    assert any("transit" in x.lower() for x in top.rank_reasons)
    sid = top.space.space_id
    assert "Cost per desk" in ctx.fs[C.AGENT_CANDIDATE_DIR.format(space_id=sid) + "numbers.md"]
    assert "Break-even" not in ctx.fs[C.AGENT_MEMO.format(space_id=sid)]


def test_bakery_never_gets_office_spaces():
    ctx, _ = _run()
    assert ctx.results and all("office" not in (r.space.property_type or "").lower() for r in ctx.results)
