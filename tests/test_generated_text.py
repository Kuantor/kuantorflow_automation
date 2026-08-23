"""Writing a text out of the learner's own words (kuantorflow#237).

The one activity that *produces* language rather than testing it, and the only
one that costs real money every time it runs. Which is what most of this file is
about: the call is stubbed throughout, so the suite stays offline and free, and
the tests that matter most are the ones proving the call did **not** happen —
a refused generation, a held text being re-read, a page merely being opened.

The seam is `textgen._ask_claude`, the one function that touches the network.
Everything above it — the prompt, the bounds, the highlighting, the log line —
stays in the path, because those are what is being tested.
"""

import re
import sys
import types

import pytest

import games
import textgen


CARDS = [
    {"id": 1, "word": "resign", "pos": "verb", "topic": "Work",
     "explanation_en": "to give up a job or position",
     "translation_ukr": "звільнятися", "translation_rus": "увольняться",
     "examples_en": ["He resigned from the board."]},
    {"id": 2, "word": "tactic", "pos": "noun", "topic": "Work",
     "explanation_en": "a method used to achieve something",
     "translation_ukr": "тактика", "translation_rus": "тактика"},
    {"id": 3, "word": "apply", "pos": "verb", "topic": "Work",
     "translation_ukr": "подавати заяву", "translation_rus": "подавать заявление"},
]

PASSAGE = ("She applied for the job in March. The tactics were obvious to "
           "everyone, and by June she had resigned.")

PLAY = "/games/read_a_text/play"
ONE_TOPIC = f"{PLAY}?topic=Work"


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS)


