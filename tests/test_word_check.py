"""Settling a word *Real or fake* called invented (kuantorflow#258).

The game invents words with a trigram model trained on the deck, and a model
trained on English sometimes produces English — so a learner is marked wrong
for being right, and told a real word is not one. #132's filters ask what the
*deck* knows; the deck knows some 2,500 words. The gap they cannot close is the
rare end of English, which is exactly where the model collides: `bailment`, the
word that opened the ticket, is a real legal term.

So the results page lets the learner challenge, and a real lexicon settles it.

**The shape of the whole thing is "positive-only", and most of this file is
about that.** A hit is strong evidence a word is real. A miss is evidence of
nothing — Wiktionary and Oxford both miss rare words, which is the very reason
the button exists — and a failed request is not a miss at all. Three outcomes,
one of which is a verdict:

| result | means |
|---|---|
| `real: true` | a lexicon has it; correct the score, remember it |
| `real: false` | both answered, neither had it — **not** proof |
| `real: null` | nothing could be reached — "could not check" |

Collapsing the last two is the failure mode this file exists to catch: it would
tell a learner their word was invented because Wikimedia was rate-limiting us.
"""

import pytest

import parsers


@pytest.fixture()
def lexicons(monkeypatch):
    """What Wiktionary and Oxford answer, decided per test.

    `None` from either is a failed request, which is a different thing from an
    answer of "no" — and telling those two apart is what the whole file is
    about, so the fixture makes both expressible.
    """
    def install(wiktionary=False, oxford=None, oxford_raises=False):
        monkeypatch.setattr(parsers, "_wiktionary_has_english",
                            lambda word: wiktionary)

        def oxford_lookup(word):
            if oxford_raises:
                raise RuntimeError("oxford is unreachable")
            return oxford or {}

        monkeypatch.setattr(parsers, "_fetch_oxford_definitions", oxford_lookup)
    return install


# --- the three answers ------------------------------------------------------

def test_wiktionary_confirming_is_the_end_of_it(lexicons, monkeypatch):
    """And Oxford is not asked. It is the weaker oracle for this job — #258
    measured 71% of rare real words absent from a *learner's* dictionary — so
    a second request after a confirmation buys nothing."""
    asked = []
    lexicons(wiktionary=True)
    monkeypatch.setattr(parsers, "_fetch_oxford_definitions",
                        lambda word: asked.append(word) or {})

    verdict = parsers.confirm_word("bailment")

    assert verdict["real"] is True
    assert verdict["source"] == "Wiktionary"
    assert verdict["link"].endswith("/bailment#English")
    assert asked == [], "Oxford was asked anyway"


def test_oxford_is_the_second_chance(lexicons):
    """It holds ordinary words a `bd` lookup might skip, and when it answers it
    answers with a definition written for this exact reader."""
    lexicons(wiktionary=False, oxford={"noun": ["a formal agreement"]})

    verdict = parsers.confirm_word("covenant")

    assert verdict["real"] is True
    assert verdict["source"] == "Oxford Learner's Dictionaries"
    assert verdict["definition"] == "a formal agreement"


def test_neither_having_it_is_not_proof_of_anything(lexicons):
    """`real: False` means both answered. The page says "that is not proof" in
    those words, and this is the flag it says it about."""
    lexicons(wiktionary=False, oxford={})

    assert parsers.confirm_word("pictualism") == {"real": False}


def test_an_unreachable_lexicon_is_not_a_missing_word(lexicons):
    """The failure this file exists for. Wikimedia rate-limits bursts, and a
    429 that read as "no such word" would tell a learner their word was
    invented because of our own traffic."""
    lexicons(wiktionary=None, oxford_raises=True)

    assert parsers.confirm_word("subrogation") == {"real": None}


def test_oxford_alone_can_still_say_no(lexicons):
    """Wiktionary unreachable but Oxford answering is a half-answer, and the
    honest reading of it is "not found" rather than "could not check": one
    lexicon did look."""
    lexicons(wiktionary=None, oxford={})

    assert parsers.confirm_word("pictualism") == {"real": False}


