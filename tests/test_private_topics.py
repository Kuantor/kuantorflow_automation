"""Private topics (kuantorflow#382).

`topics.is_public` is false and only its creator — and the admin, who monitors
the deck — can see the topic. Everything else about the site is unchanged, and
most of the work is making sure of that.

**It is not #127's "Use only individual cards", and the two are deliberately
kept apart in the code.** That is a *preference*, per visitor, about which
cards they want to look at: turn it off and the whole deck is back. This is a
*permission*, and no setting reaches past it. In the query layer they are two
arguments — `owner_id`, which is None whenever the preference is off, and
`viewer_id`, which is simply who is asking. Passing one where the other belongs
would make a topic private only for visitors who happened to have the setting
on, which is the failure this file exists to catch.

What is asserted here is the plumbing: that every read is told who is asking,
that a private topic is refused when named rather than merely left out of the
lists, who may change it, and what the page draws. The SQL itself — what each
viewer actually gets back — is proved against a real MySQL in
`test_private_topics_db.py`, because a fake that answers a WHERE clause by
agreeing with it proves nothing.
"""

import json

import pytest

import settings_store


TEST_USER_ID = 7          # conftest's signed-in user


def _capture_viewer(app_module, monkeypatch):
    """Record the (viewer_id, admin) every read is asked for."""
    seen = []

    def record(*_args, viewer_id=None, admin=False, **_kw):
        seen.append((viewer_id, admin))
        return []

    def record_sections(*_args, viewer_id=None, admin=False, **_kw):
        seen.append((viewer_id, admin))
        return []

    monkeypatch.setattr(app_module, "get_flashcards_by_topic", record)
    monkeypatch.setattr(app_module, "get_flashcards_by_topics", record)
    monkeypatch.setattr(app_module, "get_topics", record)
    monkeypatch.setattr(app_module, "get_topics_by_section", record_sections)
    return seen


@pytest.fixture()
def topic(app_module, monkeypatch):
    """What `resolve_topic()` answers for the page under test."""
    def install(name="vocab", is_public=True, creator=TEST_USER_ID,
                creator_name="Anton", topic_id=11):
        monkeypatch.setattr(
            app_module, "resolve_topic",
            lambda name_=None, viewer_id=None, admin=False, topic_id_=None,
            **kw: ({"id": topic_id, "name": name, "is_public": is_public,
                    "created_by_user_id": creator, "creator": creator_name}
                   if name_ else None),
            raising=False)
    return install


@pytest.fixture()
def hidden(app_module, monkeypatch):
    """A topic this visitor may not see: the resolver finds nothing."""
    monkeypatch.setattr(app_module, "resolve_topic",
                        lambda *a, **kw: None, raising=False)


# --- every read is told who is asking --------------------------------------

def test_the_pages_that_read_cards_pass_the_viewer(user_client, app_module,
                                                   monkeypatch, topic):
    """The half a route can forget. #127's filter is passed beside it and is
    None most of the time, so a read that took only that would look right and
    show private topics to everybody."""
    topic()
    seen = _capture_viewer(app_module, monkeypatch)

    user_client.get("/")
    user_client.get("/flashcards/vocab")
    user_client.get("/topics.json")

    assert seen, "no read was made at all"
    assert all(entry == (TEST_USER_ID, False) for entry in seen), seen


def test_an_anonymous_visitor_asks_as_nobody(client, app_module, monkeypatch,
                                             topic):
    """`viewer_id` None is "no account", which sees public topics only -- not
    "no filter", which is what None means to #127's owner argument one
    parameter to the left. The two Nones mean opposite things, which is why
    they are two arguments."""
    topic()
    seen = _capture_viewer(app_module, monkeypatch)

    client.get("/")

    assert seen and all(entry == (None, False) for entry in seen)


def test_the_admin_asks_as_the_admin(user_client, app_module, monkeypatch,
                                     topic):
    """Their decision, and the reason the guide says "only you and the admin"
    rather than "only you"."""
    monkeypatch.setattr(app_module, "is_admin", lambda: True)
    topic()
    seen = _capture_viewer(app_module, monkeypatch)

    user_client.get("/")

    assert seen and all(entry == (TEST_USER_ID, True) for entry in seen)


