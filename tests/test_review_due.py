"""Review (N due): a round of the words due for review (kuantorflow#92).

A review is an ordinary round of an ordinary game, dealt only from the words
due today, reached from a *Review (N due)* badge and the `/review` page. What
is pinned here:

* **the count** -- words due today *that have a visible card*, duplicates once;
* **the round** -- `?review=1` deals only due words in each of the seven
  one-card games, on the GET and on the grading POST, and the answers are
  recorded like any round's;
* **the way out** -- *Play again* returns to `/review` rather than rebuilding
  a whole-deck URL (#342), and a game with nothing to deal says so;
* **who** -- an anonymous visitor gets no badge, a sign-in message, and the
  ordinary whole-deck round if they type `?review=1` by hand.

Dates are pinned by patching `recall.today()`, so nothing depends on when the
suite runs.
"""

import re
from datetime import date

import pytest

import games
import recall
import rounds
from conftest import TEST_USER_ID
from test_draw_prefers_due import DECK, WEIGHTED

TODAY = date(2026, 9, 30)

# delegate: 3 days overdue; resign: due today; appraise: next week;
# commute: never answered; negotiate: not in the schedule either; and a due
# word with no card at all, which must never be counted or promised.
SCHEDULE = {
    ("delegate", "verb"): date(2026, 9, 27),
    ("resign", "verb"): TODAY,
    ("appraise", "verb"): date(2026, 10, 7),
    ("ghost", "noun"): date(2026, 9, 1),
}
DUE_IDS = {1, 2}          # delegate, resign


@pytest.fixture()
def review(stub_deck, monkeypatch):
    """The deck, a pinned today, and a schedule for the signed-in learner."""
    import utils

    stub_deck(cards=DECK)
    monkeypatch.setattr(recall, "today", lambda: TODAY)

    def install(schedule=SCHEDULE):
        keyed = {recall.word_key(w, p): d for (w, p), d in schedule.items()}
        monkeypatch.setattr(utils, "due_dates",
                            lambda user_id: dict(keyed) if user_id else {})
    install()
    return install


@pytest.fixture()
def dealt(app_module, monkeypatch):
    """The ids of everything each round hands `games.sample()`."""
    calls = []
    original = games.sample

    def recording(items, count, rng=None, weight=None):
        calls.append({(item[0] if isinstance(item, tuple) else item)["id"]
                      for item in items})
        return original(items, count, rng=rng, weight=weight)

    monkeypatch.setattr("games.sample", recording)
    return calls


def _badge(body):
    return re.findall(r'class="review-badge"[^>]*>\s*Review\s*\((\d+) due\)', body)


# --- the badge and the count ------------------------------------------------------

def test_the_badge_counts_due_words_that_have_a_card(user_client, review):
    """Two words due (one overdue, one today). `appraise` is scheduled later,
    `commute` was never answered, and `ghost` is due but has no card -- the
    badge must not promise a round it cannot deal."""
    assert _badge(user_client.get("/").get_data(as_text=True)) == ["2"]


def test_no_badge_when_nothing_is_due(user_client, review):
    review({("appraise", "verb"): date(2026, 10, 7)})

    assert _badge(user_client.get("/").get_data(as_text=True)) == []


def test_no_badge_for_an_anonymous_visitor(client, review):
    assert "review-badge" not in client.get("/").get_data(as_text=True)


def test_duplicate_cards_are_one_word(user_client, stub_deck, review):
    """The deck holds two identical `resign` cards; it is still one word."""
    stub_deck(cards=DECK + [dict(DECK[1], id=9)])

    assert _badge(user_client.get("/").get_data(as_text=True)) == ["2"]


# --- the review page ------------------------------------------------------------

def test_the_page_lists_the_due_words_longest_waiting_first(user_client, review):
    body = user_client.get("/review").get_data(as_text=True)

    words = re.findall(r'<span class="review-word">([^<]+)</span>', body)
    assert words == ["delegate", "resign"]
    assert "3 days overdue" in body and "due today" in body
    assert "ghost" not in body


def test_the_page_offers_every_one_card_game_as_a_review(user_client, review):
    body = user_client.get("/review").get_data(as_text=True)
    offered = re.findall(r'href="([^"]*review=1[^"]*)"', body)

    assert set(rounds.REVIEW_GAMES) == {slug for slug, _ in WEIGHTED}
    assert len(offered) == len(rounds.REVIEW_GAMES)
    assert "/quiz?review=1" in offered


def test_with_nothing_due_the_page_names_the_next_day(user_client, review):
    review({("appraise", "verb"): date(2026, 10, 7)})
    body = user_client.get("/review").get_data(as_text=True)

    assert "Nothing is due today" in body
    assert "7 October" in body


