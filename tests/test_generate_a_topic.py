"""Building a topic from an idea (kuantorflow#406).

An idea in, a proposed title and word list back, the learner edits and approves,
and the dictionaries fill the cards.

**The order of the guards is the feature**, and it is what most of this file
checks. Three things must happen before three others, and each pairing has a
ticket behind it:

* the **write** guard runs before the **model call** (#200) -- an anonymous
  visitor cannot save a card (#125), so proposing twenty of them is paying for
  a refusal;
* the **free checks** run before the **paid ones** (#389/#391) -- a word no
  lexicon has is found for nothing, and #221 is what finding out afterwards
  costs: a card with translations and no explanation;
* the **lookups are claimed** before the **fill opens**, all or nothing, because
  a partial claim is the half-built topic #406's ceiling decision exists to
  avoid -- and because a session write after the first byte of a stream never
  reaches the browser.

Nothing here calls Claude or a dictionary: `topicgen.propose`,
`parsers.wiktionary_pages` and `lookup_word` are all stubbed. What the model
writes is not this repo's behaviour; what the app does with it is.
"""

import json

import pytest

import topicgen


PROPOSED = ["tenancy", "deposit", "landlord", "sublet", "quorble"]


@pytest.fixture()
def proposes(monkeypatch, app_module):
    """A model that answers, and a lexicon that has all but `quorble`."""
    monkeypatch.setattr(app_module.topicgen, "propose",
                        lambda idea, count: ("Renting a flat", PROPOSED[:count]))
    monkeypatch.setattr(app_module.parsers, "wiktionary_pages",
                        lambda words: {w for w in words if w != "quorble"})
    monkeypatch.setattr(app_module, "existing_words", lambda owner_id=None: set())
    monkeypatch.setattr(app_module, "lookups_used_today", lambda user_id: 0)
    monkeypatch.setattr(app_module, "claim_word_lookups",
                        lambda user_id, count, u, a: (True, None, count))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def _propose(client, idea="renting a flat", count=5):
    return client.post("/topics/generate",
                       data={"idea": idea, "count": str(count)})


# --- proposing --------------------------------------------------------------

def test_a_proposal_writes_nothing_and_spends_no_lookup(user_client, proposes,
                                                        app_module, monkeypatch):
    """The half of #406 that is free, and must stay free. Nothing is saved and
    no dictionary is asked until the learner has seen the list and approved it."""
    saved, claimed = [], []
    monkeypatch.setattr(app_module, "_save_and_log",
                        lambda entry, source, **kw: saved.append(entry))
    monkeypatch.setattr(app_module, "claim_word_lookups",
                        lambda *a: claimed.append(a) or (True, None, 0))

    body = _propose(user_client).get_data(as_text=True)

    assert "Renting a flat" in body
    assert saved == [] and claimed == []


def test_the_write_guard_runs_before_the_model(user_client, proposes,
                                               app_module, monkeypatch):
    """#200's rule, and the reason `upload_notes` asks at the door. A visitor
    who cannot save a card must not pay for twenty proposed ones."""
    asked = []
    monkeypatch.setattr(app_module.topicgen, "propose",
                        lambda idea, count: asked.append(idea) or ("T", ["x"]))
    monkeypatch.setattr(app_module, "add_refusal", lambda: "Sign in to add cards.")

    _propose(user_client)

    assert asked == [], "the model was asked despite the refusal"


def test_a_word_no_lexicon_has_is_flagged_and_unticked(user_client, proposes):
    """#389's batched check, spent here on the list before the money is."""
    body = _propose(user_client).get_data(as_text=True)

    assert "no dictionary entry" in body
    quorble = body[body.index('value="quorble"'):][:200]
    assert "checked" not in quorble, "a word with no entry starts unticked"
    tenancy = body[body.index('value="tenancy"'):][:200]
    assert "checked" in tenancy


def test_a_word_already_in_the_deck_is_noted_but_left_ticked(user_client,
                                                            proposes,
                                                            app_module,
                                                            monkeypatch):
    """A note, not a veto. #101 keeps one card per word **and part of speech**,
    so a deck holding `tip` the noun still gains `tip` the verb -- unticking it
    would be the screen claiming something it does not know."""
    monkeypatch.setattr(app_module, "existing_words",
                        lambda owner_id=None: {"deposit"})

    body = _propose(user_client).get_data(as_text=True)

    assert "already in your deck" in body
    deposit = body[body.index('value="deposit"'):][:200]
    assert "checked" in deposit


def test_an_unreachable_lexicon_leaves_the_list_usable(user_client, proposes,
                                                       app_module, monkeypatch):
    """#389's failure mode again: the check is a bonus, not a gate. A lexicon
    that cannot be reached must not empty an approve screen."""
    monkeypatch.setattr(app_module.parsers, "wiktionary_pages",
                        lambda words: None)

    body = _propose(user_client).get_data(as_text=True)

    assert "could not run just now" in body
    assert "no dictionary entry" not in body, "nothing may be flagged on silence"
    assert body.count('name="word"') == len(PROPOSED)