def test_the_setting_and_the_permission_are_separate_arguments(app_module):
    """`viewer()` is not `cards_owner_filter()`, and must never become it."""
    import ast
    import inspect
    import textwrap

    fn = ast.parse(textwrap.dedent(inspect.getsource(app_module.viewer))).body[0]
    called = {node.func.id for node in ast.walk(fn)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

    # Read off the calls rather than the text: the docstring says
    # "cards_owner_filter" on purpose, to explain what this is *not*.
    assert "cards_owner_filter" not in called, (
        "the viewer must not be the preference")
    assert {"_current_user_id", "is_admin"} <= called


# --- a topic you may not see is refused, not merely hidden -----------------

def test_a_private_topic_is_a_404_when_named(user_client, hidden):
    """Left out of every list is not enough: a name reaches the topic page
    from a URL somebody kept, a bookmark, or a guess, and the page would
    otherwise open empty and say the topic has no cards -- which is a lie
    about somebody else's topic and an invitation to keep trying."""
    assert user_client.get("/flashcards/somebody-elses").status_code == 404


def test_a_topic_you_may_see_still_opens(user_client, topic):
    topic(name="vocab")

    assert user_client.get("/flashcards/vocab").status_code == 200


def test_the_page_asks_the_resolver_before_it_reads_cards(user_client,
                                                          app_module,
                                                          monkeypatch, hidden):
    """Order matters: a refused topic must cost no card read at all."""
    reads = []
    monkeypatch.setattr(app_module, "get_flashcards_by_topic",
                        lambda *a, **kw: reads.append(a) or [])

    user_client.get("/flashcards/somebody-elses")

    assert reads == []


def test_an_id_in_the_url_is_checked_rather_than_trusted(user_client,
                                                         app_module,
                                                         monkeypatch):
    """`?t=` settles which topic when a name matches two, which only the admin
    can see -- so it goes through the same rule rather than around it."""
    asked = {}

    def resolver(name=None, viewer_id=None, admin=False, topic_id=None, **kw):
        asked.update(name=name, viewer_id=viewer_id, admin=admin,
                     topic_id=topic_id)
        return None

    monkeypatch.setattr(app_module, "resolve_topic", resolver, raising=False)

    assert user_client.get("/flashcards/vocab?t=99").status_code == 404
    assert asked["topic_id"] == 99
    assert asked["viewer_id"] == TEST_USER_ID


# --- who may change it ------------------------------------------------------

def test_the_creator_gets_the_control(user_client, topic):
    topic(creator=TEST_USER_ID)
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)

    assert 'id="topic-visibility-select"' in body
    assert "Topic visibility:" in body


def test_somebody_elses_topic_offers_no_control(user_client, topic):
    """The admin can *see* a private topic that is not theirs (#382) and still
    does not own it, so they get the state and whose it is in words rather
    than a control that would refuse them."""
    topic(is_public=False, creator=999, creator_name="Olena")
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)

    assert 'id="topic-visibility-select"' not in body
    assert "Private topic" in body
    assert "Olena" in body


def test_a_public_topic_of_somebody_elses_says_nothing(user_client, topic):
    """No control, and no note either: public is the ordinary state and every
    topic page would otherwise carry a line about it."""
    topic(is_public=True, creator=999, creator_name="Olena")
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)

    assert 'id="topic-visibility-select"' not in body
    assert "Private topic" not in body


def test_a_topic_nobody_created_offers_no_control(user_client, topic):
    """The seeded deck (#203) and anything saved anonymously. A topic with no
    creator cannot be private -- there is nobody for it to belong to -- so the
    control would be a switch that refuses."""
    topic(creator=None, creator_name=None)
    body = user_client.get("/flashcards/vocab").get_data(as_text=True)

    assert 'id="topic-visibility-select"' not in body


# --- the route that changes it ---------------------------------------------

@pytest.fixture()
def flip(app_module, monkeypatch):
    """Capture what the route asks `set_topic_visibility()` for."""
    calls = []

    def install(outcome="changed"):
        def fake(topic_id, public, viewer_id=None, admin=False):
            calls.append({"id": topic_id, "public": public,
                          "viewer_id": viewer_id, "admin": admin})
            return outcome
        monkeypatch.setattr(app_module, "set_topic_visibility", fake,
                            raising=False)
        return calls
    return install


def test_making_a_topic_private_asks_for_exactly_that(user_client, flip):
    calls = flip()

    user_client.post("/topics/11/visibility",
                     data={"visibility": "private", "topic": "vocab"})

    assert calls == [{"id": 11, "public": False, "viewer_id": TEST_USER_ID,
                      "admin": False}]


def test_making_it_public_again(user_client, flip):
    calls = flip()

    user_client.post("/topics/11/visibility",
                     data={"visibility": "public", "topic": "vocab"})

    assert calls[0]["public"] is True


def test_a_blocked_account_changes_nothing(user_client, block_state, flip):
    """#126. A blocked account is refused every write, and this is one."""
    block_state.block()
    calls = flip()

    user_client.post("/topics/11/visibility",
                     data={"visibility": "private", "topic": "vocab"})

    assert calls == []


@pytest.mark.parametrize("outcome,expected", [
    ("shared", "cards other people added"),
    ("taken", "already have a topic with that name"),
    ("nobodys", "no creator"),
    ("denied", "not yours"),
])
def test_a_refusal_is_explained(user_client, flip, outcome, expected):
    """The two that will be reported as "it did nothing" are `shared` and
    `taken`, and a learner who is told which needs no bug report."""
    flip(outcome)

    body = user_client.post("/topics/11/visibility",
                            data={"visibility": "private", "topic": "vocab"},
                            follow_redirects=True).get_data(as_text=True)

    assert expected in body