@pytest.fixture(autouse=True)
def has_key(monkeypatch):
    """A key is present unless a test says otherwise — read at request time on
    purpose, so setting it here is enough (kuantorflow#237)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")


@pytest.fixture(autouse=True)
def no_ceilings(app_module, monkeypatch):
    """No database behind the daily counters. Tests about the ceilings patch
    this themselves; every other test would otherwise write to a real one."""
    monkeypatch.setattr(app_module, "claim_text_generation",
                        lambda user_id, user_limit, daily: (True, None, 1))
    monkeypatch.setattr(app_module, "GENERATION_ANON_LIMIT", 0)


@pytest.fixture()
def claude(monkeypatch):
    """The model call replaced by a recorder. Returns the list of prompts."""
    prompts = []

    def fake(prompt, length):
        prompts.append((prompt, length))
        return PASSAGE

    monkeypatch.setattr(textgen, "_ask_claude", fake)
    return prompts


def _write(client, url=ONE_TOPIC, **form):
    """Press the button, then follow the redirect the way a browser does."""
    return client.post(url, data=form, follow_redirects=True)


def _passage(body):
    """The rendered text with its markup taken back off.

    Necessary rather than fussy: the highlighting cuts the passage into runs,
    so `"she had resigned"` is not a substring of the page — `resigned` is
    inside a `<strong>` of its own. Asserting on the raw HTML would mean
    asserting on where the bold happened to fall.
    """
    found = re.search(r'<div class="panel reader-text">(.*?)</div>', body, re.S)
    return re.sub(r"<[^>]+>", "", found.group(1)).strip() if found else ""


def _bold(body):
    return re.findall(r'<strong class="reader-word">(.*?)</strong>', body)


def _used(body):
    return re.findall(r'<span class="reader-word-used">(.*?)</span>', body)


def _unused(body):
    return re.findall(r'<span class="reader-word-unused">(.*?)</span>', body)


# --- it is a real activity now ----------------------------------------------

def test_the_activity_is_no_longer_a_stub():
    """`ticket` is present exactly while an activity is a stub (#253), and
    dropping it is what lights up the tile, the topic row and the round."""
    assert games.ACTIVITIES["read_a_text"].ticket == ""


def test_the_picker_counts_words_of_prose_not_questions(client, deck):
    """One box, two meanings: a quiz's number is questions asked, this one is
    words of prose, and a picker offering 1–200 words would be wrong."""
    body = client.get("/games/read_a_text").get_data(as_text=True)
    assert f'min="{games.GENERATED_WORDS_MIN}"' in body
    assert f'max="{games.GENERATED_WORDS_MAX}"' in body
    assert f'value="{games.GENERATED_WORDS_DEFAULT}"' in body
    assert games.GENERATED_WORDS.hint in body


def test_the_quiz_picker_still_counts_questions(client, deck):
    body = client.get("/quiz").get_data(as_text=True)
    assert f'max="{games.QUIZ_WORDS_MAX}"' in body
    assert f'value="{games.QUIZ_WORDS_DEFAULT}"' in body
    assert "picker-words-hint" not in body


def test_only_the_reader_asks_what_it_should_be_about(client, deck):
    assert 'name="about"' in client.get("/games/read_a_text").get_data(as_text=True)
    assert 'name="about"' not in client.get("/quiz").get_data(as_text=True)


# --- opening the page spends nothing ----------------------------------------

def test_opening_the_page_does_not_call_the_model(client, deck, claude):
    """The whole reason Start does not generate: a tile, a link and a bookmark
    all land here, and none of them asked to spend anything."""
    body = client.get(ONE_TOPIC).get_data(as_text=True)
    assert claude == []
    assert "Write my text" in body


# --- writing one ------------------------------------------------------------

def test_pressing_the_button_writes_a_text(client, deck, claude):
    body = _write(client).get_data(as_text=True)
    assert len(claude) == 1
    assert "she had resigned" in _passage(body)


def test_the_words_are_highlighted_by_matching_not_by_the_model(client, deck,
                                                                claude):
    """The model was asked for plain prose and never emits markup of its own;
    the bold is found afterwards, inflections and all."""
    body = _write(client).get_data(as_text=True)
    assert sorted(_bold(body)) == ["applied", "resigned", "tactics"]


def test_the_words_that_appeared_and_the_ones_that_did_not_are_both_listed(
        client, deck, monkeypatch):
    """No claimed coverage that was not checked. A missing word is information,
    not a failure — the text is still shown."""
    monkeypatch.setattr(textgen, "_ask_claude",
                        lambda prompt, length: "She resigned in March.")
    body = _write(client).get_data(as_text=True)
    assert _used(body) == ["resign"]
    assert sorted(_unused(body)) == ["apply", "tactic"]
    assert _passage(body) == "She resigned in March."


def test_a_generation_writes_one_log_line_naming_the_model(client, deck, claude,
                                                           action_logs):
    _write(client)
    line = (action_logs / "dict.log").read_text(encoding="utf-8")
    assert "GENERATE" in line
    assert f"model={textgen.TEXT_MODEL}" in line
    assert "supplied=3" in line and "used=3" in line


# --- the prompt -------------------------------------------------------------

def test_the_prompt_carries_the_words_alone(client, deck, claude):
    """No explanation, no examples, no translations — the card's other fields
    are exactly what #237 says not to send, and they are most of its bulk."""
    _write(client)
    prompt, _ = claude[0]
    for word in ("resign", "tactic", "apply"):
        assert word in prompt
    assert "to give up a job or position" not in prompt      # explanation_en
    assert "He resigned from the board." not in prompt       # examples_en
    assert "звільнятися" not in prompt                       # translation_ukr


def test_the_learners_line_reaches_the_prompt_on_one_line(client, deck, claude):
    _write(client, about="a letter\nof   complaint\r\nto a hotel")
    prompt, _ = claude[0]
    assert "a letter of complaint to a hotel" in prompt


def test_the_learners_line_is_capped(client, deck, claude):
    """Free text on its way into a model prompt, capped and flattened for the
    reason clean_preferred_name() gives (ai_agent#62)."""
    _write(client, about="x" * 5000)
    prompt, _ = claude[0]
    assert "x" * (textgen.INSTRUCTION_MAX_CHARS + 1) not in prompt


@pytest.mark.parametrize("length", [50, 150, 400])
def test_at_most_twenty_words_go_into_one_text(length):
    """A passage using two hundred words would be unreadable, and the rest of
    the deck is what the next text is for."""
    many = [{"word": f"word{i}"} for i in range(200)]
    chosen = textgen.words_for_text(many, length)
    assert textgen.WORDS_PER_TEXT_MIN <= len(chosen) <= textgen.WORDS_PER_TEXT_MAX


def test_a_word_that_is_two_cards_is_asked_for_once(deck):
    """#101 keeps one card per word *and part of speech*, so a word that is
    both a noun and a verb is two cards — and one of the dozen places a text
    has should not go to the same word twice."""
    both = [{"word": "resign"}, {"word": "Resign"}, {"word": "tactic"}]
    assert sorted(textgen.words_for_text(both, 150)) == ["resign", "tactic"]


def test_max_tokens_leaves_room_for_the_length_asked_for(client, deck,
                                                          monkeypatch):
    """English runs about 1.3 tokens a word, so a 1:1 cap stops the passage
    mid-sentence. The cap still makes a runaway impossible."""
    assert textgen.max_tokens(150) > 150
    assert textgen.max_tokens(150) < 150 * 3


def test_the_requested_length_reaches_the_call(client, deck, claude):
    _write(client, f"{PLAY}?topic=Work&words=300")
    _, length = claude[0]
    assert length == 300


def test_a_length_from_the_url_is_clamped_rather_than_refused(client, deck,
                                                              claude):
    """It arrives from a URL anybody can edit, and a round is not the place to
    argue about it."""
    _write(client, f"{PLAY}?topic=Work&words=99999")
    assert claude[0][1] == games.GENERATED_WORDS_MAX


# --- generate once ----------------------------------------------------------

def test_re_reading_a_held_text_costs_nothing(client, deck, claude):
    """A stray refresh, a flip back, a bookmark — none of them may spend."""
    _write(client)
    for _ in range(3):
        body = client.get(ONE_TOPIC).get_data(as_text=True)
        assert "she had resigned" in _passage(body)
    assert len(claude) == 1


def test_writing_the_text_redirects_so_a_refresh_is_a_get(client, deck, claude):
    """Post/redirect/get is what makes the refresh above a plain GET rather
    than a resubmitted POST."""
    posted = client.post(ONE_TOPIC, data={})
    assert posted.status_code == 302
    assert "/games/read_a_text/play" in posted.headers["Location"]


def test_regenerating_is_explicit_and_spends_again(client, deck, claude):
    _write(client)
    _write(client)
    assert len(claude) == 2


def test_changing_the_instruction_offers_a_fresh_text(client, deck, claude):
    """The held text is keyed on what produced it, so a different request does
    not silently show a text about something else."""
    _write(client, about="a news report")
    body = client.get(f"{ONE_TOPIC}&about=a+letter").get_data(as_text=True)
    assert "she had resigned" not in _passage(body)
    assert "Write my text" in body
    assert len(claude) == 1


def test_a_different_length_offers_a_fresh_text(client, deck, claude):
    _write(client, f"{PLAY}?topic=Work&words=150")
    body = client.get(f"{PLAY}?topic=Work&words=300").get_data(as_text=True)
    assert "she had resigned" not in _passage(body)


# --- the ceilings, all checked before the call ------------------------------

def test_an_anonymous_visitor_gets_one_text_then_the_sign_in_prompt(
        client, deck, claude, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "GENERATION_ANON_LIMIT", 1)
    _write(client)
    body = _write(client, about="something else").get_data(as_text=True)
    assert len(claude) == 1, "the refused text must not reach the model"
    # By the reader's own class: both the words "Sign in with Google" and
    # the shared `signin-required-go` styling appear in base.html on every
    # page, so neither can say whether *this* refusal offered a way on.
    assert "reader-signin" in body


def test_a_refusal_keeps_the_text_the_learner_already_has(
        client, deck, claude, app_module, monkeypatch):
    """Being told you cannot have a second text is no reason to lose the
    first."""
    monkeypatch.setattr(app_module, "GENERATION_ANON_LIMIT", 1)
    _write(client)
    body = _write(client, about="something else").get_data(as_text=True)
    assert "she had resigned" in _passage(body)


def test_the_daily_account_ceiling_says_so_plainly(client, deck, claude,
                                                   app_module, monkeypatch):
    monkeypatch.setattr(app_module, "claim_text_generation",
                        lambda *a: (False, "user", 10))
    body = _write(client).get_data(as_text=True)
    assert claude == []
    assert "today" in body.lower()
    assert "reader-signin" not in body         # signing in does not help here


def test_the_site_wide_ceiling_says_so_plainly(client, deck, claude,
                                               app_module, monkeypatch):
    monkeypatch.setattr(app_module, "claim_text_generation",
                        lambda *a: (False, "daily", 100))
    body = _write(client).get_data(as_text=True)
    assert claude == []
    assert "tomorrow" in body.lower()


def test_a_blocked_account_cannot_spend_anything(client, deck, claude,
                                                 app_module, monkeypatch):
    monkeypatch.setattr(app_module, "is_blocked", lambda: True)
    _write(client)
    assert claude == []


def test_a_dead_counter_does_not_take_the_activity_down(client, deck, claude,
                                                        app_module, monkeypatch):
    """Best-effort in the same direction as #164's counter: an unreachable
    database cannot enforce a ceiling, and it has already made the deck
    unreadable."""
    def boom(*a):
        raise RuntimeError("database is away")

    monkeypatch.setattr(app_module, "claim_text_generation", boom)
    assert "she had resigned" in _passage(_write(client).get_data(as_text=True))


# --- no key, no activity ----------------------------------------------------

def test_with_no_api_key_the_activity_is_not_there_at_all(client, deck,
                                                          monkeypatch):
    """Hide what the learner cannot act on (#233), exactly as
    MYKOLA_AVAILABLE=False removes the chat widget. There is no fallback —
    nothing else can write the text."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/games/read_a_text").status_code == 404
    assert client.get(ONE_TOPIC).status_code == 404
    assert "/games/read_a_text" not in client.get("/").get_data(as_text=True)


def test_the_other_games_do_not_need_a_key(client, deck, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/games/scrambled").status_code == 200


# --- when the call fails ----------------------------------------------------

def test_a_failed_call_is_reported_and_logged(client, deck, monkeypatch,
                                              action_logs):
    """A silent fallback reads as a bug (#30), and there is no fallback here
    worth the name — so it says so, and the log says why."""
    def boom(prompt, length):
        raise RuntimeError("anthropic is away")

    monkeypatch.setattr(textgen, "_ask_claude", boom)
    body = _write(client).get_data(as_text=True)
    assert "could not be written" in body
    log = (action_logs / "dict.log").read_text(encoding="utf-8")
    assert "GENERATE" in log and "anthropic is away" in log


def test_an_empty_reply_counts_as_a_failure(client, deck, monkeypatch):
    monkeypatch.setattr(textgen, "_ask_claude", lambda prompt, length: "   ")
    assert "could not be written" in _write(client).get_data(as_text=True)


# --- the text's own title (kuantorflow#315) ----------------------------------

def _title(body):
    found = re.search(r'<h2 class="reader-title">(.*?)</h2>', body, re.S)
    return re.sub(r"<[^>]+>", "", found.group(1)).strip() if found else None


def titled(text):
    """A reply shaped the way the prompt asks for: title, blank line, prose."""
    return lambda prompt, length: text


@pytest.mark.parametrize("reply, title", [
    ("A Trial In Three Acts\n\nShe resigned in March.", "A Trial In Three Acts"),
    ("# Local Man Acquitted\n\nShe resigned in March.", "Local Man Acquitted"),
    ("Title: The Long Wait\n\nShe resigned in March.", "The Long Wait"),
    ('"Quiet Streets"\n\nShe resigned in March.', "Quiet Streets"),
    ("“Quiet Streets”\n\nShe resigned in March.", "Quiet Streets"),
])
def test_the_title_is_parsed_out_of_whatever_shape_arrives(client, deck,
                                                           monkeypatch,
                                                           reply, title):
    """One call, not two: the title rides in the same reply, and the model
    decorates it differently from run to run."""
    monkeypatch.setattr(textgen, "_ask_claude", titled(reply))
    assert _title(_write(client).get_data(as_text=True)) == title


def test_a_first_line_that_is_really_prose_is_left_alone(client, deck,
                                                         monkeypatch):
    """The failure worth protecting against: eating the opening sentence of the
    passage is worse than showing no title at all."""
    prose = ("The defendant in yesterday's trial was acquitted of all charges.\n\n"
             "She resigned in March.")
    monkeypatch.setattr(textgen, "_ask_claude", titled(prose))
    body = _write(client).get_data(as_text=True)
    assert _title(body) is None
    assert "The defendant in yesterday" in _passage(body)


def test_a_reply_with_no_second_line_is_all_text(client, deck, monkeypatch):
    """A one-line reply is a short text, not a title with nothing under it."""
    monkeypatch.setattr(textgen, "_ask_claude",
                        titled("She resigned in March and never looked back"))
    body = _write(client).get_data(as_text=True)
    assert _title(body) is None
    assert "never looked back" in _passage(body)


def test_a_word_only_in_the_title_still_counts_as_used(client, deck, monkeypatch):
    """#315's one real rule. The learner reads the title, so reporting a word
    as unused while it sits in bold two lines above would be exactly the
    unverified claim #237 exists to avoid."""
    monkeypatch.setattr(textgen, "_ask_claude",
                        titled("The Tactics Of Delay\n\nShe applied in March."))
    body = _write(client).get_data(as_text=True)
    assert "tactic" in _used(body)
    assert "tactic" not in _unused(body)
    assert "Tactics" in re.findall(
        r'<strong class="reader-word">(.*?)</strong>',
        re.search(r'<h2 class="reader-title">(.*?)</h2>', body, re.S).group(1))


def test_the_title_survives_a_refresh(client, deck, monkeypatch):
    """It is stored beside the text and the marking is recomputed on read, so
    the re-read has to reach the same answer the generation did."""
    monkeypatch.setattr(textgen, "_ask_claude",
                        titled("A Trial In Three Acts\n\nShe resigned in March."))
    _write(client)
    assert _title(client.get(ONE_TOPIC).get_data(as_text=True)) == "A Trial In Three Acts"


def test_the_prompt_asks_for_a_title(client, deck, claude):
    """It used to forbid one — the model wrote a headline anyway."""
    _write(client)
    prompt, _ = claude[0]
    assert "title" in prompt.lower()
    assert "no title" not in prompt.lower()


def test_the_title_is_capped(client, deck, monkeypatch):
    """Held in a signed cookie with measured headroom, so an enormous first
    line cannot be stored whole."""
    monkeypatch.setattr(textgen, "_ask_claude",
                        titled("Word " * 40 + "\n\nShe resigned in March."))
    body = _write(client).get_data(as_text=True)
    # 40 words is past TITLE_MAX_WORDS, so it is not a title at all
    assert _title(body) is None


# --- a reply the model did not finish (kuantorflow#344) ----------------------
#
# The ceiling stops the model mid-flow and the API says so, in
# `stop_reason == "max_tokens"`. That used to be discarded, so a passage
# reached the learner ending "increases your success rate considerably. You".
#
# The stub in most of this file replaces `_ask_claude` itself, which is above
# the place the truncation is reported -- so these tests stub the SDK instead,
# one layer lower, and are the only ones here that do.


class _FakeMessage:
    def __init__(self, text, stop_reason):
        self.content = [types.SimpleNamespace(type="text", text=text)]
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, message, calls):
        self._message, self._calls = message, calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        return self._message


@pytest.fixture()
def api(monkeypatch):
    """A stub `anthropic` module, and the recorder of what was sent to it.

    Installed into `sys.modules` rather than monkeypatched onto the real
    package, because **the SDK is deliberately not installed in this venv** --
    the suite is offline, and `_ask_claude()` imports `anthropic` inside the
    function precisely so it can be. That import picks up whatever is in
    `sys.modules` at call time, which is what makes this possible at all.

    `arm(text, stop_reason)` sets the reply and returns the list of keyword
    arguments each `messages.create` was given, so a test can assert on the
    ceiling that actually went out.
    """
    calls = []

    def arm(text, stop_reason):
        message = _FakeMessage(text, stop_reason)

        class _Client:
            def __init__(self, *a, **k):
                self.messages = _FakeMessages(message, calls)

        monkeypatch.setitem(sys.modules, "anthropic",
                            types.SimpleNamespace(Anthropic=_Client))
        return calls

    return arm


TRUNCATED = ("A Quiet Week\n\nHe resigned in March. Professional support, "
             "whether counselling or medication, increases your success "
             "rate considerably. You")


def test_a_truncated_reply_is_cut_back_to_its_last_whole_sentence(api):
    api(TRUNCATED, "max_tokens")
    text = textgen._ask_claude("prompt", 150)
    assert text.endswith("increases your success rate considerably.")
    assert not text.endswith("You")


def test_a_finished_reply_is_passed_through_untouched(api):
    """`end_turn` means the model stopped because it was done. Trimming there
    would silently drop a last sentence that legitimately has no full stop."""
    api(TRUNCATED, "end_turn")
    assert textgen._ask_claude("prompt", 150).endswith("You")


def test_a_reply_cut_before_any_whole_sentence_is_a_failure(api):
    """Half a sentence is not a text. Raised rather than returned, so
    `generate()` reports it the way it reports any other failed call."""
    api("Quitting smoking is one of the best decisions you can possibly",
        "max_tokens")
    with pytest.raises(ValueError):
        textgen._ask_claude("prompt", 150)


def test_the_ceiling_that_was_sent_is_the_one_max_tokens_computed(api):
    calls = api(TRUNCATED, "end_turn")
    textgen._ask_claude("prompt", 150)
    assert calls[0]["max_tokens"] == textgen.max_tokens(150)


# --- the ceiling itself -----------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("He resigned. Then he left. And she", "He resigned. Then he left."),
    ('She said "no." Then', 'She said "no."'),
    ("Ends already.", "Ends already."),
    ("A question? Yes! But", "A question? Yes!"),
])
def test_trim_to_sentence_keeps_whole_sentences(text, expected):
    assert textgen.trim_to_sentence(text) == expected


@pytest.mark.parametrize("text", [
    "", "   ", "no terminal punctuation at all",
    # More than half the reply would go: a stub, not a text.
    "Short. " + "and then it kept going without ever stopping again " * 3,
])
def test_trim_to_sentence_refuses_to_return_a_stub(text):
    assert textgen.trim_to_sentence(text) is None


def test_the_ceiling_leaves_room_for_the_words_that_were_asked_for():
    """The bug was a ceiling sitting on top of the measurement: a generated
    passage runs about 1.45 tokens a word, and the ratio was 1.5."""
    assert textgen.max_tokens(150) / 150 >= 1.8


def test_the_ceiling_never_passes_what_the_cookie_can_hold():
    """The held text lives in a signed cookie Werkzeug drops past ~4 KB, and
    600 tokens was the measured worst case that fits (kuantorflow#237)."""
    assert textgen.max_tokens(games.GENERATED_WORDS_MAX) == 600
    assert textgen.max_tokens(10_000) == 600
