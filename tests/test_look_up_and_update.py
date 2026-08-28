"""Look up & update in the edit dialog (kuantorflow#191).

A card created early or imported from notes usually carries a translation and
nothing else. Until now the only way to enrich one was to retype it, or to
delete it and look the word up again — which loses its id, its `created_at`
and its ownership. This button refills the dialog's fields from the providers
instead.

**It writes nothing**, and that is the design constraint rather than a detail:
`edit_card()` stays the only path a card changes by, so its ownership rule,
its duplicate check and its logging remain the single place any of that is
decided. A second write path is a second place to get permissions wrong.

What is tested here is the endpoint — its guards, its part-of-speech matching
and the shape of its answer. The dialog's own behaviour (which fields are
offered for replacement, what each way out of the popup does) is browser
behaviour and was measured there; the parts of it a test can hold honestly are
at the bottom of this file, and say plainly what they are.
"""

import pytest

import parsers


ENTRIES = [
    {"word": "resilient", "pos": "adjective", "topic": "t",
     "explanation_en": "able to recover quickly",
     "examples_en": ["A resilient child."],
     "translation_ukr": "пружний", "translation_rus": "устойчивый"},
    {"word": "resilient", "pos": "noun", "topic": "t",
     "explanation_en": "a noun sense", "translation_ukr": "стійкість"},
]


@pytest.fixture()
def lookup(app_module, monkeypatch):
    """`lookup_word` stubbed at the app's own name, recording its arguments."""
    calls = []

    def fake(word, topic=None, **providers):
        calls.append(dict(word=word, **providers))
        return [dict(e) for e in ENTRIES]

    monkeypatch.setattr(app_module, "lookup_word", fake)
    return calls


def _ask(client, **payload):
    return client.post("/lookup.json", json=payload)


# --- who may spend a lookup -------------------------------------------------

def test_an_anonymous_visitor_is_refused(client, lookup):
    """Not the same rule as the home page's lookup, and deliberately so.

    kuantorflow#125 lets an anonymous visitor read, and a lookup used to be
    free scraping. Since kuantorflow#353 it is a licensed API call that costs
    money per word, and the dialog this serves is signed-in only anyway
    (kuantorflow#176) — so an open endpoint here would be a way to spend the
    site's budget without an account.
    """
    r = _ask(client, word="resilient")

    assert r.status_code == 403
    assert lookup == [], "refused before the providers were called"


def test_a_blocked_account_is_refused(user_client, lookup, block_state):
    block_state.block()

    r = _ask(user_client, word="resilient")

    assert r.status_code == 403
    assert lookup == []


def test_a_signed_in_visitor_may_look_up(user_client, lookup):
    r = _ask(user_client, word="resilient", pos="adjective")

    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert lookup and lookup[0]["word"] == "resilient"


def test_the_word_is_required(user_client, lookup):
    assert _ask(user_client, word="   ").status_code == 400
    assert lookup == []


def test_it_uses_this_visitors_providers(user_client, lookup):
    """The same settings *Look up & save* uses, not a fixed pair."""
    user_client.post("/settings", json={"explanatory_dictionary": "oxford",
                                        "translator": "claude"})
    _ask(user_client, word="resilient")

    assert lookup[0]["translator"] == "claude"
    assert lookup[0]["explanatory_dictionary"] == "oxford"


# --- what comes back --------------------------------------------------------

def test_the_matching_part_of_speech_is_picked_out(user_client, lookup):
    data = _ask(user_client, word="resilient", pos="adjective").get_json()

    assert data["match"]["pos"] == "adjective"
    assert data["match"]["explanation_en"] == "able to recover quickly"
    assert [e["pos"] for e in data["entries"]] == ["adjective", "noun"]


def test_the_match_goes_through_the_synonym_map(user_client, app_module,
                                                monkeypatch):
    """kuantorflow#228 both ways: a card the translator called `modal verb`
    takes the entry the dictionary filed under `auxiliary verb`. The map lives
    in `parsers`, and matching here rather than in the browser is what keeps
    one copy of it."""
    monkeypatch.setattr(app_module, "lookup_word",
                        lambda word, topic=None, **kw: [
                            {"word": "must", "pos": "auxiliary verb",
                             "explanation_en": "used to say something is necessary"}])

    data = _ask(user_client, word="must", pos="modal verb").get_json()

    assert data["match"]["pos"] == "auxiliary verb"


