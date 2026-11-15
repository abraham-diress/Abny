"""The Deep Agent: an orchestrator that plans with todos, writes files, and delegates to 5 subagents.

    build_agent(ctx)        -> compiled deepagents graph whose tools are bound to this run
    run_agent(ctx, start)   -> stream it, turning its updates into AgentEvents (README §5.4)

Tools never return big objects to the LLM: they store full results in the RunContext and
return a short text summary. The LLM decides *which* spaces deserve the expensive stages
and in what order; the numbers stay deterministic and sourced.
"""

from __future__ import annotations

import functools
import json
import logging
from typing import Any

from agent import config
from agent.context import RunContext
from agent.tools import funnel as F
from shared import conventions as C

log = logging.getLogger(__name__)


ORCHESTRATOR_PROMPT = f"""You are Hestia, an agent that finds a real vacant commercial space for a small business
(a bakery/cafe, or an office for a team), fits the business into it, and explains the trade-offs with sourced numbers.
The brief's business_type decides what matters: food businesses care about storefront glass, an existing kitchen,
foot traffic, competitors and parking; offices care about transit, nearby amenities, daylight, the existing build-out
and cost per desk (for offices, seats_wanted is the number of desks).

The owner's brief is in {C.AGENT_BRIEF}. Read it first.

Work as a funnel, cheapest checks first, so expensive stages only run on spaces that deserve them:
1. `scout` subagent: search + rank neighborhoods -> {C.AGENT_SHORTLIST} (up to {config.FUNNEL_INSPECT_TOP} spaces).
2. `inspector` subagent: inspect the shortlist from 3D-scan panoramas.
3. Call `pick_fitout_spaces` to re-rank with the inspections and choose the top {config.FUNNEL_FIT_TOP}.
4. `designer` subagent: layouts for those spaces. Then `stager` (hero images) and `analyst` (numbers);
   both only need the designer's layouts, so you may dispatch stager and analyst in parallel.
5. Call `publish_results` with the final order and a one-line reason per space. Then write a 3-sentence summary.

Rules:
- Start by writing a todo list (write_todos) and keep it updated: the owner watches it live.
- Pass subagents explicit space_ids in the task description; they cannot see your files unless you say which.
- If a stage fails for a space, drop it and continue with the next best; never stop the whole run.
- If the brief's "Feedback so far" section exists, this is a re-plan: say what changed, and only redo the
  stages it affects ({{restart_hint}}). Earlier results are cached, so re-running a stage on an unchanged space is free.
- Never invent numbers or space_ids. Use only the space_ids that tools returned.
- Tools write the files ({C.AGENT_SHORTLIST}, per-candidate files). Don't write or rewrite them yourself.
"""

SUBAGENTS: dict[str, dict[str, str]] = {
    "scout": {
        "description": "Searches the database for spaces matching the brief and ranks them by neighborhood, budget and size. Give it nothing but the goal.",
        "prompt": f"You are the scout. Call `find_shortlist` once with top_n={config.FUNNEL_INSPECT_TOP}. It writes the "
                  f"shortlist file for you; don't write files. Reply with the shortlisted space_ids exactly as returned, "
                  f"in order, and one line on the strongest and weakest options.",
    },
    "inspector": {
        "description": "Inspects spaces from their 3D-scan panoramas (food: storefront glass, kitchen, vent hood, restroom; office: daylight, existing build-out, restroom; ceiling). Give it the space_ids.",
        "prompt": "You are the inspector. Call `inspect_spaces` once with all the space_ids you were given "
                  "(or with none to inspect the whole shortlist). Don't write files. "
                  "Reply with one line per space: what it has that matters for this business, and anything unverified.",
    },
    "designer": {
        "description": "Plans and validates the furniture/equipment layout inside the real rooms. Give it the space_ids (and a strategy if retrying).",
        "prompt": "You are the designer. Call `design_layouts` with the space_ids. If a layout is INVALID, call it again for just "
                  "those spaces with strategy='fewer_tables' or 'compact'. Reply with seats (desks for offices) and validity per space.",
    },
    "stager": {
        "description": "Renders and scores the photoreal 'this is your business' image for spaces that already have layouts. Give it the space_ids.",
        "prompt": "You are the stager. Call `stage_heroes` with the space_ids. Reply with which images passed the quality check.",
    },
    "analyst": {
        "description": "Works out rent, fit-out cost, and revenue + break-even (food) or cost per desk (office), and drafts a broker email. Give it the space_ids.",
        "prompt": "You are the analyst. Call `compute_numbers` with the space_ids. Reply with rent, fit-out range and break-even (or cost per desk for offices) per space.",
    },
}


