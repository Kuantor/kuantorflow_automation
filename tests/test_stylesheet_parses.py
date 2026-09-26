"""The stylesheet's braces balance, so no rule is silently dropped.

**Why this file exists.** #431 removed a `@media (max-width: 600px)` block and
left its closing `}` behind. A stray `}` at the top level of a stylesheet is
not ignored: the parser treats it as the start of a qualified rule, reads
everything up to the next `{` as that rule's selector -- here the *next*
`@media (max-width: 600px)` -- and drops that whole block as invalid.

So the neighbouring phone block was dead in every browser. It held the "Meet
Mykola" welcome popup's single-column layout, which on a 375pt phone kept its
desktop grid with a 28px text column, and the lookup form's stacking (#298).

**Nothing else in the suite could see it**, which is the case for this file.
Every rule was still in `style.css`, so a test reading the source -- and
several do, through a `_rule()` helper -- finds them all. Only a parser drops
them. Measured in a browser at 375x812: zero 600px blocks parsed with the
stray brace, one with nine rules after it was removed.

A full CSS parser would be the thorough answer and is not in this venv. Brace
depth is the cheap one, and it is exactly the property that broke: a count
that never goes negative and ends at zero.
"""

import re

import pytest


def _css(client):
    return client.get("/static/css/style.css").get_data(as_text=True)


def _depths(css):
    """(line of every stray `}`, depth left open at the end).

    Comments are blanked first, keeping their length so line numbers stay
    right: this stylesheet documents nearly every rule, and a brace inside a
    comment -- `{% if %}` in an example, a quoted selector -- is not structure.
    """
    blanked = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()),
                     css, flags=re.S)
    depth, stray = 0, []
    for index, char in enumerate(blanked):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                stray.append(blanked.count("\n", 0, index) + 1)
                depth = 0
    return stray, depth


def test_no_closing_brace_is_stray(client):
    """The failure that happened. A stray `}` drops the rule after it."""
    stray, _ = _depths(_css(client))

    assert stray == [], (
        f"a stray '}}' at line(s) {stray} makes the browser drop the block "
        "that follows it")


def test_every_opened_block_is_closed(client):
    """The other half. An unclosed `{` swallows the rest of the file into one
    block, which fails the same way from the other direction."""
    _, open_at_end = _depths(_css(client))

    assert open_at_end == 0, f"{open_at_end} block(s) never closed"


def test_the_check_sees_a_stray_brace(client):
    """The control. A brace counter that ignored its input would pass both
    tests above on any file; this feeds it the exact shape of #431's mistake
    and insists it notices."""
    broken = ".a { color: red; }\n}\n@media (max-width: 600px) { .b { x: 1; } }\n"

    stray, _ = _depths(broken)

    assert stray == [2]


def test_a_brace_inside_a_comment_is_not_structure(client):
    """This stylesheet quotes Jinja and selectors in its comments. Counting
    those would make the check fail on documentation and teach people to
    ignore it."""
    documented = "/* like `{% if x %}` or a stray } */\n.a { color: red; }\n"

    assert _depths(documented) == ([], 0)


def test_the_phone_block_the_brace_was_killing_is_present(client):
    """Belt and braces, and specific: the block that went missing holds the
    welcome popup's single column. Balanced braces could still come with the
    block deleted outright."""
    css = re.sub(r"/\*.*?\*/", "", _css(client), flags=re.S)
    blocks = re.findall(r"@media\s*\(max-width:\s*600px\)\s*\{", css)

    assert blocks, "no 600px phone block at all"
    at = css.index(".welcome-mykola-layout", css.index(blocks[-1]))
    assert "grid-template-columns: 1fr" in css[at:at + 200]
