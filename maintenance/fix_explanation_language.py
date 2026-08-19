r"""Move a translation out of `explanation_en` into the field it belongs in
(kuantorflow#323).

Thirteen cards in the local deck hold a Russian translation in
`explanation_en`, with `translation_ukr` and `translation_rus` both NULL —
`smuggle` explained as `контрабанда`, `spaz out` as `сойти с ума, психануть.`.
All are ids <= 30 in topic `general`: one early block, not a scattering.

**The parser bug that made them is already fixed.** `_entry_from_line()` has
sent a Cyrillic right-hand side to the matching translation field since
kuantorflow#137 (89f58ac, 2026-07-27), and every one of these lines parses
correctly against today's code. The rows simply predate the fix and were never
migrated. So this repairs data; it does not work around a live defect.

    .\venv\Scripts\python maintenance\fix_explanation_language.py           # inspect
    .\venv\Scripts\python maintenance\fix_explanation_language.py --apply   # write

Dry run by default. Take a backup first if you are pointing it at anything you
care about:

    .\venv\Scripts\python backup\backup_db.py

**Selected by predicate, never by the id list in the ticket**: a Cyrillic
`explanation_en` and no translation in either language. So it is safe to run
against any deployment and says `nothing to repair` on one that never had them.

**The empty-translation half of the predicate is the safety catch.** A card
whose `translation_rus` is already filled would be one where this script has to
choose between two values, and choosing wrong loses text somebody wrote. There
are no such rows today; if one ever appears it is left alone and reported, for
a person to look at rather than a script to guess at.

The language is asked of `_detect_cyrillic_lang()` rather than assumed. All
thirteen are Russian, but the parser this repairs makes that decision per
string, and hard-coding `rus` here would be a second rule that could disagree
with it. A string with no letter unique to either language falls back to `rus`,
exactly as `_entry_from_line()` does.

`explanation_en` is cleared rather than left in place: the whole point is that
the text is not an English explanation, and leaving a copy would keep it on the
card deck and in kuantorflow#235's reveal, which is where it is wrong today.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# This script's entire subject is Cyrillic text, and a Windows console is
# cp1252 by default -- printing a Russian translation there raises
# UnicodeEncodeError and ends a run that was repairing rows perfectly well.
# kuantorflow's seed_topics.py hit exactly this and answered it by keeping its
# output ASCII; that will not do here, because the whole point of the dry run
# is to read the text before it moves. So the stream is widened instead, and
# `errors="replace"` means a console that still cannot render a character
# prints a placeholder rather than taking the run down with it.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

KUANTORFLOW_PATH = os.environ.get(
    "KUANTORFLOW_PATH",
    str(Path(__file__).resolve().parent.parent.parent.parent / "kuantorflow"),
)
sys.path.insert(0, KUANTORFLOW_PATH)


def misfiled_cards():
    """Cards whose `explanation_en` is really a translation.

    Cyrillic in the explanation *and* nothing in either translation field. The
    MySQL pattern is a character range rather than a regex class because the
    collation makes `REGEXP '[а-я]'` case- and accent-insensitive in ways that
    also match Latin text; the range is checked literally.
    """
    from utils import get_db_connection

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT id, word, pos, topic, explanation_en,
                      translation_ukr, translation_rus
                 FROM flashcards
                WHERE explanation_en REGEXP '[Ѐ-ӿ]'
                ORDER BY id""")
        rows = cursor.fetchall()
        cursor.close()
        return rows
    finally:
        conn.close()


def target_field(text):
    """`translation_ukr` or `translation_rus` for this text."""
    from parsers import _detect_cyrillic_lang

    return f"translation_{_detect_cyrillic_lang(text) or 'rus'}"


def write(card_id, field, text):
    """Move `text` into `field` and clear the explanation. One statement, so a
    card cannot end up holding the translation twice or losing it entirely."""
    from utils import get_db_connection

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE flashcards SET {field} = %s, explanation_en = NULL "
            "WHERE id = %s AND explanation_en = %s",
            (text, card_id, text))
        conn.commit()
        changed = cursor.rowcount
        cursor.close()
        return "updated" if changed else "no longer matched"
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default is a dry run)")
    args = parser.parse_args(argv)

    rows = misfiled_cards()
    if not rows:
        print("nothing to repair")
        return 0

    repairable = [r for r in rows
                  if not r["translation_ukr"] and not r["translation_rus"]]
    conflicted = [r for r in rows if r not in repairable]

    print(f"{len(rows)} card(s) with a Cyrillic explanation_en")
    print("dry run - nothing is written\n" if not args.apply else "")

    moved = failed = 0
    for card in repairable:
        text = card["explanation_en"]
        field = target_field(text)
        label = f"id={card['id']} {card['word']} ({card['topic']})"
        if not args.apply:
            moved += 1
            print(f"  + {label}: -> {field} = {text[:52]}")
            continue
        outcome = write(card["id"], field, text)
        if outcome == "updated":
            moved += 1
            print(f"  + {label}: moved to {field}")
        else:
            failed += 1
            print(f"  ! {label}: {outcome}")

    for card in conflicted:
        # Left alone on purpose -- see the module docstring. Two values, and
        # picking one silently would lose text somebody wrote.
        print(f"  - id={card['id']} {card['word']}: already has a translation, "
              "left for a person to look at")

    verb = "would move" if not args.apply else "moved"
    print(f"\n{verb} {len(repairable)} card(s)"
          + (f"; {len(conflicted)} skipped" if conflicted else "")
          + (f"; {failed} refused" if failed else ""))
    if not args.apply and moved:
        print("re-run with --apply to write them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
