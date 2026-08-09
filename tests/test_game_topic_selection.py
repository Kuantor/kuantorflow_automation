"""
Which topics a round plays over, and the cards it draws (kuantorflow#248).

The groundwork under #233's umbrella. Two things are proved here:

* `games.resolve_selection()` and friends, which turn a query string, a
  remembered selection and "no topics at all" into one list of names. They are
  pure, so they are tested on plain lists and a plain dict — no request context,
  no database, no app.
* the SQL `utils.get_flashcards_by_topics()` builds. What the database then
  *does* with it lives in test_topics_table_db.py, against a real MySQL.

The rule worth stating once, because three tests circle it: **empty means
opposite things on either side of the seam.** No `?topic=` in a URL means the
whole visible deck, and that is resolved into an explicit list of names before
any query runs. An empty list reaching `get_flashcards_by_topics()` therefore
means "nothing was selected" and must return no cards — the same trap
`_owner_clause()` documents for `owner_id`, where "no filter" and "nobody" look
alike and guessing wrong returns the entire deck.
"""

import json

import pytest

import games
import utils


SECTIONS = [
    ("B2–C1 Conversational Topics", [("Work and careers", 20), ("Travel", 20)]),
    ("Other", [("animals", 3), ("Work stuff", 1)]),
]
VISIBLE = ["Work and careers", "Travel", "animals", "Work stuff"]


# --- what the learner can see ------------------------------------------


def test_visible_names_keep_the_order_the_page_renders():
    """#215's (section.position, topic.position, topic.name), flattened.

    Not sorted: the curriculum section is deliberately not alphabetical, and a
    picker that re-sorted would show a different order from the front page the
    learner just looked at."""
    assert games.visible_topic_names(SECTIONS) == VISIBLE


def test_an_empty_section_contributes_nothing():
    """#218 keeps an empty section's heading on the browse page. It still has
    no topics to select."""
    assert games.visible_topic_names([("B2–C1 Conversational Topics", []),
                                      ("Other", [("animals", 3)])]) == ["animals"]


# --- resolving what to play --------------------------------------------


def test_nothing_requested_plays_the_whole_visible_deck():
    """#233: a bare /games/<game>/play link is meaningful, and the picker has a
    'just start' default."""
    assert games.resolve_selection([], VISIBLE) == VISIBLE


def test_a_selection_comes_back_in_page_order_not_parameter_order():
    assert games.resolve_selection(["animals", "Work and careers"], VISIBLE) == \
        ["Work and careers", "animals"]


def test_a_topic_that_is_no_longer_visible_is_dropped_silently():
    """Deleted, renamed, or hidden by turning on #127 between two rounds. The
    stored list is a hint, so the rest of the selection survives."""
    assert games.resolve_selection(["Work and careers", "Deleted"], VISIBLE) == \
        ["Work and careers"]


def test_a_selection_of_nothing_that_still_exists_resolves_to_nothing():
    """The distinction that matters: *requested but all gone* is empty, and must
    not fall through to the whole-deck default."""
    assert games.resolve_selection(["Deleted", "Also deleted"], VISIBLE) == []


def test_a_name_matches_regardless_of_case_and_comes_back_canonical():
    """The database's collation is case-insensitive, so a hand-typed URL should
    behave the same way. The topics row's spelling is what the page shows."""
    assert games.resolve_selection(["work AND careers"], VISIBLE) == \
        ["Work and careers"]


def test_a_repeated_topic_is_played_once():
    assert games.resolve_selection(["Travel", "Travel"], VISIBLE) == ["Travel"]


def test_a_blank_parameter_is_not_a_topic():
    """?topic=&topic=Travel — an empty value selects nothing, and does not
    accidentally read as 'no selection, play everything'."""
    assert games.resolve_selection(["", "Travel"], VISIBLE) == ["Travel"]


# --- remembering it ----------------------------------------------------


def test_nothing_remembered_is_nothing_not_everything():
    """The mirror image of the rule above, and the reason the two do not share
    a path: a first-time visitor has expressed no preference, and ticking the
    whole deck for them would be inventing one."""
    assert games.remembered_selection({}, VISIBLE) == []


