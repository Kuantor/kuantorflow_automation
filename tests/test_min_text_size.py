"""No text smaller than 12px (kuantorflow#502, item 7).

Five rules sat at 0.72rem (11.5px) -- the part-of-speech badges, Mykola's
caption and sources, the consent note, the topic builder's "saved" badge --
and the worksheet's blank numbers at 0.7em. The Help page's code examples
measured 11.7px for a subtler reason: a font list that is only `monospace` is
sized from 13px, so `0.9em` of it is 11.7px.

Every page was scanned in the PR (home with Settings open, a topic, five
rounds, the quiz, Help, the word list, the review page, Mykola open): nothing
visible under 12px. This holds the two things that produced that.
"""

import re
from pathlib import Path

import chat

FLOOR_PX = 12
APP = Path(chat.__file__).parent


def _sources():
    """The stylesheet, and every template's own <style> blocks and style=""."""
    yield "style.css", (APP / "static" / "css" / "style.css").read_text(encoding="utf-8")
    for template in sorted((APP / "templates").glob("*.html")):
        text = template.read_text(encoding="utf-8")
        blocks = re.findall(r"<style[^>]*>(.*?)</style>", text, re.S)
        blocks += re.findall(r'style="([^"]*)"', text)
        if blocks:
            yield template.name, "\n".join(blocks)


def _px(number, unit):
    """A size in px where it can be known without the page: rem and em are
    taken against the 16px root, which is what an em size inherits from in
    every rule this site writes; pt is 4/3px."""
    return number * {"rem": 16, "em": 16, "px": 1, "pt": 4 / 3}[unit]


def test_no_font_size_is_under_12px():
    small = []
    for name, css in _sources():
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for number, unit in re.findall(r"font-size\s*:\s*([\d.]+)(rem|em|px|pt)\b", css):
            if _px(float(number), unit) < FLOOR_PX:
                small.append(f"{name}: {number}{unit}")
    assert not small, small


def test_code_is_not_sized_from_the_13px_monospace_default():
    css = (APP / "static" / "css" / "style.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    families = [body for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
                if "code" in [s.strip() for s in selectors.split(",")]
                and "font-family" in body]
    assert families, "no font-family for code: browsers fall back to 13px monospace"
    family = re.search(r"font-family\s*:\s*([^;]+)", families[-1]).group(1)
    first = family.split(",")[0].strip().strip('"')
    assert first != "monospace", family
