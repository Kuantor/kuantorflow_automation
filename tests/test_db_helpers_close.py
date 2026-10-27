"""Every connection a DB test opens is closed in `finally` (found during kuantorflow#210).

The real-MySQL tests build scratch databases and drop them in their fixtures.
Their helpers used to close a connection only after every statement had
succeeded. When one failed, the connection stayed open holding its lock on the
table the statement touched, pytest kept it alive in the saved traceback, and
the fixture's `DROP DATABASE` then waited on it for ever: **one failing test
hung the whole tier**, twice while #210 was built. The fix is `try/finally`.

Read from the test files themselves, not listed: every function in a
`tests/*_db.py` file (and `conftest.py`) that assigns a connection from
`_connect()`, `get_db_connection()` or `connect()` must close it inside a
`finally` block, so a helper written next month is held to it too.
`test_db_helpers_close_db.py` shows the hang itself against real MySQL.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted((ROOT / "tests").glob("*_db.py")) + [ROOT / "conftest.py"]
OPENERS = {"_connect", "get_db_connection", "connect"}


def _opener(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)


def _unguarded_closes(path):
    """`[(function, line)]` where a connection it opened is closed outside `finally`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        opened = {n.targets[0].id for n in ast.walk(fn)
                  if isinstance(n, ast.Assign) and len(n.targets) == 1
                  and isinstance(n.targets[0], ast.Name)
                  and isinstance(n.value, ast.Call) and _opener(n.value) in OPENERS}
        if not opened:
            continue
        guarded = {id(node) for t in ast.walk(fn) if isinstance(t, ast.Try)
                   for stmt in t.finalbody for node in ast.walk(stmt)}
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "close"
                    and getattr(node.func.value, "id", None) in opened
                    and id(node) not in guarded):
                found.append((fn.name, node.lineno))
    return found


def test_the_rule_reaches_the_files_it_is_about():
    # Guards the derivation: if the file list or the parse came back empty,
    # the check below would pass over nothing.
    assert len(FILES) > 20
    assert any(_opens_a_connection(p) for p in FILES)


def _opens_a_connection(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(isinstance(n, ast.Call) and _opener(n) in OPENERS for n in ast.walk(tree))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_connection_is_closed_in_finally(path):
    assert _unguarded_closes(path) == [], (
        f"{path.name}: close these connections in `finally`, or one failed "
        "statement hangs the whole DB tier")
