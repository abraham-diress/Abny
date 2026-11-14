"""RunContext: everything one run knows, shared by the agent's tools, the scripted funnel and the server.

* emit(...)     -> numbered AgentEvent to the server's SSE stream (README §5.4)
* write_file()  -> our mirror of the agent's virtual filesystem (+ a file_written event)
* caches        -> per-space results, so feedback re-runs only what changed
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from shared.schemas import (
    AgentEvent,
    Brief,
    CandidateResult,
    FunnelStats,
    HeroImage,
    Inspection,
    Layout,
    NeighborhoodProfile,
    Numbers,
    Space,
    TodoItem,
    ValidationReport,
)

EventSink = Callable[[AgentEvent], None]


@dataclass
class RunContext:
    brief: Brief
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    sink: EventSink | None = None
    round: int = 0

    seq: int = 0
    fs: dict[str, str] = field(default_factory=dict)
    todos: list[TodoItem] = field(default_factory=list)
    funnel: FunnelStats = field(default_factory=FunnelStats)

    # caches (space-intrinsic ones survive feedback rounds)
    spaces: dict[str, Space] = field(default_factory=dict)
    filtered: list[str] = field(default_factory=list)
    shortlist: list[str] = field(default_factory=list)
    neighborhoods: dict[str, NeighborhoodProfile] = field(default_factory=dict)
    inspections: dict[str, Inspection] = field(default_factory=dict)
    layouts: dict[str, Layout] = field(default_factory=dict)  # space_id -> current layout
    validations: dict[str, ValidationReport] = field(default_factory=dict)
    heroes: dict[str, HeroImage] = field(default_factory=dict)
    numbers: dict[str, Numbers] = field(default_factory=dict)
    emails: dict[str, str] = field(default_factory=dict)
    layout_cache: dict[tuple, tuple[Layout, ValidationReport]] = field(default_factory=dict)
    hero_cache: dict[tuple, HeroImage] = field(default_factory=dict)
    fit_list: list[str] = field(default_factory=list)
    rejected: set[str] = field(default_factory=set)
    results: list[CandidateResult] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)  # space_id -> what went wrong

    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # ------------------------------------------------------------------ events
    def emit(self, type: str, agent: str | None = None, message: str | None = None, **payload: Any) -> AgentEvent:
        with self._lock:
            self.seq += 1
            ev = AgentEvent(run_id=self.run_id, seq=self.seq, type=type, agent=agent,  # type: ignore[arg-type]
                            message=message, payload=_jsonable(payload))
            if self.sink:  # inside the lock so events reach the sink in seq order
                self.sink(ev)
        return ev

    def log(self, message: str, agent: str | None = "orchestrator") -> None:
        self.emit("log", agent=agent, message=message)

    def write_file(self, path: str, content: str, agent: str | None = None) -> None:
        with self._lock:
            self.fs[path] = content
        self.emit("file_written", agent=agent, message=path, path=path)

    def set_todos(self, todos: list[TodoItem] | list[dict], agent: str = "orchestrator") -> None:
        self.todos = [t if isinstance(t, TodoItem) else TodoItem(**{k: t[k] for k in ("content", "status") if k in t})
                      for t in todos]
        self.emit("plan_update", agent=agent, todos=[t.model_dump() for t in self.todos])

    def update_funnel(self, **counts: int) -> None:
        with self._lock:
            for k, v in counts.items():
                setattr(self.funnel, k, v)
        self.emit("funnel_update", agent="orchestrator", funnel=self.funnel.model_dump())

    def space(self, space_id: str) -> Space:
        if space_id not in self.spaces:
            from agent import providers as P

            self.spaces[space_id] = P.get_space(space_id)
        return self.spaces[space_id]

    def active_ids(self, ids: list[str]) -> list[str]:
        return [i for i in ids if i not in self.rejected]


def _jsonable(obj: Any) -> Any:
    """Pydantic models -> dicts so payloads serialize cleanly."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)
