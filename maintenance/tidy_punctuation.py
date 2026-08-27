r"""Close the gap before punctuation on cards saved before kuantorflow#359.

Every extraction in `parsers.py` reads a node as `get_text(" ", strip=True)`,
and that separator is load-bearing -- without it Oxford's markup glues words
together. Its cost is a space wherever an element ends and punctuation
follows, which is what happens when a sentence ends on the word being looked
up:

    Are your grandparents still alive ?

kuantorflow#359 fixed the scraping. It repairs nothing already written, and
looking the word up again will not either: #101 refuses the duplicate, and
`fill_missing_fields()` only fills columns that are **empty**. So the rows
saved before it need this.

**The repair is the app's own `parsers._readable()`, not a copy of it.** Two
spellings of one rule is how kuantorflow#359 happened in the first place --
the notes half of the parser had carried a private fix for the padded bracket
since #134, and the dictionaries never got one. Imported, they cannot drift: a
card tidied today is tidied by the same function that tidies the next card
saved.

Which rows are candidates is asked the same way, in Python rather than as a
regex WHERE. A row is a candidate when `_readable()` would change it. A regex
would be a second description of the artifact, and the two would disagree the
first time the normaliser learnt something.

    .\venv\Scripts\python maintenance\tidy_punctuation.py            # inspect
    .\venv\Scripts\python maintenance\tidy_punctuation.py --apply    # write

Dry run by default, printing every before/after it would write. Take a backup
first if you are pointing it at anything you care about:

    .\venv\Scripts\python backup\backup_db.py

Run against the deployed database from a PythonAnywhere console; run against a
local one by pointing the kuantorflow .env at it, as with the backup scripts.
It has no network of its own -- unlike backfill_examples.py it asks no
dictionary anything, so there is nothing to pause between and nothing to fail
halfway through.

**`word` and `pos` are deliberately not touched.** Renaming a card is a
different act with #101's duplicate rule attached, and a headword does not
carry sentence punctuation to begin with.

Punctuation is not quite all of it, because `_readable()` collapses whitespace
first: a thin space inside a scraped number goes with it, and Oxford's
"released on \N{POUND SIGN}2\N{THIN SPACE}000 bail" is stored with a plain
space instead. Worth knowing rather than worth avoiding -- it is one more
place the deck ends up spelling something one way.

Output is **ASCII**, which is not fussiness: a Ukrainian example printed to a
cp1252 console raises `UnicodeEncodeError`, and with `--apply` that ends a run
that was writing correctly, halfway through, with no summary. `seed_topics.py`
carries the same rule for the same reason.

It cannot tell scraped text from text somebody typed -- since kuantorflow#357
the examples are editable in the review popup. That is a smaller worry than it
looks: the change it makes is exactly the change the parser now makes to every
new card, so the deck ends up spelling punctuation one way rather than two.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

KUANTORFLOW_PATH = os.environ.get(
    "KUANTORFLOW_PATH",
    str(Path(__file__).resolve().parent.parent.parent.parent / "kuantorflow"),
)
sys.path.insert(0, KUANTORFLOW_PATH)

# The text a learner reads. `word` and `pos` are absent on purpose -- see the
# module docstring.
TEXT_FIELDS = ("explanation_en", "translation_ukr", "translation_rus")
LIST_FIELDS = ("examples_en", "examples_ukr", "examples_rus")


def cards(topic=None, section=None):
    """Every card's readable text, narrowed by topic or section if asked."""
    from utils import get_db_connection

    columns = ", ".join("f." + name for name in
                        ("id", "word", "pos", "topic") + TEXT_FIELDS + LIST_FIELDS)
    sql = ["SELECT " + columns + " FROM flashcards f"
           " LEFT JOIN topics t ON t.id = f.topic_id"
           " LEFT JOIN topic_sections s ON s.id = t.section_id"]
    params = []
    if topic or section:
        sql.append("WHERE 1 = 1")
    if topic:
        sql.append("AND f.topic = %s")
        params.append(topic)
    if section:
        sql.append("AND s.name = %s")
        params.append(section)
    sql.append("ORDER BY f.word, f.id")

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(" ".join(sql), tuple(params))
        rows = cursor.fetchall()
        cursor.close()
        return rows
    finally:
        conn.close()


