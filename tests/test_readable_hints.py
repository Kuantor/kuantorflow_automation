"""Hint text is readable over the photograph (kuantorflow#502, item 3).

Every panel is translucent white over a photograph of London, and hint text is
`--muted`. At `--panel-alpha: 0.72` and `--muted: #5b6b7a` it measured 2.76:1
over the photo's darkest area and 3.66:1 over a typical one -- below WCAG AA's
4.5:1 for body-size text. Now 0.80 and #4a5866.

**Computed, not restated.** Every number here is read from `style.css` and the
contrast is worked out from it, so a later edit to either value is checked
against the rule rather than against a copy of today's numbers.

**Against black, not against the photo.** A panel can sit over any part of the
picture, and the picture can be replaced. Pure black is the worst backdrop that
exists, so passing there means passing everywhere; the photo's own darkest
pixel (2, 0, 7) is barely lighter.
"""

import re

import pytest

AA_BODY = 4.5


def _root_vars(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found = {}
    for body in re.findall(r":root\s*\{([^}]*)\}", css):
        found.update((k, v.strip()) for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))
    return found


def _hex(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(rgb):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _white_over_black(alpha):
    return (alpha * 255,) * 3


@pytest.mark.parametrize("surface", ["--panel-alpha", "--flashcard-alpha", "--widget-alpha"])
def test_hint_text_passes_on_every_translucent_surface(client, surface):
    """The main panels, the topic page's cards and Mykola's panel all show
    `--muted` text over the photograph, each at its own opacity."""
    root = _root_vars(client)
    alpha = float(root[surface])
    ratio = _contrast(_hex(root["--muted"]), _white_over_black(alpha))
    assert ratio >= AA_BODY, (
        f"hint text on {surface} ({alpha}) is {ratio:.2f}:1 over a dark backdrop")


def test_body_text_passes_too(client):
    root = _root_vars(client)
    alpha = float(root["--panel-alpha"])
    assert _contrast(_hex(root["--ink"]), _white_over_black(alpha)) >= AA_BODY


def test_a_hint_still_looks_like_a_hint(client):
    """Darkening `--muted` until it passes is easy; darkening it until it is
    body text is the failure. It must stay visibly lighter than `--ink`."""
    root = _root_vars(client)
    assert _contrast(_hex(root["--muted"]), _hex(root["--ink"])) >= 1.5


# --- "n cards here are not usable" on its own line -----------------------------

def test_the_shortfall_sentence_has_its_own_line(client):
    """#266's sentence ran on after each game's instruction as one run-on
    sentence ("Choose the English word ... (3 questions): 24 cards here are
    not usable ..."); two messages, so two lines (#502)."""
    css = client.get("/static/css/style.css").get_data(as_text=True)
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rule = re.search(r"\.hint\.shortfall\s*\{([^}]*)\}", css)
    assert rule and re.search(r"display\s*:\s*block", rule.group(1)), \
        "the shortfall hint is inline again"


def test_every_round_marks_its_shortfall(client, stub_deck):
    """The class is what the line break hangs on, so the shared partial must
    carry it -- a game that grew its own copy of the sentence would not."""
    words = ["salary", "overtime", "deadline", "promotion", "colleague", "employer"]
    usable = [{"id": i, "word": w, "pos": "noun", "topic": "Work",
               "translation_ukr": f"переклад{i}", "translation_rus": f"перевод{i}",
               "explanation_en": f"meaning {i}", "examples_en": []}
              for i, w in enumerate(words, 1)]
    unusable = {"id": 99, "word": "bonus", "pos": "noun", "topic": "Work",
                "translation_ukr": None, "translation_rus": None,
                "explanation_en": None, "examples_en": []}
    stub_deck(cards=usable + [unusable])
    body = client.get("/games/multiple_choice/play?topic=Work").get_data(as_text=True)
    assert 'class="hint shortfall"' in body


@pytest.mark.parametrize("template, opening", [
    ("game_fill_the_gap.html", "Only {{ cards|length }}"),
    ("game_multiple_choice.html", "{{ unbuildable }}"),
    ("game_odd_one_out.html", "These topics could only make"),
])
def test_the_rounds_own_shortfall_notes_have_their_own_line(template, opening):
    """Three rounds say "fewer than you asked for" in a sentence of their own,
    in the same spot as #266's; they break the same way."""
    from pathlib import Path
    import chat
    source = (Path(chat.__file__).parent / "templates" / template).read_text(encoding="utf-8")
    assert f'<span class="hint shortfall">{opening}' in source, template


def test_no_instruction_ends_in_a_colon():
    """With the shortfall note on the next line, "(3 questions):" read as
    introducing that note rather than the questions. Every round's count
    closes a sentence now (#502)."""
    from pathlib import Path
    import chat
    templates = Path(chat.__file__).parent / "templates"
    offenders = [p.name for p in sorted(templates.glob("game_*.html")) + [templates / "quiz.html"]
                 if re.search(r"else 's' \}\}\)\s*:", p.read_text(encoding="utf-8"))]
    assert not offenders, offenders
