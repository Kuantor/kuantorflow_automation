"""One event, one log line, and no field name that can raise (kuantorflow#557, #558).

**#557.** `applog._value()` quoted a value holding whitespace, but a line
break inside the quotes still ended the line: `lookup_started("two" + LF +
"lines")` wrote two lines to `dict.log`, the second with no timestamp and no
action. Every reader that counts one event per line -- the daily report,
`weekly_numbers.py` -- miscounted it. A break is now written escaped, so the
line stays one line and the text stays greppable; and the two lookup routes
squash whitespace inside the word, since a word never holds a line break.

**#558.** `_write(name, action, **fields)` swallows every error, but a field
called `action=` or `name=` raised `TypeError` while Python bound the
arguments, before the `try` began. It shipped for one commit in #448 and broke
every refusal it touched. Both parameters are positional-only now, so those
names are ordinary fields.
"""

import pytest

import applog

LF, CR, BS = chr(10), chr(13), chr(92)

# Every character `str.splitlines()` splits on: the readers use it, and a
# file opened in text mode also ends a line at a bare CR.
BREAKS = [LF, CR, CR + LF, chr(0x0b), chr(0x0c), chr(0x1c), chr(0x1d),
          chr(0x1e), chr(0x85), chr(0x2028), chr(0x2029)]


def _raw(directory, name):
    path = directory / f"{name}.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _lines(directory, name):
    return [line for line in _raw(directory, name).splitlines() if line]


# --- #557: a line break stays inside its line --------------------------------

@pytest.mark.parametrize("brk", BREAKS, ids=[f"U+{ord(b[0]):04X}{'+LF' if len(b) > 1 else ''}"
                                             for b in BREAKS])
def test_a_line_break_in_a_value_stays_on_one_line(action_logs, brk):
    applog.card_created({"word": "two" + brk + "lines", "topic": "t"},
                        source="test")

    (line,) = _lines(action_logs, "cards")
    assert " CREATE " in line and "topic=t" in line


def test_the_escaped_break_is_still_findable(action_logs):
    applog.card_created({"word": "two" + LF + "lines", "topic": "t"}, source="test")

    assert "two" + BS + "nlines" in _raw(action_logs, "cards")


def test_a_carriage_return_is_written_as_one_too(action_logs):
    applog.card_created({"word": "two" + CR + "lines", "topic": "t"}, source="test")

    assert "two" + BS + "rlines" in _raw(action_logs, "cards")


def test_a_value_with_plain_spaces_is_written_as_before(action_logs):
    applog.card_created({"word": "lucid dream", "topic": "t"}, source="review popup")

    line = _lines(action_logs, "cards")[0]
    assert "word='lucid dream'" in line and "source='review popup'" in line


def test_a_quote_is_still_escaped(action_logs):
    applog.card_created({"word": "rock 'n' roll", "topic": "t"}, source="test")

    assert "word='rock " + BS + "'n" + BS + "' roll'" in _lines(action_logs, "cards")[0]


# --- #557: the lookup routes squash a break inside the word -------------------

@pytest.fixture()
def looked_up(monkeypatch):
    words = []
    monkeypatch.setattr("parsers.lookup_word",
                        lambda word, *a, **k: words.append(word) or [])
    return words


def test_the_home_page_lookup_squashes_the_word(client, saved, looked_up, action_logs):
    client.post("/", data={"action": "parse_word", "topic": "vocab",
                           "word": " ice" + CR + LF + "  cream "})

    assert looked_up == ["ice cream"]
    lines = [l for l in _lines(action_logs, "dict") if " LOOKUP " in l]
    assert len(lines) == 1 and "word='ice cream'" in lines[0]


def test_the_dialog_lookup_squashes_the_word(user_client, looked_up):
    user_client.post("/lookup.json", json={"word": "ice" + LF + "cream"})

    assert looked_up == ["ice cream"]


# --- #558: action= and name= are ordinary fields ----------------------------

@pytest.mark.parametrize("field", ["action", "name"])
def test_a_field_named_like_a_parameter_is_written(action_logs, field):
    applog._write(applog.CARDS, "LIMIT", **{field: "chat"}, used=40)

    (line,) = _lines(action_logs, "cards")
    assert line.endswith(f"LIMIT {field}=chat used=40")
