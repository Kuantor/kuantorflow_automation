"""Mykola knows the app, from the user guide (kuantorflow#310).

He used to answer questions about the site from a copy of its description kept
in `ai_agent/knowledge/kuantorflow_faq.md`, written in July and never updated —
by the end it was answering "why can't I add cards?" from a description written
before an account was needed to write at all. That copy is gone. The app now
hands the agent its **own** `docs/user-guide.md`, the same document it ships to
learners as a PDF.

What is worth testing here is the seam and the document, not the model: that
the guide is handed over, that it survives an older agent that cannot accept
it, and that it still describes the app as it is. Whether Mykola phrases the
answer well is the agent repo's business, and its `test_rag.py` covers the
retrieval half.
"""

import inspect
from pathlib import Path

import pytest


@pytest.fixture()
def guide(app_module):
    """The document Mykola is given, as text."""
    return Path(app_module.MYKOLA_KNOWLEDGE[0]).read_text(encoding="utf-8")


# --- the seam ---------------------------------------------------------------

def test_the_guide_is_what_gets_handed_over(app_module):
    """The learner's guide itself — not a second description written for him,
    which is the arrangement that went stale last time."""
    docs = app_module.MYKOLA_KNOWLEDGE
    assert len(docs) == 1
    assert Path(docs[0]).name == "user-guide.md"
    assert Path(docs[0]).exists(), "the injected document must actually be there"


def test_the_injection_is_feature_detected(app_module, monkeypatch):
    """An older ai_agent has no `knowledge_docs` parameter, and must still get
    an agent — the two repos deploy in either order."""
    seen = {}

    class OldAgent:
        def __init__(self, card_saver=None, name_saver=None):
            seen["kwargs"] = {"card_saver": card_saver, "name_saver": name_saver}

    # raising=False: ai_agent is not importable from the test venv, so
    # `app.MykolaAgent` does not exist here at all — which is itself the
    # "older or absent agent" case this is about.
    monkeypatch.setattr(app_module, "MykolaAgent", OldAgent, raising=False)
    monkeypatch.setattr(app_module, "_mykola_agent", None, raising=False)
    app_module.get_mykola()
    assert "knowledge_docs" not in seen["kwargs"]


def test_a_newer_agent_is_given_the_guide(app_module, monkeypatch):
    seen = {}

    class NewAgent:
        def __init__(self, card_saver=None, name_saver=None, topic_reader=None,
                     card_reader=None, knowledge_docs=None):
            seen["docs"] = knowledge_docs

    monkeypatch.setattr(app_module, "MykolaAgent", NewAgent, raising=False)
    monkeypatch.setattr(app_module, "_mykola_agent", None, raising=False)
    app_module.get_mykola()
    assert seen["docs"], "a capable agent must be handed the guide"
    assert Path(seen["docs"][0]).name == "user-guide.md"


def test_get_mykola_passes_only_what_the_agent_accepts(app_module):
    """The rule the whole arrangement rests on: every injected argument is
    checked against the installed agent's signature first."""
    source = inspect.getsource(app_module.get_mykola)
    assert "inspect.signature" in source
    assert "knowledge_docs" in source


# --- the document itself ----------------------------------------------------
#
# It is the source of truth now, so "the app changed and the guide did not" is
# a bug these tests can catch. Checked against the app's own declarations
# rather than against a written-down list, or this file becomes the next thing
# to drift.


def test_every_activity_is_described(guide):
    """A learner can ask about any activity on the front page, so the guide has
    to have something to say about each."""
    import games

    for activity in games.ACTIVITIES.values():
        assert activity.name.lower() in guide.lower(), \
            f"the guide never mentions {activity.name!r}"


def _games_table(guide):
    """The rows of the guide's list of games, as `{name: description}`."""
    rows = {}
    for line in guide.splitlines():
        if not line.startswith("|") or set(line) <= set("| -"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 2:
            rows[cells[0].strip("*").lower()] = cells[1].lower()
    return rows


def test_an_activity_that_ships_is_no_longer_called_unbuilt(guide):
    """The failure this replaces: the guide called *Generate a text* "not yet
    built" for as long as it took anyone to notice it had shipped.

    Read off `ticket`, which is the app's own record of whether a game exists
    (#253): the field is present exactly while an activity is a stub, so this
    cannot disagree with the front page."""
    import games

    rows = _games_table(guide)
    for activity in games.ACTIVITIES.values():
        described = rows.get(activity.name.lower())
        if described is None:
            continue
        shipped = not activity.ticket
        says_unbuilt = "not built" in described or "not yet built" in described
        assert shipped != says_unbuilt, (
            f"{activity.name!r}: ticket={activity.ticket!r} but the guide says "
            f"{described!r}")


def test_the_games_are_listed_somewhere_all_together(guide):
    """A learner asks "tell me about the games", not "tell me about Scrambled".

    Chunks split on headings, so a section per game answers the specific
    question and *nothing* answers the general one — which is exactly what
    happened: with a heading each and no list, "which games are there?"
    retrieved nothing at all. One section has to name them all, so there is a
    single chunk for the question people actually ask first.
    """
    import games

    sections = guide.split("\n### ")
    names = [a.name.lower() for a in games.ACTIVITIES.values()]
    assert any(all(name in section.lower() for name in names)
               for section in sections), \
        "no single section names every game — the general question has no chunk"


def test_the_guide_calls_them_games(guide):
    """The word the app and its learners use. The guide once managed to
    describe all six without using it once, so a question containing "games"
    matched no chunk in the document at all."""
    assert "game" in guide.lower()


def test_every_setting_is_described(guide):
    """The guide's Settings table against the store's own `DEFAULTS`, so a new
    setting cannot arrive without a line telling learners what it does.

    Counted rather than matched by name: the table is written in the learner's
    words, not the store's — `restart_chat_interval` appears as *Restart chat
    after*, `mykola_typewriter` as *Type his answer out* — and a test that
    insisted on the key names would either fail on good prose or force the
    prose to name its variables.

    One row fewer is expected and is the only allowance: `show_ukrainian` and
    `show_russian` are one row, because hiding a language is one idea.
    """
    import settings_store

    # Scoped to the Settings section: the guide has a table of games too, and
    # counting every row in the document would let this pass while the settings
    # table was empty.
    section = guide.split("## Settings", 1)[-1].split("\n## ", 1)[0]
    table = [line for line in section.splitlines()
             if line.startswith("|") and not set(line) <= set("| -")]
    rows = len(table) - 1                       # minus the header row
    assert rows >= len(settings_store.DEFAULTS) - 1, (
        f"{rows} rows in the guide's Settings table for "
        f"{len(settings_store.DEFAULTS)} settings — has one just been added?")


def test_each_feature_has_its_own_heading(guide):
    """The headings are the retrieval units — chunks split on them. One heading
    covering four activities scores too low on a question about any one of them
    to come back at all, which is how the speaker button once retrieved a note
    about French loanwords."""
    headings = [line for line in guide.splitlines() if line.startswith("### ")]
    assert len(headings) >= 15, f"only {len(headings)} sub-headings"


def test_the_guide_does_not_promise_what_mykola_cannot_do(guide):
    """He can save a card in chat but cannot move one, and the guide is what
    tells him so. A guide that said otherwise would have him offering it."""
    assert "cannot move" in guide.lower() or "not move" in guide.lower()
