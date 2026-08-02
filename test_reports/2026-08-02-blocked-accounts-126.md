# Test Report — blocking an account

**PR:** [kuantorflow#183](https://github.com/Kuantor/kuantorflow/pull/183) + [kuantorflow_automation#41](https://github.com/Kuantor/kuantorflow_automation/pull/41) · **Issue:** [kuantorflow#126](https://github.com/Kuantor/kuantorflow/issues/126) · **Date:** 2026-08-02

## Summary

An account can now be blocked: the learner keeps every read-only part of the
site and their own settings, but cannot change the database or talk to Mykola,
and is told which admin to write to. Verified end to end against local MySQL
with a throwaway account blocked by the real admin script. **424 offline tests
pass** (was 388). The first schema change to go through #180's migration list.

## What changed

- **`users.blocked_at` / `users.blocked_reason`** — a nullable timestamp, so
  "blocked?" and "since when?" are one column and unblocking is clearing it.
  Added as a `Step` in `apply_schema.py`, two `ADD COLUMN`s in one `ALTER` so
  they arrive together.
- **`app.current_block()` / `is_blocked()`** — read live per signed-in
  request, cached in `g`. Not stamped into the session: a session cookie lasts
  30 days and a block must take effect on the next request. Never asked for an
  anonymous visitor; a failed lookup means no block is visible.
- **Refusals in the routes** — card writes share #125's path via
  `add_refusal()`; the delete route checks the block before ownership;
  `/mykola/chat` refuses before its length and content checks; the recap and
  restart-check endpoints answer as if there were no conversation.
- **`blocked_notice()`** names an address from `ADMIN_EMAILS`, and stops after
  the fact when none is configured. Shown in the refusal dialog (with no
  sign-in link — they are signed in already) and in the Settings popup.
- **`utils.set_user_blocked()`** — the mutation, called by
  `maintenance/block_user.py` and logging `USER-BLOCK` / `USER-UNBLOCK`
  itself.

## Automated tests

- **Added:** `tests/test_blocked_accounts.py` — 36 tests: refusal on every
  write path with block wording rather than #125's sign-in prompt; the admin
  address named, and the message still sensible with `ADMIN_EMAILS` empty; the
  widget hidden *and* the chat endpoint refusing a hand-made request without
  calling the model; reading, lookups and own settings untouched; unblocking
  restoring everything; the block read once per request and never for an
  anonymous visitor; a dead database not locking the site; and
  `set_user_blocked()` directly — exact matching, a miss reported as a miss,
  both columns cleared on unblock, and the log lines.
- **Added:** autouse `block_state` fixture in `conftest.py`. Without it the
  offline suite would open a real connection on every signed-in request — the
  same trap the `saved` fixture exists for.
- **Fixed:** the `apply_schema` tests asserted "4 migrations" as a literal, so
  a fifth broke four unrelated assertions. They now count from `MIGRATIONS`.
- **Suite result:** `pytest -m "not live"` — **424 passed, 6 skipped**
  (was 388 passed, 6 skipped).

## Manual & browser verification

A throwaway account (`blocked.probe@example.com`) was created in the local
database, blocked with the real script, and removed afterwards along with its
card and settings file.

**The migration**, before anything else: `apply_schema.py --dry-run` reported
exactly one pending change (`~ users.blocked_at`), applying it printed
`+ users.blocked_at   applied`, and the re-run reported `nothing to do - 8
object(s) already in place`.

**The script:** `--list` showed both accounts and their state; blocking
printed what it did and what it means; `--unblock` twice reported
`is now UNBLOCKED` then `was not blocked; nothing changed`; an unknown email
exited **1** with `no account with email …`.

**Live HTTP**, with that account's session against the running server:

| Request | Result |
| --- | --- |
| `POST /cards/add` | **403**, block message naming the admin |
| `POST /mykola/chat` | **403**, same message |
| `POST /mykola/restart-check` | `{"restart": false, "reason": "blocked"}` |
| `POST /settings` | **200** — their own preference still saves |
| `GET /flashcards/character` | **200** — reading stays open |

**Rendered pages** (produced by the app, served from it so the real CSS
applies), at 1280×720:

- The delete cross carries `aria-disabled="true"` with the block message as
  its `title`, and computes to the muted colour with `cursor: default` — the
  #162 greying pattern, with the new reason.
- `#mykola-panel` is absent; it is present for the same account once
  unblocked.
- The Settings notice renders with its red left border inside the modal
  (627px inside 700px), carrying the admin address.

**After unblocking:** `POST /cards/add` returned **200 saved**, the widget was
back, and the notice was gone.

**One defect found and fixed during this run:** unblocking twice wrote two
`USER-UNBLOCK` lines, though the second changed nothing. The log now records
an unblock only when a block was actually lifted, with a test for it.

**Cleanup:** probe card, probe user row, `settings/config-12.json` and the two
rendered probe pages all removed; `SELECT` afterwards shows only the real
account, unblocked.

## Result

**Pass**, against every acceptance criterion in the issue.

Not covered here:

- **The blocked view was not driven through a real Google sign-in** — the
  browser cannot be handed a session cookie (it is HttpOnly), so the pages
  were rendered by the app itself and inspected in the browser with the real
  stylesheet. Behaviour is covered by the suite and by the live HTTP checks
  above.
- **Deploy is not a no-op this time**: `apply_schema.py` on PythonAnywhere
  will add both columns.