def test_an_anonymous_visitor_is_told_to_sign_in(client, review):
    body = client.get("/review").get_data(as_text=True)

    assert "needs an account" in body
    assert "review=1" not in body


# --- the round ------------------------------------------------------------------

@pytest.mark.parametrize("slug,url", WEIGHTED, ids=[s for s, _ in WEIGHTED])
def test_a_review_round_deals_only_due_words(user_client, review, dealt,
                                             slug, url):
    """Every one-card game, through `?review=1`: whatever it samples is due."""
    review_url = url.split("?")[0] + "?review=1"
    if slug in ("quiz", "multiple_choice"):
        review_url += "&lang=ukr"
    response = user_client.get(review_url + "&words=10")

    assert response.status_code == 200
    assert dealt, f"{slug} dealt nothing"
    assert set().union(*dealt) <= DUE_IDS, f"{slug} dealt a word not due"


def test_without_the_flag_the_round_is_the_whole_selection(user_client, review,
                                                          dealt):
    user_client.get("/games/spell_it/play?topic=Work&words=10")

    assert dealt[0] == {card["id"] for card in DECK}


def test_a_typed_review_url_deals_the_whole_deck_to_an_anonymous_visitor(
        client, review, dealt):
    client.get("/games/spell_it/play?review=1&words=10")

    assert dealt[0] == {card["id"] for card in DECK}


def test_grading_a_review_records_the_due_word(user_client, review, monkeypatch):
    """The POST reads the deck through the same filter, so the id is found
    and the answer reaches the log -- which is what moves the date."""
    recorded = []
    monkeypatch.setattr("utils.record_answers",
                        lambda user_id, game, answers: recorded.append(
                            (game, [(c["id"], ok) for c, ok in answers])))
    body = user_client.post("/games/spell_it/play?review=1",
                            data={"answer_1": "delegate"}).get_data(as_text=True)

    assert "Score: 1 / 1" in body
    assert recorded == [("spell_it", [(1, True)])]


def test_a_review_post_cannot_grade_a_word_that_is_not_due(user_client, review,
                                                          monkeypatch):
    """`appraise` is not due: a hand-built POST naming it grades nothing."""
    recorded = []
    monkeypatch.setattr("utils.record_answers",
                        lambda user_id, game, answers: recorded.append(answers))
    user_client.post("/games/spell_it/play?review=1",
                     data={"answer_3": "appraise"})

    assert recorded == []


def test_the_most_overdue_word_weighs_most():
    weight = recall.review_weight(
        {recall.word_key(w, p): d for (w, p), d in SCHEDULE.items()}, TODAY)

    assert weight({"word": "delegate", "pos": "verb"}) == 4      # 3 days late
    assert weight({"word": "resign", "pos": "verb"}) == 1        # due today
    assert weight({"word": "appraise", "pos": "verb"}) == recall.NOT_DUE_WEIGHT


# --- the way out ---------------------------------------------------------------

def test_after_a_review_the_way_on_is_back_to_review(user_client, review):
    """Rebuilding the URL from the round's topics would name every visible
    topic, drop the flag, and remember the whole deck as the learner's own
    selection (#342)."""
    body = user_client.post("/games/spell_it/play?review=1",
                            data={"answer_1": "delegate"}).get_data(as_text=True)

    assert 'href="/review">Back to review</a>' in body
    assert "Play again" not in body


def test_an_ordinary_round_still_plays_again(user_client, review):
    body = user_client.post("/games/spell_it/play?topic=Work",
                            data={"answer_1": "delegate"}).get_data(as_text=True)

    assert "Play again" in body


def test_a_review_the_game_cannot_deal_says_so(user_client, stub_deck, review):
    """No due word has an example to rebuild: the page says so and offers
    another game, not the topic picker."""
    stub_deck(cards=[dict(card, examples_en=[]) for card in DECK])
    body = user_client.get(
        "/games/rebuild_the_sentence/play?review=1").get_data(as_text=True)

    assert "None of the words due today can be played" in body
    assert 'href="/review">Try another game</a>' in body


def test_the_quiz_review_keeps_the_flag_through_its_form(user_client, review):
    """The quiz posts to `self_url`, which must carry the flag, or grading
    would read the whole deck and the language switch would leave the review."""
    body = user_client.get("/quiz?review=1&lang=ukr").get_data(as_text=True)
    # The quiz's own form, not the account-deletion form base.html carries.
    action = re.search(r'<form method="POST" action="(/quiz[^"]*)"', body).group(1)

    assert "review=1" in action
    assert "Choose the topics" not in body