def test_an_anonymous_visitor_is_refused_at_the_door(client, proposes,
                                                     app_module, monkeypatch):
    asked = []
    monkeypatch.setattr(app_module.topicgen, "propose",
                        lambda idea, count: asked.append(1) or ("T", ["x"]))

    body = _propose(client).get_data(as_text=True)

    assert asked == []
    assert "name=\"word\"" not in body


def test_without_a_key_the_page_does_not_exist(user_client, proposes,
                                               monkeypatch):
    """`_reachable_activity()`'s rule (#237): not offered rather than offered
    and broken."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert user_client.get("/topics/generate").status_code == 404


# --- the way in -------------------------------------------------------------
#
# The tests below are the ones that were missing when this shipped. Every
# assertion in this file was about the page, and none about whether a learner
# could *reach* it -- so the routes and templates went out with nothing linking
# to them, and the feature was usable only by typing the URL. A page nobody can
# find is not a feature, and that is as much a regression as a broken one.

def test_the_front_page_offers_it(user_client, proposes):
    body = user_client.get("/").get_data(as_text=True)

    assert "/topics/generate" in body
    assert "Build a topic" in body


def test_the_offer_disappears_without_a_key(user_client, proposes, monkeypatch):
    """#237's shape: hidden rather than offered and broken, the same way
    `MYKOLA_AVAILABLE=False` removes the chat widget. The route already 404s --
    this is the half that keeps a learner from meeting the 404."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    body = user_client.get("/").get_data(as_text=True)

    assert "/topics/generate" not in body


def test_the_link_is_styled_as_a_button_this_stylesheet_has(user_client,
                                                            proposes):
    """`button-link`, not `button` (#340). The first version used a class the
    stylesheet does not define, so it rendered as bare text -- invisible to
    pytest, and the reason a browser pass found it instead."""
    body = user_client.get("/").get_data(as_text=True)
    at = body.index("/topics/generate")
    tag = body[max(0, at - 120):at]

    assert "button-link" in tag


# --- approving --------------------------------------------------------------

def test_only_the_ticked_words_are_paid_for(user_client, proposes, app_module,
                                            monkeypatch):
    """The tick is the decision. A word the learner unticked is not looked up
    and not claimed for."""
    claimed = []
    monkeypatch.setattr(app_module, "claim_word_lookups",
                        lambda user_id, count, u, a: claimed.append(count)
                        or (True, None, count))

    user_client.post("/topics/generate/start",
                     data={"title": "Renting a flat",
                           "word": ["tenancy", "deposit"]})

    assert claimed == [2]


def test_the_claim_happens_before_the_fill_page(user_client, proposes,
                                                app_module, monkeypatch):
    """#406's ceiling decision, and the SSE constraint behind it: a session
    write after the first byte of a stream never reaches the browser, so the
    claim cannot live inside the fill."""
    order = []
    monkeypatch.setattr(app_module, "claim_word_lookups",
                        lambda *a: order.append("claim") or (True, None, 1))

    reply = user_client.post("/topics/generate/start",
                             data={"title": "T", "word": ["tenancy"]})

    assert order == ["claim"]
    assert reply.status_code == 302
    assert reply.headers["Location"].endswith("/topics/generate/filling")


def test_a_refused_claim_builds_nothing(user_client, proposes, app_module,
                                        monkeypatch):
    """The refusal arrives while the learner is still looking at the list,
    which is the whole point of stating the cost on that screen."""
    monkeypatch.setattr(app_module, "claim_word_lookups",
                        lambda *a: (False, "user", 48))

    reply = user_client.post("/topics/generate/start",
                             data={"title": "T", "word": ["tenancy", "deposit"]})

    assert reply.headers["Location"].endswith("/topics/generate")
    assert not user_client.get("/topics/generate/filling",
                               follow_redirects=False).headers[
        "Location"].endswith("/filling")


def test_a_word_that_is_not_a_headword_never_reaches_a_dictionary(
        user_client, proposes, app_module, monkeypatch):
    """The form is a form: what comes back is whatever was posted, and
    `lookup_word()` is built for single alphabetic headwords."""
    claimed = []
    monkeypatch.setattr(app_module, "claim_word_lookups",
                        lambda user_id, count, u, a: claimed.append(count)
                        or (True, None, count))

    user_client.post("/topics/generate/start",
                     data={"title": "T",
                           "word": ["tenancy", "two words", "", "9", "tenancy"]})

    assert claimed == [1], "only the one real headword, and no duplicate"


# --- filling ----------------------------------------------------------------

