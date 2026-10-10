"""The upload review popup splits its two columns half and half (kuantorflow#576).

The *File content* column was a narrow strip beside the cards: both panes were
meant to be `flex: 1 1 0`, but #349's later `.proposal-dialog
.proposal-cards-pane { flex: 1 1 auto }` has the same specificity and a later
place, so the cards pane started from its content's width and the file's text
got what was left (measured 265px against 598px at 1280px). The same ordering
had overridden the phone rule that stacks the columns, so at 375px they stayed
side by side and the file column was 0px wide.

The suite cannot lay a page out, so these resolve the stylesheet's cascade for
the popup's elements the way a browser would -- specificity, then order, with
the phone media query applied or not -- and check what wins. The widths were
measured in a real browser for the PR.
"""

import re

import pytest

# The popup's elements, each as its chain of class sets from the dialog down.
DIALOG = {"modal", "modal-dialog", "proposal-dialog", "proposal-dialog--source"}
BODY = [DIALOG, {"proposal-body"}]
SOURCE = BODY + [{"proposal-source"}]
CARDS = BODY + [{"modal-scroll", "proposal-cards-pane"}]

PHONE_QUERY = "(max-width: 640px)"


def _rules(css):
    """`(media, selector, declarations)` in source order; media is None at top
    level. Only what this file needs: plain rules and one level of @media."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, i = [], 0
    while True:
        brace = css.find("{", i)
        if brace < 0:
            return out
        head = css[i:brace].strip()
        if head.startswith("@media"):
            depth, j = 1, brace + 1
            while depth:
                depth += {"{": 1, "}": -1}.get(css[j], 0)
                j += 1
            media = " ".join(head[len("@media"):].split())
            out += [(media, s, d) for _, s, d in _rules(css[brace + 1:j - 1])]
            i = j
        else:
            end = css.index("}", brace)
            out.append((None, head, css[brace + 1:end]))
            i = end + 1


def _matches(selector, chain):
    """A descendant selector of class-only compounds against a class chain."""
    parts = selector.split()
    if not all(re.fullmatch(r"(\.[\w-]+)+", p) for p in parts):
        return False
    compounds = [set(p.split(".")[1:]) for p in parts]
    if not compounds[-1] <= chain[-1]:
        return False
    ancestors = iter(chain[:-1])
    return all(any(c <= a for a in ancestors) for c in compounds[:-1])


def _winning(css, chain, prop, phone):
    """The value of `prop` that wins on the element, or None."""
    best = None
    for order, (media, selectors, decls) in enumerate(_rules(css)):
        if media is not None and not (phone and media == PHONE_QUERY):
            continue
        values = dict((k.strip(), v.strip()) for k, v in
                      (d.split(":", 1) for d in decls.split(";") if ":" in d))
        if prop not in values:
            continue
        for selector in (s.strip() for s in selectors.split(",")):
            if _matches(selector, chain):
                rank = (selector.count("."), order)
                if best is None or rank > best[0]:
                    best = (rank, values[prop])
    return best and best[1]


@pytest.fixture()
def css(app_module):
    from pathlib import Path
    return (Path(app_module.__file__).parent / "static" / "css" / "style.css") \
        .read_text(encoding="utf-8")


def test_on_a_computer_the_columns_sit_side_by_side(css):
    assert _winning(css, BODY, "flex-direction", phone=False) == "row"


def test_on_a_computer_both_columns_take_half(css):
    source = _winning(css, SOURCE, "flex", phone=False)
    cards = _winning(css, CARDS, "flex", phone=False)

    assert source == cards == "1 1 50%"


def test_on_a_phone_the_columns_stack(css):
    assert _winning(css, BODY, "flex-direction", phone=True) == "column"


def test_on_a_phone_the_file_content_keeps_its_height_cap(css):
    """Stacked, the file pane takes its own height up to 30vh and the cards
    the rest; a zero basis in a column would give the file nothing."""
    assert _winning(css, SOURCE, "flex", phone=True) == "0 0 auto"
    assert _winning(css, SOURCE, "max-height", phone=True) == "30vh"


def test_the_resolver_sees_the_override_that_caused_this(css):
    """The premise: #349's rule still gives the cards pane `1 1 auto` on its
    own, which is why the upload variant must restate its basis after it."""
    plain = [DIALOG - {"proposal-dialog--source"}, {"proposal-body"},
             {"modal-scroll", "proposal-cards-pane"}]
    assert _winning(css, plain, "flex", phone=False) == "1 1 auto"
