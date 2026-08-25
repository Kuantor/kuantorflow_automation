"""Settings and chat logs keyed on the user id (kuantorflow#174).

Both stores used to be named after the email prefix — everything before the
'@'. That key was neither stable nor unique: changing your address orphaned
your settings and your whole chat history, and anton@gmail.com and
anton@outlook.com collapsed to one `anton`, silently sharing both.

They are keyed on the users-table id now, with the address recorded *inside*
the file so a directory listing is still readable. Pre-#174 files are moved
onto their id-keyed name the first time that user is seen.
"""

import json

import pytest

import settings_store
from conftest import TEST_USER_EMAIL, TEST_USER_ID


ANON = "config-default.json"


# --- the settings key ---------------------------------------------------------

def test_the_file_is_named_after_the_id(settings_dir):
    settings_store.load(7, "anton@example.com")
    assert (settings_dir / "config-7.json").is_file()
    assert not (settings_dir / "config-anton.json").exists()


def test_anonymous_visitors_still_share_the_default(settings_dir):
    settings_store.load(None)
    assert (settings_dir / ANON).is_file()


def test_colliding_email_prefixes_get_separate_files(settings_dir):
    """The bug the id fixes: both of these used to be `config-anton.json`."""
    settings_store.save({"translator": "microsoft"}, 7, "anton@gmail.com")
    settings_store.save({"translator": "google"}, 8, "anton@outlook.com")
    assert settings_store.load(7, "anton@gmail.com")["translator"] == "microsoft"
    assert settings_store.load(8, "anton@outlook.com")["translator"] == "claude"


def test_an_email_change_keeps_the_settings(settings_dir):
    """The other bug: the file used to be orphaned by a rename."""
    settings_store.save({"translator": "microsoft"}, 7, "before@example.com")
    assert settings_store.load(7, "after@example.com")["translator"] == "microsoft"


@pytest.mark.parametrize("bad", ["../../etc/passwd", "7; rm -rf /", "", None,
                                 "abc", 7.5])
def test_a_junk_id_falls_back_to_the_default(bad):
    """Whatever arrives, the name must stay inside SETTINGS_DIR."""
    assert settings_store.safe_key(bad) == settings_store.DEFAULT_USERNAME


# --- the email is metadata, not a setting -------------------------------------

def test_the_file_records_the_owner(settings_dir):
    settings_store.save({}, 7, "anton@example.com")
    raw = json.loads((settings_dir / "config-7.json").read_text(encoding="utf-8"))
    assert raw["_email"] == "anton@example.com"


def test_the_email_refreshes_itself_on_save(settings_dir):
    """No rename is ever needed — save() rewrites the whole file."""
    settings_store.save({}, 7, "before@example.com")
    settings_store.save({}, 7, "after@example.com")
    raw = json.loads((settings_dir / "config-7.json").read_text(encoding="utf-8"))
    assert raw["_email"] == "after@example.com"


def test_the_email_is_not_a_setting(settings_dir):
    """It must not reach a template or the /settings JSON response."""
    stored = settings_store.save({}, 7, "anton@example.com")
    assert "_email" not in stored
    assert "_email" not in settings_store.load(7, "anton@example.com")


def test_the_settings_response_carries_no_email(user_client, settings_dir):
    body = user_client.post("/settings", json={"translator": "microsoft"}).get_json()
    assert "_email" not in body["settings"]


# --- migrating pre-#174 files -------------------------------------------------

def _legacy(settings_dir, name, **values):
    settings_dir.mkdir(parents=True, exist_ok=True)
    path = settings_dir / f"config-{name}.json"
    path.write_text(json.dumps(dict(settings_store.DEFAULTS, **values)),
                    encoding="utf-8")
    return path


def test_a_legacy_file_is_migrated_on_read(settings_dir):
    legacy = _legacy(settings_dir, "anton", translator="microsoft")
    assert settings_store.load(7, "anton@example.com")["translator"] == "microsoft"
    assert (settings_dir / "config-7.json").is_file()
    assert not legacy.exists(), "the old file is moved, not copied"


def test_migration_happens_once(settings_dir):
    _legacy(settings_dir, "anton", translator="microsoft")
    settings_store.load(7, "anton@example.com")
    settings_store.save({"translator": "google"}, 7, "anton@example.com")
    # a stale legacy file reappearing must not clobber the migrated settings
    _legacy(settings_dir, "anton", translator="microsoft")
    assert settings_store.load(7, "anton@example.com")["translator"] == "claude"


