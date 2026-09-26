"""The games and text generation have logs of their own (kuantorflow#448).

Two things were in the wrong file, or in none.

**The nine games wrote nothing.** `rounds.py` held ten activities and a single
`applog` call, and that one was the Wiktionary vet rather than anything about a
round, so "what do people actually play?" could not be answered from any log.
Every round now leaves one `ROUND` line in `games.log`.

**Text generation wrote into `dict.log`**, a file named for dictionary lookups,
and with no `user=` -- the only outward-going logger without one. It now writes
to `gen_texts.log`, and says who asked.

Four properties are pinned, and three of them fail silently:

**Every game logs, including the two the obvious seam misses.** A line hung on
`rounds._graded_answers()` would miss *Odd one out* and *Real or fake*, which
never reach it -- one posts indexes, the other invented words with no row
behind them. Both are played for real here, beside one of the shared-URL games
and the quiz, which is its own call site. A structural test then asks every
round function for its call, so a tenth game cannot arrive without one.

**The logged score is the displayed score.** Counted off the same results the
page renders, and asserted against the "Score: X / Y" the learner actually saw.

**`dict.log` holds dictionary traffic and nothing else.** The done-when of the
ticket, and the one that needed more than the ticket named: refusals of chat,
recap and upload were in `dict.log` too, and have each gone to the log of the
thing refused.

**A log call must not break the request.** The first cut passed `action=`
through `_write()`, whose own second parameter is called `action`, and every
refusal raised `TypeError` before the error-swallowing body ran. Twenty tests
caught it; one here names it.
"""

import inspect
import re

import pytest

import applog


def _lines(logs, name, action=None):
    path = logs / f"{name}.log"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [l for l in lines if action is None or f" {action} " in f"{l} "]


def _field(line, key):
    match = re.search(rf"\b{key}=(\S+)", line)
    return match.group(1) if match else None


# --- a round of each call-site shape ----------------------------------------

SCRAMBLED = [
    {"id": 1, "word": "delegate", "topic": "Work"},
    {"id": 2, "word": "resign", "topic": "Work"},
    {"id": 3, "word": "burnout", "topic": "Work"},
]


def test_a_shared_url_game_leaves_one_round_line(client, stub_deck,
                                                 action_logs):
    """Scrambled stands for the eight that share `/games/<slug>/play`."""
    stub_deck(cards=SCRAMBLED)
    client.post("/games/scrambled/play?topic=Work",
                data={"answer_1": "delegate", "answer_2": "resign",
                      "answer_3": "wrong"})

    rounds = _lines(action_logs, "games", "ROUND")
    assert len(rounds) == 1, rounds
    line = rounds[0]
    assert _field(line, "game") == "scrambled"
    assert _field(line, "stage") == "graded"
    assert _field(line, "topics") == "1"
    assert _field(line, "asked") == "3"
    assert _field(line, "correct") == "2"
    assert _field(line, "user") == "anonymous"


def test_the_logged_score_is_the_score_the_learner_saw(client, stub_deck,
                                                       action_logs):
    """Counted off the results the page renders, so the two cannot differ --
    asserted against the page rather than against arithmetic."""
    stub_deck(cards=SCRAMBLED)
    body = client.post("/games/scrambled/play?topic=Work",
                       data={"answer_1": "delegate", "answer_2": "nope",
                             "answer_3": "burnout"}).get_data(as_text=True)
    shown = re.search(r"Score: (\d+) / (\d+)", body)
    line = _lines(action_logs, "games", "ROUND")[0]

    assert shown, "the results page stopped showing a score"
    assert (_field(line, "correct"), _field(line, "asked")) == shown.groups()


QUIZ = [
    {"id": 1, "word": "resign", "pos": "verb", "topic": "Work",
     "translation_ukr": "звільнятися", "translation_rus": "увольняться"},
    {"id": 2, "word": "commute", "pos": "noun", "topic": "Work",
     "translation_ukr": "поїздка", "translation_rus": "поездка"},
]


def test_the_quiz_leaves_a_round_line_too(client, stub_deck, action_logs):
    """Its own call site: the quiz keeps its own URLs (#250) and grades in
    `_run_quiz()` rather than through `game_play()`."""
    stub_deck(cards=QUIZ)
    client.post("/quiz?topic=Work&lang=ukr",
                data={"answer_1": "звільнятися", "answer_2": ""})

    line = _lines(action_logs, "games", "ROUND")[0]
    assert _field(line, "game") == "quiz"
    assert _field(line, "asked") == "2"
    assert _field(line, "correct") == "1"


