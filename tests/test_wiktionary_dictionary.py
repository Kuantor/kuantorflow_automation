"""Wiktionary as an explanatory dictionary, and the credit it comes with
(kuantorflow#390).

Two things arrive together here, and only one of them is a feature.

The **feature** is a third dictionary. It needs no key, so it is offered
wherever the app runs, and it answers from PythonAnywhere -- which is what #365
left worth having: Merriam-Webster is blocked there, so Oxford was the
deployment's only explanatory source, and a card's explanation is most of its
value to the learner this app is for.

The **obligation** is that its definitions are CC BY-SA 4.0. Copying one onto a
card is exactly what that licence permits, on three conditions: name the
source, link the entry, link the licence. Two consequences run through this
file:

* the text is stored **verbatim**. Rewording or summarising would make the card
  an *adaptation*, which share-alike binds; copying with a credit is what the
  licence plainly allows. So nothing in the path may tidy a definition up.
* a card records **which dictionary wrote its explanation**, because a credit
  needs something that remembers what to credit. And it is a fact about the
  sentence rather than about the card: an explanation somebody has rewritten is
  theirs, and leaving Wiktionary's name on it would put other people's names on
  their words -- the one misattribution the licence actually cares about.

Nothing here touches the network or a database.
"""

import pytest

import parsers
import utils

from conftest import fake_card_db, inserted_card, TEST_USER_ID


# One section, as the REST endpoint returns it: the definitions are HTML, and
# the part of speech is capitalised where Oxford's is not.
PAYLOAD = {"en": [{
    "partOfSpeech": "Noun",
    "definitions": [
        {"definition": 'The <a href="/wiki/handing_over">handing over</a> of '
                       'control over personal property.'},
        {"definition": "Bail."},
    ],
}]}


@pytest.fixture()
def wiktionary(monkeypatch):
    """What the endpoint answers, per requested title.

    Keyed on the title so the case retry can be seen: the returned list is the
    order the titles were tried in, which is the only way to tell a second
    request from a first one that happened to work.
    """
    asked = []

    class Response:
        def __init__(self, payload, status=200):
            self.payload = payload
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise parsers.requests.RequestException(str(self.status_code))

        def json(self):
            return self.payload

    def install(pages):
        def fake_get(url, headers=None, timeout=None, **kw):
            title = url.rsplit("/", 1)[-1]
            asked.append(title)
            if title not in pages:
                return Response({}, status=404)
            return Response(pages[title])

        monkeypatch.setattr(parsers.requests, "get", fake_get)
        return asked

    return install


# --- reading the endpoint ---------------------------------------------------

def test_the_answer_is_turned_into_the_entry_shape(wiktionary):
    """`(definitions, examples)` (#225), the only seam `lookup_word()` knows
    about. The part of speech is lower-cased on the way through: #228's
    POS_SYNONYMS matches on the label, and two providers cannot disagree about
    the wording until they agree about the case."""
    wiktionary({"bailment": PAYLOAD})

    definitions, examples = parsers._wiktionary_entry("bailment")

    assert list(definitions) == ["noun"]
    assert definitions["noun"] == [
        "The handing over of control over personal property.", "Bail."]
    assert examples == {}


def test_the_markup_is_stripped_and_the_words_are_not(wiktionary):
    """The definitions arrive as HTML, and turning that into text is the only
    change the licence leaves room for. A summariser here would quietly make
    every card an adaptation."""
    wiktionary({"bailment": PAYLOAD})

    definitions, _ = parsers._wiktionary_entry("bailment")

    assert "<a" not in definitions["noun"][0]
    assert "handing over of control" in definitions["noun"][0]


def test_the_usage_examples_come_with_the_definitions(wiktionary):
    """They are the editors' own sentences, under the same CC BY-SA as the
    definitions, so the credit already on the card covers them and there is
    nothing further to check per example."""
    wiktionary({"thrive": {"en": [{
        "partOfSpeech": "Verb",
        "definitions": [{
            "definition": "To grow or increase stature.",
            "examples": ["Not all animals thrive well in captivity."],
        }],
    }]}})

    definitions, examples = parsers._wiktionary_entry("thrive")

    assert definitions["verb"]
    assert examples["verb"] == ["Not all animals thrive well in captivity."]


