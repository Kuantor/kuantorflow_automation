"""Adding more words to a topic that already exists (kuantorflow#524).

#406's machine pointed at an existing topic: *Add more words* on the topic page
opens a form with a count and an optional "what kind of words?" line, Claude
proposes, the learner approves on #406's own screen, and #406's stream fills
the cards into this topic.

What is worth pinning, beyond what `test_generate_a_topic.py` already holds
for the shared half:

* **who may** -- an account, on a topic that is public or theirs, and only
  where a save would really file into this topic (a card is filed by name, and
  a private namesake wins). The button and the route ask one rule;
* **the prompt** names the topic, its existing words and the steer, and the
  steer is cleaned like #406's idea;
* **the topic's own words never come back**, even when the model returns them,
  and never reach a lookup even when a form posts them;
* **the guards keep #406's order**: refusals before the model call, the
  generation ceiling just before it, the lookups claimed all or nothing before
  the fill opens;
* a `TOPIC-EXTENDED` line in `cards.log`.

Nothing here calls Claude or a dictionary.
"""

import json

import pytest

import applog
import topicgen

TOPIC = "City life and housing"
PAGE = "/flashcards/City life and housing"
FORM = PAGE + "/add-words"
START = FORM + "/start"
TOPIC_ID = 11
HAVE = ["lease", "tenant"]


def _topic(public=True, creator=None, topic_id=TOPIC_ID):
    return {"id": topic_id, "name": TOPIC, "is_public": public,
            "created_by_user_id": creator, "creator": None}


@pytest.fixture()
def extendable(app_module, monkeypatch):
    """A public topic holding two words, a key, a model that answers, a lexicon
    that knows everything, and a lookup claim that succeeds."""
    calls = {"extend": [], "claims": []}

    def extend(topic, existing, count, steer=""):
        calls["extend"].append({"topic": topic, "existing": list(existing),
                                "count": count, "steer": steer})
        return ["deposit", "sublet", "landlord"][:count]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("utils.resolve_topic",
                        lambda name, topic_id=None, **kw: _topic())
    monkeypatch.setattr(
        "utils.get_flashcards_by_topic",
        lambda topic, owner_id=None, **kw: [
            {"id": i, "word": w, "pos": "noun", "topic": TOPIC}
            for i, w in enumerate(HAVE, start=1)])
    monkeypatch.setattr(app_module.topicgen, "extend", extend)
    monkeypatch.setattr(app_module.parsers, "wiktionary_pages",
                        lambda words: set(words))
    monkeypatch.setattr("utils.existing_words", lambda owner_id=None: set())
    monkeypatch.setattr("utils.lookups_used_today", lambda user_id: 0)
    monkeypatch.setattr(
        "utils.claim_word_lookups",
        lambda user_id, count, u, a, **kw: calls["claims"].append(count)
        or (True, None, count))
    return calls


def _button(client):
    return 'class="topic-extend"' in client.get(PAGE).get_data(as_text=True)


# --- who sees the button, and who the route lets in ----------------------------

def test_a_signed_in_learner_is_offered_it(user_client, extendable):
    body = user_client.get(PAGE).get_data(as_text=True)
    assert _button(user_client)
    assert f'href="{FORM.replace(" ", "%20")}?t={TOPIC_ID}"' in body, \
        "the link carries t= so a shared name stays this topic"


def test_not_offered_to_an_anonymous_visitor(client, extendable):
    """#125: only an account writes."""
    assert not _button(client)