def test_a_selection_survives_a_round_trip_through_the_store():
    store = {}
    games.remember_selection(store, ["Work and careers", "animals"])
    assert games.remembered_selection(store, VISIBLE) == \
        ["Work and careers", "animals"]


def test_only_the_names_are_stored():
    """Names rather than ids (#207's convention), and a plain list — the session
    is a signed cookie, so what goes in it has to stay small and serialisable."""
    store = {}
    games.remember_selection(store, ["Travel"])
    assert store == {games.SELECTION_KEY: ["Travel"]}
    assert json.loads(json.dumps(store)) == store


def test_a_remembered_topic_that_has_gone_is_dropped_and_the_rest_survive():
    store = {}
    games.remember_selection(store, ["Work and careers", "animals"])
    assert games.remembered_selection(store, ["animals"]) == ["animals"]


def test_a_remembered_selection_that_has_entirely_gone_opens_as_a_newcomers():
    store = {}
    games.remember_selection(store, ["Work and careers"])
    assert games.remembered_selection(store, ["Travel"]) == []


@pytest.mark.parametrize("junk", ["not-a-list", 42, {"a": 1}, None])
def test_junk_in_the_session_is_ignored_rather_than_raising(junk):
    """A cookie is client-side. It is signed, so it cannot be forged, but an old
    build's value can still arrive — and a picker must not 500 on one."""
    assert games.remembered_selection({games.SELECTION_KEY: junk}, VISIBLE) == []


# --- the query -----------------------------------------------------------


@pytest.fixture()
def sql(monkeypatch):
    """Capture the statement and parameters, returning one card."""
    sent = []

    class Cursor:
        def execute(self, statement, params=None):
            sent.append((" ".join(statement.split()), params))

        def fetchall(self):
            return [{"id": 1, "word": "resilient",
                     "examples_en": json.dumps(["one"]),
                     "examples_ukr": None, "examples_rus": None}]

        def close(self):
            pass

    class Connection:
        def cursor(self, dictionary=False):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr(utils, "get_db_connection", lambda: Connection())
    return sent


def test_several_topics_are_one_query_with_one_placeholder_each(sql):
    """The point of the function: a selection of eighteen is one round trip, not
    eighteen connections."""
    utils.get_flashcards_by_topics(["Work", "Travel", "animals"])

    assert len(sql) == 1
    statement, params = sql[0]
    assert "t.name IN (%s, %s, %s)" in statement
    assert params == ("Work", "Travel", "animals")


def test_the_names_travel_as_parameters(sql):
    """Interpolated into the statement they would be an injection point, and
    topic names are user-supplied."""
    utils.get_flashcards_by_topics(["'; DROP TABLE flashcards; --"])

    statement, params = sql[0]
    assert "DROP TABLE" not in statement
    assert params == ("'; DROP TABLE flashcards; --",)


def test_the_owner_filter_still_applies(sql):
    """#127, and it is about who owns the *card* — f., not t."""
    utils.get_flashcards_by_topics(["Work"], owner_id=7)

    statement, params = sql[0]
    assert "f.added_by_user_id = %s" in statement
    assert params == ("Work", 7)


def test_no_owner_means_every_card_not_nobodys(sql):
    utils.get_flashcards_by_topics(["Work"])

    statement, params = sql[0]
    assert "added_by_user_id" not in statement
    assert params == ("Work",)


def test_one_topic_goes_through_the_same_query(sql):
    """get_flashcards_by_topic() delegates, so there is one query builder rather
    than two that have to agree."""
    utils.get_flashcards_by_topic("Work")

    statement, params = sql[0]
    assert "t.name IN (%s)" in statement
    assert params == ("Work",)


def test_examples_are_still_deserialised(sql):
    """The list fields come back as lists, whichever entry point was used."""
    cards = utils.get_flashcards_by_topics(["Work"])

    assert cards[0]["examples_en"] == ["one"]
    assert cards[0]["examples_ukr"] == []


@pytest.mark.parametrize("nothing", [[], None, ["", None]])
def test_selecting_nothing_returns_nothing_and_asks_the_database_nothing(
        sql, nothing):
    """Not every card — see this module's docstring. And no query at all: an
    empty IN () is a syntax error, so the early return is load-bearing as well
    as correct."""
    assert utils.get_flashcards_by_topics(nothing) == []
    assert sql == []
