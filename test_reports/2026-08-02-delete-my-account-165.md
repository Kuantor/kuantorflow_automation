# Test Report — Delete my account, with a keep-or-delete choice for the cards

**PR:** kuantorflow#179 (+ kuantorflow_automation#38) · **Issue:** kuantorflow#165 · **Date:** 2026-08-02

## Summary

A signed-in user can delete their own account from the Settings popup, choosing whether their flashcards stay for other learners or go with the account. Verified against the real local database in both directions, including that the `ON DELETE RESTRICT` guarantee from #89 actually fires when the cards are not resolved first — which is the whole reason that decision was made.

## What changed

- `utils.resolve_user_cards(user_id, keep_cards)` — "keep" sets `added_by_user_id = NULL` (community property, admin-only under #162); "delete" removes them. Both branches are scoped by owner.
- `utils.delete_user(user_id)` — the users row, deleted **last**.
- `app.delete_account(user_id, keep_cards)` — orchestrates cards → files → row. Free of Flask request state, so the admin script calls exactly what the route calls.
- `POST /account/delete` — signed-in only; a sign-in whose users row could not be written (#148) has no account and is refused too.
- Settings popup: a **Delete account** control, visible only to a signed-in visitor, opening a confirmation that names what goes and carries the card choice.
- `applog.account_deleted()` → `ACCOUNT-DELETE id=… cards=… choice=…`.
- `maintenance/delete_account.py` in this repo — the admin entry point, with `--list`, an email-typing confirmation, and no default for the card choice.

## Why the order matters

Files cannot join a database transaction, so a failure midway must leave the account in a state that can be retried. While the users row exists the account is still coherent; once it is gone, leftover files and cards have nothing to attribute them to. Hence: resolve the cards, delete the files, delete the row last.

## Automated tests

- **Added:** `tests/test_account_deletion.py` — 25 tests: both card branches and their exact SQL, ownership scoping on every statement, the orchestration order, the route (keep / delete / missing / junk choice), the session identity cleared while the gate pass survives, anonymous and id-`None` refusals, a failure removing nothing and not signing the user out, `GET` rejected, the log line's contents *and* its absence of an address, and the dialog markup including the danger styling and the preselected non-destructive option.
- **Suite result:** `pytest -m "not live"` — **347 passed** (was 322), 1 skipped, 6 deselected.

## Real-database verification

Probe accounts with cards, chat logs and settings files, then both branches end to end:

| Check | Result |
| --- | --- |
| Deleting the users row **without** resolving cards | Refused — `1451 … Cannot delete or update a parent row` |
| **Keep**: cards after deletion | Both survive with `added_by_user_id = NULL` |
| **Keep**: log dir, settings file, users row | All removed |
| **Delete**: the user's own cards | Removed |
| **Delete**: a bystander's card in the same topic | Untouched, owner intact |
| Cleanup | Probe rows and files removed; only the real account remains |

## One thing the tests caught

`test_a_missing_or_junk_choice_keeps_the_cards` failed on its second request — because the first deletion had already signed the client out, so the second was refused as anonymous. Not a product bug: the test was wrong, and the failure is the session-clearing behaviour working. Fixed by re-establishing the session between the two requests.

## Result

**Pass.** Every acceptance criterion in #165 met, including the admin-side script and the "fails loudly" property of the foreign key.

Not done: the dialog was verified through its rendered markup and the test suite, **not** eyeballed in a browser — worth a look at the confirmation's layout before deploying, since it is the one screen a user sees only once and cannot undo.
