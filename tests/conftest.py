"""Shared test settings: tests never call paid or rate-limited image APIs.

agent/config.py and pipeline/db.py load .env, which may hold real keys. Hero images run in
preview mode and the image judge is off, unless a test sets them itself.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_image_api_calls(monkeypatch):
    monkeypatch.setenv("HERO_MODE", "preview")
    monkeypatch.setenv("SCORER_LLM", "0")


@pytest.fixture(scope="session")
def sample_db_path(tmp_path_factory):
    """Natnael's synthetic sample database (pipeline/sample_data.py), built once per test session.
    Placeholder panoramas are written to data/media/panos/sample-model-* (gitignored), like
    `python -m pipeline.sample_data` does, so hero images and the inspector have files to read."""
    from pipeline import sample_data

    return sample_data.build(tmp_path_factory.mktemp("db") / "sample.duckdb", images=True)


@pytest.fixture
def sample_db(sample_db_path, monkeypatch):
    """Point the real query functions at the sample database for one test (no LLM calls either)."""
    from pipeline import queries

    monkeypatch.setenv("HESTIA_DB_PATH", str(sample_db_path))
    monkeypatch.setattr("agent.llm.llm_available", lambda: False)
    monkeypatch.setattr("agent.runner.llm_available", lambda: False)
    for fn in (queries._neighborhood_cached, queries.market_rent_psf_year):
        fn.cache_clear()
    yield sample_db_path
    for fn in (queries._neighborhood_cached, queries.market_rent_psf_year):
        fn.cache_clear()
