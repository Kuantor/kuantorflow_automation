"""Claiming the cards nobody wrote (kuantorflow#396).

The other half of #394. That one gives a topic a creator; this gives its cards
an author, and the first does not finish its job without it:
`set_topic_visibility()` refuses a topic holding *other people's* cards, and a
card with no author counts as somebody else's — so a claimed topic full of
unowned cards still cannot be hidden.

**`added_by_user_id` is three things at once**, which is why this file cares
more than an attribution fix would: #127 hides other people's cards, #162 lets
only the owner delete one, and #382 reads it to decide whether a topic may be
private. Claiming a card therefore hands over a permission, not a label — so
the rule that only a NULL author is ever taken matters here more than it does
for a topic, and most of these tests are about that.

The clause that enforces it is proved against a real MySQL in
`test_claim_flashcards_db.py` (marker `db`): a fake cursor agrees with any
WHERE it is handed, which is exactly the assertion not to trust here.
"""

import pytest

import claim_flashcards
import utils


# --- a database that answers the three reads and records the write ----------

class FakeCursor:
    """Answers the section lookup, the claimable group-by and the others
    group-by, dispatching on the statement.

    One cursor asks three different questions here, so a fake that handed the
    same rows to every `fetchall()` would report the claimable cards as other
    people's — which is the exact confusion this feature must not make.
    """

    def __init__(self, claimable=(), others=(), section_id=6, user=None):
        self.claimable = list(claimable)     # (topic, count)
        self.others = list(others)           # (user_id, email, count)
        self.section_id = section_id
        self.user = user
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
        if "IS NOT NULL" in self._last:
            return list(self.others)
        return list(self.claimable)

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
    def install(claimable=(), others=(), section_id=6, user=(7,)):
        cursor = FakeCursor(claimable, others, section_id, user)
        conn = FakeConn(cursor)
        monkeypatch.setattr(utils, "get_db_connection", lambda: conn)
        monkeypatch.setattr(claim_flashcards, "get_db_connection", lambda: conn)
        return cursor
    return install


def _update(cursor):
    return next(((q, p) for q, p in cursor.queries if q.startswith("UPDATE")),
                (None, None))


# --- what it claims ---------------------------------------------------------

def test_authorless_cards_get_an_author(db):
    cursor = db(claimable=[("general", 38), ("IT", 5)])

    claimed, others, missing = utils.claim_unowned_cards("Other", 7)

    assert claimed == [("general", 38), ("IT", 5)]
    assert (others, missing) == ([], False)
    query, params = _update(cursor)
    assert "added_by_user_id = %s" in query
    assert params[0] == 7


def test_the_write_asks_for_the_null_rows_itself(db):
    """A read-then-write would leave a gap between deciding a card has no
    author and giving it one, and this write is large enough that the gap is
    real. The section filter belongs in the same statement for the same
    reason: a list of ids assembled here and trusted later is a list that can
    go stale."""
    cursor = db(claimable=[("general", 38)])

    utils.claim_unowned_cards("Other", 7)

    query, _ = _update(cursor)
    assert "added_by_user_id IS NULL" in query
    assert "JOIN topics t" in query and "t.section_id = %s" in query


def test_another_authors_cards_are_counted_named_and_left(db):
    """The report the run is half for, and the rule it turns on. An author is
    a permission (#162) and a visibility (#127), so taking one would hand
    somebody's work to another account in three ways at once."""
    cursor = db(claimable=[("general", 38)],
                others=[(2, "olena@example.com", 12)])

    claimed, others, _ = utils.claim_unowned_cards("Other", 7)

    assert claimed == [("general", 38)]
    assert others == [(2, "olena@example.com", 12)]
    query, params = _update(cursor)
    assert "IS NULL" in query, "the UPDATE never widens to another author"


def test_nothing_to_claim_writes_nothing(db):
    """And so a second run does nothing, because the first left no NULLs."""
    cursor = db(claimable=[], others=[(2, "olena@example.com", 12)])

    claimed, others, _ = utils.claim_unowned_cards("Other", 7)

    assert claimed == []
    assert others == [(2, "olena@example.com", 12)]
    assert _update(cursor) == (None, None)


def test_a_dry_run_reads_and_does_not_write(db):
    cursor = db(claimable=[("general", 38)])

    claimed, _, _ = utils.claim_unowned_cards("Other", 7, dry_run=True)

    assert claimed == [("general", 38)], "it still says what it would do"
    assert _update(cursor) == (None, None)


def test_an_unknown_section_is_not_a_write(db):
    cursor = db(claimable=[("general", 38)], section_id=None)

    claimed, others, missing = utils.claim_unowned_cards("Nowhere", 7)

    assert missing is True
    assert (claimed, others) == ([], [])
    assert _update(cursor) == (None, None)


# --- the log ----------------------------------------------------------------

def test_it_logs_one_line_per_topic(db, action_logs):
    """Not one per card. Fifty-two card-shaped lines for a single console
    command would drown the day's real card events, and "these cards in this
    topic changed hands from nobody" is what one line says."""
    db(claimable=[("general", 38), ("IT", 5)])

    utils.claim_unowned_cards("Other", 7)

    lines = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert lines.count("CARDS-CLAIMED") == 2
    assert "topic=general" in lines and "count=38" in lines
    assert "section=Other" in lines and "created_by=7" in lines


def test_a_dry_run_logs_nothing(db, action_logs):
    db(claimable=[("general", 38)])

    utils.claim_unowned_cards("Other", 7, dry_run=True)

    log = action_logs / "cards.log"
    written = log.read_text(encoding="utf-8") if log.exists() else ""
    assert "CARDS-CLAIMED" not in written


# --- the console front ------------------------------------------------------

def test_an_email_nobody_has_fails_before_any_write(db, capsys):
    cursor = db(claimable=[("general", 38)], user=None)

    code = claim_flashcards.main(["--owner", "nobody@example.com"])

    assert code == 1
    assert "no account with email" in capsys.readouterr().err
    assert _update(cursor) == (None, None)


def test_it_reports_the_other_authors_by_name(db, capsys):
    """"Who else has cards here" is the question somebody runs this to answer,
    and silence would read as "nobody"."""
    db(claimable=[("general", 38)], others=[(2, "olena@example.com", 12)])

    code = claim_flashcards.main(["--owner", "anton@example.com", "--dry-run"])
    out = capsys.readouterr().out

    assert code == 0
    assert "+ general   38 card(s)" in out
    assert "user 2 (olena@example.com)" in out and "12 card(s), left alone" in out
    assert "nothing written" in out


def test_an_author_whose_account_is_gone_is_still_named(db, capsys):
    """`added_by_user_id` is RESTRICT (#165), so this should not happen -- and
    if it ever does, a row printing `None` as an email is worse than one saying
    what it means."""
    db(claimable=[], others=[(3, None, 4)])

    claim_flashcards.main(["--owner", "anton@example.com"])

    assert "account deleted" in capsys.readouterr().out


def test_a_name_a_windows_console_cannot_print_is_escaped(db, capsys):
    db(claimable=[("українська", 2)])

    code = claim_flashcards.main(["--owner", "anton@example.com", "--dry-run"])

    assert code == 0
    assert capsys.readouterr().out.isascii()
