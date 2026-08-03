"""
Editing a saved card (kuantorflow#176), and what a duplicate is called (#186).

Editing follows #162's rule exactly — the admin edits any card, a signed-in
user only their own, nobody else at all — and is enforced in the route, since
greying the pencil is presentation and a hand-made POST goes straight past it.

The interesting part is the word: renaming into an existing word+pos would
create the duplicate #101 exists to prevent, while the card being edited must
not count as its own duplicate.
"""

import json

import pytest

import utils
from conftest import TEST_USER_ID, TEST_USER_EMAIL

STORED = {
    "id": 5,
    "word": "resilient",
    "pos": "adjective",
    "explanation_en": "able to recover quickly",
    "examples_en": '["She stayed resilient."]',
    "translation_ukr": "стійкий",
    "examples_ukr": None,
    "translation_rus": "упругий",
    "examples_rus": None,
}

CARD_FOR_PAGE = dict(STORED, examples_en=["She stayed resilient."],
                     examples_ukr=[], examples_rus=[], topic="vocab",
                     added_by_user_id=TEST_USER_ID)


# --- the storage layer --------------------------------------------------

class FakeCursor:
    """Answers the SELECT then records the UPDATE, like the real driver."""

    def __init__(self, row=None, clash=None, rowcount=1):
        self.row = row
        self.clash = clash
        self.rowcount = rowcount
        self.queries = []
        self._last = None

    def execute(self, query, params=None):
        flat = " ".join(query.split())
        self.queries.append((flat, params))
        self._last = flat

    def fetchone(self):
        if self._last.startswith("SELECT id FROM flashcards WHERE word"):
            return {"id": self.clash} if self.clash else None
        return dict(self.row) if self.row else None

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


def _db(monkeypatch, **kwargs):
    kwargs.setdefault("row", STORED)
    cursor = FakeCursor(**kwargs)
    monkeypatch.setattr(utils, "get_db_connection", lambda: FakeConn(cursor))
    return cursor


def _update(cursor):
    return next((q, p) for q, p in cursor.queries if q.startswith("UPDATE"))


def test_a_changed_field_is_written_and_named(monkeypatch):
    cursor = _db(monkeypatch)
    outcome, changed = utils.update_flashcard(
        5, {"explanation_en": "bounces back"}, owner_id=TEST_USER_ID)
    assert outcome == "updated"
    assert changed == ["explanation_en"]
    query, params = _update(cursor)
    assert "explanation_en = %s" in query
    assert params[0] == "bounces back"


def test_only_the_changed_fields_are_written(monkeypatch):
    """The log's `changed` list has to be accurate, so the UPDATE is too."""
    cursor = _db(monkeypatch)
    outcome, changed = utils.update_flashcard(
        5, dict(STORED, explanation_en="bounces back"), owner_id=TEST_USER_ID)
    assert changed == ["explanation_en"]
    query, _ = _update(cursor)
    assignments = query.split("WHERE")[0]
    assert assignments.count("= %s") == 1, "only the field that differs"


def test_submitting_nothing_new_is_not_an_edit(monkeypatch):
    """An edit that changed nothing must not write an EDIT line — the log
    counts events, not attempts (the lesson from #126's unblock logging)."""
    cursor = _db(monkeypatch)
    outcome, changed = utils.update_flashcard(5, dict(STORED),
                                              owner_id=TEST_USER_ID)
    assert (outcome, changed) == ("unchanged", [])
    assert not any(q.startswith("UPDATE") for q, _ in cursor.queries)


def test_a_field_that_was_not_submitted_is_left_alone(monkeypatch):
    """The editor renders no field for a language the visitor has hidden
    (#46/#79/#111), so it must not be blanked — hiding has always been
    visual only, and an editor that emptied it would make it destructive."""
    cursor = _db(monkeypatch)
    utils.update_flashcard(5, {"word": "resilient", "pos": "adjective",
                               "explanation_en": "bounces back"},
                           owner_id=TEST_USER_ID)
    query, _ = _update(cursor)
    assert "translation_rus" not in query and "translation_ukr" not in query


