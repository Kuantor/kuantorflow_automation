"""
Moving a card to another topic (kuantorflow#177).

Split from #176 because the rules differ: **no duplicate check applies** —
save_flashcard() deduplicates on word+pos globally, never per topic, so a move
cannot create a duplicate where a rename can.

Topics are not a table; get_topics() derives them with GROUP BY. So moving a
card to an unknown topic creates it, and moving the last card out of a topic
makes that topic cease to exist — which is why the route has to think about
where the user lands.
"""

import pytest

import utils
from conftest import TEST_USER_ID, TEST_USER_EMAIL

CARD = {"id": 5, "word": "resilient", "pos": "adjective", "topic": "vocab",
        "explanation_en": "able to recover quickly", "examples_en": [],
        "examples_ukr": [], "examples_rus": [], "translation_ukr": "стійкий",
        "translation_rus": None, "added_by_user_id": TEST_USER_ID}


# --- the storage layer --------------------------------------------------

class FakeCursor:
    def __init__(self, row=("resilient", "vocab"), rowcount=1):
        self.row = row
        self.rowcount = rowcount
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.row

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
    cursor = FakeCursor(**kwargs)
    conn = FakeConn(cursor)
    monkeypatch.setattr(utils, "get_db_connection", lambda: conn)
    return cursor, conn


def _update(cursor):
    return next((q, p) for q, p in cursor.queries if q.startswith("UPDATE"))


def test_the_card_is_moved_and_its_old_topic_reported(monkeypatch):
    """The caller needs the old topic to know whether it still exists."""
    cursor, conn = _db(monkeypatch)
    outcome, detail = utils.move_flashcard(5, "character",
                                           owner_id=TEST_USER_ID)
    assert outcome == "moved"
    assert detail == ("resilient", "vocab")
    assert conn.committed


def test_only_the_topic_column_is_written(monkeypatch):
    cursor, _ = _db(monkeypatch)
    utils.move_flashcard(5, "character", owner_id=TEST_USER_ID)
    query, params = _update(cursor)
    assert query.split("WHERE")[0].strip() == \
        "UPDATE flashcards SET topic = %s"
    assert params[0] == "character"


def test_no_duplicate_check_is_made(monkeypatch):
    """The rule is global, so a move can never create a duplicate — asking
    would be a query that can only ever answer 'no'."""
    cursor, _ = _db(monkeypatch)
    utils.move_flashcard(5, "character", owner_id=TEST_USER_ID)
    assert not any("word = %s" in q for q, _ in cursor.queries)


def test_moving_a_card_to_where_it_already_is_changes_nothing(monkeypatch):
    cursor, conn = _db(monkeypatch, row=("resilient", "vocab"))
    assert utils.move_flashcard(5, "vocab", owner_id=TEST_USER_ID) == \
        ("unchanged", None)
    assert not any(q.startswith("UPDATE") for q, _ in cursor.queries)
    assert not conn.committed


def test_the_owner_is_part_of_the_update(monkeypatch):
    cursor, _ = _db(monkeypatch)
    utils.move_flashcard(5, "character", owner_id=TEST_USER_ID)
    query, params = _update(cursor)
    assert "added_by_user_id = %s" in query
    assert params[-1] == TEST_USER_ID


def test_the_admin_moves_without_the_owner_clause(monkeypatch):
    cursor, _ = _db(monkeypatch)
    utils.move_flashcard(5, "character", admin=True)
    query, _ = _update(cursor)
    assert "added_by_user_id" not in query


def test_someone_elses_card_affects_no_rows(monkeypatch):
    cursor, conn = _db(monkeypatch, rowcount=0)
    assert utils.move_flashcard(5, "character", owner_id=99) == ("denied", None)
    assert not conn.committed


def test_a_missing_card_is_reported(monkeypatch):
    _db(monkeypatch, row=None)
    assert utils.move_flashcard(5, "character")[0] == "missing"


# --- the route ----------------------------------------------------------


@pytest.fixture()
def moved(app_module, monkeypatch):
    """Capture move_flashcard(), and keep the topic list under control."""
    calls = []

    def fake(card_id, to_topic, owner_id=None, admin=False):
        calls.append({"id": card_id, "to": to_topic, "owner": owner_id,
                      "admin": admin})
        return "moved", ("resilient", "vocab")

    monkeypatch.setattr(app_module, "move_flashcard", fake)
    monkeypatch.setattr(app_module, "get_topics",
                        lambda owner_id=None: [("vocab", 1), ("character", 3)])
    # Following a redirect renders the topic page, which would otherwise read
    # the real database — local MySQL is reachable, so "offline" is a property
    # of the fixtures, not the network.
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [dict(CARD)])
    return calls


def _move(client, to_topic="character", **kwargs):
    return client.post("/flashcards/vocab/move/5",
                       data={"to_topic": to_topic}, **kwargs)