def _ok(d: dict[str, str]) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in d.items()) or "nothing to do"


def _wrap(fn):
    """Tool errors come back to the LLM as text so it can recover (B4)."""
    @functools.wraps(fn)  # keeps the signature + docstring the LLM reads
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {type(e).__name__}: {e}. Continue with the spaces that worked."
    return inner


def make_tools(ctx: RunContext) -> dict[str, list]:
    """Tools bound to this run, grouped by which agent may call them."""

    def find_shortlist(top_n: int = config.FUNNEL_INSPECT_TOP) -> str:
        """Filter the database by the brief's hard constraints (city, size, rent, has a 3D scan), then profile each
        match's neighborhood (tenants, homes, competitors, transit, parking) and rank by neighborhood fit, budget
        and size. Writes the shortlist file. Returns the top_n space_ids in order."""
        # One tool on purpose: two separate tools got called in parallel, and ranking ran before the search.
        found = F.search_spaces(ctx, agent="scout")
        ids = F.rank_neighborhoods(ctx, top_n, agent="scout")
        lines = [f"{len(found)} spaces passed the filters (of {ctx.funnel.total} total). Top {len(ids)}:"]
        for i in ids:
            s, nb = ctx.space(i), ctx.neighborhoods.get(i)
            lines.append(f"{i} | {s.address} | ${s.asking_rent_month or 0:,.0f}/mo | {s.sqft or '?'} sqft | "
                         f"nbhd {nb.score if nb else '?'}")
        return f"Shortlist written to {C.AGENT_SHORTLIST}:\n" + "\n".join(lines)

    def known(space_ids: list[str] | None, default: list[str]) -> tuple[list[str], str]:
        """Drop space_ids the tools never returned (models sometimes invent them); empty -> default."""
        ids = [i for i in (space_ids or default) if i in ctx.spaces]
        bad = [i for i in (space_ids or []) if i not in ctx.spaces]
        note = (f"\nIgnored unknown space_ids {bad}; valid ones come from the shortlist: {', '.join(ctx.shortlist)}"
                if bad else "")
        return ids, note

    def inspect_spaces(space_ids: list[str] | None = None) -> str:
        """Inspect spaces from cached 3D-scan panoramas with a vision model (runs in parallel). Pass the
        shortlisted space_ids, or none for the whole shortlist. Returns per space: storefront glass, existing
        kitchen, restroom, vent hood, daylight, build-out, ceiling height, confidence."""
        ids, note = known(space_ids, ctx.shortlist)
        return _ok(F.inspect_spaces(ctx, ids, agent="inspector")) + note

    def pick_fitout_spaces(top_n: int = config.FUNNEL_FIT_TOP) -> str:
        """Re-rank the shortlist using the inspections and return the top_n space_ids worth fitting out."""
        ids = F.select_for_fitout(ctx, top_n)
        ctx.log(f"Fitting out the top {len(ids)}: {', '.join(ids)}")
        return "Fit out these, in order: " + ", ".join(ids)

    def design_layouts(space_ids: list[str], strategy: str | None = None) -> str:
        """Plan the business's layout inside each space's real rooms and validate it (aisles, entrance, overlaps,
        seat/desk count). strategy: None for default, 'fewer_tables' or 'compact' to retry. Runs in parallel."""
        space_ids, note = known(space_ids, ctx.fit_list)
        return _ok(F.design_layouts(ctx, space_ids, strategy, agent="designer")) + note

    def stage_heroes(space_ids: list[str], style: str | None = None) -> str:
        """Render and score a photoreal image of the business inside each space (needs a layout first)."""
        space_ids, note = known(space_ids, ctx.fit_list)
        return _ok(F.stage_heroes(ctx, space_ids, style, agent="stager")) + note

    def compute_numbers(space_ids: list[str]) -> str:
        """Rent and fit-out cost range per space, plus revenue + break-even (food) or cost per desk (office),
        and a broker email draft."""
        space_ids, note = known(space_ids, ctx.fit_list)
        return _ok(F.compute_numbers(ctx, space_ids, agent="analyst")) + note

    def publish_results(space_ids: list[str], reasons: dict[str, str] | None = None) -> str:
        """Publish the final ranked results to the owner's screen. space_ids: in your preferred order
        (final order also uses the scores). reasons: optional one-line reason per space_id."""
        res = F.publish_results(ctx, space_ids, reasons, agent="orchestrator")
        return "Published:\n" + "\n".join(f"#{r.rank} {r.space.space_id} score {r.rank_score:.2f} ({r.status})" for r in res)

    w = _wrap
    return {
        "orchestrator": [w(pick_fitout_spaces), w(publish_results)],
        "scout": [w(find_shortlist)],
        "inspector": [w(inspect_spaces)],
        "designer": [w(design_layouts)],
        "stager": [w(stage_heroes)],
        "analyst": [w(compute_numbers)],
    }