def test_an_empty_value_still_clears_the_field(monkeypatch):
    """A *missing* key means 'leave it'; a key holding None means 'clear it'."""
    cursor = _db(monkeypatch)
    _, changed = utils.update_flashcard(5, {"translation_rus": None},
                                        owner_id=TEST_USER_ID)
    assert changed == ["translation_rus"]
    query, params = _update(cursor)
    assert "translation_rus = %s" in query and params[0] is None


def test_examples_are_stored_as_json(monkeypatch):
    cursor = _db(monkeypatch)
    utils.update_flashcard(5, {"examples_en": ["one", "two"]},
                           owner_id=TEST_USER_ID)
    _, params = _update(cursor)
    assert json.loads(params[0]) == ["one", "two"]


# --- the duplicate rule -------------------------------------------------


def test_renaming_onto_an_existing_card_is_refused(monkeypatch):
    cursor = _db(monkeypatch, clash=9)
    outcome, detail = utils.update_flashcard(5, {"word": "walk"},
                                             owner_id=TEST_USER_ID)
    assert outcome == "duplicate"
    assert detail[0] == 9 and detail[1] == "walk"
    assert not any(q.startswith("UPDATE") for q, _ in cursor.queries)


def test_the_card_does_not_count_as_its_own_duplicate(monkeypatch):
    """Without the exclusion, every rename would collide with itself."""
    cursor = _db(monkeypatch, clash=None)
    utils.update_flashcard(5, {"word": "walk"}, owner_id=TEST_USER_ID)
    check = next(q for q, _ in cursor.queries
                 if q.startswith("SELECT id FROM flashcards WHERE word"))
    assert "id != %s" in check
    params = next(p for q, p in cursor.queries if q == check)
    assert params[-1] == 5


def test_changing_only_the_part_of_speech_is_checked_too(monkeypatch):
    """word+pos is the key, so either half moving can create a duplicate."""
    cursor = _db(monkeypatch, clash=9)
    outcome, _ = utils.update_flashcard(5, {"pos": "verb"},
                                        owner_id=TEST_USER_ID)
    assert outcome == "duplicate"


def test_the_check_uses_the_values_the_card_will_end_up_with(monkeypatch):
    """Only `pos` is submitted, so the word must come from the stored row —
    checking a missing word against the database would find nothing."""
    cursor = _db(monkeypatch, clash=None)
    utils.update_flashcard(5, {"pos": "verb"}, owner_id=TEST_USER_ID)
    params = next(p for q, p in cursor.queries
                  if q.startswith("SELECT id FROM flashcards WHERE word"))
    assert params[0] == "resilient" and params[1] == "verb"


def test_leaving_word_and_pos_alone_skips_the_check(monkeypatch):
    cursor = _db(monkeypatch)
    utils.update_flashcard(5, {"explanation_en": "bounces back"},
                           owner_id=TEST_USER_ID)
    assert not any(q.startswith("SELECT id FROM flashcards WHERE word")
                   for q, _ in cursor.queries)


# --- ownership ----------------------------------------------------------


def test_a_card_that_is_not_yours_affects_no_rows(monkeypatch):
    """Zero rows affected is the refusal — and nothing is committed."""
    cursor = FakeCursor(row=STORED, rowcount=0)
    conn = FakeConn(cursor)
    monkeypatch.setattr(utils, "get_db_connection", lambda: conn)
    outcome, _ = utils.update_flashcard(5, {"explanation_en": "mine now"},
                                        owner_id=99)
    assert outcome == "denied"
    assert conn.committed is False


def test_the_owner_is_part_of_the_update_not_a_prior_check(monkeypatch):
    """One conditional statement, as #162 does — no gap between deciding the
    card is yours and changing it."""
    cursor = _db(monkeypatch)
    utils.update_flashcard(5, {"explanation_en": "x"}, owner_id=TEST_USER_ID)
    query, params = _update(cursor)
    assert "added_by_user_id = %s" in query
    assert params[-1] == TEST_USER_ID


