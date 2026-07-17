"""One-off cleanup for kuantorflow#101: remove duplicate flashcards.

The app used to save a card again on every repeated lookup; since the #101
fix, save_flashcard() skips a card whose word + part of speech already
exists — but the duplicates accumulated before the fix are still in the
table. This script removes them.

A duplicate group = the same word and part of speech (word matched
case-insensitively, NULL pos equal to NULL pos — the same rule as the app's
check). The OLDEST card of each group (lowest id) is kept, since that is the
one topic pages and quizzes have been showing all along.

Dry run by default — prints every group and what would be deleted.
Pass --apply to actually delete. Take a backup first:

    .\venv\Scripts\python backup\backup_db.py
    .\venv\Scripts\python maintenance\dedup_flashcards.py          # inspect
    .\venv\Scripts\python maintenance\dedup_flashcards.py --apply  # delete

Configuration: the same DB_* variables (from .env) as the app and the
backup script.
"""

import os
import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get_db_connection():
    """Same connection convention as kuantorflow's utils.get_db_connection."""
    user = os.environ.get("DB_USER", "kuantorflow")
    password = os.environ.get("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD is not set — fill it in .env")
    return mysql.connector.connect(
        user=user,
        password=password,
        host=os.environ.get("DB_HOST", f"{user}.mysql.pythonanywhere-services.com"),
        database=os.environ.get("DB_NAME", f"{user}$default"),
        connection_timeout=10,
    )


def find_duplicates(cursor):
    """[(kept_row, [duplicate_rows...])] — rows are (id, word, pos, topic)."""
    cursor.execute(
        "SELECT id, word, pos, topic FROM flashcards ORDER BY id"
    )
    groups = {}  # (word.lower(), pos) -> [rows in id order]
    for row in cursor.fetchall():
        key = ((row[1] or "").strip().lower(), row[2])
        groups.setdefault(key, []).append(row)
    return [(rows[0], rows[1:]) for rows in groups.values() if len(rows) > 1]


def main():
    apply_changes = "--apply" in sys.argv[1:]
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        duplicate_groups = find_duplicates(cursor)
        if not duplicate_groups:
            print("No duplicates found — every word+pos is unique. \U0001F389")
            return

        doomed = []
        for kept, extras in duplicate_groups:
            print(f"\n'{kept[1]}' ({kept[2] or 'no pos'}):")
            print(f"  keep   id={kept[0]:<6} topic={kept[3]!r}")
            for row in extras:
                print(f"  delete id={row[0]:<6} topic={row[3]!r}")
                doomed.append(row[0])

        print(f"\n{len(duplicate_groups)} duplicated word+pos group(s), "
              f"{len(doomed)} card(s) to delete.")

        if not apply_changes:
            print("Dry run — nothing deleted. Re-run with --apply to delete "
                  "(after taking a backup: python backup/backup_db.py).")
            return

        cursor.execute(
            "DELETE FROM flashcards WHERE id IN "
            f"({', '.join(['%s'] * len(doomed))})",
            doomed,
        )
        conn.commit()
        print(f"Deleted {cursor.rowcount} duplicate card(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