def test_an_anonymous_visitor_is_refused(client, moved):
    resp = _move(client, )
    assert resp.status_code == 302
    assert moved == []


def test_a_blocked_account_is_refused(user_client, block_state, moved,
                                      action_logs):
    block_state.block()
    _move(user_client)
    assert moved == []
    assert "EDIT-DENIED" in (action_logs / "cards.log").read_text(encoding="utf-8")


def test_a_signed_in_user_moves_with_their_own_id(user_client, moved):
    _move(user_client)
    assert moved[0]["owner"] == TEST_USER_ID and moved[0]["admin"] is False
    assert moved[0]["to"] == "character"


def test_the_destination_is_trimmed(user_client, moved):
    _move(user_client, "  character  ")
    assert moved[0]["to"] == "character"


def test_an_empty_destination_is_rejected_before_the_database(user_client,
                                                              moved):
    _move(user_client, "   ")
    assert moved == []


def test_a_brand_new_topic_is_accepted(user_client, moved):
    """Topics are derived from the cards, so there is nothing to create."""
    _move(user_client, "a topic that did not exist")
    assert moved[0]["to"] == "a topic that did not exist"


def test_the_confirmation_names_the_destination(user_client, moved):
    body = _move(user_client, follow_redirects=True).get_data(as_text=True)
    # Jinja escapes the quotes around the names, hence &#39; rather than '.
    assert "Moved &#39;resilient&#39; to &#39;character&#39;." in body


def test_the_move_is_logged_as_an_edit_of_the_topic(user_client, moved,
                                                    action_logs):
    _move(user_client)
    line = [l for l in (action_logs / "cards.log").read_text(encoding="utf-8")
            .splitlines() if "EDIT " in l][0]
    assert "changed=topic" in line
    assert "source='topic move'" in line
    assert "id=5" in line


def test_a_forged_move_of_someone_elses_card_is_refused(user_client,
                                                        app_module,
                                                        monkeypatch,
                                                        action_logs):
    """The control is greyed, but that is presentation — this is the part
    that holds."""
    monkeypatch.setattr(app_module, "move_flashcard",
                        lambda *a, **k: ("denied", None))
    monkeypatch.setattr(app_module, "get_topics",
                        lambda owner_id=None: [("vocab", 1)])
    resp = user_client.post("/flashcards/vocab/move/5",
                            data={"to_topic": "character"},
                            follow_redirects=True)
    body = resp.get_data(as_text=True)
    assert "cannot move the card" in body
    assert "EDIT-DENIED" in (action_logs / "cards.log").read_text(encoding="utf-8")


# --- where the user lands -----------------------------------------------


def test_the_user_stays_on_a_topic_that_still_has_cards(user_client, moved):
    resp = _move(user_client)
    assert resp.headers["Location"].endswith("/flashcards/vocab")


def test_emptying_a_topic_sends_the_user_to_the_topic_list(user_client,
                                                           app_module,
                                                           monkeypatch, moved):
    """The topic has just ceased to exist — there is no topics table — so the
    page they came from would be empty and its chip gone."""
    monkeypatch.setattr(app_module, "get_topics",
                        lambda owner_id=None: [("character", 4)])
    resp = _move(user_client)
    assert resp.headers["Location"] in ("/", "http://localhost/")


def test_a_dead_database_leaves_them_where_they_were(user_client, app_module,
                                                     monkeypatch, moved):
    def boom(owner_id=None):
        raise RuntimeError("database is down")
    monkeypatch.setattr(app_module, "get_topics", boom)
    resp = _move(user_client)
    assert resp.headers["Location"].endswith("/flashcards/vocab")


# --- the control on the page --------------------------------------------


def test_the_move_control_is_rendered_for_your_own_card(user_client,
                                                        app_module,
                                                        monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [dict(CARD)])
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)
    marker = body[body.index('class="card-move"'):]
    assert 'aria-disabled="true"' not in marker[:marker.index(">")]


def test_the_move_control_is_greyed_for_someone_elses_card(user_client,
                                                           app_module,
                                                           monkeypatch):
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [
                            dict(CARD, added_by_user_id=99)])
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)
    marker = body[body.index('class="card-move"'):]
    marker = marker[:marker.index(">")]
    assert 'aria-disabled="true"' in marker
    assert "cannot move" in marker


def test_the_topic_page_does_not_query_the_topic_list(user_client, app_module,
                                                      monkeypatch):
    """Suggestions are fetched from /topics.json only when the dialog opens,
    so a page everyone loads does not pay for a feature few use."""
    calls = []
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda topic, owner_id=None: [dict(CARD)])
    monkeypatch.setattr(app_module, "get_topics",
                        lambda owner_id=None: calls.append(owner_id) or [])
    user_client.get("/flashcards/vocab")
    assert calls == []
