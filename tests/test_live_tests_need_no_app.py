"""A live smoke check must run where the app cannot be imported.

`test_live_site.py` imports `os`, `pytest` and `requests`, speaks HTTP to a
deployed site and has no use for an app object. That is the point of it: the
machine you want to run it from is the one that is *not* the development
machine — a deployment host, a CI runner, a laptop with the test runner and
none of the app's dependencies.

It could not. Two autouse fixtures in `conftest.py` imported the app for
**every** test in the suite (`chat_logs` directly, `block_state` by taking
`app_module` as a parameter), so a live test failed during *setup* with
`ModuleNotFoundError: No module named 'authlib'`.

**Three separate things hid this**, which is why it is worth a file rather
than a comment:

1. `-m live` deselects *after* collection, so the first symptom was 58
   collection errors from test modules that were never going to run.
2. Scoping by path fixed collection and left the setup failure — a different
   error, at a different phase, looking like a different bug.
3. With `SITE_URL` unset every live test skips itself. Six skips print in
   yellow and exit 0, which reads as success.

So the property is asserted from outside, in a subprocess with `authlib`
blocked, because nothing observable from inside this process can tell the
difference: here the app imports perfectly well.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


AUTO_ROOT = Path(__file__).resolve().parent.parent

# Runs pytest with `authlib` unimportable. A `sys.meta_path` finder rather
# than uninstalling anything: it is reversible, scoped to one process, and
# reproduces the only thing that matters about the deployment host — that one
# of the app's imports is not satisfiable.
BLOCKER = textwrap.dedent('''
    import sys

    class Blocker:
        def find_spec(self, name, path=None, target=None):
            if name == "authlib" or name.startswith("authlib."):
                raise ModuleNotFoundError("No module named 'authlib'")
            return None

    sys.meta_path.insert(0, Blocker())
    import pytest
    sys.exit(pytest.main(sys.argv[1:]))
''')


def _run_without_authlib(tmp_path, *args):
    """pytest, in a fresh process, with `authlib` unreachable."""
    runner = tmp_path / "no_authlib.py"
    runner.write_text(BLOCKER, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(runner), *args],
        capture_output=True, text=True, cwd=str(AUTO_ROOT),
        # A URL that cannot resolve: enough to get past the skipif without
        # any risk of a request leaving the machine.
        env={**os.environ, "SITE_URL": "https://example.invalid"})


def test_the_blocker_actually_blocks(tmp_path):
    """The control, and it is not ceremony.

    Every assertion below is of the form "this worked without authlib". If
    the blocker silently failed to block, they would all pass against a
    conftest that imports the app on every test — which is the bug, restored.
    """
    runner = tmp_path / "no_authlib.py"
    runner.write_text(BLOCKER.replace(
        "sys.exit(pytest.main(sys.argv[1:]))",
        "import authlib\nprint('NOT BLOCKED')"), encoding="utf-8")

    done = subprocess.run([sys.executable, str(runner)],
                          capture_output=True, text=True)

    assert "NOT BLOCKED" not in done.stdout
    assert "No module named 'authlib'" in done.stderr


def test_the_live_tests_collect_without_the_app(tmp_path):
    """Phase one: import. This is what `-m live` failed at, 58 times over,
    because the marker is applied after every test module is imported."""
    done = _run_without_authlib(tmp_path, "tests/test_live_site.py",
                                "--collect-only", "-q")

    assert done.returncode == 0, done.stdout[-3000:]
    assert "ModuleNotFoundError" not in done.stdout


def test_the_live_tests_set_up_without_the_app(tmp_path):
    """Phase two, and the one the fix is about.

    `--setup-only` runs every fixture for each test and then skips the body,
    so this exercises the whole autouse chain — `settings_dir`, `action_logs`,
    `chat_logs`, `block_state` — **without making a single HTTP request**.
    Collection alone would not have caught the bug: it passed.
    """
    done = _run_without_authlib(tmp_path, "tests/test_live_site.py",
                                "--setup-only", "-q")

    assert done.returncode == 0, done.stdout[-3000:]
    assert "authlib" not in done.stdout + done.stderr, (
        "a fixture still reached for the app during setup")


def test_every_live_test_is_covered_by_that(tmp_path):
    """The two cases above name one file. If a second live-marked file is
    added elsewhere, this is what notices — otherwise the guarantee quietly
    applies to whichever file happened to exist when it was written."""
    done = _run_without_authlib(tmp_path, "-m", "live", "--collect-only", "-q",
                                "tests/test_live_site.py")
    assert done.returncode == 0

    collected = [l for l in done.stdout.splitlines() if "::" in l]

    assert collected, "no live tests were collected at all"


# --- the marker is what the fixtures key on ---------------------------------

def test_a_live_test_gets_no_chat_log_directory(request):
    """Asserted from inside, on the fixture's own return value, because the
    subprocess cases above can only see that nothing blew up.

    `None` is the signal that the fixture declined: a live test has no app
    whose log directory could be redirected.
    """
    assert request.node.get_closest_marker("live") is None
    assert request.getfixturevalue("chat_logs") is not None, (
        "an ordinary test must still get its temp log directory")


@pytest.mark.live
def test_the_fixtures_decline_for_a_live_test(request, chat_logs, block_state):
    """The same thing the other way round, and it needs no network — it asks
    the fixtures what they returned rather than making a request, so it is
    safe to run with the live tier deselected.

    Marked `live` so it is deselected by default alongside the smoke checks;
    run it with `-m live` and it still makes no HTTP call.
    """
    assert request.node.get_closest_marker("live") is not None
    assert chat_logs is None, "chat_logs imported the app for a live test"
    assert block_state is None, "block_state imported the app for a live test"
