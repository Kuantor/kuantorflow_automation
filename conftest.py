"""
Shared fixtures for the KuantorFlow test suite.

The app-level tests import the Flask app from the kuantorflow repository
(path from KUANTORFLOW_PATH in .env, defaulting to a sibling checkout)
and stub out the database and external services — they run fully offline
and never write anywhere.
"""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

KUANTORFLOW_PATH = os.environ.get(
    "KUANTORFLOW_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "kuantorflow"),
)
sys.path.insert(0, KUANTORFLOW_PATH)

# Keyword used by the app-level tests (patched into the app; the real
# keyword from .env is only used by the live site tests).
TEST_KEYWORD = "test-keyword"


@pytest.fixture()
def keyword():
    return TEST_KEYWORD


@pytest.fixture()
def app_module(monkeypatch):
    """The imported app module with a known gate keyword and a stubbed
    topic list (so no test touches a real database by accident)."""
    import app as app_mod

    monkeypatch.setattr(app_mod, "ACCESS_KEYWORD", TEST_KEYWORD)
    monkeypatch.setattr(app_mod, "get_topics", lambda: [])
    return app_mod


@pytest.fixture()
def saved(app_module, monkeypatch):
    """Capture save_flashcard() calls instead of writing to MySQL."""
    captured = []
    monkeypatch.setattr(
        app_module, "save_flashcard", lambda entry: captured.append(entry) or 1
    )
    return captured


@pytest.fixture()
def client(app_module):
    """A test client already through the keyword gate."""
    c = app_module.app.test_client()
    resp = c.post("/enter", data={"keyword": TEST_KEYWORD})
    assert resp.status_code == 302, "gate login failed in fixture"
    return c


@pytest.fixture()
def fresh_client(app_module):
    """A test client with no session — still outside the gate."""
    return app_module.app.test_client()
