"""Action logs in logs/ (kuantorflow#30).

Three files — cards.log, dict.log, parsed_files.log — written as
`<timestamp> ACTION key=value …`. The autouse `action_logs` fixture points
them at a temp directory, so these tests never touch a real checkout.
"""

import io
import logging
from logging.handlers import TimedRotatingFileHandler

import pytest

import applog
import parsers


def _lines(directory, name):
    path = directory / f"{name}.log"
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def _find(directory, name, action):
    return [line for line in _lines(directory, name)
            if line.split(" ", 2)[2].startswith(action + " ")]


def _card_form(**overrides):
    form = {"word": "resilient", "pos": "adjective", "topic": "character",
            "explanation_en": "able to recover quickly",
            "translation_ukr": "стійкий"}
    form.update(overrides)
    return form


# --- cards.log --------------------------------------------------------------

def test_card_creation_is_logged(user_client, saved, action_logs):
    # Signed in because only an account may write since kuantorflow#125.
    user_client.post("/cards/add", data=_card_form())
    created = _find(action_logs, "cards", "CREATE")
    assert len(created) == 1 and saved
    line = created[0]
    assert "word=resilient" in line
    assert "pos=adjective" in line
    assert "topic=character" in line
    assert "id=1" in line                        # the row id save_flashcard gave
    assert "langs=ukr" in line                   # which translations it carries
    assert "source='review popup'" in line
    assert "user=test.user@gmail.com" in line


def test_signed_in_user_is_named(user_client, saved, action_logs):
    user_client.post("/cards/add", data=_card_form())
    assert "user=test.user@gmail.com" in _find(action_logs, "cards", "CREATE")[0]


def test_duplicate_card_is_logged_as_skipped(user_client, app_module,
                                             monkeypatch, action_logs):
    monkeypatch.setattr(app_module, "save_flashcard",
                        lambda entry, added_by_user_id=None: None)
    resp = user_client.post("/cards/add", data=_card_form())
    assert resp.get_json()["duplicate"] is True
    line = _find(action_logs, "cards", "SKIP")[0]
    assert "word=resilient" in line and "reason=duplicate" in line


def test_automatic_add_is_logged_with_its_own_source(user_client, saved,
                                                     app_module, monkeypatch,
                                                     action_logs):
    monkeypatch.setattr(app_module, "lookup_word", lambda *a, **k: [
        {"word": "resilient", "pos": "adjective", "topic": "vocab"}])
    monkeypatch.setattr(app_module, "current_settings", lambda: dict(
        translator="google", explanatory_dictionary="oxford",
        cards_automatically=True, show_ukrainian=True, show_russian=True,
        quiz_lang="ukr"))
    user_client.post("/", data={"action": "parse_word", "word": "resilient",
                                "topic": "vocab"})
    assert "source='automatic add'" in _find(action_logs, "cards", "CREATE")[0]


def test_card_deletion_is_logged(user_client, app_module, monkeypatch,
                                 action_logs):
    monkeypatch.setattr(app_module, "delete_flashcard",
                        lambda card_id, **kw: ("resilient", "deleted"))
    user_client.post("/flashcards/character/delete/42")
    line = _find(action_logs, "cards", "DELETE")[0]
    assert "id=42" in line and "word=resilient" in line and "topic=character" in line


def test_deleting_a_missing_card_is_logged_too(user_client, app_module,
                                               monkeypatch, action_logs):
    monkeypatch.setattr(app_module, "delete_flashcard",
                        lambda card_id, **kw: (None, "missing"))
    user_client.post("/flashcards/character/delete/99")
    assert _find(action_logs, "cards", "DELETE-MISS")
    assert not _find(action_logs, "cards", "DELETE")


def test_edit_helper_is_ready_for_an_edit_feature(action_logs):
    """The app has no edit-a-saved-card route yet; the helper exists so that
    one logs from the first commit."""
    applog.card_edited({"word": "resilient", "pos": "adjective", "topic": "t"},
                       source="card page", card_id=7, changed=["explanation_en"],
                       user="someone@example.com")
    line = _find(action_logs, "cards", "EDIT")[0]
    assert "id=7" in line and "changed=explanation_en" in line


# --- dict.log ---------------------------------------------------------------

def test_lookup_logs_every_site_it_used(action_logs, monkeypatch):
    monkeypatch.setattr(parsers, "_google_dictionary",
                        lambda word, code: {"noun": ["стійкість"]})
    monkeypatch.setattr(parsers, "_fetch_oxford_definitions",
                        lambda word: {"noun": ["able to recover"]})
    parsers.lookup_word("resilient", translator="google",
                        explanatory_dictionary="oxford")

    translate = _find(action_logs, "dict", "TRANSLATE")
    assert len(translate) == 2                    # one per language
    assert "provider=google" in translate[0] and "pos_count=1" in translate[0]
    assert "ms=" in translate[0]
    define = _find(action_logs, "dict", "DEFINE")[0]
    assert "provider=oxford" in define and "pos_count=1" in define
    assert "cards=1" in _find(action_logs, "dict", "RESULT")[0]


