"""Hestia API server (README §5.3 routes, §5.4 event stream).

    uvicorn server.app:app --reload --port 8000
    DEMO=1 uvicorn server.app:app --port 8000      # replay a recorded run (works offline)

SSE: GET /api/runs/{id}/events streams every event since the start (or since Last-Event-ID /
?after=<seq>), then keeps the connection open with heartbeats so feedback rounds arrive on the
same stream. Pass ?follow=0 to close as soon as the run is idle (handy for curl and tests).
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent import config
from agent import providers as P
from agent import samples
from server.runs import RunManager
from shared.conventions import ASSETS_DIR, CATALOG_PATH, MEDIA_DIR
from shared.schemas import (
    CandidateResult,
    CatalogItem,
    CreateRunRequest,
    CreateRunResponse,
    FeedbackRequest,
    RunStatus,
    Space,
)

app = FastAPI(title="Hestia API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["*"])
runs = RunManager()

HEARTBEAT_S = 15.0
POLL_S = 0.15


def _run_or_404(run_id: str):
    run = runs.get(run_id)
    if not run:
        raise HTTPException(404, f"unknown run {run_id}")
    return run


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mode": runs.mode(), "replay_types": sorted(config.DEMO_REPLAY),
            "llm_provider": config.LLM_PROVIDER, "providers": P.SOURCES}


@app.post("/api/runs", response_model=CreateRunResponse)
def create_run(req: CreateRunRequest) -> CreateRunResponse:
    if not req.text.strip() and not req.brief:
        raise HTTPException(422, "text is empty")
    return CreateRunResponse(run_id=runs.create(req.text, req.brief).run_id)


@app.get("/api/runs/{run_id}", response_model=RunStatus)
def run_status(run_id: str) -> RunStatus:
    return _run_or_404(run_id).status()


@app.get("/api/runs/{run_id}/results", response_model=list[CandidateResult])
def run_results(run_id: str) -> list[CandidateResult]:
    return _run_or_404(run_id).results()


@app.post("/api/runs/{run_id}/feedback", response_model=RunStatus)
def run_feedback(run_id: str, req: FeedbackRequest) -> RunStatus:
    run = _run_or_404(run_id)
    prev_round = run.ctx.round if run.ctx else 0
    try:
        runs.feedback(run, req)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    st = run.status()
    st.round = prev_round + 1  # the new round runs in the background; it may already have advanced
    if st.state == "done" and run.ctx and run.ctx.round == prev_round:
        st.state = "running"
    return st


@app.get("/api/runs/{run_id}/files")
def run_files(run_id: str) -> dict[str, str]:
    """The agent's virtual filesystem (brief, shortlist, per-candidate files, memos). Debug/extra UI."""
    run = _run_or_404(run_id)
    return dict(run.ctx.fs) if run.ctx else {}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, after: int | None = None, follow: int = 1) -> StreamingResponse:
    run = _run_or_404(run_id)
    last = request.headers.get("last-event-id")
    start_after = after if after is not None else (int(last) if last and last.isdigit() else 0)

    async def stream():
        yield "retry: 2000\n\n"
        idx = next((i for i, e in enumerate(run.events) if e.seq > start_after), len(run.events))
        last_beat = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            while idx < len(run.events):
                ev = run.events[idx]
                idx += 1
                yield f"id: {ev.seq}\nevent: {ev.type}\ndata: {ev.model_dump_json()}\n\n"
                last_beat = time.monotonic()
            if run.state in ("done", "error") and idx >= len(run.events) and not follow:
                return
            if time.monotonic() - last_beat > HEARTBEAT_S:
                yield ": ping\n\n"
                last_beat = time.monotonic()
            await asyncio.sleep(POLL_S)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/spaces/{space_id}", response_model=Space)
def space(space_id: str) -> Space:
    try:
        return P.get_space(space_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"unknown space {space_id}: {e}") from e


@app.get("/api/catalog", response_model=list[CatalogItem])
def catalog() -> list[CatalogItem]:
    if CATALOG_PATH.is_file():
        return [CatalogItem.model_validate(x) for x in json.loads(CATALOG_PATH.read_text())]
    return samples.CATALOG


# Static files: media/... (generated/downloaded, data/media) and assets/... (committed).
app.mount("/media", StaticFiles(directory=MEDIA_DIR, check_dir=False), name="media")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR, check_dir=False), name="assets")


def main() -> None:
    import os

    import uvicorn

    uvicorn.run("server.app:app", host=os.getenv("API_HOST", "127.0.0.1"), port=int(os.getenv("API_PORT", "8000")))


if __name__ == "__main__":
    main()