def test_anything_that_looks_quoted_is_dropped(wiktionary):
    """The belt to the endpoint's braces. Wiktionary keeps usage examples and
    quotations apart in its own markup -- `#:` against `#*` with a `quote-book`
    template -- and this endpoint was measured returning only the first kind:
    `thrive` has 3 and 9 and answered with 3, `reluctant` 2 and 7 and answered
    with 2, and 91 examples over 30 seeded words held nothing quotation-shaped.

    That is observed rather than promised, and a quotation is somebody's book
    rather than the community's writing. So a year at the front -- how every
    citation opens -- means the example is not taken, and a change at their end
    costs examples instead of a licensing problem."""
    wiktionary({"resilient": {"en": [{
        "partOfSpeech": "Adjective",
        "definitions": [{
            "definition": "Returning quickly to its original shape.",
            "examples": ["1997, A Book Somebody Wrote, page 12: the resilient "
                         "tent poles sprang back into shape",
                         "The tent poles are resilient enough to bend."],
        }],
    }]}})

    _, examples = parsers._wiktionary_entry("resilient")

    assert examples["adjective"] == [
        "The tent poles are resilient enough to bend."]


def test_a_phrase_is_not_a_sentence(wiktionary):
    """`spotless shirt` and `sustainable economy` are true and useless: nothing
    to read, and #235 cannot gap a sentence that is not one. Measured over 91
    examples on 30 seeded words -- 70 are sentences and the 21 that are not are
    all fragments of this shape."""
    wiktionary({"spotless": {"en": [{
        "partOfSpeech": "Adjective",
        "definitions": [{
            "definition": "Having no spots.",
            "examples": ["spotless shirt", "to thrive upon hard work",
                         "He kept the kitchen spotless all week."],
        }],
    }]}})

    _, examples = parsers._wiktionary_entry("spotless")

    assert examples["adjective"] == [
        "He kept the kitchen spotless all week."]


def test_examples_are_capped_like_every_other_backend(wiktionary):
    wiktionary({"negotiate": {"en": [{
        "partOfSpeech": "Verb",
        "definitions": [{
            "definition": "To confer with others in order to reach a deal.",
            "examples": ["We negotiated the contract number %d today." % n
                         for n in range(10)],
        }],
    }]}})

    _, examples = parsers._wiktionary_entry("negotiate")

    assert len(examples["verb"]) == parsers.MAX_EXAMPLES


def test_examples_never_outlive_the_definition_they_came_with(wiktionary):
    """`lookup_word()` falls back to Reverso for **definitions alone**, so a
    card can carry Reverso's explanation -- and the credit that names Reverso.
    Wiktionary sentences surviving that swap would be its text on a card
    crediting somebody else, so a part of speech that produced no definition
    contributes no examples either."""
    wiktionary({"ghost": {"en": [{
        "partOfSpeech": "Verb",
        "definitions": [{
            "definition": "",
            "examples": ["He ghosted her after three dates entirely."],
        }],
    }]}})

    definitions, examples = parsers._wiktionary_entry("ghost")

    assert definitions == {}
    assert examples == {}


def test_a_word_nobody_has_is_not_a_failure(wiktionary):
    """#349's rule: a lookup with no explanation is still a lookup, and a 404
    is this endpoint's ordinary answer for a word it does not carry."""
    wiktionary({})

    assert parsers._wiktionary_entry("crasterrupt") == ({}, {})


def test_a_capitalised_word_is_retried_in_lower_case(wiktionary):
    """Wiktionary distinguishes `polish` from `Polish`, so a learner who typed
    a capital would otherwise be told nobody has the word. The retry costs a
    request only on a miss, the way Oxford's probing does."""
    asked = wiktionary({"bailment": PAYLOAD})

    definitions, _ = parsers._wiktionary_entry("Bailment")

    assert definitions["noun"], "the lower-case entry was never asked for"
    assert asked == ["Bailment", "bailment"]


def test_a_word_that_answers_is_asked_once(wiktionary):
    asked = wiktionary({"bailment": PAYLOAD})

    parsers._wiktionary_entry("bailment")

    assert asked == ["bailment"]