def test_lookup_logs_the_fallback_provider(action_logs, monkeypatch):
    """Bing is unreachable → Google answers instead; the log says so."""
    monkeypatch.setattr(parsers, "_bing_dictionary",
                        lambda word, code: (_ for _ in ()).throw(ValueError("401")))
    monkeypatch.setattr(parsers, "_google_dictionary",
                        lambda word, code: {"noun": ["стійкість"]})
    monkeypatch.setattr(parsers, "_fetch_oxford_definitions", lambda word: {})
    monkeypatch.setattr(parsers, "_fetch_definitions", lambda word: {})
    parsers.lookup_word("resilient", translator="bing",
                        explanatory_dictionary="oxford")

    lines = _find(action_logs, "dict", "TRANSLATE")
    assert "provider=bing" in lines[0] and "error=401" in lines[0]
    assert "provider=google" in lines[1] and "fallback_from=bing" in lines[1]
    # the dictionary fell back to Reverso as well
    assert "fallback_from=oxford" in _find(action_logs, "dict", "DEFINE")[1]


def test_failed_lookup_is_logged(action_logs, monkeypatch):
    monkeypatch.setattr(parsers, "_google_dictionary", lambda word, code: {})
    with pytest.raises(ValueError):
        parsers.lookup_word("zzzz", translator="google")
    assert "error='no translations'" in _find(action_logs, "dict", "FAILED")[0]


def test_lookup_route_logs_the_user_and_their_providers(client, saved, app_module,
                                                        monkeypatch, action_logs):
    monkeypatch.setattr(app_module, "lookup_word", lambda *a, **k: [])
    client.post("/", data={"action": "parse_word", "word": "resilient",
                           "topic": "vocab"})
    line = _find(action_logs, "dict", "LOOKUP")[0]
    assert "word=resilient" in line
    assert "translator=google" in line and "dictionary=oxford" in line
    assert "user=anonymous" in line


# --- parsed_files.log -------------------------------------------------------

NOTES = "pursuit - преследование\nhaunting - навязчивый\n"


def _upload(client, data, filename):
    return client.post(
        "/",
        data={"action": "upload_notes", "topic": "vocab",
              "notes_file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def test_parsed_file_is_logged(user_client, saved, action_logs):
    payload = NOTES.encode("utf-8")
    _upload(user_client, payload, "notes.txt")
    line = _find(action_logs, "parsed_files", "PARSE")[0]
    assert "file=notes.txt" in line
    assert f"bytes={len(payload)}" in line
    assert "cards=2" in line
    # Signed-in since #200: an upload with no account is refused before parsing.
    assert "topic=vocab" in line and "user=test.user@gmail.com" in line and "ms=" in line


def test_rejected_file_is_logged(user_client, saved, action_logs):
    _upload(user_client, b"whatever", "notes.pdf")
    line = _find(action_logs, "parsed_files", "REJECT")[0]
    assert "file=notes.pdf" in line and "Unsupported notes format" in line
    assert not _find(action_logs, "parsed_files", "PARSE")


def test_ai_term_split_is_logged(action_logs, monkeypatch):
    """The split fails silently by design (#134), so the log is the only trace."""
    parsers._split_glued_translations(["абвгде"])       # no anthropic package
    line = _find(action_logs, "parsed_files", "SPLIT")[0]
    assert "lines=1" in line and "error=" in line
    assert parsers.SPLIT_MODEL in line


# --- the log files themselves -----------------------------------------------

def test_the_three_log_files_are_written_where_the_issue_asks(client, saved,
                                                              action_logs):
    client.post("/cards/add", data=_card_form())
    applog.lookup_started("resilient", "google", "oxford")
    applog.file_parsed("notes.txt", 10, 1)
    assert sorted(p.name for p in action_logs.iterdir()) == [
        "cards.log", "dict.log", "parsed_files.log"]


def test_logs_rotate_monthly_and_keep_a_year():
    handler = applog._logger("cards").handlers[0]
    assert isinstance(handler, TimedRotatingFileHandler)
    assert handler.when == "MIDNIGHT"
    assert handler.interval == 30 * 24 * 60 * 60      # 30 days, in seconds
    assert handler.backupCount == 12


def test_values_with_spaces_are_quoted(action_logs):
    applog.card_created({"word": "lucid dream", "topic": "my topic"},
                        source="review popup")
    line = _find(action_logs, "cards", "CREATE")[0]
    assert "word='lucid dream'" in line and "topic='my topic'" in line


def test_a_broken_log_never_breaks_the_action(user_client, saved, monkeypatch,
                                              action_logs):
    def boom(name):
        raise OSError("read-only file system")
    monkeypatch.setattr(applog, "_logger", boom)
    resp = user_client.post("/cards/add", data=_card_form())
    assert resp.status_code == 200 and resp.get_json()["saved"] is True
    assert saved, "the card must still be saved when logging fails"


def test_logs_do_not_leak_into_the_app_console(action_logs):
    """propagate=False: these lines belong in the file, not in stderr."""
    applog.file_parsed("notes.txt", 10, 1)
    assert applog._logger("parsed_files").propagate is False
    assert logging.getLogger().handlers is not applog._logger("parsed_files").handlers
