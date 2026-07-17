"""Duplicate prevention on repeated lookups (kuantorflow#101).

save_flashcard() must skip a card whose word + part of speech already exists,
and every save path must tell the user: /cards/add reports {duplicate: true}
(the popup shows 'Already in DB'), the automatic-add flow counts skips in its
banner. The utils-level tests drive save_flashcard against a fake DB
connection; the route-level tests stub save_flashcard as usual.
"""

import utils
from maintenance.dedup_flashcards import find_duplicates


# --- save_flashcard against a fake connection ---------------------------------

class FakeCursor:
    def __init__(self, existing_row=None, rows=()):
        self.existing = existing_row
        self.rows = list(rows)
        self.queries = []
        self.lastrowid = 42

    def execute(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.existing

    def fetchall(self):
        return self.rows

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


ENTRY = {"word": "resilient", "pos": "adjective", "topic": "vocab"}


def _fake_db(monkeypatch, cursor):
    conn = FakeConn(cursor)
    monkeypatch.setattr(utils, "get_db_connection", lambda: conn)
    return conn


def test_duplicate_word_pos_is_skipped(monkeypatch):
    cursor = FakeCursor(existing_row=(7,))       # the word+pos already exists
    conn = _fake_db(monkeypatch, cursor)
    assert utils.save_flashcard(dict(ENTRY)) is None
    assert not any("INSERT" in q for q, _ in cursor.queries), \
        "a duplicate must not be inserted"
    assert conn.committed is False


def test_new_card_is_inserted(monkeypatch):
    cursor = FakeCursor(existing_row=None)
    conn = _fake_db(monkeypatch, cursor)
    assert utils.save_flashcard(dict(ENTRY)) == 42
    assert any(q.startswith("INSERT INTO flashcards") for q, _ in cursor.queries)
    assert conn.committed is True


def test_duplicate_check_is_null_safe_on_pos(monkeypatch):
    """pos-less cards (.mht imports) must deduplicate too: the check uses the
    NULL-safe <=> comparison with the entry's (possibly None) pos."""
    cursor = FakeCursor(existing_row=None)
    _fake_db(monkeypatch, cursor)
    utils.save_flashcard({"word": "ubiquitous", "topic": "vocab"})
    check_query, params = cursor.queries[0]
    assert "pos <=> %s" in check_query
    assert params == ("ubiquitous", None)


# --- the save routes report duplicates ----------------------------------------

def test_add_card_reports_duplicate(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "save_flashcard", lambda entry: None)
    r = client.post("/cards/add", data={"word": "resilient", "pos": "adjective"})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "saved": False, "duplicate": True}


def test_review_popup_knows_the_duplicate_state(client, app_module, monkeypatch, saved):
    """The popup JS must be able to show 'Already in DB' on a duplicate."""
    monkeypatch.setattr(
        app_module, "lookup_word",
        lambda word, topic=None, **providers: [
            {"word": word, "pos": "noun", "topic": topic}],
    )
    body = client.post("/", data={"action": "parse_word", "word": "run"})\
        .get_data(as_text=True)
    assert "Already in DB" in body


def _stub_lookup_two_cards(app_module, monkeypatch):
    monkeypatch.setattr(
        app_module, "lookup_word",
        lambda word, topic=None, **providers: [
            {"word": word, "pos": "adjective", "topic": topic},
            {"word": word, "pos": "noun", "topic": topic},
        ],
    )


def test_auto_add_banner_counts_skipped_duplicates(client, app_module, monkeypatch):
    _stub_lookup_two_cards(app_module, monkeypatch)
    # the noun card is already in the DB, the adjective card is new
    monkeypatch.setattr(
        app_module, "save_flashcard",
        lambda entry: None if entry["pos"] == "noun" else 1,
    )
    client.post("/settings", json={"cards_automatically": True})
    body = client.post("/", data={"action": "parse_word", "word": "resilient"},
                       follow_redirects=True).get_data(as_text=True)
    assert ("Added 1 card(s) for &#39;resilient&#39; automatically, "
            "skipped 1 already in the database.") in body


def test_auto_add_banner_when_everything_is_a_duplicate(client, app_module, monkeypatch):
    _stub_lookup_two_cards(app_module, monkeypatch)
    monkeypatch.setattr(app_module, "save_flashcard", lambda entry: None)
    client.post("/settings", json={"cards_automatically": True})
    body = client.post("/", data={"action": "parse_word", "word": "resilient"},
                       follow_redirects=True).get_data(as_text=True)
    assert "All 2 card(s) for &#39;resilient&#39; are already in the database" in body
    assert "nothing added" in body


# --- the dedup maintenance script ---------------------------------------------

def test_find_duplicates_groups_and_keeps_oldest():
    rows = [
        (1, "run", "verb", "general"),
        (2, "Run", "verb", "sports"),      # duplicate of 1 (case-insensitive)
        (3, "run", "noun", "general"),     # different pos — not a duplicate
        (4, "ubiquitous", None, "vocab"),
        (5, "ubiquitous", None, "vocab"),  # NULL pos duplicates group too
        (6, "unique", "adjective", "vocab"),
    ]
    cursor = FakeCursor(rows=rows)
    groups = find_duplicates(cursor)
    assert [(kept[0], [d[0] for d in dupes]) for kept, dupes in groups] == [
        (1, [2]),
        (4, [5]),
    ]