def _events(client):
    raw = client.get("/topics/generate/stream").get_data(as_text=True)
    return [json.loads(line[len("data: "):])
            for line in raw.splitlines() if line.startswith("data: ")]


def test_the_fill_reports_every_word_and_then_finishes(user_client, proposes,
                                                       app_module, monkeypatch):
    monkeypatch.setattr(app_module, "TOPIC_FILL_PAUSE", 0)
    monkeypatch.setattr(app_module, "lookup_word",
                        lambda w, t, d: [{"word": w, "pos": "noun"}])
    monkeypatch.setattr(app_module, "_save_and_log",
                        lambda entry, source, **kw: True)
    user_client.post("/topics/generate/start",
                     data={"title": "Renting a flat",
                           "word": ["tenancy", "deposit"]})

    events = _events(user_client)

    assert [e["word"] for e in events if e["type"] == "word"] == ["tenancy",
                                                                  "deposit"]
    assert events[-1]["type"] == "done" and events[-1]["saved"] == 2


def test_a_failed_lookup_is_a_skipped_word_not_a_dead_run(user_client, proposes,
                                                          app_module,
                                                          monkeypatch):
    """`seed_topics.py`'s rule, and it matters more here: Reverso and
    Merriam-Webster are blocked from PythonAnywhere, so one word failing is
    ordinary. Losing the other nineteen to it would not be."""
    monkeypatch.setattr(app_module, "TOPIC_FILL_PAUSE", 0)

    def flaky(word, translator, dictionary):
        if word == "deposit":
            raise ValueError("nothing came back")
        return [{"word": word, "pos": "noun"}]

    monkeypatch.setattr(app_module, "lookup_word", flaky)
    monkeypatch.setattr(app_module, "_save_and_log",
                        lambda entry, source, **kw: True)
    user_client.post("/topics/generate/start",
                     data={"title": "T",
                           "word": ["tenancy", "deposit", "landlord"]})

    events = _events(user_client)
    outcomes = {e["word"]: e["outcome"] for e in events if e["type"] == "word"}

    assert outcomes == {"tenancy": "saved", "deposit": "failed",
                        "landlord": "saved"}
    assert events[-1]["saved"] == 2 and events[-1]["failed"] == 1


def test_every_card_still_goes_through_the_single_write_path(user_client,
                                                             proposes,
                                                             app_module,
                                                             monkeypatch):
    """CLAUDE.md's rule for a new save path: it goes through `_save_and_log()`,
    which is where #125, #89 and the card log all live. A generator that wrote
    cards its own way would be a second place to get permissions wrong."""
    monkeypatch.setattr(app_module, "TOPIC_FILL_PAUSE", 0)
    monkeypatch.setattr(app_module, "lookup_word",
                        lambda w, t, d: [{"word": w, "pos": "noun"}])
    through = []
    monkeypatch.setattr(app_module, "_save_and_log",
                        lambda entry, source, **kw: through.append(
                            (entry["word"], entry["topic"], source)) or True)
    user_client.post("/topics/generate/start",
                     data={"title": "Renting a flat", "word": ["tenancy"]})

    _events(user_client)

    assert through == [("tenancy", "Renting a flat", "topic generator")]


def test_the_stream_says_so_rather_than_streaming_nothing(user_client, proposes,
                                                          app_module):
    """Reached with no held plan -- a bookmark, or a second tab after the first
    finished. One error frame beats an empty stream the page waits on forever."""
    events = _events(user_client)

    assert events and events[0]["type"] == "error"


# --- the parser, which is where a model's output stops being trusted --------

@pytest.mark.parametrize("line", [
    "two words", "TENANCY!", "9", "a", "",
])
def test_only_single_headwords_survive_parsing(line):
    _title, words = topicgen._parse("TITLE: T\n" + line, 10)

    assert words == []


def test_a_duplicate_is_dropped_rather_than_shown_twice():
    _title, words = topicgen._parse(
        "TITLE: T\ntenancy\nTenancy\ndeposit", 10)

    assert words == ["tenancy", "deposit"]


def test_the_idea_is_capped_and_collapsed_before_it_reaches_a_prompt():
    """`textgen.INSTRUCTION_MAX_CHARS` and ai_agent's `clean_preferred_name()`
    are the precedents, and the reason is theirs: this value ends up inside a
    model prompt."""
    cleaned = topicgen.clean_idea("a\nb\r\nc   d" + "x" * 500)

    assert "\n" not in cleaned and "\r" not in cleaned
    assert len(cleaned) == topicgen.IDEA_MAX_CHARS


def test_the_word_count_is_clamped_to_what_a_budget_can_pay_for():
    assert topicgen.word_count("999") == topicgen.MAX_WORDS
    assert topicgen.word_count("1") == topicgen.MIN_WORDS
    assert topicgen.word_count("nonsense") == topicgen.DEFAULT_WORDS
