""".env.example states the code's numbers, every one of them (kuantorflow#645).

`.env.example` is what a new server's `.env` is copied from, and a set value
overrides the code's default. It had drifted: `ANONYMOUS_DAILY_LIMIT=200`
where the code says 15 -- larger than everybody's chat pool (40), so signed-out
visitors could use up the whole site's Mykola messages -- and
`GENERATION_DAILY_LIMIT=100` where the code says 60; fifteen of the twenty
numbers were not listed at all, and a comment still said signed-in users are
never limited.

The list is read from `web.py` -- every `NAME = _int_env("NAME", default)` --
never written here, so a new ceiling without an example line fails, and so
does an example line the code no longer reads.
"""

import ast
import re
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

ROOT = Path(KUANTORFLOW_PATH)
EXAMPLE_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def _code_defaults():
    """{NAME: default} for every `_int_env("NAME", default)` in web.py."""
    tree = ast.parse((ROOT / "web.py").read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_int_env"
                and len(node.args) == 2 and isinstance(node.args[0], ast.Constant)):
            found[node.args[0].value] = ast.literal_eval(node.args[1])
    return found


def _example():
    """{NAME: value} for every uncommented setting in .env.example."""
    out = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        match = EXAMPLE_LINE.match(line.strip())
        if match:
            out[match.group(1)] = match.group(2).strip()
    return out


def test_the_code_has_the_numbers_this_test_is_about():
    # Guards the derivation: an empty dict would make every check below pass.
    defaults = _code_defaults()
    assert len(defaults) >= 20
    assert {"ANONYMOUS_DAILY_LIMIT", "CHAT_ALL_DAILY", "CHECK_ALL_DAILY"} <= set(defaults)


@pytest.mark.parametrize("name", sorted(_code_defaults()))
def test_every_number_the_code_reads_is_in_the_example_at_its_default(name):
    example = _example()

    assert name in example, f"{name} is read by web.py but missing from .env.example"
    assert example[name] == str(_code_defaults()[name]), \
        f"{name}: .env.example says {example[name]}, the code's default is {_code_defaults()[name]}"


def test_the_example_names_no_ceiling_the_code_does_not_read():
    ceilings = {n for n in _example() if n.endswith(("_LIMIT", "_DAILY"))}
    # NOTIFY_LIMIT_PERCENT is notify.py's (#594), not a spending ceiling.
    ceilings.discard("NOTIFY_LIMIT_PERCENT")

    assert ceilings <= set(_code_defaults()), ceilings - set(_code_defaults())


def test_the_example_does_not_say_accounts_are_unlimited():
    text = (ROOT / ".env.example").read_text(encoding="utf-8").lower()

    assert "never limited" not in text