def test_a_user_with_no_legacy_file_just_gets_defaults(settings_dir):
    assert settings_store.load(7, "nobody@example.com") == settings_store.DEFAULTS
    assert (settings_dir / "config-7.json").is_file()


def test_the_shared_default_is_never_migrated(settings_dir):
    """An address with no usable prefix was on config-default.json, which is
    everybody's — it must not be adopted as one user's settings."""
    _legacy(settings_dir, "default", translator="microsoft")
    assert settings_store.load(7, "@@@")["translator"] == "claude"
    assert (settings_dir / ANON).is_file()


def test_a_numeric_prefix_does_not_hand_over_someone_elses_settings(settings_dir):
    """The pathological collision: 7@example.com was already config-7.json,
    which is the name user id 7 now wants. The stranger's settings must not be
    inherited — the file has no _email, so it is recognised as pre-#174."""
    _legacy(settings_dir, "7", translator="microsoft")          # belongs to 7@example.com
    _legacy(settings_dir, "anton", translator="google")    # belongs to id 7

    assert settings_store.load(7, "anton@example.com")["translator"] == "claude"
    assert (settings_dir / "config-7.json.orphaned").is_file(), \
        "the stranger's file is set aside, not deleted"


def test_an_already_migrated_file_is_left_alone(settings_dir):
    """Once a file carries _email it is this user's own — a legacy leftover
    must not overwrite it."""
    settings_store.save({"translator": "google"}, 7, "anton@example.com")
    _legacy(settings_dir, "anton", translator="microsoft")
    assert settings_store.load(7, "anton@example.com")["translator"] == "claude"


# --- the chat log folder ------------------------------------------------------

def _chat(directory, name="chat_2026-07-20_11-00-00_aaaa.txt", text="hello"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")


def test_the_log_folder_is_named_after_the_id(user_client, app_module,
                                              chat_logs):
    with app_module.app.test_request_context("/"):
        from flask import session
        session["user"] = {"id": TEST_USER_ID, "email": TEST_USER_EMAIL,
                           "name": "Test User"}
        assert app_module._current_user_log_dir() == chat_logs / str(TEST_USER_ID)


def test_anonymous_chats_stay_at_the_top_level(app_module, chat_logs):
    with app_module.app.test_request_context("/"):
        assert app_module._current_user_log_dir() == chat_logs


def test_a_legacy_log_folder_is_migrated(app_module, chat_logs):
    _chat(chat_logs / "anton", text="an old conversation")
    with app_module.app.test_request_context("/"):
        from flask import session
        session["user"] = {"id": 7, "email": "anton@example.com", "name": "A"}
        user_dir = app_module._current_user_log_dir()

    assert user_dir == chat_logs / "7"
    assert (user_dir / "chat_2026-07-20_11-00-00_aaaa.txt").read_text(
        encoding="utf-8") == "an old conversation"
    assert not (chat_logs / "anton").exists(), "moved, not copied"


def test_the_folder_records_who_it_belongs_to(app_module, chat_logs):
    with app_module.app.test_request_context("/"):
        from flask import session
        session["user"] = {"id": 7, "email": "anton@example.com",
                           "name": "Anton Kuznietsov"}
        user_dir = app_module._current_user_log_dir()

    marker = (user_dir / "user.txt").read_text(encoding="utf-8")
    assert "id: 7" in marker
    # the FULL address, not the prefix — prefixes are what collide
    assert "email: anton@example.com" in marker
    assert "name: Anton Kuznietsov" in marker


def test_the_marker_is_never_read_as_a_conversation(app_module, chat_logs):
    """_user_log_files() globs chat_*.txt, so user.txt can't reach the recap."""
    with app_module.app.test_request_context("/"):
        from flask import session
        session["user"] = {"id": 7, "email": "anton@example.com", "name": "A"}
        app_module._current_user_log_dir()
        assert app_module._user_log_files() == []
        assert app_module._read_user_logs() == ""


def test_a_migrated_file_is_stamped_immediately(settings_dir):
    """Not on the user's next settings save — otherwise a just-migrated file
    is unreadable in a directory listing, which is most of the point."""
    _legacy(settings_dir, "anton", translator="microsoft")
    settings_store.load(7, "anton@example.com")
    raw = json.loads((settings_dir / "config-7.json").read_text(encoding="utf-8"))
    assert raw["_email"] == "anton@example.com"
    assert raw["translator"] == "microsoft", "the settings survive the stamping"