def test_a_blank_word_asks_nobody(lexicons):
    lexicons(wiktionary=True)

    assert parsers.confirm_word("   ") == {"real": None}


# --- what Wiktionary is actually asked --------------------------------------

def test_it_asks_for_an_english_entry_rather_than_a_page(monkeypatch):
    """Wiktionary is multilingual: a page can exist for a word that is not
    English. `==English==` in the wikitext is the question being asked."""
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"query": {"pages": [{"revisions": [{"slots": {"main": {
                "content": "==Latin==\n# something"}}}]}]}}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(url=url, params=params, headers=headers)
        return Response()

    monkeypatch.setattr(parsers.requests, "get", fake_get)

    assert parsers._wiktionary_has_english("aqua") is False
    assert captured["params"]["titles"] == "aqua"
    assert "KuantorFlow" in captured["headers"]["User-Agent"], (
        "Wikimedia asks for an agent that identifies the application; the "
        "browser string the other fetchers use is wrong here")


def test_a_missing_page_is_a_no(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"query": {"pages": [{"missing": True}]}}

    monkeypatch.setattr(parsers.requests, "get",
                        lambda *a, **kw: Response())

    assert parsers._wiktionary_has_english("splusive") is False


def test_a_refused_request_is_neither(monkeypatch):
    def boom(*a, **kw):
        raise parsers.requests.RequestException("429")

    monkeypatch.setattr(parsers.requests, "get", boom)

    assert parsers._wiktionary_has_english("bailment") is None


# --- the endpoint -----------------------------------------------------------

@pytest.fixture()
def checker(app_module, monkeypatch):
    """The app's view of the lexicons, and what it remembered."""
    class Checker:
        def __init__(self):
            self.asked = []
            self.remembered = []
            self.answer = {"real": True, "source": "Wiktionary"}

        def confirm(self, word):
            self.asked.append(word)
            return dict(self.answer)

        def remember(self, word, source):
            self.remembered.append((word, source))
            return True

    state = Checker()
    monkeypatch.setattr(app_module.parsers, "confirm_word", state.confirm)
    monkeypatch.setattr(app_module, "remember_confirmed_word", state.remember,
                        raising=False)
    monkeypatch.setattr(app_module, "confirmed_words", lambda: set(),
                        raising=False)
    return state


def test_a_confirmation_is_remembered(user_client, checker):
    body = user_client.post("/games/word-check.json",
                            json={"word": "bailment"}).get_json()

    assert body["real"] is True
    assert checker.remembered == [("bailment", "Wiktionary")]


def test_a_word_that_is_not_confirmed_is_not_remembered(user_client, checker):
    """The set is what stops a word being offered as invented again, so only a
    confirmation may grow it. A "not found" is not evidence of anything and
    must leave no trace."""
    checker.answer = {"real": False}

    user_client.post("/games/word-check.json", json={"word": "pictualism"})

    assert checker.remembered == []


def test_a_settled_word_asks_nobody(user_client, app_module, monkeypatch,
                                    checker):
    """A second learner disputing the same word pays nothing, and the answer
    cannot change between rounds."""
    monkeypatch.setattr(app_module, "confirmed_words",
                        lambda: {"bailment"}, raising=False)

    body = user_client.post("/games/word-check.json",
                            json={"word": "Bailment"}).get_json()

    assert body["real"] is True and body["known"] is True
    assert checker.asked == [], "it went to a lexicon for a settled word"


def test_a_word_is_required(user_client, checker):
    assert user_client.post("/games/word-check.json",
                            json={"word": "  "}).status_code == 400


def test_a_blocked_account_cannot_check(user_client, block_state, checker):
    """#126. It writes to a shared table, so it is a write."""
    block_state.block()

    assert user_client.post("/games/word-check.json",
                            json={"word": "bailment"}).status_code == 403
    assert checker.asked == []