def test_the_admin_updates_without_the_owner_clause(monkeypatch):
    cursor = _db(monkeypatch)
    utils.update_flashcard(5, {"explanation_en": "x"}, admin=True)
    query, _ = _update(cursor)
    assert "added_by_user_id" not in query


def test_a_missing_card_is_reported(monkeypatch):
    _db(monkeypatch, row=None)
    assert utils.update_flashcard(5, {"word": "x"})[0] == "missing"


# --- the route ----------------------------------------------------------


@pytest.fixture()
def edited(app_module, monkeypatch):
    """Capture update_flashcard() instead of touching MySQL."""
    calls = []

    def fake(card_id, entry, owner_id=None, admin=False):
        calls.append({"id": card_id, "entry": entry, "owner": owner_id,
                      "admin": admin})
        return calls[-1].get("result", ("updated", sorted(entry)))

    monkeypatch.setattr(app_module, "update_flashcard", fake)
    return calls


def _post(client, **fields):
    data = {"word": "resilient", "pos": "adjective"}
    data.update(fields)
    return client.post("/flashcards/vocab/edit/5", data=data)


def test_an_anonymous_visitor_is_refused(client, edited):
    resp = _post(client)
    assert resp.status_code == 403
    assert "sign in" in resp.get_json()["error"].lower()
    assert edited == []


def test_a_blocked_account_is_refused(user_client, block_state, edited):
    block_state.block()
    resp = _post(user_client)
    assert resp.status_code == 403
    assert "blocked" in resp.get_json()["error"].lower()
    assert edited == []


def test_a_signed_in_user_edits_with_their_own_id(user_client, edited):
    resp = _post(user_client, explanation_en="bounces back")
    assert resp.status_code == 200
    assert edited[0]["owner"] == TEST_USER_ID and edited[0]["admin"] is False


def test_a_word_is_still_required(user_client, edited):
    assert _post(user_client, word="   ").status_code == 400
    assert edited == []


def test_examples_are_read_one_per_line(user_client, edited):
    _post(user_client, examples_en="first line\n\nsecond line")
    assert edited[0]["entry"]["examples_en"] == ["first line", "second line"]


def test_examples_still_accept_the_review_popup_json(user_client, edited):
    _post(user_client, examples_en=json.dumps(["from json"]))
    assert edited[0]["entry"]["examples_en"] == ["from json"]


def test_a_field_absent_from_the_form_is_absent_from_the_entry(user_client,
                                                               edited):
    """This is what stops a hidden language being wiped by an edit."""
    _post(user_client, explanation_en="x")
    assert "translation_rus" not in edited[0]["entry"]
    assert "translation_ukr" not in edited[0]["entry"]


def test_a_refused_rename_is_a_409_naming_the_other_card(user_client,
                                                         app_module,
                                                         monkeypatch):
    monkeypatch.setattr(app_module, "update_flashcard",
                        lambda *a, **k: ("duplicate", (9, "walk", "verb")))
    resp = _post(user_client, word="walk", pos="verb")
    assert resp.status_code == 409
    body = resp.get_json()["error"]
    assert "walk" in body and "verb" in body


def test_someone_elses_card_is_refused_by_the_route(user_client, app_module,
                                                    monkeypatch, action_logs):
    monkeypatch.setattr(app_module, "update_flashcard",
                        lambda *a, **k: ("denied", None))
    resp = _post(user_client, explanation_en="mine now")
    assert resp.status_code == 403
    log = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert "EDIT-DENIED" in log and "reason='not owner'" in log


def test_a_missing_card_is_a_404(user_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "update_flashcard",
                        lambda *a, **k: ("missing", None))
    assert _post(user_client).status_code == 404


def test_the_edit_is_logged_with_what_changed(user_client, app_module,
                                              monkeypatch, action_logs):
    monkeypatch.setattr(app_module, "update_flashcard",
                        lambda *a, **k: ("updated", ["word", "explanation_en"]))
    _post(user_client, word="walk")
    line = [l for l in (action_logs / "cards.log").read_text(encoding="utf-8")
            .splitlines() if "EDIT " in l][0]
    assert "changed=word,explanation_en" in line
    assert "id=5" in line