def test_senses_are_capped_like_every_other_backend(wiktionary):
    wiktionary({"run": {"en": [{
        "partOfSpeech": "Verb",
        "definitions": [{"definition": "sense %d" % n} for n in range(10)],
    }]}})

    definitions, _ = parsers._wiktionary_entry("run")

    assert len(definitions["verb"]) == parsers.MAX_DEFINITIONS


def test_two_etymologies_are_one_card(wiktionary):
    """A word with two histories has two sections for the same part of speech,
    and they are the same card's senses -- so the cap is per part of speech
    rather than per section, and neither section is thrown away."""
    wiktionary({"lead": {"en": [
        {"partOfSpeech": "Noun", "definitions": [{"definition": "a metal"}]},
        {"partOfSpeech": "Noun",
         "definitions": [{"definition": "a first place"}]},
    ]}})

    definitions, _ = parsers._wiktionary_entry("lead")

    assert definitions["noun"] == ["a metal", "a first place"]


# --- the registry -----------------------------------------------------------

def test_it_needs_no_key_so_it_is_offered_wherever_the_app_runs(monkeypatch):
    """Which is the whole point of adding it: #365 left Oxford as the
    deployment's single explanatory source, and a second one needing a key
    nobody has would not have changed that."""
    monkeypatch.delenv("MERRIAM_WEBSTER_API_KEY", raising=False)
    entry = parsers._dictionary_by_slug("wiktionary")

    assert entry.key_env is None
    assert entry in parsers.available_dictionaries()


def test_the_fetcher_is_held_by_name():
    """#353's scar: a registry holding the function object captures it at
    import, and every test that patches a backend silently reaches the real one
    -- which for this backend means a live request per test."""
    entry = parsers._dictionary_by_slug("wiktionary")

    assert isinstance(entry.fetch_name, str)
    assert entry.fetch is parsers._wiktionary_entry


def test_choosing_it_dispatches_to_it():
    assert parsers._dictionary_backend("wiktionary") \
        is parsers._wiktionary_entry


def test_the_setting_accepts_it():
    import settings_store

    assert "wiktionary" in settings_store.CHOICES["explanatory_dictionary"]


# --- the credit, from the lookup to the card --------------------------------

@pytest.fixture()
def silent_translators(monkeypatch):
    """No translator answers, so the cards come from the dictionary (#349).

    The shape #348 proved is real, and it keeps these tests to one provider's
    behaviour instead of two.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(parsers, "_claude_dictionary", lambda word, code: {})


@pytest.fixture(autouse=True)
def no_reverso(monkeypatch):
    """Reverso answers when the chosen dictionary has nothing, and it is a real
    request. Silenced by default; the test that cares about it says so."""
    monkeypatch.setattr(parsers, "_fetch_definitions", lambda word: {})


def test_the_card_says_which_dictionary_explained_it(action_logs,
                                                     silent_translators,
                                                     monkeypatch):
    monkeypatch.setattr(parsers, "_wiktionary_entry",
                        lambda word: ({"noun": ["a handing over"]}, {}))

    cards = parsers.lookup_word("bailment",
                                explanatory_dictionary="wiktionary")

    assert [c["explanation_source"] for c in cards] == ["wiktionary"]


def test_a_card_with_no_explanation_is_credited_to_nobody(action_logs,
                                                          monkeypatch):
    """The credit travels with the text and never on its own. A card the
    dictionary could not explain keeps its translations and claims nothing."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    monkeypatch.setattr(parsers, "_claude_dictionary",
                        lambda word, code: {"noun": ["zastava"]})
    monkeypatch.setattr(parsers, "_wiktionary_entry", lambda word: ({}, {}))

    cards = parsers.lookup_word("bailment",
                                explanatory_dictionary="wiktionary")

    assert cards[0].get("explanation_source") is None


def test_the_credit_names_the_provider_that_answered(action_logs,
                                                     silent_translators,
                                                     monkeypatch):
    """Not the one that was asked. Reverso still answers when the chosen
    dictionary has nothing, and a card credited to a provider that returned
    nothing is a wrong credit rather than a missing one."""
    monkeypatch.setattr(parsers, "_wiktionary_entry", lambda word: ({}, {}))
    monkeypatch.setattr(parsers, "_fetch_definitions",
                        lambda word: {"noun": ["a handing over"]})

    cards = parsers.lookup_word("bailment",
                                explanatory_dictionary="wiktionary")

    assert cards[0]["explanation_source"] == "reverso"


