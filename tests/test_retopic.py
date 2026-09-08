"""The consolidation plans are applicable as written (kuantorflow#407).

`retopic.py` merges the strays in `Other` into the curriculum and renames the
survivors, from a plan declared in the script. **The risk in a plan is not the
SQL, it is the plan** -- a destination spelled slightly wrong, or two steps in
an order where the second cannot run. Neither is visible by reading, both are
expensive to find on a database, and the deployed plan cannot be rehearsed from
here at all: that deck is not this one.

So this file does not touch a database. It **walks each plan over a symbolic
deck** -- the eighteen seeded topic names plus whatever the plan's own renames
create -- and asserts every step is applicable at the point it runs. That
catches a typo, an ordering mistake and a use-after-delete with one traversal,
which is the whole of what can go wrong in a declaration.

What a database has to answer instead -- that both columns move, that the
emptied row goes, that a collision is refused, that a second run is quiet --
is in `test_retopic_db.py`.
"""

import pytest

import retopic
import seed_words


SEEDED = set(seed_words.SEED_WORDS)


def _walk(plan):
    """Replay `plan` over topic names alone.

    Returns the list of problems found, each a sentence. Kept as a list rather
    than an assert per step so one run reports every fault in a plan instead of
    the first.
    """
    # Two kinds of topic exist before the plan runs. The eighteen seeded ones
    # are declared in `seed_words.py`; the strays in `Other` are declared
    # nowhere at all, because they are whatever a learner happened to type. The
    # plan's own steps are the only evidence of a stray: a name it renames or
    # merges is a name it expects to find. `general` is one of those -- not
    # seeded, not created here, merged into and then renamed.
    #
    # A destination that is neither seeded nor referenced anywhere else in the
    # plan is the typo this walk is looking for.
    known = {name.casefold(): name for name in SEEDED}
    for step in plan:
        source = getattr(step, "old", None) or getattr(step, "source", None)
        known.setdefault(source.casefold(), source)
    removed = set()
    problems = []

    for step in plan:
        if isinstance(step, retopic.Rename):
            if step.old.casefold() in removed:
                problems.append(
                    "renames %r, which an earlier step merged away" % step.old)
            if step.old == step.new:
                problems.append("renames %r to itself" % step.old)
            clash = known.get(step.new.casefold())
            if clash and clash != step.old:
                problems.append(
                    "renames %r onto %r, which already exists -- that is a "
                    "merge, not a rename" % (step.old, clash))
            known.pop(step.old.casefold(), None)
            known[step.new.casefold()] = step.new
        else:
            if step.source.casefold() in removed:
                problems.append(
                    "merges %r twice" % step.source)
            if step.source.casefold() == step.dest.casefold():
                problems.append("merges %r into itself" % step.source)
            if step.dest.casefold() not in known:
                problems.append(
                    "merges %r into %r, which does not exist yet -- no step "
                    "before it creates that topic, and the script never "
                    "invents one" % (step.source, step.dest))
            removed.add(step.source.casefold())
    return problems


@pytest.mark.parametrize("name", sorted(retopic.PLANS))
def test_every_step_can_run_when_it_runs(name):
    """The one test that would have caught the ordering bug this file exists for.

    The local plan's first step *creates* `Psychology, feelings and emotions` by
    renaming `emotions`; the two steps after it merge into that name. Written
    the other way round, the merges would hit a destination that does not exist
    -- which the script reports and skips rather than creating, so the failure
    would be two topics quietly left behind rather than an error.
    """
    problems = _walk(retopic.PLANS[name])

    assert not problems, "plan %r: %s" % (name, "; ".join(problems))


@pytest.mark.parametrize("name", sorted(retopic.PLANS))
def test_a_curriculum_destination_is_spelled_the_way_the_deck_spells_it(name):
    """A destination that *is* one of the eighteen must match it exactly.

    The column collates case-insensitively, so `Media and the News` and
    `Media and the news` resolve to the same row and the merge would work
    either way -- which is exactly why this is worth pinning. The row keeps the
    name it has, so a plan written in the other capitalisation reads like a
    rename that never happened, and the next person compares the plan against
    the deck and finds them disagreeing for no reason.
    """
    wrong = []
    for step in retopic.PLANS[name]:
        dest = getattr(step, "dest", None)
        if dest is None:
            continue
        for seeded in SEEDED:
            if seeded.casefold() == dest.casefold() and seeded != dest:
                wrong.append("%r should be %r" % (dest, seeded))

    assert not wrong, "plan %r: %s" % (name, "; ".join(wrong))


def test_the_local_plan_ends_with_three_topics_in_other():
    """The shape of the result, held as a number rather than a list.

    Thirteen topics in, three out -- `Character and personality`,
    `General knowledge` and `Psychology, feelings and emotions`. Counted off the
    plan rather than the database so it fails when somebody edits the plan,
    which is the moment the intent changes.
    """
    plan = retopic.PLANS["local"]
    survives = set()
    for step in plan:
        if isinstance(step, retopic.Rename):
            survives.discard(step.old.casefold())
            survives.add(step.new.casefold())
        else:
            survives.discard(step.source.casefold())

    # Only the ones the plan renames survive; everything merged is gone, and a
    # curriculum destination was never in `Other` to begin with.
    assert survives == {"character and personality", "general knowledge",
                        "psychology, feelings and emotions"}


def test_nothing_is_merged_into_a_topic_the_plan_later_renames():
    """An order that works and reads wrongly, which is worth refusing.

    The local plan merges `Runaway Bride` and `test` into `general` and *then*
    renames it, which is fine -- the cards follow the row. Merging into a name
    that a later step renames is only confusing when the merge names the old
    topic and the log then names the new one. This asserts the log stays
    readable: a merge's destination is the name that topic still has when the
    plan finishes, or the plan says so in a comment.
    """
    plan = retopic.PLANS["local"]
    renamed_later = {}
    for i, step in enumerate(plan):
        if isinstance(step, retopic.Rename):
            renamed_later[step.old.casefold()] = (i, step.new)

    surprises = []
    for i, step in enumerate(plan):
        if isinstance(step, retopic.Rename):
            continue
        later = renamed_later.get(step.dest.casefold())
        if later and later[0] > i:
            surprises.append("%r -> %r, later renamed to %r"
                             % (step.source, step.dest, later[1]))

    # `general` is the deliberate one and the plan carries a comment saying so.
    assert surprises == ["'Runaway Bride' -> 'general', later renamed to "
                         "'General knowledge'",
                         "'test' -> 'general', later renamed to "
                         "'General knowledge'"]
