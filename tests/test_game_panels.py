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
from urllib.parse import quote_plus

import pytest

import games
from conftest import browse_panel

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


def test_every_built_tile_opens_a_picker_not_a_round(client, deck):
    """#233: a tile that went straight into a round would teach the seam the
    panel exists to hide.

    Read off the declaration rather than written down, so a game landing does
    not need this edited (kuantorflow#69's rule, applied to the panel): a tile
    still carrying `ticket` is greyed and has no href at all (#261)."""
    panel = _games_panel(client.get("/").get_data(as_text=True))
    hrefs = re.findall(r'href="(/quiz|/games/[a-z_]+)"', panel)
    expected = ["/quiz"] + [f"/games/{a.slug}" for a in games.panel("game")
                            if not a.ticket]
    assert hrefs == expected


def test_a_tile_with_no_round_yet_is_greyed_and_goes_nowhere(client, deck):
    """A greyed tile that still opened a picker would be the old behaviour with
    decoration on top."""
    panel = _games_panel(client.get("/").get_data(as_text=True))
    for activity in games.panel("game"):
        block = panel.split(f">{activity.name}</span>")[0].rsplit("<", 1)[0]
        if activity.ticket:
            assert f'href="/games/{activity.slug}"' not in panel, activity.slug
            assert "topic-tile--soon" in panel
        else:
            assert f'href="/games/{activity.slug}"' in panel, activity.slug


def test_a_greyed_tile_says_why_on_hover(client, deck):
    """It stays on the page and explains itself rather than vanishing — the
    same treatment the card controls get (#162/#176/#177), and what keeps the
    set of activities legible.

    Skipped once every game has landed, which happened with kuantorflow#130:
    there is no greyed tile left to hover. Kept rather than deleted because
    the rule it guards is about the *next* stub — anything promoted out of
    #236 gets a tile before it gets a round, and this is what says the tile
    must explain itself."""
    if all(not a.ticket for a in games.panel("game")):
        pytest.skip("no game is a stub — nothing on the panel is greyed")
    panel = _games_panel(client.get("/").get_data(as_text=True))
    assert 'aria-disabled="true"' in panel
    assert "under construction" in panel


def test_every_tile_carries_an_icon_and_a_sub_line(client, deck):
    """The set of activities is closed and known, so unlike topics every one
    ships with a picture; the no-icon path stays only as a safety net."""
    panel = _games_panel(client.get("/").get_data(as_text=True))
    tiles = len(games.panel("quiz")) + len(games.panel("game"))
    assert panel.count("topic-tile--image") == tiles
    assert panel.count('class="topic-tile-img"') == tiles
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
    assert "Practise your words" not in browse_panel(body)


def test_the_panel_renders_on_an_empty_deck(client, app_module, monkeypatch):
    """Structure, like #218's empty section heading. A learner who cannot see
    that the games exist will not add cards in order to reach them."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False, **kw: [])
    body = client.get("/").get_data(as_text=True)
    assert "Practise your words" in body
    assert (_games_panel(body).count("topic-tile--image")
            == len(games.panel("quiz")) + len(games.panel("game")))


def test_no_tile_judges_whether_a_selection_can_play(client, app_module,
                                                     monkeypatch):
    """The rule #233 actually sets, and it survives #261 intact.

    Two different questions get confused here. *Can this selection play?*
    depends on what the learner ticked, so it stays in the picker — a tile has
    no selection to reason about and could only guess. *Does this game exist?*
    is true before any selection, identical for everyone, and already on the
    declaration — which is what #261 greys on.

    So an empty deck must still leave every tile inviting: the greying that
    remains is about the activity, never about the deck."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda owner_id=None, alphabetical=False, **kw: [])
    panel = _games_panel(client.get("/").get_data(as_text=True))
    assert "Tick at least" not in panel
    assert "topic-tile--soon" not in panel.split(">Quiz</span>")[0]
    # every built activity is still a live link on a deck with nothing in it
    for activity in games.panel("game"):
        if not activity.ticket:
            assert f'href="/games/{activity.slug}"' in panel, activity.slug


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


