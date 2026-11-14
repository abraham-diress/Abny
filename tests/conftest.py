"""Shared test settings: tests never call paid or rate-limited image APIs.

agent/config.py and pipeline/db.py load .env, which may hold real keys. Hero images run in
preview mode and the image judge is off, unless a test sets them itself.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_image_api_calls(monkeypatch):
    monkeypatch.setenv("HERO_MODE", "preview")
    monkeypatch.setenv("SCORER_LLM", "0")
