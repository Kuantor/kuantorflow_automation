"""Where `ANTHROPIC_API_KEY` comes from, and what happens when it does not
(kuantorflow#412).

Three paid features need that key and none of them is Mykola: the Claude
translator in `parsers.TRANSLATORS`, #237's generated text and #406's topic
builder. The code was always separate -- each builds its own client and none
touches `MykolaAgent`. The **key** was not: it reached the process only because
importing the agent loads `ai_agent/.env`.

Two things are pinned here, and neither is about Mykola working.

**Precedence**, because the whole fix rests on it. `utils.py` loads this repo's
`.env` before the agent import, and `load_dotenv` does not override a value that
is already set — so a key in `kuantorflow/.env` wins and the agent's copy is a
fallback. If that ever inverted, the deployment would silently go back to
depending on a repo it does not use, and nothing else would notice.

**The silence**, because it is what made the coupling dangerous rather than
merely untidy. A missing agent is a *supported* state — the two repos deploy in
either order — so the import is caught and must stay caught. It just may not be
quiet about it: that same catch used to take the lookup's only configured
translator and two activities with it, three graceful degradations firing at
once from one invisible cause.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


AUTO_ROOT = Path(__file__).resolve().parent.parent
KUANTORFLOW_PATH = Path(os.environ.get(
    "KUANTORFLOW_PATH", str(AUTO_ROOT.parent.parent / "kuantorflow")))


# --- precedence, which is the whole mechanism -------------------------------

def test_a_value_in_this_repos_env_wins_over_the_agents(tmp_path):
    """The claim the fix rests on, tested rather than assumed.

    Both files are loaded in the order `app.py` loads them: `utils.py` at
    import line 40, then `ai_agent/agent.py` at 215.
    """
    from dotenv import load_dotenv

    (tmp_path / "app.env").write_text("KF_PROBE=from-kuantorflow\n")
    (tmp_path / "agent.env").write_text("KF_PROBE=from-ai-agent\n")
    os.environ.pop("KF_PROBE", None)
    try:
        load_dotenv(tmp_path / "app.env")
        load_dotenv(tmp_path / "agent.env")

        assert os.environ["KF_PROBE"] == "from-kuantorflow"
    finally:
        os.environ.pop("KF_PROBE", None)


def test_the_agents_copy_still_works_when_it_is_the_only_one(tmp_path):
    """Which is what makes the deploy step additive and reversible: adding the
    key here changes nothing for a deployment that has not, and deleting it
    restores the old behaviour exactly."""
    from dotenv import load_dotenv

    (tmp_path / "agent.env").write_text("KF_PROBE=from-ai-agent\n")
    os.environ.pop("KF_PROBE", None)
    try:
        load_dotenv(tmp_path / "agent.env")

        assert os.environ["KF_PROBE"] == "from-ai-agent"
    finally:
        os.environ.pop("KF_PROBE", None)


def test_neither_dotenv_call_overrides_the_real_environment(tmp_path):
    """PythonAnywhere's own environment, and the test suite's `monkeypatch`,
    both set variables directly. Neither file may quietly replace them."""
    from dotenv import load_dotenv

    (tmp_path / "app.env").write_text("KF_PROBE=from-a-file\n")
    os.environ["KF_PROBE"] = "from-the-environment"
    try:
        load_dotenv(tmp_path / "app.env")

        assert os.environ["KF_PROBE"] == "from-the-environment"
    finally:
        os.environ.pop("KF_PROBE", None)


def test_the_app_loads_its_own_env_before_the_agents():
    """The ordering the precedence above depends on, asserted against the source.

    The two `load_dotenv` calls are in different repositories and neither knows
    about the other; what decides which wins is purely that `app.py` imports
    `utils` before it imports `agent`. Move the agent import upward for any
    reason and the deployment silently goes back to taking its key from a repo
    it does not use -- with every other test here still green, because dotenv's
    behaviour would not have changed at all.
    """
    source = (KUANTORFLOW_PATH / "app.py").read_text(encoding="utf-8")

    assert source.index("from utils import") < source.index("from agent import")


# --- the key is documented where it is now read from ------------------------

def test_env_example_gives_the_default_translator_a_slot():
    """It had none. Every other translator key had a `KEY=` line and the one
    the app defaults to did not, which is the coupling written down: the file
    said Claude was the default and offered nowhere to configure it."""
    example = (KUANTORFLOW_PATH / ".env.example").read_text(encoding="utf-8")

    assert "\nANTHROPIC_API_KEY=" in example


def test_the_deploy_notes_no_longer_send_the_key_to_the_agents_env():
    """`CLAUDE.md` is what a deploy is read from, and it said the opposite."""
    guidance = (KUANTORFLOW_PATH / "CLAUDE.md").read_text(encoding="utf-8")
    at = guidance.index("ANTHROPIC_API_KEY` belongs in")

    passage = guidance[at:at + 1600]
    assert "kuantorflow/.env" in passage[:200]
    # The duplication is deliberate and has a cost; the passage has to say so,
    # because a rotation that happens in one file and not the other puts the
    # app and Mykola on different keys with nothing to report it. Scoped to the
    # passage rather than the file, and on the whole phrase rather than its
    # words: the sentence above this one *also* contains "both files" -- "with
    # both files set, this one is used" -- so deleting the rotation warning
    # entirely still left a version of this assertion green. Proved by deleting
    # it, which is the only reason that was noticed.
    assert "rotating **both files**" in passage


# --- what a missing agent does, and no longer does quietly ------------------

def _app_python():
    """The **app's own** interpreter, not the suite's.

    `import app` pulls in the agent, which needs dependencies installed in
    kuantorflow's venv rather than this repo's. Running it under
    `sys.executable` makes every one of these answers `MYKOLA_AVAILABLE=False`
    for the wrong reason -- which is how the "nothing is logged when the agent
    loads" test came to skip on a machine where the agent loads perfectly well.
    """
    for candidate in ("venv/Scripts/python.exe", "venv/bin/python"):
        found = KUANTORFLOW_PATH / candidate
        if found.exists():
            return str(found)
    return sys.executable


def _import_app(tmp_path, **env):
    """Import the app in a fresh process with the environment given."""
    script = (
        "import sys, os, json\n"
        f"sys.path.insert(0, {str(KUANTORFLOW_PATH)!r})\n"
        "import app\n"
        "print(json.dumps({'mykola': app.MYKOLA_AVAILABLE,\n"
        "                  'generation': app._generation_available()}))\n"
    )
    done = subprocess.run(
        [_app_python(), "-c", script], capture_output=True, text=True,
        env={**os.environ, "KF_LOGS_DIR": str(tmp_path), **env},
        cwd=str(KUANTORFLOW_PATH))
    assert done.returncode == 0, done.stderr
    import json
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.fixture()
def no_agent(tmp_path):
    return {"AI_AGENT_PATH": str(tmp_path / "there-is-no-agent-here")}


def test_a_missing_agent_does_not_stop_the_app(tmp_path, no_agent):
    """The supported state, and it must stay supported: the two repos deploy in
    either order, so the import is caught on purpose."""
    answer = _import_app(tmp_path, **no_agent, ANTHROPIC_API_KEY="")

    assert answer["mykola"] is False


def test_the_paid_features_survive_a_missing_agent(tmp_path, no_agent):
    """#412 in one assertion. Before it, the key arrived *through* the agent, so
    these two answers could never disagree."""
    answer = _import_app(tmp_path, **no_agent, ANTHROPIC_API_KEY="a-key")

    assert answer["mykola"] is False
    assert answer["generation"] is True


def test_a_failed_agent_import_says_why(tmp_path, no_agent):
    """The line that did not exist. A supported state is still worth one
    sentence, because the alternative is three features going quiet at once and
    nothing anywhere saying that the agent could not be loaded."""
    _import_app(tmp_path, **no_agent, ANTHROPIC_API_KEY="a-key")

    written = (tmp_path / "mykola.log").read_text(encoding="utf-8")

    assert "AGENT-UNAVAILABLE" in written
    assert "error=" in written, "the cause, not just the fact"


def test_nothing_is_logged_when_the_agent_loads(tmp_path):
    """A supported state that *worked* is not an event. This would otherwise
    write a line on every import in every environment that has the agent."""
    answer = _import_app(tmp_path)
    if not answer["mykola"]:
        pytest.skip("ai_agent is not importable in this environment")

    log = tmp_path / "mykola.log"

    assert not log.exists() or "AGENT-UNAVAILABLE" not in log.read_text(
        encoding="utf-8")
