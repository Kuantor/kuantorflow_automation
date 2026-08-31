"""Claiming the topics nobody created (kuantorflow#394).

`topics.created_by_user_id` is NULL for every topic that predates #207, for
everything `seed_topics.py` filed without `--owner`, and for anything an
anonymous visitor created before #125. That reads as missing attribution, and
since #382 it is also a dead end: the creator is what decides who may see a
private topic, so `set_topic_visibility()` refuses a creatorless one -- the
`nobodys` outcome -- and such a topic can never be hidden by anybody.

`claim_unowned_topics()` is the way out and `claim_topics.py` is its console
front. **Most of this file is about what it refuses to do.** It runs from a
PythonAnywhere console against production, where the cost of being wrong is
somebody's data, so the rule that matters is that another learner's topic is
never taken: their creator id is the only thing standing between their private
topic and everybody else's deck.

The `IS NULL` in the UPDATE is proved against a real MySQL in
`test_claim_topics_db.py` (marker `db`) -- a fake cursor agrees with any WHERE
clause it is handed, which is exactly the assertion worth not trusting here.
"""

import pytest

import claim_topics
import utils


# --- a database that answers the two reads and records the write ------------

class FakeCursor:
    """Answers the section lookup and the topic listing, then keeps the UPDATE.

    Dispatches on the statement rather than handing the same row to every
    `fetchone()`, for `conftest.FakeCardCursor`'s reason: this path asks two
    different questions on one cursor, and a fake that cannot tell them apart
    answers the first with the second's data.
    """

    def __init__(self, topics=(), section_id=6, user=None):
        self.topics = list(topics)          # (name, created_by_user_id)
        self.section_id = section_id
        self.user = user                    # the row `SELECT id FROM users`
        self.queries = []
        self._last = ""

    def execute(self, query, params=None):
        flat = " ".join(query.split())
        self.queries.append((flat, params))
        self._last = flat

    def fetchone(self):
        if "FROM topic_sections" in self._last:
            return (self.section_id,) if self.section_id is not None else None
        if "FROM users" in self._last:
            return self.user
        return None

    def fetchall(self):
        return list(self.topics)

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


@pytest.fixture()
def db(monkeypatch):
    """Point both `utils` and the script at one fake cursor."""
    def install(topics=(), section_id=6, user=(7,)):
        cursor = FakeCursor(topics, section_id, user)
        conn = FakeConn(cursor)
        monkeypatch.setattr(utils, "get_db_connection", lambda: conn)
        monkeypatch.setattr(claim_topics, "get_db_connection", lambda: conn)
        return cursor
    return install


def _update(cursor):
    return next(((q, p) for q, p in cursor.queries if q.startswith("UPDATE")),
                (None, None))


# --- what it claims ---------------------------------------------------------

def test_a_topic_with_no_creator_gets_one(db):
    cursor = db(topics=[("general", None), ("vocabulary", None)])

    claimed, left, missing = utils.claim_unowned_topics("Other", 7)

    assert claimed == ["general", "vocabulary"]
    assert (left, missing) == ([], False)
    query, params = _update(cursor)
    assert "created_by_user_id = %s" in query
    assert params[0] == 7


def test_the_write_asks_for_the_null_rows_itself(db):
    """A read-then-write would leave a gap between deciding a topic is
    creatorless and claiming it -- the shape every ownership-sensitive
    statement in `utils` avoids. Two consoles running this at once must not
    both claim the same row."""
    cursor = db(topics=[("general", None)])

    utils.claim_unowned_topics("Other", 7)

    query, _ = _update(cursor)
    assert "created_by_user_id IS NULL" in query
    assert "section_id = %s" in query


def test_somebody_elses_topic_is_reported_and_left(db):
    """The rule the whole thing turns on. `created_by_user_id` is not only a
    label: for a private topic it is the only thing that decides who can see
    it, so rewriting another learner's creator would take their topic out of
    their deck and put it in the caller's."""
    cursor = db(topics=[("general", None), ("Olena's diary", 2)])

    claimed, left, _ = utils.claim_unowned_topics("Other", 7)

    assert claimed == ["general"]
    assert left == [("Olena's diary", 2)]


