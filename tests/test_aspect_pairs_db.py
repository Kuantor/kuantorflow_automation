"""`aspect_pairs` against a real MySQL (kuantorflow#100).

Pairs stored both ways, a "checked, no partner" marker, `INSERT IGNORE` so a
re-run adds nothing twice, the partners of a round in one query (markers
never answered as partners), and the verb cards the script reads -- adverbs
left out.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv


@pytest.fixture(autouse=True)
def _the_real_utils(real_utils):
    """A real scratch database, so the offline stubs would answer first
    (kuantorflow#436)."""


AUTO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(AUTO_ROOT / ".env")

KUANTORFLOW_PATH = Path(os.environ.get(
    "KUANTORFLOW_PATH", str(AUTO_ROOT.parent.parent / "kuantorflow")))
SCRIPT = KUANTORFLOW_PATH / "scripts" / "apply_schema.py"

SCRATCH_DB = "kuantorflow_aspect_pairs_test"

pytestmark = [pytest.mark.db, pytest.mark.skipif(
    not (os.environ.get("RUN_DB_ROUNDTRIP") == "1"
         and os.environ.get("DB_HOST") in ("localhost", "127.0.0.1")
         and os.environ.get("DB_PASSWORD")
         and SCRIPT.exists()),
    reason="opt-in: set RUN_DB_ROUNDTRIP=1 with a local MySQL (DB_HOST=localhost) "
    "and DB_* configured; the test creates its own scratch database")]


def _execute(statements):
    import mysql.connector
    conn = mysql.connector.connect(
        user=os.environ.get("DB_USER", "kuantorflow"),
        password=os.environ["DB_PASSWORD"], host=os.environ["DB_HOST"])
    cursor = conn.cursor()
    for statement in statements:
        cursor.execute(statement)
    conn.commit()
    cursor.close()
    conn.close()


@pytest.fixture()
def scratch_db(monkeypatch):
    _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}",
              f"CREATE DATABASE {SCRATCH_DB} CHARACTER SET utf8mb4"])
    subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                   env=dict(os.environ, DB_NAME=SCRATCH_DB),
                   cwd=str(KUANTORFLOW_PATH), check=True)
    monkeypatch.setenv("DB_NAME", SCRATCH_DB)
    try:
        yield SCRATCH_DB
    finally:
        _execute([f"DROP DATABASE IF EXISTS {SCRATCH_DB}"])


def test_pairs_are_stored_both_ways_with_a_no_partner_marker(scratch_db):
    import utils

    utils.save_aspect_pairs("ukr", {"писати": {"написати"}, "гуляти": set()})

    assert utils.aspect_partners("ukr", {"писати", "написати", "гуляти"}) == {
        "писати": {"написати"}, "написати": {"писати"}}
    assert utils.aspect_forms_checked("ukr", {"писати", "написати", "гуляти", "читати"}) == {
        "писати", "написати", "гуляти"}


def test_a_rerun_adds_nothing_twice(scratch_db):
    import utils

    utils.save_aspect_pairs("rus", {"писать": {"написать"}})
    assert utils.save_aspect_pairs("rus", {"написать": {"писать"}}) == 0


def test_languages_are_kept_apart(scratch_db):
    import utils

    utils.save_aspect_pairs("rus", {"писать": {"написать"}})

    assert utils.aspect_partners("ukr", {"писать"}) == {}
    assert utils.aspect_forms_checked("ukr", {"писать"}) == set()


def test_the_script_reads_verb_cards_only(scratch_db):
    import utils

    for word, pos, ukr in (("write", "verb", "писати"), ("give up", "phrasal verb", "здатися"),
                           ("quickly", "adverb", "швидко"), ("house", "noun", "дім")):
        utils.save_flashcard({"word": word, "pos": pos, "translation_ukr": ukr,
                              "translation_rus": None, "topic": "t"})

    assert sorted(r[0] for r in utils.verb_card_translations()) == ["здатися", "писати"]
