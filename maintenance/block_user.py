r"""Block or unblock a KuantorFlow account (kuantorflow#126).

A blocked account can still read the site — flashcards, the deck, quizzes and
word lookups — but cannot change the database or talk to Mykola. The blocked
person is shown the admin's address so they can ask for access back.

    .\venv\Scripts\python maintenance\block_user.py --list
    .\venv\Scripts\python maintenance\block_user.py someone@gmail.com --reason "spam in chat"
    .\venv\Scripts\python maintenance\block_user.py someone@gmail.com --unblock

Sibling of delete_account.py, and the same shape: the mutation itself lives in
`kuantorflow/utils.py` as `set_user_blocked()`, which this only calls. An
admin page, if one is ever wanted, calls the same function rather than
reimplementing the UPDATE — and neither can drift from the other.

Not hand-written SQL, deliberately. `UPDATE users SET blocked_at = NOW()`
works the moment the column exists, but one mistyped WHERE blocks every
account and records nothing. Fine as an emergency fallback, not as the
mechanism.

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


def _accounts():
    """Every account, with its block state."""
    from utils import get_db_connection

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email, blocked_at, blocked_reason FROM users ORDER BY id")
        rows = cursor.fetchall()
        cursor.close()
        return rows
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email", nargs="?",
                        help="email of the account to block (see --list)")
    parser.add_argument("--unblock", action="store_true",
                        help="lift the block instead of applying one")
    parser.add_argument("--reason",
                        help="admin-facing note on why (blocking only)")
    parser.add_argument("--list", action="store_true",
                        help="list accounts with their block state and exit")
    args = parser.parse_args(argv)

    if args.list:
        rows = _accounts()
        if not rows:
            print("no accounts")
            return 0
        for user_id, email, blocked_at, reason in rows:
            state = f"BLOCKED since {blocked_at}" if blocked_at else "active"
            print(f"{user_id:>4}  {email:<40} {state}"
                  + (f"  ({reason})" if blocked_at and reason else ""))
        return 0

    if not args.email:
        # A bare invocation must never touch a row.
        parser.error("an email is required (or --list)")
    if args.unblock and args.reason:
        parser.error("--reason applies to blocking, not unblocking")

    from utils import set_user_blocked

    result = set_user_blocked(args.email, blocked=not args.unblock,
                              reason=args.reason)
    if result is None:
        # A miss is reported as a miss: a typo must not look like success.
        print(f"no account with email {args.email}", file=sys.stderr)
        return 1

    user_id, was_blocked = result
    if args.unblock:
        if not was_blocked:
            print(f"account {user_id} <{args.email}> was not blocked; nothing changed")
            return 0
        print(f"account {user_id} <{args.email}> is now UNBLOCKED")
    else:
        print(f"account {user_id} <{args.email}> is now BLOCKED"
              + (f" ({args.reason})" if args.reason else ""))
        if was_blocked:
            print("  (it was already blocked; the timestamp and reason are updated)")
        print("  They can still read the site. They cannot add or delete cards,")
        print("  and Mykola's widget is not shown to them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