def _enough_topics(activity):
    """A `?topic=` query big enough to clear the activity's `min_topics`.

    kuantorflow#266 lets a game ask for several topics — odd one out needs two,
    since the stranger has to come from somewhere else — and a round asked for
    fewer meets *that* page rather than the one under test.

    Drawn from `TOPICS` rather than invented, because a name the deck does not
    have is dropped in silence (#248) and would leave the selection short
    again. From the end, so `animals` is in every query and the assertion that
    the stub names its selection holds whatever `min_topics` says."""
    names = [name for name, _ in TOPICS][-activity.min_topics:]
    return "&".join(f"topic={quote_plus(name)}" for name in names)


@pytest.mark.parametrize("activity", STUBBED, ids=lambda a: a.slug)
def test_an_activity_that_still_carries_a_ticket_renders_a_stub(
        client, deck, activity):
    """`ticket=` is present exactly while an activity is a stub, so the page
    can name who will build it."""
    url = f"/games/{activity.slug}/play?{_enough_topics(activity)}"
    body = client.get(url).get_data(as_text=True)
    assert "isn&rsquo;t built yet" in body
    assert activity.ticket in body
    assert "animals" in body


@pytest.mark.parametrize("activity", LANDED, ids=lambda a: a.slug)
def test_an_activity_that_has_landed_plays_instead_of_apologising(
        client, deck, activity):
    """The other half of the same rule, and the one that would otherwise go
    unnoticed: dropping `ticket=` has to actually take the stub away.

    Matched on the stub's **whole sentence** rather than on "built yet".
    kuantorflow#271 collided with the loose version: a landed round explaining
    that no sentence here can be *rebuilt yet* contains "built yet" and was
    read as a stub. The marker has to be a phrase only game_stub.html can
    produce."""
    url = f"/games/{activity.slug}/play?{_enough_topics(activity)}"
    body = client.get(url).get_data(as_text=True)
    assert "isn&rsquo;t built yet" not in body


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


# --- the topic row, and the reader (kuantorflow#261) ---------------------


def test_the_row_greys_the_same_activities_as_the_panel(client, deck, with_key):
    """Greying the front page alone would leave this row inviting the same dead
    click one page away."""
    body = client.get("/flashcards/Work%20and%20careers").get_data(as_text=True)
    row = _row(body)
    for activity in games.panel("game"):
        if activity.ticket:
            assert f">{activity.name}</span>" in row, activity.slug
            assert f"/games/{activity.slug}/play" not in row, activity.slug
        else:
            assert f"/games/{activity.slug}/play" in row, activity.slug


def test_the_reader_button_greys_on_the_same_field(client, deck, with_key):
    body = client.get("/").get_data(as_text=True)
    banner = body.split('class="reader-banner')[1].split(">")[0]
    if games.ACTIVITIES["read_a_text"].ticket:
        assert "reader-banner--soon" in banner
        assert 'href=' not in banner
    else:
        assert "reader-banner--soon" not in banner


def test_one_wording_across_all_three_surfaces(client, deck, with_key):
    """A tooltip that differed between them would read as three states.

    Counted from `ACTIVITIES` rather than written down. The number of greyed
    tiles falls every time a game lands — it was two until #235 shipped Fill
    the gap — so a literal here is a test that fails on success, which is the
    worst kind: it says "something broke" when the right thing happened.
    """
    import app as app_mod
    import games

    stubs = [a for a in games.ACTIVITIES.values() if a.ticket]
    home = client.get("/").get_data(as_text=True)
    topic = client.get("/flashcards/Work%20and%20careers").get_data(as_text=True)
    assert home.count(app_mod.UNDER_CONSTRUCTION) == len(stubs)
    if stubs:
        assert app_mod.UNDER_CONSTRUCTION in _row(topic)


def test_a_game_that_lands_ungreys_itself(client, deck, monkeypatch):
    """The whole point of greying on `ticket`: dropping the field is the only
    edit a game ticket makes to this page."""
    import dataclasses
    import games as games_mod
    landed = dataclasses.replace(games_mod.ACTIVITIES["fill_the_gap"], ticket="")
    monkeypatch.setitem(games_mod.ACTIVITIES, "fill_the_gap", landed)
    panel = _games_panel(client.get("/").get_data(as_text=True))
    assert 'href="/games/fill_the_gap"' in panel
    block = panel.split(">Fill the gap</span>")[0]
    assert "topic-tile--soon" not in block.rsplit("<a", 1)[-1]