def test_an_edit_that_changed_nothing_writes_no_log_line(user_client,
                                                         app_module,
                                                         monkeypatch,
                                                         action_logs):
    monkeypatch.setattr(app_module, "update_flashcard",
                        lambda *a, **k: ("unchanged", []))
    resp = _post(user_client)
    assert resp.status_code == 200 and resp.get_json()["changed"] == []
    log = action_logs / "cards.log"
    assert not log.exists() or "EDIT " not in log.read_text(encoding="utf-8")


# --- the pencil on the page ---------------------------------------------


def test_the_pencil_is_rendered_for_your_own_card(user_client, app_module,
                                                  monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [dict(CARD_FOR_PAGE)])
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)
    assert "card-edit" in body
    marker = body[body.index('class="card-edit"'):]
    assert 'aria-disabled="true"' not in marker[:marker.index(">")]


def test_the_pencil_is_greyed_for_someone_elses_card(user_client, app_module,
                                                     monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [
                            dict(CARD_FOR_PAGE, added_by_user_id=99)])
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)
    marker = body[body.index('class="card-edit"'):]
    marker = marker[:marker.index(">")]
    assert 'aria-disabled="true"' in marker
    assert "cannot edit" in marker


def test_a_hidden_language_never_reaches_the_edit_markup(user_client,
                                                         app_module,
                                                         monkeypatch):
    """The whole reason the route reads only submitted fields: a hidden
    language must not appear in the page, so its field is not rendered."""
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [dict(CARD_FOR_PAGE)])
    user_client.post("/settings", json={"show_russian": False})
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)
    assert "упругий" not in body
    assert 'name="translation_rus"' not in body
    assert 'name="translation_ukr"' in body, "the visible one still edits"


# --- #186: what a duplicate is called -----------------------------------


def test_no_extra_note_when_the_filter_is_off(user_client, app_module,
                                              monkeypatch, saved):
    monkeypatch.setattr(app_module, "save_flashcard",
                        lambda entry, added_by_user_id=None: None)
    body = user_client.post("/cards/add",
                            data={"word": "resilient"}).get_json()
    assert body["duplicate"] is True
    assert "note" not in body, "the plain wording is right when it is visible"


def test_a_hidden_duplicate_is_explained(user_client, app_module, monkeypatch,
                                         saved):
    """#186: 'already in the database' about a card the filter hides reads as
    the app contradicting itself."""
    monkeypatch.setattr(app_module, "save_flashcard",
                        lambda entry, added_by_user_id=None: None)
    monkeypatch.setattr(app_module, "find_duplicate",
                        lambda word, pos, exclude_id=None: (9, 99))
    user_client.post("/settings", json={"individual_cards": True})
    body = user_client.post("/cards/add",
                            data={"word": "resilient"}).get_json()
    assert "individual cards" in body["note"].lower()


def test_your_own_hidden_duplicate_needs_no_explanation(user_client,
                                                        app_module,
                                                        monkeypatch, saved):
    """It is your card and the filter shows it — the plain message is true."""
    monkeypatch.setattr(app_module, "save_flashcard",
                        lambda entry, added_by_user_id=None: None)
    monkeypatch.setattr(app_module, "find_duplicate",
                        lambda word, pos, exclude_id=None: (9, TEST_USER_ID))
    user_client.post("/settings", json={"individual_cards": True})
    body = user_client.post("/cards/add",
                            data={"word": "resilient"}).get_json()
    assert "note" not in body


def test_a_dead_database_costs_the_note_not_the_answer(user_client, app_module,
                                                       monkeypatch, saved):
    def boom(word, pos, exclude_id=None):
        raise RuntimeError("database is down")
    monkeypatch.setattr(app_module, "save_flashcard",
                        lambda entry, added_by_user_id=None: None)
    monkeypatch.setattr(app_module, "find_duplicate", boom)
    user_client.post("/settings", json={"individual_cards": True})
    body = user_client.post("/cards/add",
                            data={"word": "resilient"}).get_json()
    assert body["duplicate"] is True and "note" not in body