def test_a_topic_already_yours_is_neither_claimed_nor_reported(db):
    """It is not a refusal and there is nothing to do about it, so it is not
    noise the console has to read past."""
    db(topics=[("general", None), ("math", 7)])

    claimed, left, _ = utils.claim_unowned_topics("Other", 7)

    assert (claimed, left) == (["general"], [])


def test_nothing_to_claim_writes_nothing(db):
    """Which is also what makes a second run safe: the first one left no NULLs
    behind, so this is the state a re-run finds."""
    cursor = db(topics=[("math", 7)])

    claimed, left, _ = utils.claim_unowned_topics("Other", 7)

    assert claimed == []
    assert _update(cursor) == (None, None)


def test_a_dry_run_reads_and_does_not_write(db):
    cursor = db(topics=[("general", None)])

    claimed, _, _ = utils.claim_unowned_topics("Other", 7, dry_run=True)

    assert claimed == ["general"], "it still says what it would do"
    assert _update(cursor) == (None, None)


def test_an_unknown_section_is_not_a_write(db):
    cursor = db(topics=[("general", None)], section_id=None)

    claimed, left, missing = utils.claim_unowned_topics("Nowhere", 7)

    assert missing is True
    assert (claimed, left) == ([], [])
    assert _update(cursor) == (None, None)


def test_each_claim_is_logged(db, action_logs):
    """A write with no request behind it logs beside itself -- CLAUDE.md's rule,
    and `place_topic()`'s reason for logging `TOPIC-PLACED` from `utils`."""
    db(topics=[("general", None), ("vocabulary", None)])

    utils.claim_unowned_topics("Other", 7)

    lines = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert lines.count("TOPIC-CLAIMED") == 2
    assert "topic=general" in lines and "section=Other" in lines
    assert "created_by=7" in lines


def test_a_dry_run_logs_nothing(db, action_logs):
    """The log counts events. A run that wrote nothing is not one."""
    db(topics=[("general", None)])

    utils.claim_unowned_topics("Other", 7, dry_run=True)

    log = action_logs / "cards.log"
    written = log.read_text(encoding="utf-8") if log.exists() else ""
    assert "TOPIC-CLAIMED" not in written


# --- the console front ------------------------------------------------------

def test_an_email_nobody_has_fails_before_any_write(db, capsys):
    """A typo would otherwise be a run that reports success and claims
    nothing -- the same reason `seed_topics.py` refuses an unknown `--owner`
    rather than falling back to unowned."""
    cursor = db(topics=[("general", None)], user=None)

    code = claim_topics.main(["--owner", "nobody@example.com"])

    assert code == 1
    assert "no account with email" in capsys.readouterr().err
    assert _update(cursor) == (None, None)


def test_it_names_every_row_it_would_change(db, capsys):
    db(topics=[("general", None), ("Olena's diary", 2)])

    code = claim_topics.main(["--owner", "anton@example.com", "--dry-run"])
    out = capsys.readouterr().out

    assert code == 0
    assert "+ general" in out
    assert "left alone, created by user 2" in out, (
        "a silently skipped row looks like a run that had nothing to do")
    assert "nothing written" in out


def test_an_unknown_section_is_an_error_not_an_empty_run(db, capsys):
    db(topics=[], section_id=None)

    code = claim_topics.main(["--owner", "anton@example.com",
                              "--section", "Nowhere"])

    assert code == 1
    assert "no section named" in capsys.readouterr().err


def test_a_name_a_windows_console_cannot_print_is_escaped(db, capsys):
    """`seed_topics.py`'s rule. A cp1252 console raises on a non-ASCII name,
    and a `UnicodeEncodeError` here would end a run that was writing fine."""
    db(topics=[("українська", None)])

    code = claim_topics.main(["--owner", "anton@example.com", "--dry-run"])

    assert code == 0
    assert capsys.readouterr().out.isascii()
