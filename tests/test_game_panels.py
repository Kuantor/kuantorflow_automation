"""
The ways in: the games panel, the reader panel, and the activity row
(kuantorflow#253).

Everything between a learner and the picker #250 built. Most of what these
point at is still a stub, which is the point: the chassis is what is being
proved, and a stub round shows the whole chain — panel, picker, selection,
round — works before any game logic exists.

Two rules run through them:

* **one declaration, three renderers.** The panel, the reader panel and the
  topic row all read `games.ACTIVITIES`, so adding a sixth activity is one
  entry rather than one entry and three templates.
* **hide a link the learner cannot act on, show one they can.** The quiz goes
  when both languages are hidden; the reader goes without an API key. A topic
  too thin for a game keeps its link, because that is fixable from the page it
  leads to.
"""

import re

import pytest

import games

TOPICS = [("Work and careers", 20), ("animals", 3)]


@pytest.fixture()
def deck(stub_deck):
    """Topics with counts but no cards: these tests are about the ways in, and
    none of them opens a round."""
    return stub_deck(topics=TOPICS)


@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


@pytest.fixture()
def without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _games_panel(body):
    """The games panel's markup, from its heading to the end of its grid."""
    return body.split("Practise your words")[1].split("</div>\n    </div>")[0]


def _row(body):
    """The activity row at the top of a topic page."""
    return body.split('<p class="crumbs">')[1].split("</p>")[0]


# --- the games panel ----------------------------------------------------


def test_the_panel_holds_the_quiz_and_every_game(client, deck):
    panel = _games_panel(client.get("/").get_data(as_text=True))
    for name in ("Quiz", "Multiple choice", "Real or fake", "Scrambled",
                 "Fill the gap"):
        assert f">{name}</span>" in panel


def test_the_quiz_takes_the_first_tile(client, deck):
    """It is the oldest activity here and the one a returning learner is most
    likely to want — and until #250 it was reachable only from inside a topic
    page."""
    panel = _games_panel(client.get("/").get_data(as_text=True))
    assert panel.index(">Quiz<") < panel.index(">Multiple choice<")


def test_every_tile_opens_a_picker_not_a_round(client, deck):
    """#233: a tile that went straight into a round would teach the seam the
    panel exists to hide."""
    panel = _games_panel(client.get("/").get_data(as_text=True))
    hrefs = re.findall(r'href="(/quiz|/games/[a-z_]+)"', panel)
    assert hrefs == ["/quiz", "/games/multiple_choice", "/games/real_or_fake",
                     "/games/scrambled", "/games/fill_the_gap"]


def test_every_tile_carries_an_icon_and_a_sub_line(client, deck):
    """The set of activities is closed and known, so unlike topics every one
    ships with a picture; the no-icon path stays only as a safety net."""
    panel = _games_panel(client.get("/").get_data(as_text=True))
    assert panel.count("topic-tile--image") == 5
    assert panel.count('class="topic-tile-img"') == 5
    assert "Type the translation" in panel and "Pick from four" in panel


def test_the_panel_reuses_the_topic_tile_classes(client, deck):
    """Not a parallel `.game-tile`: a second set of numbers beside the first
    drifts the moment either is tuned."""
    panel = _games_panel(client.get("/").get_data(as_text=True))
    assert 'class="topic-tiles"' in panel
    assert "game-tile" not in panel


def test_the_panel_sits_outside_the_block_mykola_rebuilds(client, deck):
    """`refreshBrowseTopics()` replaces everything inside `#browse-topics` from
    /topics.json when a card is saved from chat. A panel in there would be
    wiped on the first chat save."""
    body = client.get("/").get_data(as_text=True)
    browse = body.split('id="browse-topics"')[1].split("<form")[0]
    assert "Practise your words" not in browse


def test_the_panel_renders_on_an_empty_deck(client, app_module, monkeypatch):
    """Structure, like #218's empty section heading. A learner who cannot see
    that the games exist will not add cards in order to reach them."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: [])
    body = client.get("/").get_data(as_text=True)
    assert "Practise your words" in body
    assert _games_panel(body).count("topic-tile--image") == 5


def test_no_tile_judges_whether_its_game_can_run(client, app_module,
                                                 monkeypatch):
    """That question is the picker's, and #250 answers it there. A tile has no
    selection to reason about, so a second copy could only guess."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None: [])
    panel = _games_panel(client.get("/").get_data(as_text=True))
    assert "disabled" not in panel
    assert "Tick at least" not in panel


# --- the reader panel ---------------------------------------------------


def test_the_reader_has_its_own_panel_and_wide_button(client, deck, with_key):
    """Not a game: nothing is scored, nothing is guessed, no round to finish."""
    body = client.get("/").get_data(as_text=True)
    assert "Read a text from your own words" in body
    assert 'class="reader-banner' in body
    assert "Generate a text" in body


def test_the_reader_button_is_not_a_topic_tile(client, deck, with_key):
    """A 3:4 portrait in a grid and a wide banner are different shapes doing
    different jobs; one class over both would leave neither right."""
    body = client.get("/").get_data(as_text=True)
    banner = body.split('class="reader-banner')[1].split("</a>")[0]
    assert "topic-tile" not in banner


def test_without_a_key_the_reader_panel_is_gone_entirely(client, deck,
                                                         without_key):
    """#233's rule: hide what the learner cannot act on, exactly as
    MYKOLA_AVAILABLE=False removes the chat widget."""
    body = client.get("/").get_data(as_text=True)
    assert "Read a text from your own words" not in body
    assert "reader-banner" not in body


