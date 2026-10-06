"""Shared test setup.

* The database is an in-memory SQLite, created before `app` is imported.
* The LLM is forced offline for every test (even if GEMINI_API_KEY is set
  locally); tests that exercise the AI loop install their own stub.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite://"
os.environ.pop("ADMIN_EMAIL", None)
os.environ.pop("ADMIN_PASSWORD", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import ai_engine  # noqa: E402


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    monkeypatch.setattr(ai_engine, "_generate", lambda *a, **k: None)
    monkeypatch.setattr(ai_engine, "get_client", lambda: None)
    ai_engine._CACHE.clear()
    yield
    ai_engine._CACHE.clear()
