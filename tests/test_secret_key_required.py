"""The session cookie cannot be signed with a key anybody knows (kuantorflow#445).

A Flask session cookie is **signed, not encrypted**. Its payload is plain
base64 that anyone can read; the signature is the only thing that stops a
visitor writing their own -- one saying they are signed in, that their address
is verified, and that it is the admin's. `is_admin()` is careful to require
`email_verified` (#158), but that field lives *inside* the cookie, so every
check that reads the session sits downstream of the signature.

`web.py` used to fall back to the literal "dev-secret-change-me" when
`SECRET_KEY` was unset -- a string published in the repository, which made the
signature worth nothing. #274 hardened the same cookie's `Secure`, `SameSite`
and `HttpOnly` flags; all three protect it *in transit*, and none of them is
relevant to a cookie written from scratch.

The rule now: a configured key is used, `python app.py` alone falls back to a
**random** key for that run, and every other way of starting refuses.

**These tests mostly run the app in a subprocess**, because an in-process test
cannot watch a module decline to import -- and because the refusal is a
property of starting up, which is the moment it has to happen.
"""

import os
import subprocess
import sys

import pytest

from conftest import KUANTORFLOW_PATH

PUBLISHED_DEFAULT = "dev-secret-change-me"

# An empty value rather than an absent one: `utils.py` calls `load_dotenv()`,
# which does not override a variable already in the environment (#412 relies on
# exactly that). So this neutralises whatever the developer has in their own
# .env, and the test asks the same question on every machine.
NO_KEY = {"SECRET_KEY": ""}


def _run(script, env=None, argv0=None):
    """Import the app in a fresh interpreter and report what happened."""
    args = [sys.executable, "-c", script] if argv0 is None else [sys.executable, argv0]
    return subprocess.run(args, capture_output=True, text=True,
                          cwd=str(KUANTORFLOW_PATH),
                          env={**os.environ, **(env or {})})


IMPORT_AND_REPORT = (
    "import sys; sys.path.insert(0, '.')\n"
    "import web\n"
    "print('KEY:' + web.app.secret_key)\n"
)


def test_it_refuses_to_start_without_a_key():
    """The whole ticket. A WSGI server, a console script and pytest all take
    this branch; only `python app.py` does not."""
    done = _run(IMPORT_AND_REPORT, NO_KEY)

    assert done.returncode != 0, (
        "the app started with no SECRET_KEY:\n" + done.stdout)
    assert "SECRET_KEY is not set" in done.stderr


def test_the_refusal_says_how_to_fix_it():
    """A refusal that stops a deploy has to be actionable in the console it
    prints to, not in a ticket somewhere."""
    done = _run(IMPORT_AND_REPORT, NO_KEY)

    assert "secrets.token_hex" in done.stderr, "no way to generate one"
    assert ".env" in done.stderr, "does not say where it goes"


def test_a_configured_key_is_used_exactly_as_given():
    done = _run(IMPORT_AND_REPORT, {"SECRET_KEY": "a-configured-key"})

    assert done.returncode == 0, done.stderr
    assert "KEY:a-configured-key" in done.stdout


def test_the_published_default_is_never_the_key():
    """The literal that caused this. It may still appear in `web.py` -- the
    docstring explains what it was -- but it must never come back as a value."""
    done = _run(IMPORT_AND_REPORT, {"SECRET_KEY": PUBLISHED_DEFAULT})
    assert "KEY:" + PUBLISHED_DEFAULT in done.stdout, (
        "sanity check: an explicitly configured key is used, even a bad one")

    refused = _run(IMPORT_AND_REPORT, NO_KEY)
    assert PUBLISHED_DEFAULT not in refused.stdout


# --- the one entry point that is allowed to start without one ---------------

LOCAL_PROBE = (
    "import sys\n"
    "sys.path.insert(0, %r)\n"
    "import web\n"
    "print('KEY:' + web.app.secret_key)\n"
)


def _as_app_py(tmp_path, env=None):
    """Run the probe from a file named `app.py`, which is the whole of what
    `web.py` tests for: `Path(sys.argv[0]).name`. Naming it anything else takes
    the refusing branch, which is the point of the test below."""
    probe = tmp_path / "app.py"
    probe.write_text(LOCAL_PROBE % str(KUANTORFLOW_PATH), encoding="utf-8")
    return _run(None, {**NO_KEY, **(env or {})}, argv0=str(probe))


def test_the_local_entry_point_still_starts_without_a_key(tmp_path):
    """`python app.py` is somebody's own machine, not a deployment. Refusing
    there would make a fresh clone unrunnable for no security gain."""
    done = _as_app_py(tmp_path)

    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("KEY:")


def test_and_says_so_loudly(tmp_path):
    """Silent would be the old bug wearing a different hat: the danger was
    never the fallback, it was not knowing there was one."""
    done = _as_app_py(tmp_path)

    assert "WARNING" in done.stderr
    assert "SECRET_KEY is not set" in done.stderr
    assert "restart" in done.stderr, "should say what the cost is"


def test_the_local_fallback_is_random_every_run(tmp_path):
    """The property that matters, and the reason this is not just the old
    default with better manners.

    A *fixed* fallback is forgeable the moment anyone reads the source; a
    random one cannot be guessed even if this check one day misjudges a real
    deployment as local. The cost is that sessions do not survive a restart,
    which is visible and harmless -- unlike the alternative.
    """
    first = _as_app_py(tmp_path)
    second = _as_app_py(tmp_path)

    assert first.returncode == second.returncode == 0
    assert first.stdout != second.stdout, (
        "two runs produced the same key, so it is predictable")
    assert PUBLISHED_DEFAULT not in first.stdout


def test_a_file_by_any_other_name_is_refused(tmp_path):
    """The check is narrow on purpose. A WSGI server, `flask run`, a console
    script and pytest all arrive with a different `sys.argv[0]`, and all of
    them are things that might be serving somebody other than the author."""
    probe = tmp_path / "wsgi.py"
    probe.write_text(LOCAL_PROBE % str(KUANTORFLOW_PATH), encoding="utf-8")

    done = _run(None, NO_KEY, argv0=str(probe))

    assert done.returncode != 0, "a file not named app.py was allowed to start"
    assert "SECRET_KEY is not set" in done.stderr


def test_the_suite_itself_takes_the_refusing_branch(tmp_path):
    """Worth stating, because it is why `conftest.py` sets a key at import.
    If pytest were treated as local, every test would run against a random key
    and this file would be testing nothing."""
    assert os.path.basename(sys.argv[0]) != "app.py"