def test_not_offered_without_a_key(user_client, extendable, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert not _button(user_client)
    assert user_client.get(FORM).status_code == 404


def test_not_offered_on_somebody_elses_private_topic(user_client, extendable,
                                                     monkeypatch):
    """The admin can see another learner's private topic (#382) and still does
    not own it; the route refuses as well as the button hiding."""
    monkeypatch.setattr("utils.resolve_topic",
                        lambda name, topic_id=None, **kw: _topic(public=False,
                                                                 creator=999))
    assert not _button(user_client)
    resp = user_client.post(FORM, data={"count": "5"})
    assert resp.status_code == 403
    assert extendable["extend"] == [], "the model was asked despite the refusal"


def test_offered_on_your_own_private_topic(user_client, extendable, monkeypatch):
    from conftest import TEST_USER_ID
    monkeypatch.setattr("utils.resolve_topic",
                        lambda name, topic_id=None, **kw: _topic(
                            public=False, creator=TEST_USER_ID))
    assert _button(user_client)


def test_not_offered_where_the_words_would_land_elsewhere(user_client,
                                                          extendable,
                                                          monkeypatch):
    """A card is filed by name, and a learner's private topic wins over the
    public one of the same name. Opened with `?t=` on the public one, the
    words would go into the private one -- so it is refused, not misfiled."""
    def resolve(name, topic_id=None, **kw):
        return _topic() if topic_id == TOPIC_ID else _topic(topic_id=12)

    monkeypatch.setattr("utils.resolve_topic", resolve)
    body = user_client.get(PAGE + f"?t={TOPIC_ID}").get_data(as_text=True)
    assert 'class="topic-extend"' not in body
    resp = user_client.post(FORM + f"?t={TOPIC_ID}", data={"count": "5"})
    assert resp.status_code == 403 and "private topic with the same name" in \
        resp.get_data(as_text=True)
    assert extendable["extend"] == []


def test_an_anonymous_post_never_reaches_the_model(client, extendable):
    body = client.post(FORM, data={"count": "5"}).get_data(as_text=True)
    assert extendable["extend"] == []
    assert 'name="word"' not in body


def test_a_topic_you_cannot_see_is_a_404(user_client, extendable, monkeypatch):
    monkeypatch.setattr("utils.resolve_topic", lambda *a, **kw: None)
    assert user_client.get(FORM).status_code == 404
    assert user_client.post(START, data={"word": ["deposit"]}).status_code == 404


# --- the form and the proposal ------------------------------------------------

def test_the_form_says_how_many_words_the_topic_has(user_client, extendable):
    body = user_client.get(FORM).get_data(as_text=True)
    assert "This topic has 2 words" in body
    assert 'name="count"' in body and 'value="10"' in body, "default 10"
    assert 'name="steer"' in body


def test_the_route_hands_the_model_the_topic_its_words_and_the_steer(
        user_client, extendable):
    user_client.post(FORM, data={"count": "3", "steer": "  more\nverbs  "})
    asked = extendable["extend"][0]
    assert asked["topic"] == TOPIC
    assert asked["existing"] == HAVE
    assert asked["steer"] == "more verbs", "collapsed onto one line"


def test_the_approve_screen_fixes_the_destination(user_client, extendable):
    body = user_client.post(FORM, data={"count": "3"}).get_data(as_text=True)
    assert body.count('name="word"') == 3
    assert f'action="{START.replace(" ", "%20")}?t={TOPIC_ID}"' in body
    approve = body[body.index('id="approve"'):]
    assert 'name="title"' not in approve, "the topic is not offered for editing"
    assert "Add to the topic" in approve


@pytest.mark.parametrize("raw, wanted", [("99", topicgen.MAX_WORDS),
                                         ("1", topicgen.MIN_WORDS),
                                         ("", topicgen.EXTEND_DEFAULT_WORDS),
                                         ("seven", topicgen.EXTEND_DEFAULT_WORDS)])
def test_the_count_is_clamped(user_client, extendable, raw, wanted):
    user_client.post(FORM, data={"count": raw})
    assert extendable["extend"][0]["count"] == wanted


def test_the_box_clamps_in_the_browser_too(user_client, extendable):
    """#463's rule for a number box: pulled into range when it is left."""
    body = user_client.get(FORM).get_data(as_text=True)
    assert "Math.min(high, Math.max(low, value))" in body
    assert f'min="{topicgen.MIN_WORDS}"' in body
    assert f'max="{topicgen.MAX_WORDS}"' in body


def test_the_generation_ceiling_is_asked_before_the_model(user_client,
                                                          extendable,
                                                          monkeypatch):
    monkeypatch.setattr("web._generation_refusal",
                        lambda: {"message": "No more today.", "sign_in": False})
    body = user_client.post(FORM, data={"count": "3"}).get_data(as_text=True)
    assert extendable["extend"] == []
    assert "No more today." in body


def test_a_model_that_returns_only_repeats_says_so(user_client, extendable,
                                                   monkeypatch, app_module):
    monkeypatch.setattr(app_module.topicgen, "extend",
                        lambda *a, **kw: [])
    body = user_client.post(FORM, data={"count": "3"}).get_data(as_text=True)
    assert "already in this topic" in body


# --- topicgen.extend() ---------------------------------------------------------

def test_the_prompt_carries_the_topic_its_words_and_the_steer(monkeypatch):
    prompts = []
    monkeypatch.setattr(topicgen, "_ask_claude",
                        lambda prompt, count: prompts.append(prompt) or "")
    topicgen.extend(TOPIC, ["Tenant", "lease"], 5, "the paperwork\n side")
    prompt = prompts[0]
    assert TOPIC in prompt
    assert "do not repeat" in prompt and "lease, tenant" in prompt
    assert "the paperwork side" in prompt
    assert "5 lines" in prompt


def test_the_steer_is_capped_before_it_reaches_the_prompt(monkeypatch):
    prompts = []
    monkeypatch.setattr(topicgen, "_ask_claude",
                        lambda prompt, count: prompts.append(prompt) or "")
    topicgen.extend(TOPIC, [], 5, "x" * (topicgen.IDEA_MAX_CHARS + 50))
    assert "x" * topicgen.IDEA_MAX_CHARS in prompts[0]
    assert "x" * (topicgen.IDEA_MAX_CHARS + 1) not in prompts[0]


def test_no_steer_means_no_steer_line(monkeypatch):
    prompts = []
    monkeypatch.setattr(topicgen, "_ask_claude",
                        lambda prompt, count: prompts.append(prompt) or "")
    topicgen.extend(TOPIC, ["lease"], 5)
    assert "in particular" not in prompts[0]


def test_words_already_in_the_topic_are_dropped_from_the_answer(monkeypatch):
    """The instruction alone is a request the model sometimes ignores."""
    monkeypatch.setattr(topicgen, "_ask_claude",
                        lambda prompt, count: "Lease\ndeposit\ntenant\nsublet")
    assert topicgen.extend(TOPIC, ["lease", "Tenant"], 5) == ["deposit",
                                                              "sublet"]


def test_a_failed_call_is_none_not_a_raise(monkeypatch):
    def boom(prompt, count):
        raise RuntimeError("overloaded")

    monkeypatch.setattr(topicgen, "_ask_claude", boom)
    assert topicgen.extend(TOPIC, [], 5) is None


# --- the claim and the fill ----------------------------------------------------

def test_the_ticked_words_are_claimed_all_at_once(user_client, extendable):
    resp = user_client.post(START, data={"word": ["deposit", "sublet"],
                                         "proposed": "3"})
    assert resp.status_code == 302 and resp.location.endswith(
        "/topics/generate/filling")
    assert extendable["claims"] == [2], "one claim for the whole batch"
    with user_client.session_transaction() as sess:
        plan = sess["topic_plan"]
    assert plan["title"] == TOPIC and plan["extend"] is True
    assert plan["topic_id"] == TOPIC_ID and plan["words"] == ["deposit",
                                                             "sublet"]


def test_a_word_the_topic_has_never_reaches_a_lookup(user_client, extendable):
    """A form can be posted from anywhere; the topic's own words are dropped
    on the server too, before anything is claimed for them."""
    user_client.post(START, data={"word": ["lease", "deposit"]})
    assert extendable["claims"] == [1]
    with user_client.session_transaction() as sess:
        assert sess["topic_plan"]["words"] == ["deposit"]


def test_a_refused_claim_holds_no_plan(user_client, extendable, monkeypatch):
    monkeypatch.setattr("utils.claim_word_lookups",
                        lambda *a, **kw: (False, "user", 49))
    resp = user_client.post(START, data={"word": ["deposit", "sublet"]})
    assert resp.status_code == 302 and "/add-words" in resp.location
    with user_client.session_transaction() as sess:
        assert "topic_plan" not in sess


def test_a_refused_learner_claims_nothing(user_client, extendable, monkeypatch):
    monkeypatch.setattr("utils.resolve_topic",
                        lambda name, topic_id=None, **kw: _topic(public=False,
                                                                 creator=999))
    user_client.post(START, data={"word": ["deposit"]})
    assert extendable["claims"] == []


def _events(client):
    raw = client.get("/topics/generate/stream").get_data(as_text=True)
    return [json.loads(line[len("data: "):])
            for line in raw.splitlines() if line.startswith("data: ")]


def test_the_fill_files_into_this_topic_and_logs_topic_extended(
        user_client, extendable, monkeypatch, tmp_path):
    monkeypatch.setattr(applog, "LOGS_DIR", tmp_path)
    monkeypatch.setattr("cards.TOPIC_FILL_PAUSE", 0)
    monkeypatch.setattr("parsers.lookup_word",
                        lambda w, topic=None, translator=None, explanatory_dictionary=None:
                        [{"word": w, "pos": "noun"}])
    saved = []
    monkeypatch.setattr("cards._save_and_log",
                        lambda entry, source, **kw: saved.append(entry) or True)
    user_client.post(START, data={"word": ["deposit", "sublet"],
                                  "proposed": "3"})

    page = user_client.get("/topics/generate/filling").get_data(as_text=True)
    assert "Adding words to &ldquo;City life and housing&rdquo;" in page

    events = _events(user_client)
    assert [e["topic"] for e in saved] == [TOPIC, TOPIC]
    done = events[-1]
    assert done["type"] == "done" and done["saved"] == 2
    assert done["url"].endswith(f"?t={TOPIC_ID}"), "back to this very topic"

    log = (tmp_path / "cards.log").read_text(encoding="utf-8")
    line = next(l for l in log.splitlines() if "TOPIC-EXTENDED" in l)
    assert f"topic={TOPIC}" in line or "City life" in line
    assert "asked=2" in line and "proposed=3" in line and "saved=2" in line
    assert "TOPIC-GENERATED" not in log


def test_a_new_topic_still_logs_topic_generated(user_client, extendable,
                                               monkeypatch, tmp_path):
    """The shared stream must not turn #406's line into #524's."""
    monkeypatch.setattr(applog, "LOGS_DIR", tmp_path)
    monkeypatch.setattr("cards.TOPIC_FILL_PAUSE", 0)
    monkeypatch.setattr("parsers.lookup_word",
                        lambda w, topic=None, translator=None, explanatory_dictionary=None:
                        [{"word": w, "pos": "noun"}])
    monkeypatch.setattr("cards._save_and_log", lambda entry, source, **kw: True)
    user_client.post("/topics/generate/start",
                     data={"title": "Renting", "word": ["deposit"]})
    _events(user_client)
    log = (tmp_path / "cards.log").read_text(encoding="utf-8")
    assert "TOPIC-GENERATED" in log and "TOPIC-EXTENDED" not in log


# --- the guide ----------------------------------------------------------------

def test_the_guide_explains_it():
    from pathlib import Path
    import web
    guide = Path(web.USER_GUIDE).read_text(encoding="utf-8")
    assert "### Adding more words to a topic" in guide
