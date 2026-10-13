"""A blocked account is told so on every page (kuantorflow#584).

Blocking (#126) hides Mykola's widget, and after a refresh the chat button
simply vanished: nothing on the page said why. The notice was shown only when
a save or a chat message was refused, and inside the Settings popup, which
nobody opens to find out why a button disappeared.

So while the account is blocked, every page carries the notice at the top of
the page, directly under the header: the same sentence, from
`web.blocked_notice()`, that the refusals and Settings already use. No close
button, since dismissing it would not lift the block; it is gone on the first
page after an unblock, because the block is read live on every request.
"""

import re

import pytest

import web

STORED_CARD = {
    "id": 1, "word": "resilient", "pos": "adjective",
    "explanation_en": "able to recover quickly", "examples_en": [],
    "translation_ukr": "стійкий", "examples_ukr": [],
    "translation_rus": None, "examples_rus": [], "topic": "character",
}

PAGES = ["/", "/flashcards/character", "/deck/character", "/quiz/character",
         "/help"]


@pytest.fixture(autouse=True)
def deck(monkeypatch, app_module):
    monkeypatch.setattr("utils.get_flashcards_by_topic",
                        lambda topic, owner_id=None, **kw: [dict(STORED_CARD)])
    monkeypatch.setattr("web.ADMIN_EMAILS", {"admin@example.com"})


@pytest.fixture()
def blocked_client(user_client, block_state):
    block_state.block()
    return user_client


def _banners(body):
    return re.findall(r'<div class="banner error blocked-banner"[^>]*>(.*?)</div>',
                      body, re.S)


@pytest.mark.parametrize("path", PAGES)
def test_every_page_tells_a_blocked_account_once(blocked_client, path):
    body = blocked_client.get(path).get_data(as_text=True)

    (banner,) = _banners(body)
    assert " ".join(banner.split()) == web.blocked_notice()


def test_the_notice_names_the_admin_to_write_to(blocked_client):
    (banner,) = _banners(blocked_client.get("/").get_data(as_text=True))
    assert "admin@example.com" in banner


def test_it_is_the_first_thing_on_the_page_under_the_header(blocked_client):
    """Visible without scrolling: the first element inside <main>, before any
    flashed message and before the page's own content. A message is flashed
    so "before it" is tested, not assumed (prove_fails.py caught that the
    first version had no message to be before)."""
    with blocked_client.session_transaction() as sess:
        sess["_flashes"] = [("message", ("Card saved.", None))]
    body = blocked_client.get("/").get_data(as_text=True)
    main = body.index('<main class="page">')
    after_main = body[main + len('<main class="page">'):].lstrip()
    assert after_main.startswith('<div class="banner error blocked-banner"')
    assert body.index("blocked-banner") < body.index("Card saved.")
    assert body.index("</header>") < main


def test_it_has_no_close_button(blocked_client):
    """Dismissing it would not lift the block, so nothing offers to."""
    body = blocked_client.get("/").get_data(as_text=True)
    start = body.index('<div class="banner error blocked-banner"')
    banner = body[start:body.index("</div>", start)]
    assert "<button" not in banner


@pytest.mark.parametrize("path", PAGES)
def test_an_account_in_good_standing_sees_nothing(user_client, path):
    assert _banners(user_client.get(path).get_data(as_text=True)) == []


@pytest.mark.parametrize("path", PAGES)
def test_a_signed_out_visitor_sees_nothing(client, path):
    assert _banners(client.get(path).get_data(as_text=True)) == []


def test_it_goes_on_the_first_page_after_an_unblock(user_client, block_state):
    block_state.block()
    assert _banners(user_client.get("/").get_data(as_text=True))

    block_state.value = None
    assert _banners(user_client.get("/").get_data(as_text=True)) == []


def test_the_banner_is_the_compact_one(app_module):
    """One line in the page column on a computer (measured 40px, against 70px
    and two lines at the full banner's size): it is on every page for as long
    as the block lasts."""
    from pathlib import Path
    from conftest import css_winning
    css = (Path(app_module.__file__).parent / "static" / "css" / "style.css") \
        .read_text(encoding="utf-8")
    banner = [{"banner", "error", "blocked-banner"}]

    assert css_winning(css, banner, "font-size", phone=False) == "0.9rem"
    assert css_winning(css, banner, "padding", phone=False) == "0.55rem 0.9rem"


def test_the_guide_explains_it(app_module):
    """A learner-visible change is a guide change, and Mykola reads the guide."""
    from pathlib import Path
    guide = (Path(app_module.__file__).parent / "docs" / "user-guide.md") \
        .read_text(encoding="utf-8")
    section = guide.split("### If your account is blocked", 1)[1].split("\n#", 1)[0]

    assert "notice at the top of every page" in section
    assert "read and practise everything" in section
