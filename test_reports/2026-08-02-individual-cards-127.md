# Test Report — Use only individual cards

**PR:** [kuantorflow#187](https://github.com/Kuantor/kuantorflow/pull/187) + [kuantorflow_automation#42](https://github.com/Kuantor/kuantorflow_automation/pull/42) · **Issue:** [kuantorflow#127](https://github.com/Kuantor/kuantorflow/issues/127) · **Date:** 2026-08-02

## Summary

A per-user view filter that hides everyone else's cards from the topic list,
topic page, deck, quiz and the widget's chip refresh. Verified against a real
database with two accounts side by side: the filtered account saw only its own
two cards, while the other account saw all 53. **449 offline tests pass**
(was 424). No schema change.

## What changed

- **`individual_cards`** in `settings_store.DEFAULTS`, off by default —
  `BOOLEAN_KEYS` derives from `DEFAULTS`, so the setting itself is one line.
- **`utils._owner_clause()`**, used by `get_topics(owner_id)` and
  `get_flashcards_by_topic(topic, owner_id)`. Filtering is in SQL so no page
  can render a card the query should not have returned.
- **`app.cards_owner_filter()`** — the only thing that decides whether a
  filter applies, returning `None` (no clause) when the setting is off *or*
  there is no account to filter by. Applied at all five read call sites.
- **Empty states** on the topic page, the topic list, the deck, and an extra
  line on the quiz — each says the filter is why, not "nothing here".
- **The checkbox** in the Settings popup, disabled for anonymous visitors, and
  a page reload after saving it (only this setting changes what the current
  page shows).

## Automated tests

- **Added:** `tests/test_individual_cards.py` — 25 tests: the setting itself
  (default, type, junk fallback, round trip through `POST /settings`); which
  owner each of the five read paths asks for, and that an anonymous visitor is
  never filtered; the SQL actually built — **no clause** when unfiltered
  rather than `= NULL`, an equality clause bound as a parameter when filtered,
  and never an inequality; and the four empty states, including that they are
  unchanged when the filter is off.
- **Migrated:** every stub of `get_flashcards_by_topic` / `get_topics` for the
  new `owner_id` argument — 28 tests across 8 files were calling the old
  signature.
- **Suite result:** `pytest -m "not live"` — **449 passed, 6 skipped**
  (was 424 passed, 6 skipped).

## Manual & browser verification

Against local MySQL, which already held 53 cards across six topics owned by
the real account. A throwaway account was added with two cards of its own in a
seventh topic, and both accounts were driven over real HTTP against the
running server.

**The filtered account:**

| Path | Filter off | Filter on |
| --- | --- | --- |
| topic chips on `/` | 7 topics | `probe-own` only |
| `/topics.json` | all | `[["probe-own", 2]]` |
| `/flashcards/general` | 40 cards | 0 + "No cards of your own…" |
| `/flashcards/probe-own` | 2 cards | 2 (`probeword`, `probeword2`) |
| `/deck/general` | cards | "No cards of your own in this topic…" |
| `/deck/probe-own` | 2 cards | 2, deck working (`1 / 2`, flip) |
| `/quiz/general` | quiz | "nothing to quiz on" + the filter note |

**The account next door**, signed in throughout: still saw **all 7 topics
including the probe account's**, and **all 40 cards** in `general`. The filter
is per-user and lives in the query — it is not a global mode.

**Turning it on** was done through `POST /settings`, which returned the stored
value, i.e. the same path the popup's Save uses.

**Found during this run:** the deck and the quiz still used their old "No
flashcards saved under this topic yet" wording when the filter emptied them —
the misleading message the topic page had already been fixed for. Both now
name the filter, with tests.

**Cleanup:** probe cards, probe user row and `settings/config-13.json`
removed; the database afterwards holds only the real account and its 53 cards.

## Result

**Pass.** The filter shows only the user's own cards on every read path,
leaves other accounts untouched, and explains itself wherever it empties a
page.

Left deliberately:

- **Duplicate prevention stays global** (#101), so a word saved by someone
  else is skipped even when hidden — the app can report "already in the
  database" about a card the user cannot see. Making dedup per-owner changes
  what is *stored* for everyone, so it is filed as
  [#186](https://github.com/Kuantor/kuantorflow/issues/186) with options.
- **Not driven through a real Google sign-in** — the browser cannot be handed
  a session cookie (HttpOnly), so both accounts were driven over HTTP against
  the running server with minted sessions, and the rendered pages inspected.