def test_the_synonym_map_is_applied_to_the_asked_side_too(user_client,
                                                          app_module,
                                                          monkeypatch):
    """The labels the other way round, because the map is one-directional.

    `auxiliary verb -> modal verb` only rewrites one of the two names, so a
    test where the *entry* carries the mapped name passes even if the asked
    side is never mapped at all — which is how the first version of the test
    above missed a break that removed exactly that. Here the **card** holds
    the name that needs rewriting, so nothing matches unless both sides go
    through `_pos_key()`, which is what CLAUDE.md says the map is for.
    """
    monkeypatch.setattr(app_module, "lookup_word",
                        lambda word, topic=None, **kw: [
                            {"word": "must", "pos": "modal verb",
                             "explanation_en": "used to say something is necessary"}])

    data = _ask(user_client, word="must", pos="auxiliary verb").get_json()

    assert data["match"] is not None, "the asked side was not mapped"
    assert data["match"]["pos"] == "modal verb"


def test_no_match_returns_the_entries_and_no_match(user_client, lookup):
    """The dialog asks which one to use, so it needs the list and an honest
    `null` rather than the first entry dressed up as an answer."""
    data = _ask(user_client, word="resilient", pos="verb").get_json()

    assert data["match"] is None
    assert len(data["entries"]) == 2


def test_a_card_with_no_part_of_speech_matches_nothing(user_client, lookup):
    data = _ask(user_client, word="resilient", pos="").get_json()

    assert data["match"] is None
    assert len(data["entries"]) == 2, "and the choice is offered instead"


def test_the_topic_does_not_ride_along(user_client, lookup):
    """`lookup_word()` stamps a topic on every entry it builds. This endpoint
    is refilling a card that already has one, and handing the dialog a topic it
    must remember not to apply is how a field gets moved by accident."""
    data = _ask(user_client, word="resilient", pos="adjective").get_json()

    assert "topic" not in data["match"]
    assert all("topic" not in e for e in data["entries"])


def test_nothing_is_written(user_client, lookup, saved):
    _ask(user_client, word="resilient", pos="adjective")

    assert saved == [], "a fetch-and-fill: edit_card() is still the only writer"


def test_a_provider_outage_is_not_a_500(user_client, app_module, monkeypatch):
    """The dialog says so with its fields untouched — the same tolerance the
    home page has, and the reason the message names the card's safety."""
    def boom(word, topic=None, **kw):
        raise RuntimeError("every provider is down")

    monkeypatch.setattr(app_module, "lookup_word", boom)

    r = _ask(user_client, word="resilient", pos="adjective")

    assert r.status_code == 502
    assert "unchanged" in r.get_json()["error"]


def test_the_lookup_is_logged_like_any_other(user_client, lookup, action_logs):
    """kuantorflow#30: a lookup from the edit dialog is as traceable as one
    from the home page, and it is the line that carries the identity the
    parser cannot see."""
    _ask(user_client, word="resilient", pos="adjective")

    assert "LOOKUP" in (action_logs / "dict.log").read_text(encoding="utf-8")


# --- the dialog, as far as markup can honestly go ---------------------------

def _edit_dialog(user_client, app_module, monkeypatch):
    card = {"id": 7, "word": "resilient", "pos": "adjective",
            "topic": "character", "added_by_user_id": 7,
            "explanation_en": "", "translation_ukr": "стійкий",
            "translation_rus": "", "examples_en": ["An old example."],
            "examples_ukr": [], "examples_rus": []}
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [dict(card)])
    return user_client.get("/flashcards/character").get_data(as_text=True)


def test_the_dialog_offers_the_button_and_both_popups(user_client, app_module,
                                                      monkeypatch):
    """Structural only. What each control *does* is browser behaviour, and was
    measured at 1280x900 and 375x812 with the endpoint stubbed in the page:
    the popup lists only real conflicts, unticking one keeps that field,
    dismissing changes nothing at all — not even the empty fields — an empty
    result never empties a field, and a failed lookup leaves the dialog
    untouched with its message.
    """
    body = _edit_dialog(user_client, app_module, monkeypatch)

    assert 'id="edit-lookup"' in body
    assert 'id="field-rewrite-confirm-popup"' in body
    assert 'id="lookup-pos-modal"' in body
    assert "Fill only the empty ones" in body and "Replace the ticked fields" in body


def test_the_button_posts_to_the_endpoint(user_client, app_module, monkeypatch):
    body = _edit_dialog(user_client, app_module, monkeypatch)

    assert '"/lookup.json"' in body


def test_an_answer_with_no_entries_is_still_applied_when_it_has_a_match(
        user_client):
    """The one bug the browser pass found, pinned as a string.

    The guard read `data.entries.length` before it looked at `data.match`, so
    an answer carrying a perfectly usable match was refused for the shape of
    the field beside it. Asserted in `lookup_update.js` since kuantorflow#372
    moved it there — the same guard, now serving both callers.
    """
    script = user_client.get(
        "/static/js/lookup_update.js").get_data(as_text=True)

    assert "if (!data.match && !data.entries.length)" in script