def repairs(card):
    """`{field: tidied}` for the fields `_readable()` would change, or `{}`.

    A field the normaliser leaves alone is left out rather than written back
    unchanged, because `update_flashcard()` reads a missing key as "leave this
    alone" -- so the UPDATE carries only what is actually being repaired.
    """
    import parsers
    from utils import _to_list

    found = {}
    for field in TEXT_FIELDS:
        value = card.get(field)
        if value:
            tidied = parsers._readable(value)
            if tidied != value:
                found[field] = tidied
    for field in LIST_FIELDS:
        value = card.get(field)
        if not value:
            continue
        items = _to_list(value)
        tidied = [parsers._readable(item) for item in items]
        if tidied != items:
            found[field] = tidied
    return found


def write(card_id, fields):
    """Apply one card's repairs, touching nothing else.

    `admin=True` for the reason backfill_examples.py needs it: the seeded
    curriculum cards are **unowned**, and `update_flashcard()` compares
    ownership with `=`, which never matches NULL. Without it every one of
    these comes back "denied".

    Logged here rather than by the app's `_save_and_log()`, as
    `set_user_blocked()` and `place_topic()` do: there is no request behind
    this, so there is no session for that helper to read.
    """
    import applog
    from utils import update_flashcard

    outcome, detail = update_flashcard(card_id, dict(fields), admin=True)
    if outcome == "updated":
        applog.card_edited(fields, source="punctuation tidy",
                           card_id=card_id, changed=detail)
    return outcome


def say(line):
    """Print one line safely on whatever console this is running in.

    A Ukrainian example on a cp1252 console raises `UnicodeEncodeError`, and
    under `--apply` that would end a run that was writing correctly, halfway,
    with no summary. Escaped rather than dropped, so a line stays readable
    enough to tell which card it is about.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    print(line.encode(encoding, "backslashreplace").decode(encoding))


def sample(before, after):
    """One line showing what actually changes.

    A window around the **first difference**, not the first 64 characters:
    these strings differ by one space somewhere in a sentence, so two truncated
    heads print identically and the line reads as a repair of nothing.
    """
    if isinstance(after, list):
        for was, now in zip(before, after):
            if was != now:
                return sample(was, now)
        return str(len(after)) + " item(s)"
    at = next((i for i, (a, b) in enumerate(zip(before, after)) if a != b),
              min(len(before), len(after)))
    start = max(0, at - 28)
    window = lambda text: (("..." if start else "") + text[start:at + 32]
                           + ("..." if len(text) > at + 32 else ""))
    return repr(window(before)) + " -> " + repr(window(after))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the repairs (default: dry run)")
    parser.add_argument("--topic", metavar="NAME", help="only this topic")
    parser.add_argument("--section", metavar="NAME", help="only this section")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="stop after N cards - useful for a trial run")
    args = parser.parse_args(argv)

    from utils import _to_list

    rows = cards(args.topic, args.section)
    found = [(row, repairs(row)) for row in rows]
    found = [(row, fields) for row, fields in found if fields]
    if args.limit:
        found = found[:args.limit]

    if not found:
        say(str(len(rows)) + " card(s) checked - nothing to tidy")
        return 0

    per_field = {}
    for _row, fields in found:
        for field in fields:
            per_field[field] = per_field.get(field, 0) + 1
    summary = ", ".join(name + " " + str(n)
                        for name, n in sorted(per_field.items()))
    say(str(len(found)) + " of " + str(len(rows))
        + " card(s) need tidying (" + summary + ")")
    say("dry run - nothing is written\n" if not args.apply else "")

    tidied = failed = 0
    for row, fields in found:
        label = (row["word"] + " (" + (row["pos"] or "no pos") + ") in "
                 + str(row["topic"]))
        for field, after in sorted(fields.items()):
            before = (_to_list(row[field]) if isinstance(after, list)
                      else row[field])
            say("  " + ("+" if args.apply else "~") + " " + label
                + " [" + field + "]: " + sample(before, after))
        if not args.apply:
            tidied += 1
            continue
        outcome = write(row["id"], fields)
        if outcome == "updated":
            tidied += 1
        else:
            failed += 1
            say("  ! " + label + ": " + outcome)

    say("\n" + str(tidied) + " card(s) "
        + ("tidied" if args.apply else "would be tidied")
        + (", " + str(failed) + " failed" if failed else ""))
    if not args.apply:
        say("re-run with --apply to write")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
