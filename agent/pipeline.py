"""Scripted orchestrator: the same funnel as the Deep Agent, in a fixed order, no LLM needed.

Used when there are no LLM credentials (M0, tests), with AGENT_MODE=scripted, and as the
safety net when the LLM agent fails mid-run (it finishes the job from the caches).
It emits exactly the same events the Deep Agent does, so the UI can't tell the difference.
"""

from __future__ import annotations

from agent import config
from agent.context import RunContext
from agent.tools import funnel as F

STAGES = ["scout", "inspector", "designer", "stager", "analyst"]

_TODOS = [
    ("scout", "Search spaces and rank neighborhoods"),
    ("inspector", "Inspect the shortlist from the 3D scans"),
    ("designer", "Lay out the business in the top spaces"),
    ("stager", "Render 'this is your business' images"),
    ("analyst", "Work out rent, fit-out and break-even"),
    ("publish", "Rank and publish results"),
]


def run_scripted(ctx: RunContext, start: str = "scout") -> None:
    first = STAGES.index(start) if start in STAGES else 0
    todos = [{"content": c, "status": "completed" if k in STAGES and STAGES.index(k) < first else "pending"}
             for k, c in _TODOS]

    def step(i: int, status: str) -> None:
        todos[i]["status"] = status
        ctx.set_todos(todos)

    F.write_brief(ctx)
    ctx.set_todos(todos)

    def stage(i: int, agent: str, task: str, fn) -> None:
        step(i, "in_progress")
        ctx.emit("subagent_started", agent=agent, message=task, task=task)
        summary = fn()
        ctx.emit("subagent_finished", agent=agent, message=summary, summary=summary)
        step(i, "completed")

    if first <= 0:
        def scout() -> str:
            F.search_spaces(ctx)
            short = F.rank_neighborhoods(ctx, config.FUNNEL_INSPECT_TOP)
            return f"{len(ctx.filtered)} spaces pass the filters; shortlisted {len(short)}"
        stage(0, "scout", "Find spaces matching the brief and rank their neighborhoods", scout)
    if first <= 1:
        stage(1, "inspector", f"Inspect the top {len(ctx.shortlist)} spaces",
              lambda: f"inspected {len(F.inspect_spaces(ctx, ctx.shortlist))} spaces")
    fit = F.select_for_fitout(ctx, config.FUNNEL_FIT_TOP)
    ctx.log(f"Fitting out the top {len(fit)}: {', '.join(fit)}")
    if first <= 2:
        stage(2, "designer", f"Lay out the business in {len(fit)} spaces",
              lambda: _join(F.design_layouts(ctx, fit)))
    if first <= 3:
        stage(3, "stager", f"Render hero images for {len(fit)} spaces",
              lambda: _join(F.stage_heroes(ctx, [i for i in fit if i in ctx.layouts])))
    stage(4, "analyst", f"Numbers for {len(fit)} spaces", lambda: _join(F.compute_numbers(ctx, fit)))
    step(5, "in_progress")
    F.publish_results(ctx, fit)
    step(5, "completed")


def _join(d: dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())[:600]
