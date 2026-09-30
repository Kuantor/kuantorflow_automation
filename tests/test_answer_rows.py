"""Answer options are whole rows you can hit on a phone (kuantorflow#502, item 1).

*Multiple choice*, *Odd one out* and *Real or fake* showed each answer as the
browser's bare 17px radio in a line 21px tall. Guidance for a finger is 44-48px
(Apple, Google), and WCAG 2.2's floor is 24px. Now every answer is a bordered
row at least 44px tall; the label already wraps its radio, so the whole row
selects it with no script.

The size is browser behaviour -- measured at 375px in the PR (every row 44px,
Real | Invented side by side, no sideways scroll). What the suite can hold is
the two things that produce it: the stylesheet's rules, and the markup that
makes the row the target.
"""

import re

import pytest

GAMES = {
    "multiple_choice": "/games/multiple_choice/play?words=3",
    "odd_one_out": "/games/odd_one_out/play?words=3",
    "real_or_fake": "/games/real_or_fake/play?words=3",
}


def _css(client):
    return client.get("/static/css/style.css").get_data(as_text=True)


def _declarations(css, selector):
    """Every declaration written for exactly `selector`, later ones winning.

    Comments are blanked first: this stylesheet documents nearly every rule,
    and a comment's text would otherwise be read as part of the selector.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector not in [s.strip() for s in selectors.split(",")]:
            continue
        for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body):
            found[prop.strip()] = value.strip()
    return found


def _rem(value):
    """A length in px; rem counts as 16px, as the site's root size is."""
    number = float(re.match(r"[\d.]+", value).group())
    return number * 16 if value.endswith("rem") else number


def test_every_answer_row_is_at_least_44px(client):
    row = _declarations(_css(client), ".verdict label")
    assert "min-height" in row, "an answer row has no minimum height"
    assert _rem(row["min-height"]) >= 44, row["min-height"]
    assert "border" in row and "padding" in row, \
        "the row must look like something to press, not a line of text"


def test_the_chosen_answer_shows_on_the_row(client):
    """Not only as a dot: the selected row changes colour and border."""
    chosen = _declarations(_css(client), ".verdict label:has(input:checked)")
    assert "background" in chosen and "border-color" in chosen, chosen


def test_keyboard_focus_shows_on_the_row(client):
    focused = _declarations(_css(client), ".verdict label:has(input:focus-visible)")
    assert "outline" in focused, "a keyboard user cannot see which answer is focused"


def test_the_radio_is_larger_and_in_the_sites_blue(client):
    radio = _declarations(_css(client), ".verdict input")
    assert _rem(radio["width"]) >= 20 and _rem(radio["height"]) >= 20, radio
    assert radio.get("accent-color") == "var(--blue)"


def test_four_answers_stack_and_two_sit_side_by_side(client):
    """#130's four words stack full-width; Real | Invented share a line on a
    phone (two 7rem bases fit 295px with the gap, where 9rem did not)."""
    css = _css(client)
    assert _declarations(css, ".verdict--stacked").get("flex-direction") == "column"
    basis = _declarations(css, ".verdict label")["flex"].split()[-1]
    assert 2 * _rem(basis) + 10 <= 295, f"Real | Invented would wrap at 375px ({basis})"


@pytest.mark.parametrize("game", sorted(GAMES))
def test_the_row_is_the_target(client, stub_deck, game):
    """Every radio sits inside its label, which is what makes the whole row
    select the answer without a line of script."""
    cards = [{"id": i, "word": w, "pos": "noun", "topic": t,
              "translation_ukr": f"переклад{i}", "translation_rus": f"перевод{i}",
              "explanation_en": f"meaning {i}", "examples_en": []}
             for i, (w, t) in enumerate(
                 [(w, "Work") for w in ("employer", "salary", "overtime",
                                        "deadline", "promotion", "colleague")]
                 + [(w, "Travel") for w in ("passport", "luggage", "boarding",
                                            "departure", "itinerary", "customs")])]
    stub_deck(cards=cards)
    body = client.get(GAMES[game] + "&topic=Work&topic=Travel").get_data(as_text=True)
    radios = re.findall(r'<input type="radio"[^>]*name="answer_', body)
    assert radios, f"{game} rendered no answers"
    inside = re.findall(r'<label>\s*<input type="radio"[^>]*name="answer_', body)
    assert len(inside) == len(radios), f"{game}: a radio outside its label"
