"""`web.py` is what every module may import (kuantorflow#418, step four).

Two properties hold the split up, and neither is visible in a passing run of
anything else.

**The import is one-directional.** `web.py` owns the Flask object and the
identity helpers precisely so that `rounds.py` can ask "is this visitor an
admin?" without importing the route table. One `from app import ...` inside
`web.py` closes the loop and the ticket is over -- and it would not fail
loudly, because Python resolves a cycle often enough to look fine.

**`app.py` reaches the helpers through the module.** `web.is_admin()`, never a
copy bound at import. That is #436's rule, and here is what it buys: one
`monkeypatch.setattr("web.current_settings", ...)` reaches `app.py`,
`cards_owner_filter()` inside `web.py`, and whatever module is written next.
A bare `is_admin()` in `app.py` would still work -- and would quietly be the
one call site a stub cannot reach. Moving this cluster cost 39 failures before
the suite's patches followed it; every one was this.
"""

import ast
from pathlib import Path

import pytest


# The names that moved. Written out rather than derived from `web.py`, because
# deriving them would make this test agree with any future move by definition:
# the question is whether *these* are reached correctly, not whether the file
# is self-consistent.
MOVED = {
    "_current_email", "DELETE_NOT_YOURS", "DELETE_SIGN_IN_PROMPT",
    "EDIT_NOT_YOURS", "EDIT_SIGN_IN_PROMPT", "MOVE_NOT_YOURS",
    "MOVE_SIGN_IN_PROMPT", "ADD_SIGN_IN_PROMPT", "SIGN_IN_TO_DELETE_ACCOUNT",
    "ADMIN_ACCOUNT_UNDELETABLE", "current_block", "is_blocked",
    "blocked_notice", "can_add_cards", "add_refusal", "can_delete_card",
    "_card_refusal", "can_move_card", "move_refusal", "can_edit_card",
    "edit_refusal", "delete_refusal", "is_admin", "_current_user_id",
    "_identity_token", "cards_owner_filter", "viewer", "current_settings",
    "_sections_for_visitor", "_private_marks",
    # The spending guards, which followed them (#418): the same question in the
    # same shape -- may this visitor do this, and if not, what are they told --
    # for the two actions that cost money.
    "_lookup_refusal", "LOOKUP_ANON_LIMIT", "LOOKUP_USER_DAILY",
    "LOOKUP_ANON_DAILY", "LOOKED_UP_COUNT_KEY", "LOOKUP_SIGN_IN_PROMPT",
    "LOOKUP_USER_LIMIT_PROMPT", "LOOKUP_BUSY_PROMPT",
    "_generation_refusal", "_generation_available", "GENERATION_ANON_LIMIT",
    "GENERATION_USER_DAILY", "GENERATION_DAILY_LIMIT", "GENERATED_COUNT_KEY",
    "GENERATION_SIGN_IN_PROMPT", "GENERATION_USER_LIMIT_PROMPT",
    "GENERATION_BUSY_PROMPT",
}


def _source(app_module, name):
    return Path(app_module.app.root_path, name).read_text(encoding="utf-8")


@pytest.fixture()
def web_tree(app_module):
    return ast.parse(_source(app_module, "web.py"))


@pytest.fixture()
def app_tree(app_module):
    return ast.parse(_source(app_module, "app.py"))


def _imports(tree):
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("module", ["web.py", "icons.py", "cards.py",
                                    "rounds.py", "chat.py"])
def test_no_shared_module_imports_app(app_module, module):
    """The loop that would end the split.

    The dependency runs one way -- `web.py` <- `rounds.py` <- `app.py` -- and
    every module #418 still has to write joins the left of that chain. One
    `import app` anywhere in it and the route table comes along, which is the
    whole thing the ticket is undoing.
    """
    tree = ast.parse(_source(app_module, module))
    assert "app" not in _imports(tree), (
        "%s imports app.py, which closes the import loop #418 exists to open: "
        "a feature module taking `app` from it would pull the whole route "
        "table in behind it" % module)


@pytest.mark.parametrize("module", ["cards", "chat", "icons", "rounds"])
def test_the_feature_modules_are_imported_for_their_side_effects(app_tree,
                                                                 module):
    """`app.py` asks them for nothing — routes, context processors, Jinja
    filters and `GAME_ROUNDS` all register themselves. A `from <module> import
    ...` would mean something had been left half-moved.

    `cards` is the one exception worth stating: `app.py` *does* reach
    `cards._save_and_log()` and `cards.DEFAULT_TOPIC`, because Mykola's saver
    still lives in `app.py` until it moves. It reaches them **through the
    module**, which is the rule, so there is still no `from cards import`.
    """
    assert module in _imports(app_tree), "app.py does not import " + module
    assert not [n for n in ast.walk(app_tree)
                if isinstance(n, ast.ImportFrom) and n.module == module], (
        "app.py imports a name back out of %s.py" % module)


def test_web_defines_the_identity_helpers(web_tree):
    """The half that would make the rest of this file vacuous — every
    assertion below passes trivially against a web.py that holds nothing."""
    defined = set()
    for node in web_tree.body:
        if isinstance(node, ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            defined.update(t.id for t in node.targets
                           if isinstance(t, ast.Name))
    assert MOVED <= defined, "not in web.py: %s" % sorted(MOVED - defined)


def test_app_calls_the_helpers_through_the_module(app_tree):
    """The rule a new route would break without noticing.

    A bare `is_admin()` in `app.py` reads the copy bound by the import below
    it, so a stub on `web.is_admin` does not reach it — and nothing goes red,
    because the real function still answers. It is the failure mode #436 was
    filed for, one module along.
    """
    bare = []
    for node in ast.walk(app_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in MOVED:
                bare.append("line %d: %s()" % (node.lineno, node.func.id))
    assert not bare, (
        "app.py calls these without going through the module, so a patch on "
        "web.<name> cannot reach them: " + "; ".join(bare))


def test_the_names_stay_reachable_on_app(app_module):
    """Both spellings valid, on purpose. A handful of tests call
    `app_module.is_admin()` rather than patch it, and binding the names back
    into `app.py` costs nothing — this is the assertion that says the binding
    is deliberate rather than left over."""
    missing = [n for n in sorted(MOVED) if not hasattr(app_module, n)]
    assert not missing, "no longer reachable as app.<name>: %s" % missing


def test_one_patch_reaches_a_caller_inside_web(app_module, monkeypatch):
    """The property all of the above is protecting, asserted directly.

    `cards_owner_filter()` lives in `web.py` and reads `current_settings()`
    there — a second hop, inside the module, that no route makes visible. The
    first version of this test fetched a page and asserted the stub had been
    called at all; it passed with the hop deliberately broken, because
    `inject_settings` in `app.py` calls `web.current_settings()` too and
    satisfied the assertion on its own. So this asks the two-hop function for
    its answer instead, where a stale binding changes the value.
    """
    import web

    monkeypatch.setattr("web.current_settings",
                        lambda: {"individual_cards": True})
    monkeypatch.setattr("web._current_user_id", lambda: 7)

    with app_module.app.test_request_context("/"):
        owner = web.cards_owner_filter()

    assert owner == 7, (
        "cards_owner_filter() did not see the patched current_settings, so it "
        "is reading a copy bound at import rather than the module attribute")
