"""Moving a translation out of `explanation_en` (kuantorflow#323).

A one-off repair, but it writes to rows nobody is watching, so the decisions
that could lose text quietly are pinned here rather than discovered afterwards:

* a card that **already has a translation** is left alone, because the script
  would otherwise have to choose between two values and choosing wrong deletes
  something a person wrote;
* the language is asked of `_detect_cyrillic_lang()` rather than assumed to be
  Russian, so this cannot drift from the parser it repairs after;
* the `UPDATE` carries the old text in its `WHERE`, so a row edited between the
  read and the write is refused rather than overwritten.

Nothing here touches a database — `get_db_connection` is replaced.
"""

import pytest

from maintenance import fix_explanation_language as fix


RUSSIAN = "контрабанда"
UKRAINIAN = "відставка, звільнення"


class FakeCursor:
    def __init__(self, rows, log):
        self._rows = rows
        self._log = log
        self.rowcount = 0

    def execute(self, sql, params=None):
        self._log.append((" ".join(sql.split()), params))
        self.rowcount = 1

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows, log):
        self._rows, self._log = rows, log
        self.committed = False

    def cursor(self, dictionary=False):
        return FakeCursor(self._rows, self._log)

    def commit(self):
        self.committed = True

    def close(self):
        pass


@pytest.fixture()
def db(monkeypatch):
    """A database answering with `rows`, recording every statement run."""
    import utils

    state = {"rows": [], "log": []}

    def install(rows):
        state["rows"] = rows
        return state["log"]

    monkeypatch.setattr(utils, "get_db_connection",
                        lambda: FakeConn(state["rows"], state["log"]))
    return install


# --- which cards are picked up -------------------------------------------


def test_a_card_with_no_translation_is_repaired(db, capsys):
    db([{"id": 22, "word": "smuggle", "pos": None, "topic": "general",
         "explanation_en": RUSSIAN,
         "translation_ukr": None, "translation_rus": None}])
    assert fix.main([]) == 0
    out = capsys.readouterr().out
    assert "would move 1 card" in out
    assert "smuggle" in out


def test_a_card_that_already_has_a_translation_is_left_alone(db, capsys):
    """Two values and no way to tell which is wanted. Reported for a person to
    look at rather than guessed at — the whole reason the predicate has this
    half."""
    db([{"id": 22, "word": "smuggle", "pos": None, "topic": "general",
         "explanation_en": RUSSIAN,
         "translation_ukr": None, "translation_rus": "провозить контрабандой"}])
    assert fix.main([]) == 0
    out = capsys.readouterr().out
    assert "would move 0 card" in out
    assert "1 skipped" in out
    assert "left for a person to look at" in out


def test_a_clean_deck_says_so_and_writes_nothing(db, capsys):
    log = db([])
    assert fix.main(["--apply"]) == 0
    assert "nothing to repair" in capsys.readouterr().out
    assert not [sql for sql, _ in log if sql.startswith("UPDATE")]


def test_the_query_selects_by_predicate_rather_than_by_id(db):
    """So it is safe to run against any deployment. The ticket lists thirteen
    ids; hard-coding them would make this a script that can only ever repair
    one database."""
    log = db([])
    fix.main([])
    sql = log[0][0]
    assert "REGEXP" in sql and "explanation_en" in sql
    assert "12" not in sql and "IN (" not in sql


# --- where the text goes -------------------------------------------------


def test_russian_goes_to_the_russian_field():
    assert fix.target_field(RUSSIAN) == "translation_rus"


def test_ukrainian_goes_to_the_ukrainian_field():
    """All thirteen rows are Russian, so this is the case the script has never
    met — which is exactly why it is asked rather than assumed."""
    assert fix.target_field(UKRAINIAN) == "translation_ukr"


def test_text_with_no_distinguishing_letter_falls_back_to_russian():
    """`_entry_from_line()` makes the same call the same way; two rules for one
    question would drift."""
    assert fix.target_field("текст") == "translation_rus"


# --- the write -----------------------------------------------------------


def test_the_write_moves_the_text_and_clears_the_explanation(db):
    log = db([])
    fix.write(22, "translation_rus", RUSSIAN)
    sql, params = [row for row in log if row[0].startswith("UPDATE")][0]
    assert "translation_rus = %s" in sql
    assert "explanation_en = NULL" in sql
    assert params == (RUSSIAN, 22, RUSSIAN)


def test_the_write_refuses_a_row_that_changed_underneath_it(db):
    """The old text is in the WHERE, so a card edited between the read and the
    write is reported rather than overwritten."""
    log = db([])
    fix.write(22, "translation_rus", RUSSIAN)
    sql, _ = [row for row in log if row[0].startswith("UPDATE")][0]
    assert "AND explanation_en = %s" in sql


def test_a_dry_run_writes_nothing(db):
    log = db([{"id": 22, "word": "smuggle", "pos": None, "topic": "general",
               "explanation_en": RUSSIAN,
               "translation_ukr": None, "translation_rus": None}])
    fix.main([])
    assert not [sql for sql, _ in log if sql.startswith("UPDATE")]


def test_apply_writes(db):
    log = db([{"id": 22, "word": "smuggle", "pos": None, "topic": "general",
               "explanation_en": RUSSIAN,
               "translation_ukr": None, "translation_rus": None}])
    fix.main(["--apply"])
    assert [sql for sql, _ in log if sql.startswith("UPDATE")]


def test_printing_cyrillic_does_not_take_the_run_down(db, capsys):
    """A Windows console is cp1252, and this script's whole subject is Cyrillic
    — kuantorflow's seed_topics.py hit exactly this and lost a run that was
    saving fine."""
    db([{"id": 22, "word": "smuggle", "pos": None, "topic": "general",
         "explanation_en": RUSSIAN,
         "translation_ukr": None, "translation_rus": None}])
    assert fix.main([]) == 0
    assert "smuggle" in capsys.readouterr().out