def test_odd_one_out_logs_though_it_never_reaches_graded_answers(
        client, stub_deck, action_logs):
    """The reason the line is not hung on `_graded_answers()`. This round
    posts group indexes and no card id, so a line there would never fire."""
    from werkzeug.datastructures import MultiDict
    # Two topics, because the game needs them: an intruder is a word from a
    # *different* topic, so one topic is a round it cannot deal and the POST
    # would answer with the cannot-run page instead of grading.
    stub_deck(cards=[{"id": i, "word": w, "topic": "Work"}
                     for i, w in enumerate(["delegate", "resign", "burnout",
                                            "commute"], 1)]
                   + [{"id": 10, "word": "verdict", "topic": "Law"}],
              topics=[("Work", 4), ("Law", 1)])
    client.post("/games/odd_one_out/play?topic=Work&topic=Law",
                data=MultiDict([("answer_1", "verdict"),
                                ("intruder_1", "verdict")]))

    line = _lines(action_logs, "games", "ROUND")[0]
    assert _field(line, "game") == "odd_one_out"
    assert _field(line, "stage") == "graded"


def test_real_or_fake_logs_though_it_never_reaches_graded_answers(
        client, stub_deck, action_logs):
    """The other one: its items are invented words, with no row behind them."""
    stub_deck(cards=[{"id": 1, "word": "verdict", "topic": "Crime"}])
    client.post("/games/real_or_fake/play?topic=Crime",
                data={"item_1": "verdict", "real_1": "1", "answer_1": "real",
                      "item_2": "blorvent", "real_2": "0", "answer_2": "real"})

    line = _lines(action_logs, "games", "ROUND")[0]
    assert _field(line, "game") == "real_or_fake"
    assert _field(line, "asked") == "2"
    assert _field(line, "correct") == "1"


def test_fill_the_gap_logs_the_deal_and_claims_no_score(client, stub_deck,
                                                        action_logs):
    """It never submits -- the score is the learner's own ticking, held in the
    page -- so the deal is the only moment the server sees. `correct` is
    **absent**, not zero: nobody measured it, and a zero would be a claim."""
    stub_deck(cards=[{"id": i, "word": w, "topic": "Work",
                      "examples_en": [f"She had to {w} the task."]}
                     for i, w in enumerate(["delegate", "resign"], 1)])
    client.get("/games/fill_the_gap/play?topic=Work")

    line = _lines(action_logs, "games", "ROUND")[0]
    assert _field(line, "game") == "fill_the_gap"
    assert _field(line, "stage") == "dealt"
    assert _field(line, "correct") is None, line


def test_dealing_a_graded_game_writes_nothing(client, stub_deck, action_logs):
    """A graded game logs when it is graded. Logging the deal as well would
    count every abandoned round, and make one round two lines."""
    stub_deck(cards=SCRAMBLED)
    client.get("/games/scrambled/play?topic=Work")

    assert _lines(action_logs, "games", "ROUND") == []


def test_the_round_names_a_signed_in_player(user_client, stub_deck,
                                            action_logs):
    stub_deck(cards=SCRAMBLED)
    user_client.post("/games/scrambled/play?topic=Work",
                     data={"answer_1": "delegate"})

    line = _lines(action_logs, "games", "ROUND")[0]
    assert _field(line, "user") == "test.user@gmail.com"


# --- no game can arrive without a line --------------------------------------

def test_every_round_function_logs_its_round(app_module):
    """Structural, and deliberately so: the four rounds above are played for
    real, and this covers the other five plus any tenth. A new game is one
    entry in `GAME_ROUNDS`; this is what notices it arrived without a line.

    *Read a text* is the exception by design -- it writes a GENERATE line to
    `gen_texts.log` from `textgen.generate()`, not a ROUND line."""
    import rounds

    missing = []
    for slug, view in rounds.GAME_ROUNDS.items():
        if slug == "read_a_text":
            continue
        if "_round_played(" not in inspect.getsource(view):
            missing.append(slug)

    assert missing == [], f"these rounds log nothing: {missing}"
    assert "_round_played(" in inspect.getsource(rounds._run_quiz)


