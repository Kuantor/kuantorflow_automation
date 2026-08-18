r"""Fill in `examples_en` on cards saved before kuantorflow#225 (kuantorflow#314).

#225 taught a lookup to take example sentences from Oxford. The local B2-C1
deck was seeded on 2026-08-08 between 13:45 and 21:44, and #225 was committed
at 21:38:51 -- six minutes before the run ended. So of 509 curriculum cards,
396 have an Oxford explanation and exactly **one** has examples: `appraisal`,
written at 21:44:45, the last card of the seed.

Oxford has the examples. Asked today it answers "The jury acquitted him of
murder." for `acquit` and "The job had to be delegated to an assistant." for
`delegate` -- both cards that carry none. Nothing is broken; the rows are just
older than the feature.

**Re-seeding cannot repair this.** `save_flashcard()` skips a duplicate word +
part of speech, so `seed_topics.py` adds nothing and updates nothing. Repairing
a saved card is kuantorflow#191's job in the app; this is the same thing for the
one field, from the command line.

    .\venv\Scripts\python maintenance\backfill_examples.py                  # inspect
    .\venv\Scripts\python maintenance\backfill_examples.py --apply          # write
    .\venv\Scripts\python maintenance\backfill_examples.py --topic "Work and careers"

Dry run by default. Take a backup first if you are pointing it at anything you
care about:

    .\venv\Scripts\python backup\backup_db.py

**Only `examples_en` is written, and only when the card has none.** Explanations
and translations are never touched -- a card missing its explanation is a
different gap with a different cause (#228: Google reports parts of speech
Oxford has nothing for), and widening this script to "refresh the card" would
make it a thing that can lose text rather than add it.

One Oxford request per **word**, not per card: `delegate` is three cards and one
page. There is a deliberate pause between requests, as seed_topics.py has.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

KUANTORFLOW_PATH = os.environ.get(
    "KUANTORFLOW_PATH",
    str(Path(__file__).resolve().parent.parent.parent.parent / "kuantorflow"),
)
sys.path.insert(0, KUANTORFLOW_PATH)

PAUSE = 1.0


def cards_missing_examples(topic=None, section=None):
    """Cards with no `examples_en`, newest topic grouping first.

    Both filters are optional and narrow rather than widen -- the default is
    every card in the deck, which is what a repair of a whole seeded section
    wants.
    """
    from utils import get_db_connection

    sql = ["""SELECT f.id, f.word, f.pos, f.topic
                FROM flashcards f
                LEFT JOIN topics t ON t.id = f.topic_id
                LEFT JOIN topic_sections s ON s.id = t.section_id
               WHERE (f.examples_en IS NULL OR f.examples_en IN ('', '[]'))"""]
    params = []
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


def examples_for(word, cards, pause=PAUSE):
    """`{card_id: [sentence, ...]}` for one word's cards, from Oxford.

    The part of speech is matched through `parsers._pos_key()` -- #228's
    synonym map -- and not by string equality, because the two providers name
    the same thing differently: a card saved as `modal verb` by the translator
    takes the text Oxford files under `auxiliary verb`.
    """
    import parsers

    try:
        _definitions, examples = parsers._fetch_oxford_entry(word)
    except Exception as e:                      # noqa: BLE001 - reported, not raised
        print(f"  ! {word}: lookup failed ({type(e).__name__}: {e})")
        return {}
    finally:
        time.sleep(pause)

    by_key = {}
    for pos, sentences in examples.items():
        if sentences:
            by_key.setdefault(parsers._pos_key(pos), sentences)

    found = {}
    for card in cards:
        sentences = by_key.get(parsers._pos_key(card["pos"] or ""))
        if sentences:
            found[card["id"]] = sentences
    return found


def write(card_id, sentences):
    """Put `sentences` on one card, touching nothing else.

    `admin=True` is not a flourish: the seeded curriculum cards are **unowned**
    (added before #89, or by a seed run given no `--owner`), and
    `update_flashcard()` compares ownership with `=`, which never matches NULL.
    Without it every one of these would come back "denied".

    The log line is written here rather than by the app's `_save_and_log()`,
    for the reason `set_user_blocked()` and `place_topic()` do the same: there
    is no request behind this, so there is no session for that helper to read.
    """
    import applog
    from utils import update_flashcard

    outcome, detail = update_flashcard(
        card_id, {"examples_en": sentences}, admin=True)
    if outcome == "updated":
        applog.card_edited({"examples_en": sentences}, source="backfill script",
                           card_id=card_id, changed=detail)
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the examples (default: dry run)")
    parser.add_argument("--topic", metavar="NAME", help="only this topic")
    parser.add_argument("--section", metavar="NAME",
                        help="only this section, e.g. 'B2–C1 Conversational Topics'")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="stop after N words - useful for a trial run")
    parser.add_argument("--pause", type=float, default=PAUSE, metavar="SECONDS",
                        help=f"between Oxford requests (default {PAUSE})")
    args = parser.parse_args(argv)

    cards = cards_missing_examples(args.topic, args.section)
    if not cards:
        print("every card already has examples - nothing to do")
        return 0

    by_word = {}
    for card in cards:
        by_word.setdefault(card["word"], []).append(card)
    words = sorted(by_word)
    if args.limit:
        words = words[:args.limit]

    print(f"{len(cards)} card(s) without examples across {len(by_word)} word(s)"
          f"{f' - trying {len(words)}' if args.limit else ''}")
    print("dry run - nothing is written\n" if not args.apply else "")

    filled = skipped = failed = 0
    for i, word in enumerate(words, 1):
        found = examples_for(word, by_word[word], args.pause)
        for card in by_word[word]:
            sentences = found.get(card["id"])
            label = f"{word} ({card['pos'] or 'no pos'}) in {card['topic']}"
            if not sentences:
                skipped += 1
                print(f"  - {label}: Oxford has no examples for that part of speech")
                continue
            if not args.apply:
                filled += 1
                print(f"  + {label}: {len(sentences)} example(s) "
                      f"- {sentences[0][:60]}...")
                continue
            outcome = write(card["id"], sentences)
            if outcome == "updated":
                filled += 1
                print(f"  + {label}: {len(sentences)} example(s) written")
            else:
                failed += 1
                print(f"  ! {label}: {outcome}")
        if i % 25 == 0:
            print(f"  ... {i}/{len(words)} words")

    verb = "would fill" if not args.apply else "filled"
    print(f"\n{verb} {filled} card(s); {skipped} had nothing to take"
          + (f"; {failed} refused" if failed else ""))
    if not args.apply and filled:
        print("re-run with --apply to write them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
