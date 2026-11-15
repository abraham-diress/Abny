import json
import time

import pytest
from fastapi.testclient import TestClient

from shared.schemas import AgentEvent, CandidateResult, RunStatus


@pytest.fixture()
def client(sample_db, monkeypatch, tmp_path):  # sample database + no LLM (tests/conftest.py)
    monkeypatch.setattr("server.runs.RUNS_DIR", tmp_path)
    from server.app import app

    return TestClient(app)


def _wait(client, run_id, rnd=0, timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        st = RunStatus.model_validate(client.get(f"/api/runs/{run_id}").json())
        if st.state in ("done", "error") and st.round == rnd:
            return st
        time.sleep(0.1)
    raise TimeoutError


def _events(client, run_id, after=0):
    with client.stream("GET", f"/api/runs/{run_id}/events?follow=0&after={after}") as r:
        body = "".join(r.iter_text())
    out = []
    for frame in body.split("\n\n"):
        lines = dict(l.split(": ", 1) for l in frame.splitlines() if ": " in l and not l.startswith(":"))
        if "data" in lines:
            ev = AgentEvent.model_validate_json(lines["data"])
            assert lines["event"] == ev.type and int(lines["id"]) == ev.seq
            out.append(ev)
    return out


def test_health(client):
    j = client.get("/api/health").json()
    assert j["status"] == "ok" and j["mode"] in ("scripted", "llm", "demo")


def test_run_lifecycle_and_feedback(client, tmp_path):
    rid = client.post("/api/runs", json={"text": "bakery in Houston, 20 seats, under $6k"}).json()["run_id"]
    st = _wait(client, rid)
    assert st.state == "done" and st.result_count > 0 and st.brief.city == "Houston"
    results = [CandidateResult.model_validate(r) for r in client.get(f"/api/runs/{rid}/results").json()]
    assert [r.rank for r in results] == sorted(r.rank for r in results)
    evs = _events(client, rid)
    assert evs[0].type == "run_started" and evs[-1].type == "run_finished"
    last = evs[-1].seq

    r = client.post(f"/api/runs/{rid}/feedback", json={"text": "fewer seats, closer to transit"})
    assert r.status_code == 200 and r.json()["round"] == 1
    st = _wait(client, rid, rnd=1)
    assert st.state == "done" and st.brief.seats_wanted == 15
    new = _events(client, rid, after=last)
    assert new[0].type == "feedback_received" and new[-1].payload["round"] == 1

    rec = json.loads((tmp_path / f"{rid}.json").read_text())
    assert len(rec["rounds"]) == 2


def test_demo_replay(client, monkeypatch, tmp_path):
    rid = client.post("/api/runs", json={"text": "bakery in Houston, 20 seats, under $6k"}).json()["run_id"]
    _wait(client, rid)
    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setattr("agent.config.DEMO_SPEED", 100.0)
    monkeypatch.setattr("server.runs.RUNS_DIR", tmp_path)
    assert client.get("/api/health").json()["mode"] == "demo"
    rid2 = client.post("/api/runs", json={"text": "anything"}).json()["run_id"]
    st = _wait(client, rid2)
    assert st.state == "done" and st.result_count > 0
    res = client.get(f"/api/runs/{rid2}/results").json()
    assert all(r["run_id"] == rid2 for r in res)


def test_unknown_and_catalog(client):
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/spaces/nope").status_code == 404
    assert client.get("/api/spaces/sample-hou-01").json()["city"] == "Houston"
    assert client.get("/api/spaces/sample-la-office-15").json()["city"] == "Los Angeles"
    assert len(client.get("/api/catalog").json()) >= 5


def test_replay_only_offices(client, monkeypatch, tmp_path):
    """README demo step 5: the bakery runs live while the office brief replays its recording."""
    import shutil

    from server.app import runs

    office = "Office for a 25-person team in downtown LA, near transit, under $20k/month"
    rec_id = client.post("/api/runs", json={"text": office}).json()["run_id"]
    _wait(client, rec_id)
    shutil.copy(tmp_path / f"{rec_id}.json", tmp_path / "demo_office.json")
    monkeypatch.setattr("agent.config.DEMO_REPLAY", {"office"})
    monkeypatch.setattr("agent.config.DEMO_SPEED", 100.0)

    oid = client.post("/api/runs", json={"text": office}).json()["run_id"]
    bid = client.post("/api/runs", json={"text": "bakery in Houston, 20 seats, under $6k"}).json()["run_id"]
    assert _wait(client, oid).result_count > 0 and _wait(client, bid).result_count > 0
    assert runs.get(oid).replay is not None and runs.get(bid).replay is None
    office_results = client.get(f"/api/runs/{oid}/results").json()
    assert office_results and all(r["run_id"] == oid and "office" in r["space"]["property_type"].lower() for r in office_results)


def test_space_rooms(client):
    r = client.get("/api/spaces/sample-hou-01/rooms")
    assert r.status_code == 200 and r.json() and "polygon_m" in r.json()[0]
    assert client.get("/api/spaces/nope/rooms").status_code == 404
