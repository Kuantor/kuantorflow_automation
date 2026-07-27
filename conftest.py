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


@pytest.fixture(autouse=True)
def settings_dir(tmp_path, monkeypatch):
    """Redirect the settings store to a per-test temp directory.

    Autouse because the store creates a config file on first read (#86), so
    any test that renders a page would otherwise write into the real
    kuantorflow checkout's settings/ directory."""
    import settings_store

    directory = tmp_path / "settings"
    monkeypatch.setattr(settings_store, "SETTINGS_DIR", directory)
    return directory


@pytest.fixture(autouse=True)
def action_logs(tmp_path, monkeypatch):
    """Redirect the action logs (kuantorflow#30) to a per-test temp directory.

    Autouse for the same reason as settings_dir: any test that saves a card,
    looks a word up or uploads a file writes a log line, which would otherwise
    land in the real kuantorflow checkout's logs/ directory."""
    import applog

    directory = tmp_path / "logs"
    monkeypatch.setattr(applog, "LOGS_DIR", directory)
    return directory


@pytest.fixture(autouse=True)
def chat_logs(tmp_path, monkeypatch):
    """Redirect Mykola's chat logs to a per-test temp directory.

    Same reason as settings_dir and action_logs: the chat endpoint appends a
    log file per exchange, and a restarted chat (ai_agent#54) opens one — all
    of which otherwise pile up in the real kuantorflow checkout's
    mykola_logs/. Tests that need a pre-existing conversation write it here."""
    import app as app_mod

    directory = tmp_path / "mykola_logs"
    directory.mkdir()
    monkeypatch.setattr(app_mod, "LOG_DIR", directory)
    return directory


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
    # Default: no word already exists, so lookup tests reach the review popup
    # without touching a real DB (#145). Tests opt in by re-patching this.
    monkeypatch.setattr(app_mod, "flashcard_word_exists", lambda word: False,
                        raising=False)
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


TEST_USER_EMAIL = "test.user@gmail.com"


@pytest.fixture()
def user_client(client):
    """A test client through the gate AND signed in (session identity only).

    Changing settings requires a signed-in user since kuantorflow#102 —
    anonymous visitors share config-default.json, which is read-only for
    them. Settings saved through this client land in
    config-test.user.json."""
    with client.session_transaction() as sess:
        sess["user"] = {"name": "Test User", "email": TEST_USER_EMAIL}
    return client