def test_the_confirmation_is_logged(user_client, checker, action_logs):
    user_client.post("/games/word-check.json", json={"word": "bailment"})

    line = (action_logs / "cards.log").read_text(encoding="utf-8")
    assert "WORD-CONFIRMED" in line
    assert "word=bailment" in line and "source=Wiktionary" in line


def test_a_run_of_checks_is_capped(user_client, app_module, checker):
    """Not money -- both lexicons are free -- but Wikimedia rate-limits what
    looks like a scraper, and being throttled would turn every dispute into
    "could not check" for everybody."""
    for _ in range(app_module.WORD_CHECKS_PER_HOUR):
        user_client.post("/games/word-check.json", json={"word": "bailment"})
    spent = len(checker.asked)

    body = user_client.post("/games/word-check.json",
                            json={"word": "bailment"}).get_json()

    assert body["real"] is None, "the cap must not read as a verdict"
    assert "later" in body["error"]
    assert len(checker.asked) == spent, "and it asked nobody"


# --- and the round never offers a settled word again ------------------------

def test_the_round_rejects_words_already_confirmed(user_client, app_module,
                                                   monkeypatch, stub_deck):
    """The compounding half: the deck's idea of real English grows from actual
    disagreements. Without this the same word is offered next week and the
    learner is marked wrong for it a second time."""
    stub_deck(cards=[{"id": 1, "word": "resilient", "topic": "Work",
                      "explanation_en": "able to recover quickly"}])
    monkeypatch.setattr(app_module, "confirmed_words",
                        lambda: {"bailment"}, raising=False)
    known = {}

    def capture(words, count, rng=None, order=None, known_=None, **kw):
        known["set"] = kw.get("known", known_)
        return []

    monkeypatch.setattr(app_module.games, "pseudowords", capture)

    user_client.get("/games/real_or_fake/play?topic=Work&words=6")

    assert "bailment" in known["set"], (
        "a word a learner already won an argument about")


def test_the_results_offer_the_challenge_only_where_it_is_needed(user_client,
                                                                 stub_deck):
    """A real word the learner mistook for a fake needs no adjudication: the
    game was right and the answer is already on the page. The interesting row
    is the other one."""
    stub_deck(cards=[{"id": 1, "word": "resilient", "topic": "Work"}])
    body = user_client.post(
        "/games/real_or_fake/play?topic=Work",
        data={"answer_1": "real", "item_1": "resilient", "real_1": "1",
              "answer_2": "real", "item_2": "crasterrupt", "real_2": "0"}
    ).get_data(as_text=True)

    rows = body.split('class="panel question')
    real_row = next(r for r in rows if "resilient" in r)
    invented_row = next(r for r in rows if "crasterrupt" in r)

    assert "rof-challenge" not in real_row
    assert "rof-challenge" in invented_row


def test_the_page_can_correct_its_own_score(user_client, stub_deck):
    """Offering a check, being proved wrong and leaving the mark against the
    learner would be worse than never asking. Measured on the real page:
    disputing `bailment` after answering "real" took the score from 3/6 to 4/6
    and flipped the row.
    """
    stub_deck(cards=[{"id": 1, "word": "resilient", "topic": "Work"}])
    body = user_client.post(
        "/games/real_or_fake/play?topic=Work",
        data={"answer_1": "real", "item_1": "crasterrupt", "real_1": "0"}
    ).get_data(as_text=True)

    assert 'id="rof-score"' in body and 'data-total="1"' in body
    assert 'data-said-real="1"' in body, "the script needs to know what they said"


def test_the_page_never_calls_a_miss_a_verdict(user_client, stub_deck):
    """The wording is the feature. Two of the three outcomes are not verdicts,
    and the page has to say so in both."""
    stub_deck(cards=[{"id": 1, "word": "resilient", "topic": "Work"}])
    body = " ".join(user_client.post(
        "/games/real_or_fake/play?topic=Work",
        data={"answer_1": "real", "item_1": "crasterrupt", "real_1": "0"}
    ).get_data(as_text=True).split())

    assert "That is not proof" in body
    assert "only about the connection" in body
    assert "confirmed invented" not in body
