"""Run bookkeeping for the server: live runs in background threads, recording, and demo replay.

Every finished round is recorded to data/runs/<run_id>.json (events with timing + results).
Replay instead of running live when DEMO=1 (every run), or when the brief's business type is in
DEMO_REPLAY (e.g. DEMO_REPLAY=office). The recording is picked by business type:
    DEMO_RUN_FILE (if set) -> data/runs/demo_<type>.json -> newest recording of that type.
Save the two demo recordings (bakery + office) with:  python -m scripts.save_demo <run_id>
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent import config
from agent import providers as P
from agent.brief import apply_feedback, parse_brief, parse_brief_rules
from agent.context import RunContext
from agent.runner import resolve_mode, run_round
from shared.conventions import RUNS_DIR
from shared.schemas import AgentEvent, Brief, CandidateResult, Feedback, FeedbackRequest, FunnelStats, Inspection, RunStatus

log = logging.getLogger(__name__)


@dataclass
class Run:
    run_id: str
    text: str
    state: str = "queued"
    error: str | None = None
    ctx: RunContext | None = None
    events: list[AgentEvent] = field(default_factory=list)
    recording: dict[str, Any] = field(default_factory=dict)
    replay: dict[str, Any] | None = None  # the recording being replayed in demo mode
    _round_t0: float = 0.0
    _round_events: list[dict] = field(default_factory=list)

    def status(self) -> RunStatus:
        c = self.ctx
        return RunStatus(run_id=self.run_id, state=self.state, brief=c.brief if c else None,  # type: ignore[arg-type]
                         funnel=c.funnel if c else FunnelStats(),
                         result_count=len(c.results) if c else 0, round=c.round if c else 0, error=self.error)

    def results(self) -> list[CandidateResult]:
        return sorted(self.ctx.results, key=lambda r: r.rank) if self.ctx else []

    # Called from worker threads (inside RunContext's lock, so in seq order).
    def sink(self, ev: AgentEvent) -> None:
        self.events.append(ev)
        self._round_events.append({"dt": round(time.monotonic() - self._round_t0, 3),
                                   "event": ev.model_dump(mode="json")})


class RunManager:
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def mode(self) -> str:
        return "demo" if config.demo_mode() else resolve_mode()

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    # ------------------------------------------------------------------ create
    def create(self, text: str, brief: Brief | None) -> Run:
        run = Run(run_id=uuid.uuid4().hex[:12], text=text)
        with self._lock:
            self.runs[run.run_id] = run
        btype = brief.business_type if brief else parse_brief_rules(text).business_type  # no network
        replay = config.demo_mode() or btype in config.DEMO_REPLAY
        if replay and (rec := load_recording(btype)):
            run.replay = rec
            self._start(run, self._replay_round, 0)
        else:
            self._start(run, self._first_round, brief)
        return run

    def _start(self, run: Run, target, *args) -> None:
        run.state = "running"
        threading.Thread(target=self._guard, args=(run, target, *args), daemon=True, name=f"run-{run.run_id}").start()

    def _guard(self, run: Run, target, *args) -> None:
        run._round_t0, run._round_events = time.monotonic(), []
        try:
            target(run, *args)
            run.state = "done"
        except Exception as e:  # noqa: BLE001
            log.exception("run %s failed", run.run_id)
            run.state, run.error = "error", f"{type(e).__name__}: {e}"
            if run.ctx:
                run.ctx.emit("error", agent="orchestrator", message=run.error, detail=run.error)
        finally:
            if not run.replay:
                self._record_round(run)

    def _first_round(self, run: Run, brief: Brief | None) -> None:
        brief = brief or parse_brief(run.text)
        if not brief.raw_text:
            brief.raw_text = run.text
        run.ctx = RunContext(brief=brief, run_id=run.run_id, sink=run.sink)
        run.recording = {"version": 1, "run_id": run.run_id, "text": run.text, "rounds": []}
        run_round(run.ctx, "scout")

    # ---------------------------------------------------------------- feedback
    def feedback(self, run: Run, req: FeedbackRequest) -> None:
        if run.state == "running":
            raise RuntimeError("run is still working; send feedback when it finishes")
        if run.ctx is None:
            raise RuntimeError("run has no context")
        rec = run.replay
        if rec and run.ctx.round + 1 < len(rec["rounds"]):
            self._start(run, self._replay_round, run.ctx.round + 1)
        else:
            run.replay = None  # nothing recorded for this round: go live
            self._start(run, self._feedback_round, req)

    def _feedback_round(self, run: Run, req: FeedbackRequest) -> None:
        ctx = run.ctx
        assert ctx is not None
        fb = Feedback(text=req.text, kind=req.kind, space_id=req.space_id)
        ctx.round += 1
        if req.kind == "reject" and req.space_id:
            ctx.rejected.add(req.space_id)
        ctx.emit("feedback_received", agent="orchestrator", message=req.text, feedback=fb, round=ctx.round)
        ctx.brief, stage = apply_feedback(ctx.brief, fb)
        run_round(ctx, stage or "analyst")

    # ------------------------------------------------------------- recording
    def _record_round(self, run: Run) -> None:
        if not run.ctx:
            return
        run.recording.setdefault("rounds", []).append({
            "round": run.ctx.round,
            "brief": run.ctx.brief.model_dump(mode="json"),
            "funnel": run.ctx.funnel.model_dump(),
            "events": run._round_events,
            "results": [r.model_dump(mode="json") for r in run.results()],
            "files": dict(run.ctx.fs),
        })
        try:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            (RUNS_DIR / f"{run.run_id}.json").write_text(json.dumps(run.recording))
        except OSError as e:
            log.warning("could not record run %s: %r", run.run_id, e)

    # ---------------------------------------------------------------- replay
    def _replay_round(self, run: Run, idx: int) -> None:
        rec = run.replay
        assert rec is not None
        rnd = rec["rounds"][idx]
        brief = Brief.model_validate(rnd["brief"])
        if run.ctx is None:
            run.ctx = RunContext(brief=brief, run_id=run.run_id, sink=run.sink)
        ctx = run.ctx
        ctx.brief, ctx.round, ctx.results = brief, idx, []
        t0 = time.monotonic()
        replanned: dict[str, Any] = {}
        for item in rnd["events"]:
            wait = item["dt"] / max(config.DEMO_SPEED, 0.01) - (time.monotonic() - t0)
            if wait > 0:
                time.sleep(min(wait, 5.0))  # never sit silent for long on stage
            ev = item["event"]
            payload = ev.get("payload") or {}
            if ev["type"] == "candidate_ready" and "result" in payload:
                payload["result"]["run_id"] = run.run_id
                if config.DEMO_REPLAN:
                    payload["result"] = _replan(payload["result"], brief, replanned)
            if ev["type"] == "funnel_update":
                ctx.funnel = ctx.funnel.model_validate(payload["funnel"])
            ctx.emit(ev["type"], agent=ev.get("agent"), message=ev.get("message"), **payload)
        results = [_replan(r, brief, replanned) for r in rnd["results"]] if config.DEMO_REPLAN else rnd["results"]
        ctx.results = [CandidateResult.model_validate({**r, "run_id": run.run_id}) for r in results]
        ctx.fs.update(rnd.get("files", {}))


def _replan(result: dict[str, Any], brief: Brief, cache: dict[str, Any]) -> dict[str, Any]:
    """The recorded result with its layout planned again by the current planner. The recorded photo shows the
    old layout, so it is dropped. Results without a layout, or whose planning fails, stay as recorded."""
    sid = (result.get("space") or {}).get("space_id")
    if not sid or not result.get("layout"):
        return result
    if sid not in cache:
        try:
            rooms = P.get_rooms(sid)
            insp = Inspection.model_validate(result["inspection"]) if result.get("inspection") else None
            lay = P.plan_layout(sid, rooms, insp, brief)
            cache[sid] = (lay.model_dump(mode="json"), P.validate_layout(lay, rooms).model_dump(mode="json"))
        except Exception as e:  # keep the recording rather than break the demo
            log.warning("replay: could not plan %s again: %r", sid, e)
            cache[sid] = None
    got = cache[sid]
    return result if got is None else {**result, "layout": got[0], "validation": got[1], "hero": None}


def recording_type(rec: dict[str, Any]) -> str | None:
    try:
        return rec["rounds"][0]["brief"]["business_type"]
    except (KeyError, IndexError, TypeError):
        return None


def load_recording(business_type: str | None = None) -> dict[str, Any] | None:
    """The recording to replay for this business type (None = any)."""
    if config.DEMO_RUN_FILE:
        forced = _read(Path(config.DEMO_RUN_FILE))
        if forced:
            return forced
    if business_type and (rec := _read(RUNS_DIR / f"demo_{business_type}.json")):
        return rec
    if RUNS_DIR.is_dir():
        for p in sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            rec = _read(p)
            if rec and (business_type is None or recording_type(rec) == business_type):
                return rec
    return None


def _read(p: Path) -> dict[str, Any] | None:
    try:
        rec = json.loads(p.read_text())
        return rec if rec.get("rounds") else None
    except (OSError, ValueError):
        return None
