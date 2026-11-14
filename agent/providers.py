"""Integration layer: every teammate's contract function, resolved at import time.

For each function we try the owner's real module first (README §5.2). If it doesn't exist yet
(ImportError/AttributeError) we fall back to the stand-in in agent/samples.py. So the agent
runs from M0, and switches to real code automatically as soon as a teammate merges theirs.

    from agent import providers as P
    spaces = P.query_spaces(brief)

`SOURCES` records where each function came from; the server shows it at /api/health.
Set STRICT_PROVIDERS=1 to fail loudly instead of falling back (use before the demo).
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any, Callable

from agent import samples

log = logging.getLogger(__name__)

SOURCES: dict[str, str] = {}
_STRICT = os.getenv("STRICT_PROVIDERS", "0") == "1"


def _resolve(module: str, name: str, fallback: Callable[..., Any] | None) -> Callable[..., Any] | None:
    try:
        fn = getattr(importlib.import_module(module), name)
        SOURCES[name] = module
        return fn
    except (ImportError, AttributeError) as e:
        if _STRICT and fallback is not None:
            raise RuntimeError(f"{module}.{name} is missing and STRICT_PROVIDERS=1") from e
        SOURCES[name] = "sample" if fallback else "missing"
        missing = isinstance(e, ModuleNotFoundError) and e.name and (module == e.name or module.startswith(e.name + "."))
        if not missing and fallback is not None:
            # The module exists but failed to import: that's a real bug, say so.
            log.warning("falling back for %s.%s: %r", module, name, e)
        return fallback


# Data Engine (Natnael)
query_spaces = _resolve("pipeline.queries", "query_spaces", samples.query_spaces)
get_space = _resolve("pipeline.queries", "get_space", samples.get_space)
get_rooms = _resolve("pipeline.queries", "get_rooms", samples.get_rooms)
get_panoramas = _resolve("pipeline.queries", "get_panoramas", samples.get_panoramas)
neighborhood_profile = _resolve("pipeline.queries", "neighborhood_profile", samples.neighborhood_profile)
count_spaces = _resolve("pipeline.queries", "count_spaces", None)  # optional helper for the funnel "total"
estimate_costs = _resolve("agent.analyst.costs", "estimate_costs", samples.estimate_costs)
draft_broker_email = _resolve("agent.analyst.costs", "draft_broker_email", samples.draft_broker_email)

# Reimaginer (Yared)
plan_layout = _resolve("agent.layout.planner", "plan_layout", samples.plan_layout)
validate_layout = _resolve("agent.layout.validator", "validate_layout", samples.validate_layout)
render_hero = _resolve("agent.staging.generate", "render_hero", samples.render_hero)


def using_sample_data() -> bool:
    return SOURCES.get("query_spaces") == "sample"


def total_space_count(fallback: int) -> int:
    if count_spaces is not None:
        try:
            return int(count_spaces())
        except Exception:  # noqa: BLE001
            pass
    return samples.count_spaces() if using_sample_data() else fallback