def test_the_key_is_read_per_request_not_at_import(client, deck, monkeypatch):
    """It reaches this process only as a side effect of importing ai_agent's
    own .env, which happens after a module-level constant would have been
    evaluated — so a constant would read None on a working deployment."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "reader-banner" not in client.get("/").get_data(as_text=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert "reader-banner" in client.get("/").get_data(as_text=True)


# --- the topic page's activity row --------------------------------------


def test_the_row_offers_every_activity(client, deck, with_key):
    row = _row(client.get("/flashcards/Work%20and%20careers").get_data(as_text=True))
    for name in ("Card deck", "Take quiz", "Multiple choice", "Real or fake",
                 "Scrambled", "Fill the gap", "Generate a text"):
        assert name in row


def test_the_rows_links_skip_the_picker(client, deck, with_key):
    """The topic is already chosen — that is the whole context the page is in.
    Sending somebody to a picker from inside the topic they are standing in is
    a step backwards."""
    row = _row(client.get("/flashcards/Work%20and%20careers").get_data(as_text=True))
    assert "/games/scrambled/play?topic=Work+and+careers" in row
    assert "/quiz/Work%20and%20careers" in row
    assert 'href="/games/scrambled"' not in row, "that is the picker"


def test_the_quiz_link_still_hides_with_no_visible_language(client, deck,
                                                            app_module,
                                                            monkeypatch):
    """The one thing that hides, and the rule for every future case: no visible
    language is not fixable from this page, so the link goes. A thin topic is
    fixable by adding another topic, so a game's link stays."""
    import settings_store
    monkeypatch.setattr(app_module, "current_settings",
                        lambda: dict(settings_store.DEFAULTS,
                                     show_ukrainian=False, show_russian=False))
    row = _row(client.get("/flashcards/Work%20and%20careers").get_data(as_text=True))
    assert "Take quiz" not in row
    assert "Scrambled" in row


def test_the_reader_link_follows_the_key(client, deck, without_key):
    row = _row(client.get("/flashcards/Work%20and%20careers").get_data(as_text=True))
    assert "Generate a text" not in row


def test_no_template_sharing_crumbs_kept_its_pipes(client, deck):
    """With eight links the pipes stop working: they are *text*, so a separator
    strands at the end of a line and a two-word label splits across one. `gap`
    separates them now — and `.crumbs` is shared by four templates, so they all
    lose the pipes together or the others get an untinted bar with a gap on
    each side."""
    for url in ("/flashcards/Work%20and%20careers",
                "/deck/Work%20and%20careers",
                "/quiz/Work%20and%20careers",
                "/quiz"):
        assert "|" not in _row(client.get(url).get_data(as_text=True)), url


# --- the stubs ----------------------------------------------------------


# Read off the declaration rather than written down (#69). These used to name
# `scrambled` and `#133`, and both had to be edited by hand the day that game
# landed — a test failing for a reason that is not a bug, once per remaining
# game. Now a game ticket drops its `ticket=` field and the suite follows.
#
# `parametrize` rather than a loop so each activity is its own test: a failure
# names the game, and the collected count is a live readout of how many are
# still stubs.
STUBBED = [a for a in games.ACTIVITIES.values()
           if a.kind in games.GAMES_URL_KINDS and a.ticket]
LANDED = [a for a in games.ACTIVITIES.values()
          if a.kind in games.GAMES_URL_KINDS and not a.ticket]


@pytest.mark.parametrize("activity", STUBBED, ids=lambda a: a.slug)
def test_an_activity_that_still_carries_a_ticket_renders_a_stub(
        client, deck, activity):
    """`ticket=` is present exactly while an activity is a stub, so the page
    can name who will build it."""
    body = client.get(f"/games/{activity.slug}/play?topic=animals")                  .get_data(as_text=True)
    assert "built yet" in body
    assert activity.ticket in body
    assert "animals" in body


@pytest.mark.parametrize("activity", LANDED, ids=lambda a: a.slug)
def test_an_activity_that_has_landed_plays_instead_of_apologising(
        client, deck, activity):
    """The other half of the same rule, and the one that would otherwise go
    unnoticed: dropping `ticket=` has to actually take the stub away."""
    body = client.get(f"/games/{activity.slug}/play?topic=animals")                  .get_data(as_text=True)
    assert "built yet" not in body


def test_every_registered_activity_has_a_picker_and_a_round(client, deck,
                                                            with_key):
    """A tile whose Start button led to a 404 would be worse than no tile —
    whether what it reaches is a stub or a real round."""
    for activity in games.ACTIVITIES.values():
        if activity.kind == "quiz":
            continue
        assert client.get(f"/games/{activity.slug}").status_code == 200
        assert client.get(f"/games/{activity.slug}/play").status_code == 200


@pytest.mark.skipif(not STUBBED, reason="every activity has landed")
def test_a_stub_does_not_list_every_topic_it_would_have_played(client, deck):
    """A bare /play means the whole visible deck (#248), which in production is
    twenty-six names — a wall of text where one line was wanted."""
    body = client.get(f"/games/{STUBBED[0].slug}/play").get_data(as_text=True)
    assert "2 topics" in body


# --- the one declaration ------------------------------------------------


def test_the_panel_and_the_row_render_from_the_same_declaration(client, deck,
                                                                with_key):
    """#233 warns that index.html and base.html already render topic tiles
    twice; this must not add a third copy of the same idea."""
    body = client.get("/").get_data(as_text=True)
    row = _row(client.get("/flashcards/Work%20and%20careers").get_data(as_text=True))
    for activity in games.panel("game"):
        assert activity.name in _games_panel(body)
        assert activity.name in row
