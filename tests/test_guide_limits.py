"""The user guide's limits are the app's limits (kuantorflow#462).

`docs/user-guide.md` is not documentation in the usual sense. **Mykola reads
it** -- `MYKOLA_KNOWLEDGE` hands it to the agent (#310) -- and the guide tells
the learner so: *"He can also explain the site itself, since he has read this
guide."* So a number that is wrong there is not a stale doc, it is a wrong
answer given to a learner by name.

The ceilings have reached learners ahead of this file **three times**: the
anonymous chat allowance was never in it, #447 added three more ceilings
without it, and #456 then changed every number and added a site-wide pool. Each
time nothing went red, because prose has no tests.

This is the test. The guide's table is the claim; `web.py` is the truth; the
numbers have to agree. It is deliberately a comparison rather than a copy --
asserting the guide says "40" would freeze the very number it is meant to
follow.
"""

import re

import pytest


# (row label, column heading) -> the constant that decides it.
#
# Keyed on the heading rather than the column's position, so adding a feature
# to the table does not silently re-point every assertion one column to the
# left -- which is what a positional list would have done, and this table has
# gained a column once already.
CEILINGS = {
    ("Signed out, per visit", "Looking a word up"): "LOOKUP_ANON_LIMIT",
    ("Signed out, per visit", "Generating a text"): "GENERATION_ANON_LIMIT",
    ("Signed out, per visit", "Talking to Mykola"): "ANONYMOUS_MESSAGE_LIMIT",

    ("Signed out, per day, shared by everyone signed out",
     "Looking a word up"): "LOOKUP_ANON_DAILY",
    ("Signed out, per day, shared by everyone signed out",
     "Generating a text"): "GENERATION_ANON_DAILY",
    ("Signed out, per day, shared by everyone signed out",
     "Talking to Mykola"): "ANONYMOUS_DAILY_LIMIT",

    ("Your account, per day", "Looking a word up"): "LOOKUP_USER_DAILY",
    ("Your account, per day", "Generating a text"): "GENERATION_USER_DAILY",
    ("Your account, per day", "Talking to Mykola"): "CHAT_USER_DAILY",
    ("Your account, per day", "A recap"): "RECAP_USER_DAILY",
    ("Your account, per day", "Importing notes"): "UPLOAD_USER_DAILY",

    ("Everyone together, per day", "Looking a word up"): "LOOKUP_ALL_DAILY",
    ("Everyone together, per day", "Generating a text"): "GENERATION_DAILY_LIMIT",
    ("Everyone together, per day", "Talking to Mykola"): "CHAT_ALL_DAILY",
    ("Everyone together, per day", "A recap"): "RECAP_ALL_DAILY",
    ("Everyone together, per day", "Importing notes"): "UPLOAD_ALL_DAILY",
}


@pytest.fixture()
def guide(app_module):
    from pathlib import Path
    return Path(app_module.app.root_path, "docs", "user-guide.md").read_text(
        encoding="utf-8")


def _limits(guide):
    """The limits table as `{(row label, column heading): cell}`."""
    header, cells = None, {}
    for line in guide.splitlines():
        if not line.startswith("|"):
            header = None                     # the table ended
            continue
        row = [c.strip() for c in line.strip("|").split("|")]
        if set("".join(row[1:])) <= set("- ") and header is None:
            continue                          # the |---|---| separator
        if header is None:
            header = row[1:]
            continue
        label = row[0].strip("*")
        for column, cell in zip(header, row[1:]):
            cells[(label, column)] = cell
    return cells


def test_the_guide_has_a_limits_table(guide):
    """The guard against everything below passing over an empty dict, which is
    the failure mode of every test that parses prose."""
    cells = _limits(guide)

    missing = sorted(key for key in CEILINGS if key not in cells)
    assert not missing, "the limits table lost these cells: %s" % missing


def test_every_number_in_it_is_the_number_the_app_uses(guide, app_module):
    """The drift this file exists to stop.

    Compared against `web.py` rather than against literals here: a literal
    would be a third copy of the same number, and the point is that there are
    already two.
    """
    import web

    cells = _limits(guide)
    wrong = []
    for (label, column), name in sorted(CEILINGS.items()):
        expected = getattr(web, name)
        cell = cells.get((label, column))
        if cell != str(expected):
            wrong.append("%s / %s: guide says %r, %s is %s"
                         % (label, column, cell, name, expected))

    assert not wrong, (
        "the user guide tells learners the wrong limits, and Mykola reads it: "
        + "; ".join(wrong))


def test_every_ceiling_the_app_has_appears_in_the_table(app_module):
    """The other direction, and the one that caught this three times.

    A new ceiling is added to `web.py` and nothing makes anybody write it down.
    So this asks the *app* what ceilings exist and fails on one the table has
    never heard of -- which is exactly how #447's three and #456's site-wide
    pools reached learners unannounced.
    """
    import web

    described = set(CEILINGS.values())
    # every daily or per-visit ceiling `web.py` declares
    declared = {n for n in dir(web)
                if re.search(r"_(DAILY|LIMIT)$", n)
                and isinstance(getattr(web, n), int)
                and not n.startswith("MAX_")}

    undescribed = sorted(declared - described)
    assert not undescribed, (
        "these ceilings can refuse a learner and the guide does not mention "
        "them: %s" % undescribed)