# --- what the database does with it -----------------------------------------

STORED = {"id": 5, "word": "bailment", "pos": "noun",
          "explanation_en": "a handing over", "examples_en": None,
          "translation_ukr": None, "examples_ukr": None,
          "translation_rus": None, "examples_rus": None}


def _update(cursor):
    return next((q, p) for q, p in cursor.queries if q.startswith("UPDATE"))


def test_the_credit_is_written_with_the_card(monkeypatch):
    cursor, _ = fake_card_db(monkeypatch)
    utils.save_flashcard({"word": "bailment", "pos": "noun", "topic": "Law",
                          "explanation_en": "a handing over",
                          "explanation_source": "wiktionary"})

    query, params = inserted_card(cursor)
    columns = query.split("(", 1)[1].split(")", 1)[0].split(", ")

    assert "explanation_source" in columns
    assert params[columns.index("explanation_source")] == "wiktionary"


def test_a_rewritten_explanation_loses_its_credit(monkeypatch):
    """The rule the column exists for. The sentence is now the learner's, and a
    credit left on it would attribute their words to the people who wrote the
    original."""
    cursor, _ = fake_card_db(monkeypatch, card=dict(STORED))

    outcome, changed = utils.update_flashcard(
        5, {"explanation_en": "when you leave your coat with someone"},
        owner_id=TEST_USER_ID)

    query, params = _update(cursor)
    assignments = query.split("WHERE")[0].strip().split(", ")
    assert "explanation_source = %s" in assignments
    assert params[assignments.index("explanation_source = %s")] is None
    assert changed == ["explanation_en"], (
        "the log records what somebody edited, and nobody edited this")


def test_rewriting_the_examples_drops_only_their_credit(monkeypatch):
    """The mirror rule, and the reason there are two columns. A learner who
    adds a sentence of their own to the dictionary's examples has not touched
    the definition, so its credit stands and theirs goes."""
    cursor, _ = fake_card_db(monkeypatch, card=dict(
        STORED, examples_en='["Some software runs on one platform only."]'))

    utils.update_flashcard(
        5, {"examples_en": ["Some software runs on one platform only. test2"]},
        owner_id=TEST_USER_ID)

    query, _ = _update(cursor)
    assert "examples_source = %s" in query
    assert "explanation_source" not in query


def test_rewriting_the_explanation_drops_only_its_credit(monkeypatch):
    """And the other way about: the dictionary's sentences are still the
    dictionary's when somebody rewrites the definition above them. One column
    could only ever have been right about one of these two tests."""
    cursor, _ = fake_card_db(monkeypatch, card=dict(
        STORED, examples_en='["Some software runs on one platform only."]'))

    utils.update_flashcard(5, {"explanation_en": "programs, basically"},
                           owner_id=TEST_USER_ID)

    query, _ = _update(cursor)
    assert "explanation_source = %s" in query
    assert "examples_source" not in query


def test_editing_something_else_leaves_the_credit_alone(monkeypatch):
    """An explanation that did not change is still the dictionary's sentence,
    so a learner fixing a translation must not silently strip its credit."""
    cursor, _ = fake_card_db(monkeypatch, card=dict(STORED))

    utils.update_flashcard(5, {"translation_ukr": "zastava"},
                           owner_id=TEST_USER_ID)

    query, _ = _update(cursor)
    assert "explanation_source" not in query
    assert "examples_source" not in query


def test_a_new_explanation_may_bring_its_own_credit(monkeypatch):
    """#191's dialog fills that box from a fresh lookup, so the text really can
    be a dictionary's -- and then it is credited rather than orphaned."""
    cursor, _ = fake_card_db(monkeypatch, card=dict(STORED))

    utils.update_flashcard(5, {"explanation_en": "the handing over of goods",
                               "explanation_source": "wiktionary"},
                           owner_id=TEST_USER_ID)

    query, params = _update(cursor)
    assert "wiktionary" in params


