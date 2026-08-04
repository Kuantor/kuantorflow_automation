"""Uploading notes requires an account (kuantorflow#200).

Parsing a Reverso `.mht`/`.docx` sends its glued translations to Claude
(`_split_glued_translations`), and that happens **before** the save — which
#125 refuses for a visitor with no account. So an anonymous upload spent money
producing cards the person was then not allowed to keep.

The assertion that matters is not the status code but that **the parser is
never called**: a refusal that still parses passes the obvious check and fails
the entire purpose.
"""

import io

import pytest


def _upload(client, filename="notes.docx"):
    return client.post(
        "/",
        data={"action": "upload_notes", "topic": "vocab",
              "notes_file": (io.BytesIO(b"whatever"), filename)},
        content_type="multipart/form-data", follow_redirects=True)


@pytest.fixture()
def parses(app_module, monkeypatch):
    """Record every call to the parser — it is what costs money."""
    calls = []
    monkeypatch.setattr(app_module, "parse_notes_preview",
                        lambda *a, **k: calls.append(a) or ([], ""))
    return calls


def test_an_anonymous_upload_never_reaches_the_parser(client, parses):
    _upload(client)
    assert parses == []


def test_a_blocked_account_never_reaches_it_either(user_client, block_state,
                                                   parses):
    """They have an account but may not write, so the same reasoning holds."""
    block_state.block()
    _upload(user_client)
    assert parses == []


def test_a_signed_in_upload_still_parses(user_client, parses):
    _upload(user_client)
    assert len(parses) == 1


def test_the_refusal_prompts_the_visitor_to_sign_in(client, parses):
    body = _upload(client).get_data(as_text=True)
    assert "kfSignInRequired" in body


def test_the_blocked_wording_is_not_the_sign_in_wording(user_client,
                                                        block_state, parses):
    """A blocked visitor is signed in already; telling them to sign in would
    send them round a loop that changes nothing (#126)."""
    block_state.block()
    raised = _upload(user_client).get_data(as_text=True)
    raised = raised[raised.index('kfSignInRequired("'):]
    raised = raised[:raised.index(");")]
    assert "blocked" in raised.lower()
    assert "sign in" not in raised.lower()


def test_every_upload_is_refused_not_only_the_expensive_ones(client, parses):
    """Which file calls Claude cannot be known without parsing it, so a plain
    `.txt` is refused too — the guard is at the door, not inside the parser."""
    _upload(client, filename="notes.txt")
    assert parses == []
