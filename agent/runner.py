"""Run one round of a run (round 0 = the brief, round N = after feedback N), whatever the mode.

mode "llm":      the Deep Agent orchestrates (agent/agent.py)
mode "scripted": the fixed funnel (agent/pipeline.py)
mode "auto":     llm if credentials exist, else scripted

If the LLM agent crashes mid-run we log it and let the scripted funnel finish from the
caches, so the owner always gets results.
"""

from __future__ import annotations

import logging

from agent import config
from agent.context import RunContext
from agent.llm import llm_available
from agent.pipeline import run_scripted

log = logging.getLogger(__name__)


def resolve_mode(mode: str | None = None) -> str:
    mode = (mode or config.AGENT_MODE).lower()
    if mode == "auto":
        return "llm" if llm_available() else "scripted"
    return mode


def run_round(ctx: RunContext, start: str = "scout", mode: str | None = None) -> str:
    """Returns the mode that actually produced the results."""
    mode = resolve_mode(mode)
    ctx.results = []
    ctx.emit("run_started" if ctx.round == 0 else "log", agent="orchestrator",
             message=f"Round {ctx.round} ({mode} mode), starting at {start}", brief=ctx.brief, mode=mode, start=start)
    if mode == "llm":
        try:
            from agent.agent import run_agent

            run_agent(ctx, start)
        except Exception as e:  # noqa: BLE001
            log.exception("LLM agent failed")
            ctx.emit("error", agent="orchestrator", message=f"Agent error, finishing with the scripted funnel: {e}"[:400],
                     detail=str(e)[:1000])
            mode = "scripted (fallback)"
            run_scripted(ctx, start)
    else:
        run_scripted(ctx, start)
    ctx.emit("run_finished", agent="orchestrator", message=f"{len(ctx.results)} results", result_count=len(ctx.results),
             round=ctx.round)
    return mode