def test_a_gap_filled_by_a_later_lookup_is_credited(monkeypatch):
    """#349's repair path writes an explanation, so it writes a credit."""
    cursor, _ = fake_card_db(monkeypatch, duplicate={
        "id": 7, "explanation_en": None, "examples_en": None,
        "translation_ukr": "zastava", "examples_ukr": None,
        "translation_rus": None, "examples_rus": None})

    filled = utils.fill_missing_fields({
        "word": "bailment", "pos": "noun",
        "explanation_en": "a handing over",
        "explanation_source": "wiktionary"})

    query, params = _update(cursor)
    assert "explanation_en" in filled
    assert "explanation_source = %s" in query
    assert "wiktionary" in params


def test_a_credit_is_never_filled_on_its_own(monkeypatch):
    """The sharp edge of a repair that fills only empty columns: a card that
    already holds Oxford's sentence and no credit must not be handed
    Wiktionary's name for it."""
    cursor, _ = fake_card_db(monkeypatch, duplicate={
        "id": 7, "explanation_en": "a handing over", "examples_en": None,
        "translation_ukr": None, "examples_ukr": None,
        "translation_rus": None, "examples_rus": None})

    utils.fill_missing_fields({
        "word": "bailment", "pos": "noun",
        "explanation_en": "a different sentence entirely",
        "explanation_source": "wiktionary",
        "translation_ukr": "zastava"})

    query, _ = _update(cursor)
    assert "explanation_source" not in query


# --- the route --------------------------------------------------------------

def test_a_credit_the_registry_does_not_know_is_no_credit(user_client, saved):
    """It arrives in a form field like everything else, and a credit is a claim
    about somebody else's writing. An unrecognised one becomes nothing, which
    is the safe direction: a missing credit shows nothing, where a wrong one
    puts a dictionary's name on a sentence it never wrote."""
    user_client.post("/cards/add", data={
        "word": "bailment", "pos": "noun", "topic": "Law",
        "explanation_en": "a handing over",
        "explanation_source": "<script>alert(1)</script>"})

    assert saved[0]["explanation_source"] is None


def test_the_popup_carries_the_credit_to_the_save(user_client, saved):
    user_client.post("/cards/add", data={
        "word": "bailment", "pos": "noun", "topic": "Law",
        "explanation_en": "a handing over",
        "explanation_source": "wiktionary"})

    assert saved[0]["explanation_source"] == "wiktionary"


# --- and what the learner sees ----------------------------------------------

CREDITED = {"id": 1, "word": "bailment", "pos": "noun", "topic": "Law",
            "explanation_en": "a handing over",
            "explanation_source": "wiktionary"}
UNCREDITED = {"id": 2, "word": "estoppel", "pos": "noun", "topic": "Law",
              "explanation_en": "a legal principle",
              "explanation_source": "oxford"}


def test_the_card_page_credits_the_definition(user_client, stub_deck):
    stub_deck(cards=[CREDITED])

    body = user_client.get("/flashcards/Law").get_data(as_text=True)

    assert "source-credit" in body
    assert "https://en.wiktionary.org/wiki/bailment#English" in body
    assert "creativecommons.org/licenses/by-sa/4.0" in body
    assert "CC BY-SA 4.0" in body


def test_the_card_page_credits_each_half_where_it_belongs(user_client,
                                                          stub_deck):
    """The case that prompted the second column, seen from the page. A learner
    who added a sentence of their own to the dictionary's examples keeps the
    definition's credit and loses theirs -- and a single line under the whole
    English block would then be claiming their words too. So the surviving
    credit sits against the half it actually covers."""
    stub_deck(cards=[dict(SENTENCED, examples_source=None)])

    body = " ".join(user_client.get("/flashcards/Law")
                    .get_data(as_text=True).split())

    assert body.count("source-credit") == 1
    assert body.index("source-credit") < body.index("English examples"), (
        "the credit belongs above the examples it no longer covers")


def test_a_fully_credited_card_says_so_once(user_client, stub_deck):
    """Both halves the dictionary's is the ordinary case, and it reads as one
    footnote to the English block rather than as the same line twice."""
    stub_deck(cards=[SENTENCED])

    body = " ".join(user_client.get("/flashcards/Law")
                    .get_data(as_text=True).split())

    assert body.count("source-credit") == 1
    assert body.index("English examples") < body.index("source-credit")


