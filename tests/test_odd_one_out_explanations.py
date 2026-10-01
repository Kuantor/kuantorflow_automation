"""Odd one out's results say what each word means (kuantorflow#519).

Under every one of the four words: its English explanation, or -- where the
card has none -- a translation in the learner's **prioritised language**
(Settings > Quiz language), then the other visible one, labelled so it is not
read as English. Nothing at all when the card has neither.

The answer form carries words and topic names, never card ids (#269), so the
results page reads the cards. It reads **only the topics of the round's own
visible selection** that a question names: a topic name typed into the form
reads nothing and matches nothing.
"""

import pytest
from werkzeug.datastructures import MultiDict

import chat  # noqa: F401  (the app, for the fixtures)

PLAY = "/games/odd_one_out/play"


def card(i, word, topic, **extra):
    base = {"id": i, "word": word, "pos": "noun", "topic": topic,
            "explanation_en": None, "explanation_source": None,
            "translation_ukr": None, "translation_rus": None, "examples_en": []}
    base.update(extra)
    return base


CARDS = [
    card(1, "delegate", "Work", explanation_en="to give part of your work to someone else"),
    card(2, "resign", "Work", translation_ukr="звільнитися", translation_rus="уволиться"),
    card(3, "burnout", "Work", translation_rus="выгорание"),
    card(4, "commute", "Work"),
    card(10, "verdict", "Law", explanation_en="a decision reached by a jury",
         explanation_source="wiktionary"),
    card(11, "parole", "Law", explanation_en="early release from prison"),
    card(12, "arson", "Law", explanation_en="setting fire to property on purpose"),
    # Somebody else's private topic: in the stub's answer, never in the round.
    card(90, "verdict", "Secret", explanation_en="SECRET MEANING"),
]

QUESTION = [
    ("answer_1", "resign"), ("intruder_1", "verdict"),
    ("home_1", "Work"), ("from_1", "Law"),
    ("word_1", "delegate"), ("word_1", "resign"),
    ("word_1", "burnout"), ("word_1", "verdict"),
]


@pytest.fixture()
def deck(stub_deck):
    return stub_deck(cards=CARDS, topics=[("Work", 4), ("Law", 3)])


def _results(client, form=QUESTION):
    return client.post(PLAY, data=MultiDict(form)).get_data(as_text=True)


def _gloss_of(body, word):
    """The gloss text printed under `word`, or None."""
    import re
    item = re.search(r"<li[^>]*>\s*" + re.escape(word) + r"\b(.*?)</li>", body, re.S)
    assert item, f"{word} is not on the results page"
    # The language label is a span inside the gloss; fold it into the text
    # first, so the gloss's own closing tag is the next one.
    text = re.sub(r'<span class="odd-gloss-lang">(.*?)</span>', lambda m: m.group(1), item.group(1), flags=re.S)
    gloss = re.search(r'<span class="odd-gloss">(.*?)</span>', text, re.S)
    if not gloss:
        return None
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", gloss.group(1))).strip()


def test_every_word_shows_its_explanation(client, deck):
    body = _results(client)
    assert _gloss_of(body, "delegate") == "to give part of your work to someone else"
    assert _gloss_of(body, "verdict") == "a decision reached by a jury"


def test_no_explanation_means_the_prioritised_language(client, deck):
    """Quiz language is Ukrainian by default."""
    assert _gloss_of(_results(client), "resign") == "Ukrainian: звільнитися"


def test_the_other_visible_language_when_the_card_lacks_the_prioritised_one(client, deck):
    assert _gloss_of(_results(client), "burnout") == "Russian: выгорание"


def test_the_other_visible_language_when_the_prioritised_one_is_hidden(user_client, deck):
    user_client.post("/settings", json={"show_ukrainian": False})
    assert _gloss_of(_results(user_client), "resign") == "Russian: уволиться"


def test_russian_first_when_that_is_the_quiz_language(user_client, deck):
    user_client.post("/settings", json={"quiz_lang": "russian"})
    assert _gloss_of(_results(user_client), "resign") == "Russian: уволиться"


def test_nothing_when_there_is_nothing_to_say(client, deck):
    """`commute` has no explanation and no translation in either language."""
    form = [(k, "commute" if (k, v) == ("word_1", "burnout") else v) for k, v in QUESTION]
    assert _gloss_of(_results(client, form), "commute") is None


def test_both_languages_hidden_leaves_only_explanations(user_client, deck):
    user_client.post("/settings", json={"show_ukrainian": False, "show_russian": False})
    body = _results(user_client)
    assert _gloss_of(body, "resign") is None
    assert _gloss_of(body, "delegate") == "to give part of your work to someone else"


def test_a_wiktionary_explanation_keeps_its_credit(client, deck):
    body = _results(client)
    import re
    verdict = re.search(r"<li[^>]*>\s*verdict\b(.*?)</li>", body, re.S).group(1)
    assert "source-credit" in verdict and "Wiktionary" in verdict
    delegate = re.search(r"<li[^>]*>\s*delegate\b(.*?)</li>", body, re.S).group(1)
    assert "source-credit" not in delegate


def test_a_topic_typed_into_the_form_reads_and_matches_nothing(client, stub_deck,
                                                               monkeypatch):
    """`from_1` names a topic outside the round's visible selection. The read
    must not ask for it, and the match must not use a card from it even when
    the database hands one back."""
    stub_deck(cards=CARDS, topics=[("Work", 4), ("Law", 3)])
    asked = []
    import utils
    real = utils.get_flashcards_by_topics

    def record(topics, *a, **k):
        asked.append(list(topics))
        return real(topics, *a, **k)
    monkeypatch.setattr("utils.get_flashcards_by_topics", record)
    forged = [(k, "Secret" if k == "from_1" else v) for k, v in QUESTION]
    body = _results(client, forged)
    assert all("Secret" not in topics for topics in asked), asked
    assert "SECRET MEANING" not in body
    assert _gloss_of(body, "verdict") is None


def test_the_read_is_the_rounds_own(client, deck, monkeypatch):
    """#127's owner filter and the viewer travel with it, like the round's."""
    seen = []
    import utils
    real = utils.get_flashcards_by_topics

    def record(topics, owner_id=None, **kw):
        seen.append(sorted(kw))
        return real(topics, owner_id, **kw)
    monkeypatch.setattr("utils.get_flashcards_by_topics", record)
    _results(client)
    assert seen and all({"admin", "viewer_id"} <= set(s) for s in seen), seen


def test_a_database_failure_costs_the_glosses_not_the_page(client, deck, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("database down")
    monkeypatch.setattr("utils.get_flashcards_by_topics", broken)
    resp = client.post(PLAY, data=MultiDict(QUESTION))
    assert resp.status_code == 200
    assert "Score: 0 / 1" in resp.get_data(as_text=True)


def test_a_long_explanation_stays_two_lines(client):
    import re
    css = client.get("/static/css/style.css").get_data(as_text=True)
    rule = re.search(r"\.odd-gloss\s*\{([^}]*)\}", css)
    assert rule and re.search(r"line-clamp:\s*2", rule.group(1))
