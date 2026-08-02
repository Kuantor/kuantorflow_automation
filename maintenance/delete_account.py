r"""Delete a KuantorFlow account from the command line (kuantorflow#165).

The admin-side entry point to the same operation the Settings popup offers, so
an account that cannot remove itself — an abandoned test account, or someone
who asks by email — can still be removed. One implementation, two callers:
this calls `app.delete_account()`, exactly what the route calls.

    .\venv\Scripts\python maintenance\delete_account.py --list
    .\venv\Scripts\python maintenance\delete_account.py 7 --keep-cards
    .\venv\Scripts\python maintenance\delete_account.py 7 --delete-cards

The card choice is required and has no default: it is the one decision the
user would have made for themselves, and guessing it either destroys their
cards or leaves them behind against their wishes.

Run against the deployed database from a PythonAnywhere console; run against a
local one by pointing the kuantorflow .env at it, as with the backup scripts.
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


def _users():
    """Every account, with how many cards each one owns."""
    from utils import get_db_connection

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT u.id, u.email, u.created_at, "
            "  (SELECT COUNT(*) FROM flashcards f WHERE f.added_by_user_id = u.id) "
            "FROM users u ORDER BY u.id"
        )
        rows = cursor.fetchall()
        cursor.close()
        return rows
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("user_id", nargs="?", type=int,
                        help="id of the account to delete (see --list)")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--keep-cards", action="store_true",
                        help="leave their cards on the site with no owner")
    choice.add_argument("--delete-cards", action="store_true",
                        help="remove their cards along with the account")
    parser.add_argument("--list", action="store_true",
                        help="list accounts and exit")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    args = parser.parse_args(argv)

    if args.list:
        rows = _users()
        if not rows:
            print("no accounts")
            return 0
        for user_id, email, created, cards in rows:
            print(f"{user_id:>4}  {email:<40} created {created}  {cards} card(s)")
        return 0

    if args.user_id is None:
        parser.error("a user id is required (or --list)")
    if not (args.keep_cards or args.delete_cards):
        parser.error("choose --keep-cards or --delete-cards; there is no default")

    rows = {row[0]: row for row in _users()}
    if args.user_id not in rows:
        print(f"no account with id {args.user_id}", file=sys.stderr)
        return 1

    _, email, _, cards = rows[args.user_id]
    fate = "kept for other learners" if args.keep_cards else "DELETED"
    print(f"About to delete account {args.user_id} <{email}>.")
    print(f"  {cards} card(s) will be {fate}.")
    print("  Mykola transcripts and the settings file go too. This is permanent.")
    if not args.yes and input("Type the email to confirm: ").strip() != email:
        print("aborted")
        return 1

    import app  # imported late: it loads the agent and the Flask app

    result = app.delete_account(args.user_id, keep_cards=args.keep_cards)
    print(f"cards {'kept' if result['kept'] else 'deleted'}: {result['cards']}")
    print(f"chat logs removed: {result['logs']}")
    print(f"settings file removed: {result['settings']}")
    print(f"account row removed: {result['row']}")
    return 0 if result["row"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