def test_the_deck_credits_it_too(user_client, stub_deck):
    """The credit travels with the text, to every surface that shows one. A
    page rendering the definition without it is the licence not being met,
    however many other pages get it right."""
    stub_deck(cards=[CREDITED])

    body = user_client.get("/deck/Law").get_data(as_text=True)

    assert "source-credit" in body


def test_a_link_on_a_card_face_is_a_control(app_module):
    """Measured in a browser, not here: clicking the credit on the flip deck
    opened the entry **and turned the card over behind it**, because
    `isControl()` knew about inputs, labels and buttons and not about links.

    pytest cannot press a link, so this guards the selector instead -- which is
    worth doing precisely because the failure was invisible to a green suite.
    Any future link on a face has the same problem.
    """
    deck = (app_module.app.jinja_env.get_template("deck.html")
            .filename)
    source = open(deck, encoding="utf-8").read()

    assert 'closest("input, label, button, a")' in source


SENTENCED = dict(CREDITED, id=4, word="thrive",
                 explanation_en="To grow vigorously.",
                 examples_source="wiktionary",
                 examples_en=["Not all animals thrive well in captivity.",
                              "Since expanding, the business has thrived."])


def test_the_sentence_game_credits_the_sentence_it_shuffled(user_client,
                                                            stub_deck):
    """*Rebuild the sentence* is the case that makes the credit a fact about
    the **text** rather than about the explanation it arrived beside: the whole
    question is a card's example, and the page shows no definition at all. A
    credit rendered only next to explanations would leave this page showing
    somebody's sentence with nothing saying whose."""
    stub_deck(cards=[SENTENCED], topics=[("Law", 1)])

    body = user_client.get(
        "/games/rebuild_the_sentence/play?topic=Law").get_data(as_text=True)

    assert "source-credit" in body


def test_the_gap_game_credits_it_even_with_no_definition_on_the_back(
        user_client, stub_deck):
    """#235 cuts a word out of one of the card's own examples, so the text
    needing the credit is on the front. The back carries a translation instead
    when the card has no explanation, and the credit must not go with it."""
    stub_deck(cards=[dict(SENTENCED, explanation_en=None,
                          translation_ukr="procvitaty")], topics=[("Law", 1)])

    body = user_client.get(
        "/games/fill_the_gap/play?topic=Law").get_data(as_text=True)

    assert "source-credit" in body


def test_the_review_popup_credits_below_both_boxes(user_client, monkeypatch,
                                                   app_module):
    """Between the two, it reads as covering the definition alone -- and where
    Wiktionary answered it wrote the sentences underneath as well."""
    monkeypatch.setattr(app_module, "lookup_word", lambda word, topic=None, **kw: [
        dict(SENTENCED, topic=topic)])

    body = user_client.post("/", data={"action": "parse_word", "word": "thrive",
                                       "topic": "Law", "force_lookup": "1"}
                            ).get_data(as_text=True)

    assert body.index('name="examples_en"') < body.index("source-credit"), (
        "the credit is above the examples it also covers")


def test_the_sentence_game_ignores_the_other_credit(user_client, stub_deck):
    """The scoping rule, and the reason `fields` exists. A learner who rewrote
    these sentences kept the dictionary's definition, so the card still carries
    an explanation credit -- and this page, which shows no definition, must not
    render it over words the learner wrote."""
    stub_deck(cards=[dict(SENTENCED, examples_source=None)],
              topics=[("Law", 1)])

    body = user_client.get(
        "/games/rebuild_the_sentence/play?topic=Law").get_data(as_text=True)

    assert "source-credit" not in body


def test_a_definition_from_elsewhere_is_credited_to_nobody(user_client,
                                                           stub_deck):
    """Oxford asks for nothing, and a card written before the column existed
    has nothing to say. Neither may be given Wiktionary's credit."""
    stub_deck(cards=[UNCREDITED, dict(UNCREDITED, id=3, word="novation",
                                      explanation_source=None)])

    body = user_client.get("/flashcards/Law").get_data(as_text=True)

    assert "source-credit" not in body