def test_there_are_nine_games_to_log(app_module):
    """The control for the case above: if `GAME_ROUNDS` shrank, the loop would
    pass over fewer rounds and prove less, with nothing to say so."""
    import rounds

    logged = set(rounds.GAME_ROUNDS) - {"read_a_text"} | {"quiz"}
    assert len(logged) == 9, sorted(logged)


# --- text generation ---------------------------------------------------------

def test_a_generation_goes_to_its_own_log_and_names_the_player(action_logs):
    applog.text_generated(model="m", supplied=5, used=4, length=150,
                          elapsed_ms=900, user="a.learner@example.com")

    line = _lines(action_logs, "gen_texts", "GENERATE")[0]
    assert _field(line, "user") == "a.learner@example.com"
    assert _lines(action_logs, "dict", "GENERATE") == []


def test_the_route_hands_the_player_down_to_textgen(app_module):
    """`textgen.py` has no request context by design, so the actor has to be
    handed down -- and a call that forgot to would still generate, still log,
    and log everybody as anonymous."""
    import rounds

    source = inspect.getsource(rounds._read_a_text_round)
    call = source[source.index("textgen.generate("):]
    call = call[:call.index(")") + 1]
    assert "user=" in call, call


# --- dict.log holds dictionary traffic and nothing else ---------------------

@pytest.mark.parametrize("action,log", [
    ("recap", "mykola"),
    ("upload", "parsed_files"),
])
def test_each_account_ceiling_is_logged_where_its_feature_lives(
        app_module, action, log):
    import web
    assert web._ACCOUNT_ACTION_LOGS.get(action) == log


def test_every_account_action_has_a_log(app_module):
    """A misspelt key would not fail -- it would quietly fall back to
    `dict.log`. So the map is asserted to cover exactly what goes through
    `account_refusal()`."""
    import utils, web
    assert set(web._ACCOUNT_ACTION_LOGS) == {utils.RECAP, utils.UPLOAD}


def test_a_chat_refusal_is_not_in_dict_log(client, app_module, monkeypatch,
                                           action_logs):
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    with client.session_transaction() as sess:
        sess["anon_messages"] = 10_000
    client.post("/mykola/chat", json={"question": "hello"})

    assert _lines(action_logs, "mykola", "LIMIT"), "the refusal left no line"
    assert _lines(action_logs, "dict", "LIMIT") == []


def test_a_generation_refusal_is_not_in_dict_log(action_logs):
    applog.anonymous_limit_hit("generate", 1, 1, log=applog.GEN_TEXTS,
                               action="generate")

    assert _lines(action_logs, "gen_texts", "LIMIT")
    assert _lines(action_logs, "dict", "LIMIT") == []


def test_a_lookup_refusal_stays_in_dict_log(action_logs):
    """The control: lookups *are* dictionary traffic, and moving everything
    out would satisfy "nothing else" by emptying the file."""
    applog.anonymous_limit_hit("lookup", 3, 3, action="lookup")

    line = _lines(action_logs, "dict", "LIMIT")[0]
    assert _field(line, "feature") == "lookup"


def test_the_invented_word_vet_follows_its_round(action_logs):
    """Called only from *Real or fake*, about a round -- so into `games.log`."""
    applog.invented_vetted(10, 2, words=["defence", "edition"])

    assert _lines(action_logs, "games", "INVENTED-VETTED")
    assert _lines(action_logs, "cards", "INVENTED-VETTED") == []


def test_a_failed_wiktionary_batch_is_dictionary_traffic(action_logs):
    """Not a games line: `wiktionary_pages()` serves #406's topic builder as
    well, so a batch that failed is a dictionary that did not answer."""
    applog.word_vet_failed(12, RuntimeError("timeout"))

    assert _lines(action_logs, "dict", "WORD-VET-FAILED")
    assert _lines(action_logs, "games", "WORD-VET-FAILED") == []


# --- a log call must never break the request --------------------------------

def test_naming_the_feature_does_not_raise(action_logs):
    """`_write()`'s own second parameter is `action`. The first cut passed
    `action=` through it, which raises `TypeError` *at the call* -- before the
    body that swallows errors -- and took down every refusal it touched."""
    applog.anonymous_limit_hit("user", 5, 5, log=applog.MYKOLA, action="recap")

    line = _lines(action_logs, "mykola", "LIMIT")[0]
    assert _field(line, "feature") == "recap"