def test_a_change_is_logged(user_client, flip, action_logs):
    """A write, so it is logged (#30) -- and its refusals too, which is the
    difference between a bug report and a five-second answer."""
    flip()

    user_client.post("/topics/11/visibility",
                     data={"visibility": "private", "topic": "vocab"})

    line = (action_logs / "cards.log").read_text(encoding="utf-8").strip()
    assert "TOPIC-VISIBILITY" in line
    assert "topic=vocab" in line and "visibility=private" in line
    assert "outcome=changed" in line


def test_a_refusal_is_logged_too(user_client, flip, action_logs):
    flip("shared")

    user_client.post("/topics/11/visibility",
                     data={"visibility": "private", "topic": "vocab"})

    assert "outcome=shared" in (action_logs / "cards.log").read_text(
        encoding="utf-8")


# --- what the browse page draws --------------------------------------------

@pytest.fixture()
def marks(app_module, monkeypatch):
    def install(**topics):
        monkeypatch.setattr(app_module, "private_topics",
                            lambda viewer_id=None, admin=False: topics,
                            raising=False)
    return install


def test_a_private_topic_wears_a_padlock(user_client, app_module, monkeypatch,
                                         marks):
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda *a, **kw: [("Other", [("diary", 3)])])
    marks(diary={"id": 11, "created_by_user_id": TEST_USER_ID,
                 "creator": "Anton", "mine": True})

    body = user_client.get("/").get_data(as_text=True)

    assert "topic-tile--private" in body
    assert "Only you (and the admin) can see this topic" in body


def test_the_admin_sees_whose_it_is(user_client, app_module, monkeypatch,
                                    marks):
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda *a, **kw: [("Other", [("diary", 3)])])
    marks(diary={"id": 11, "created_by_user_id": 999, "creator": "Olena",
                 "mine": False})

    body = user_client.get("/").get_data(as_text=True)

    assert "Olena" in body
    assert "t=11" in body, "and the link says *which* topic, since two can share a name"


def test_an_ordinary_topic_carries_no_id_in_its_link(user_client, app_module,
                                                     monkeypatch, marks):
    """A name is what keeps these URLs readable, and every visitor but the
    admin resolves one to a single topic."""
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda *a, **kw: [("Other", [("vocab", 3)])])
    marks()

    body = user_client.get("/").get_data(as_text=True)

    assert "/flashcards/vocab" in body
    assert "t=" not in body.split("/flashcards/vocab")[1][:40]


def test_the_widget_draws_the_same_padlock(user_client, app_module,
                                           monkeypatch, marks):
    """`refreshBrowseTopics()` rebuilds the very block index.html renders, so a
    mark drawn on one and not the other would vanish the moment a card was
    saved from chat -- the trap CLAUDE.md names for this pair.

    Read off a page that actually has a private topic on it: the class only
    appears where a padlock does, so a bare `GET /` would satisfy this by
    having no topics at all.
    """
    # The widget's renderer only reaches the page when Mykola is available,
    # which is the environment this pair actually has to agree in.
    monkeypatch.setattr(app_module, "MYKOLA_AVAILABLE", True)
    monkeypatch.setattr(app_module, "get_topics_by_section",
                        lambda *a, **kw: [("Other", [("diary", 3)])])
    marks(diary={"id": 11, "created_by_user_id": TEST_USER_ID,
                 "creator": "Anton", "mine": True})

    body = user_client.get("/").get_data(as_text=True)

    assert "topic-tile--private" in body, "index.html draws it"
    assert "data.private" in body, "and so does the widget's renderer"


def test_topics_json_carries_the_marks(user_client, marks):
    marks(diary={"id": 11, "created_by_user_id": TEST_USER_ID,
                 "creator": "Anton", "mine": True})

    payload = user_client.get("/topics.json").get_json()

    assert payload["private"]["diary"]["id"] == 11


def test_a_dead_database_costs_the_padlocks_and_nothing_else(user_client,
                                                             app_module,
                                                             monkeypatch):
    """Same tolerance the sections themselves have one line above."""
    def boom(viewer_id=None, admin=False):
        raise RuntimeError("MySQL has gone away")

    monkeypatch.setattr(app_module, "private_topics", boom, raising=False)

    assert user_client.get("/").status_code == 200
    assert user_client.get("/topics.json").get_json()["private"] == {}


# --- and what Mykola may read ----------------------------------------------

def test_the_chat_readers_pass_the_viewer(user_client, app_module, monkeypatch,
                                          topic):
    """ai_agent#68 moved Mykola's reads into the host, so the chat is filtered
    by whatever the host filters by -- which is now the viewer as well as
    #127's owner. Without this the chat would be the way around a permission
    the rest of the site keeps.
    """
    topic()
    seen = _capture_viewer(app_module, monkeypatch)

    with app_module.app.test_request_context("/"):
        from flask import session
        session["user"] = {"id": TEST_USER_ID, "email": "test.user@gmail.com"}
        app_module._topics_for_chat()
        app_module._cards_for_chat("vocab", 5)

    assert seen and all(entry == (TEST_USER_ID, False) for entry in seen)
