"""Mykola must not confirm a card he did not save (kuantorflow#308).

Duplicate detection is global (#101) while topics are not, so a card Mykola is
asked to file under *emotions* can be skipped because the word already exists
under *psychology* — and the learner, told it was saved, goes looking in
emotions and finds nothing. With #127's filter on it is worse: the blocking
card can belong to another account, so it is nowhere they can see at all.

The lie was manufactured in the host, not by the model. ai_agent's
`_run_add_flashcard()` reports `saved` for any call that does not raise and
ignores what the saver returns, and the model's own instructions already say
never to claim a card was saved unless the tool returned success. So the fix,
and this file, are about one thing: **a skipped save must raise.**
"""

import pytest
from flask import session

from conftest import TEST_USER_ID

ENTRY = {"word": "aspiration", "pos": "noun", "topic": "emotions"}


@pytest.fixture()
def skipped(app_module, monkeypatch):
    """save_flashcard() reporting a duplicate — the None that started it all."""
    monkeypatch.setattr(app_module, "save_flashcard",
                        lambda entry, added_by_user_id=None: None)
    monkeypatch.setattr(app_module, "duplicate_topic",
                        lambda word, pos: "psychology")
    # Visible to this learner: their own card, so #186 stays quiet.
    monkeypatch.setattr(app_module, "find_duplicate",
                        lambda word, pos, exclude_id=None: (9, TEST_USER_ID))


def _save(app_module, entry=None):
    """Call the injected saver as the agent does, signed in."""
    with app_module.app.test_request_context("/mykola/chat"):
        session["user"] = {"id": TEST_USER_ID, "email": "test.user@gmail.com"}
        return app_module._save_card_from_chat(dict(entry or ENTRY))


def test_a_skipped_duplicate_is_not_reported_as_saved(app_module, skipped):
    """The whole bug in one assertion. Returning normally is precisely what the
    agent reads as success, so the saver has to raise or Mykola will confirm a
    card that was never written."""
    with pytest.raises(Exception) as excinfo:
        _save(app_module)
    assert "already saved" in str(excinfo.value).lower()


def test_the_message_names_the_topic_the_card_is_really_in(app_module, skipped):
    """Naming it is the difference between a correction and a riddle: the
    learner asked for *emotions* and the card is in *psychology*."""
    with pytest.raises(Exception) as excinfo:
        _save(app_module)
    message = str(excinfo.value)
    assert "psychology" in message
    assert "noun" in message           # the pos is half of what made it a dupe


def test_a_hidden_duplicate_is_explained_rather_than_located(app_module,
                                                             monkeypatch,
                                                             skipped):
    """#186's case, reached through chat. The blocking card belongs to someone
    else and #127 hides it, so its topic is not ours to name — naming it would
    send them looking through a deck they cannot see, and leak where another
    account files its cards."""
    monkeypatch.setattr(app_module, "find_duplicate",
                        lambda word, pos, exclude_id=None: (9, 99))
    monkeypatch.setattr(app_module, "current_settings",
                        lambda: {"individual_cards": True, "quiz_lang": "ukr"})
    with pytest.raises(Exception) as excinfo:
        _save(app_module)
    message = str(excinfo.value)
    assert "individual cards" in message.lower()
    assert "psychology" not in message


def test_a_real_save_still_reports_success(app_module, saved):
    """The regression that would matter most: every card that really is
    written must still come back as saved."""
    assert _save(app_module) is not None
    assert saved.owner_ids == [TEST_USER_ID]


def test_a_dead_database_still_corrects_the_claim(app_module, monkeypatch,
                                                  skipped):
    """Losing the topic name costs the nicety, not the correction — saying
    'already saved' without it still beats claiming it was saved."""
    def boom(word, pos):
        raise RuntimeError("database is down")

    monkeypatch.setattr(app_module, "duplicate_topic", boom)
    with pytest.raises(Exception) as excinfo:
        _save(app_module)
    assert "already saved" in str(excinfo.value).lower()


def test_the_skip_is_still_logged_exactly_as_before(app_module, skipped,
                                                    action_logs):
    """cards.log was right all along — it recorded the SKIP while the chat
    claimed a save. Raising must not cost the line."""
    with pytest.raises(Exception):
        _save(app_module)
    written = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert "SKIP" in written
    assert "word=aspiration" in written
    assert "reason=duplicate" in written
    assert "source='Mykola chat'" in written


def test_an_anonymous_visitor_is_still_refused_first(app_module, skipped):
    """#125 unchanged, and it comes first: no account, no write, and the
    refusal says so rather than mentioning duplicates."""
    with app_module.app.test_request_context("/mykola/chat"):
        with pytest.raises(PermissionError) as excinfo:
            app_module._save_card_from_chat(dict(ENTRY))
    assert "sign in with google" in str(excinfo.value).lower()
