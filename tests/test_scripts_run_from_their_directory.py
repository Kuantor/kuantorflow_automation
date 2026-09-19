"""The console one-offs still run from `scripts/` (kuantorflow#442).

Five scripts moved out of the repo root, and every one of them imports the
app's own modules -- `utils`, `applog`, `settings_store`, `parsers` -- because
doing the job through the code the site runs is the whole point of them.

**That move is invisible to the rest of this suite, which is the problem.**
`conftest.py` puts both the repo root *and* `scripts/` on `sys.path`, so
`import seed_topics` works here whether or not the script could ever run on
its own. A script that forgot `_bootstrap` would import cleanly in every test
in this repository and die on the deployment, at the one moment somebody is
following the deploy instructions in CLAUDE.md.

So these tests run the scripts the way a person does: a subprocess, from the
repo root, with nothing arranged for them. `--help` is enough -- argparse
cannot print anything until the module-level imports have all succeeded, which
is exactly the failure being guarded.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

SCRIPTS = Path(KUANTORFLOW_PATH) / "scripts"

# The app modules a script may reach for. `seed_words` is in the list because
# `seed_topics` imports it, and it is deliberately *not* one of the runnable
# scripts below: it holds the word list and imports nothing at all.
APP_MODULES = {"utils", "applog", "settings_store", "parsers", "games",
               "web", "seed_words"}

RUNNABLE = ["apply_schema.py", "claim_flashcards.py", "claim_topics.py",
            "retopic.py", "seed_topics.py"]


def _tree(name):
    return ast.parse((SCRIPTS / name).read_text(encoding="utf-8"))


def test_the_scripts_are_where_the_deploy_instructions_say():
    """A guard against every assertion below passing over an empty list."""
    found = sorted(p.name for p in SCRIPTS.glob("*.py")
                   if not p.name.startswith("_"))
    assert found == sorted(RUNNABLE + ["seed_words.py"]), found


@pytest.mark.parametrize("name", RUNNABLE)
def test_it_can_be_run_from_the_repo_root(name):
    """The thing the move could break, checked the way it would break.

    No `sys.path` help, no cwd trickery beyond standing in the repo as the
    deploy instructions do. If `_bootstrap` were missing this dies on
    `import utils` with a traceback, and prints nothing.
    """
    done = subprocess.run(
        [sys.executable, str(Path("scripts") / name), "--help"],
        capture_output=True, text=True, cwd=KUANTORFLOW_PATH)

    assert done.returncode == 0, (
        "%s could not be run from the repo root:\n%s" % (name, done.stderr))
    assert "usage" in done.stdout.lower()


@pytest.mark.parametrize("name", RUNNABLE)
def test_it_puts_the_repo_on_the_path_before_reaching_for_the_app(name):
    """The rule, stated as well as exercised.

    The subprocess above is the real check; this one names the reason, so a
    failure says *what to do* rather than only that an import died. The order
    matters and is the only import in these files that does: `_bootstrap` is
    what makes the line after it resolvable.
    """
    tree = _tree(name)
    bootstrap = app = None
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = {node.module.split(".")[0]}
        else:
            continue
        if "_bootstrap" in names and bootstrap is None:
            bootstrap = node.lineno
        if names & APP_MODULES and app is None:
            app = node.lineno

    assert app, "%s imports nothing from the app; is it still a script?" % name
    assert bootstrap, (
        "%s imports the app but not `_bootstrap`, so running it from the repo "
        "root cannot find `utils` -- add `import _bootstrap` above it" % name)
    assert bootstrap < app, (
        "%s imports the app before `_bootstrap`, which is too late" % name)


def test_seed_words_needs_no_bootstrap():
    """It holds data and imports nothing, which is why it is the one file here
    that is not in `RUNNABLE` and carries no bootstrap. Asserted so that
    "it was forgotten" and "it does not need one" stay different facts."""
    imports = [n for n in _tree("seed_words.py").body
               if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not imports, "seed_words.py has grown imports: %s" % [
        ast.unparse(n) for n in imports]


def test_apply_schema_still_finds_the_file_it_applies():
    """`schema.sql` stayed in the repo root while the script moved down a
    level, so its `__file__`-relative path had to change. This is the kind of
    path #442 records as failing *silently* under a further move -- here it
    would at least fail loudly, but only when somebody deploys."""
    import apply_schema

    assert apply_schema.SCHEMA_PATH.exists(), (
        "apply_schema.py cannot find schema.sql at %s" % apply_schema.SCHEMA_PATH)
    assert apply_schema.SCHEMA_PATH.parent == Path(KUANTORFLOW_PATH), (
        "schema.sql is expected in the repo root, not beside the script")


# --- the paths the database tier points at ----------------------------------

def _repo_paths(source):
    """Every `KUANTORFLOW_PATH / "a" / "b"` literal in a module's source."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            continue
        parts, cur = [], node
        while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
            if not isinstance(cur.right, ast.Constant) or not isinstance(cur.right.value, str):
                break
            parts.insert(0, cur.right.value)
            cur = cur.left
        else:
            if isinstance(cur, ast.Name) and cur.id == "KUANTORFLOW_PATH" and parts:
                found.append(tuple(parts))
    return found


def test_the_database_tier_still_points_at_files_that_exist():
    """The failure this test exists for cost 127 tests and said nothing.

    Every `*_db.py` gates itself on `_prerequisites_met()`, and that predicate
    includes `SCRIPT.exists()` beside the environment checks. So when
    kuantorflow#442 moved `apply_schema.py` into `scripts/`, the whole database
    tier stopped running — and pytest reported it as **skipped**, which is what
    it reports when the switch is simply off. Nothing was red. The only signal
    was the run finishing in a minute instead of four.

    A missing script is not an environment prerequisite, it is a broken
    checkout, so it belongs in an assertion rather than in a skip. This is that
    assertion, for every path the tier names, derived from the files rather
    than listed here.
    """
    root = Path(KUANTORFLOW_PATH)
    missing = []
    seen = 0
    for module in sorted(Path(__file__).parent.glob("*_db.py")):
        for parts in _repo_paths(module.read_text(encoding="utf-8")):
            seen += 1
            if not root.joinpath(*parts).exists():
                missing.append("%s -> %s" % (module.name, "/".join(parts)))

    assert seen, "no repo paths found; this test has stopped looking at anything"
    assert not missing, (
        "the database tier gates itself on these existing, so a missing one "
        "turns the whole tier into a silent skip: " + "; ".join(missing))