def build_agent(ctx: RunContext, restart_hint: str = "full run", model: Any = None):
    from deepagents import create_deep_agent
    from langchain.agents.middleware import TodoListMiddleware

    from agent.llm import get_chat_model

    model = model or get_chat_model(max_tokens=8192)
    tools = make_tools(ctx)
    subagents = [{"name": name, "description": s["description"], "system_prompt": s["prompt"], "tools": tools[name]}
                 for name, s in SUBAGENTS.items()]
    return create_deep_agent(
        model=model,
        tools=tools["orchestrator"],
        system_prompt=ORCHESTRATOR_PROMPT.replace("{restart_hint}", restart_hint),
        subagents=subagents,
        middleware=[TodoListMiddleware()],  # write_todos -> the live plan panel
        name="hestia",
    )


def run_agent(ctx: RunContext, start: str = "scout", model: Any = None) -> None:
    """Run one round with the Deep Agent, streaming its updates as events. Raises on LLM failure."""
    from deepagents.backends.utils import create_file_data

    hint = "full run" if ctx.round == 0 else f"restart at the {start} stage"
    agent = build_agent(ctx, hint, model=model)
    brief_md = F.write_brief(ctx)
    task = ("Find and fit out the best spaces for this brief." if ctx.round == 0 else
            f"The owner gave feedback (see the end of {C.AGENT_BRIEF}). Re-plan: restart at the {start} stage.")
    inputs = {"messages": [{"role": "user", "content": f"{task}\n\n{brief_md}"}],
              "files": {C.AGENT_BRIEF: create_file_data(brief_md)}}

    pending_tasks: dict[str, str] = {}  # tool_call_id -> subagent name
    for chunk in agent.stream(inputs, stream_mode="updates", subgraphs=True,
                              config={"recursion_limit": 150}):
        namespace, update = chunk if isinstance(chunk, tuple) and len(chunk) == 2 else ((), chunk)
        in_sub = bool(namespace)
        if not isinstance(update, dict):
            continue
        for node_update in update.values():
            if not isinstance(node_update, dict):
                continue
            if not in_sub and isinstance(node_update.get("todos"), list):
                ctx.set_todos(node_update["todos"])
            for msg in _messages(node_update.get("messages")):
                _handle_message(ctx, msg, in_sub, pending_tasks)

    if not ctx.results:  # the LLM forgot to publish: do it for it
        ctx.log("Publishing results (agent finished without publishing).")
        if not ctx.fit_list:
            F.select_for_fitout(ctx)
        F.publish_results(ctx)


def _messages(v: Any) -> list:
    if v is None:
        return []
    v = getattr(v, "value", v)  # langgraph Overwrite wrapper
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _handle_message(ctx: RunContext, msg: Any, in_sub: bool, pending: dict[str, str]) -> None:
    mtype = getattr(msg, "type", None)
    if mtype == "ai":
        for tc in getattr(msg, "tool_calls", None) or []:
            name, args = tc.get("name"), tc.get("args") or {}
            if name == "task" and not in_sub:
                sub = args.get("subagent_type") or args.get("agent") or "general-purpose"
                pending[tc.get("id", "")] = sub
                desc = str(args.get("description", ""))[:500]
                ctx.emit("subagent_started", agent=sub, message=desc, task=desc)
            elif name in ("write_file", "edit_file"):
                path = args.get("file_path") or args.get("path")
                if path:
                    content = args.get("content")
                    if isinstance(content, str):
                        ctx.fs[path] = content
                    ctx.emit("file_written", agent=None if not in_sub else "subagent", message=path, path=path)
        text = _text(msg)
        if text and not in_sub and not getattr(msg, "tool_calls", None):
            ctx.log(text[:1500])
    elif mtype == "tool" and getattr(msg, "name", None) == "task" and not in_sub:
        sub = pending.pop(getattr(msg, "tool_call_id", ""), "subagent")
        summary = _text(msg)[:800]
        ctx.emit("subagent_finished", agent=sub, message=summary[:200], summary=summary)


def _text(msg: Any) -> str:
    c = getattr(msg, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return json.dumps(c, default=str)[:500]
