"""Run the agent from the terminal.

    python -m agent.cli "bakery in Houston, 20 seats, under $6k"
    python -m agent.cli "..." --feedback "fewer seats, closer to transit" --mode scripted --files

Prints the live events, then the ranked results. --files also prints the agent's virtual files.
"""

from __future__ import annotations

import argparse
import logging
import sys

from agent import providers as P
from agent.brief import apply_feedback, parse_brief
from agent.context import RunContext
from agent.runner import resolve_mode, run_round
from agent.tools.funnel import numbers_lines
from shared.schemas import AgentEvent, Feedback

_ICON = {"subagent_started": "->", "subagent_finished": "<-", "tool_call": "  .", "tool_result": "  =",
         "file_written": "  #", "funnel_update": "[F]", "plan_update": "[P]", "error": "!!", "log": "  i"}


def _print_event(ev: AgentEvent, verbose: bool) -> None:
    if ev.type in ("tool_call", "tool_result", "plan_update") and not verbose:
        return
    if ev.type == "funnel_update":
        f = ev.payload["funnel"]
        msg = f"{f['total']} -> {f['filtered']} -> {f['ranked']} -> {f['inspected']} -> {f['fitted']}"
    elif ev.type == "plan_update":
        msg = " | ".join(f"{'x' if t['status'] == 'completed' else '>' if t['status'] == 'in_progress' else ' '} {t['content']}"
                         for t in ev.payload["todos"])
    else:
        msg = (ev.message or "")[:160].replace("\n", " ")
    print(f"{ev.seq:4d} {_ICON.get(ev.type, '  *')} {ev.type:<18} {ev.agent or '':<12} {msg}", flush=True)


def _print_results(ctx: RunContext) -> None:
    print("\n=== Results ===")
    for r in ctx.results:
        n = r.numbers
        office = ctx.brief.business_type == "office"
        money = (" | " + ", ".join(numbers_lines(n, ctx.brief.business_type)[::2 if office else 1])) if n else ""
        seats = f" | {r.layout.seat_count} {'desks' if office else 'seats'}" if r.layout else ""
        print(f"#{r.rank} [{r.rank_score:.2f}] {r.space.address} ({r.status}){seats}{money}")
        for reason in r.rank_reasons[:3]:
            print(f"     - {reason}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", help="the owner's brief")
    ap.add_argument("--feedback", action="append", default=[], help="feedback to apply after the first round (repeatable)")
    ap.add_argument("--mode", choices=["auto", "llm", "scripted"], default=None)
    ap.add_argument("--files", action="store_true", help="print the agent's virtual files at the end")
    ap.add_argument("-v", "--verbose", action="store_true", help="show tool calls and todo updates")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    print(f"mode: {resolve_mode(a.mode)} | providers: {P.SOURCES}")
    brief = parse_brief(a.text)
    print("brief:", brief.model_dump_json(exclude={"raw_text", "feedback_history"}, exclude_none=True))
    ctx = RunContext(brief=brief, sink=lambda ev: _print_event(ev, a.verbose))
    run_round(ctx, "scout", a.mode)
    _print_results(ctx)

    for text in a.feedback:
        ctx.round += 1
        fb = Feedback(text=text)
        ctx.brief, stage = apply_feedback(ctx.brief, fb)
        print(f"\n=== Feedback round {ctx.round}: {text!r} -> restart at {stage} ===")
        ctx.emit("feedback_received", agent="orchestrator", message=text, feedback=fb, round=ctx.round)
        run_round(ctx, stage or "analyst", a.mode)
        _print_results(ctx)

    if a.files:
        print("\n=== Agent files ===")
        for path in sorted(ctx.fs):
            print(f"--- {path}\n{ctx.fs[path][:1200]}")
    return 0 if ctx.results else 1


if __name__ == "__main__":
    sys.exit(main())
