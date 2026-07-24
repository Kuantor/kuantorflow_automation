# Test Report — Early duplicate-word warning on lookup

**PR:** kuantorflow#<pending> · kuantorflow_automation#<pending> · **Issue:** kuantorflow#145 · **Date:** 2026-07-19

## Summary

Looking up a word that already has cards now shows a **warning modal before the (slow) lookup and the review dialog** — "You already have card(s) for X … look it up anyway?" — instead of silently going through the motions. The save-time duplicate skip (#101) is unchanged. Verified end-to-end in the browser against the real local DB; 6 new offline tests, suite 108 → **114 passed**.

## What changed

- **`utils.flashcard_word_exists(word)`** — `SELECT 1 FROM flashcards WHERE word = %s LIMIT 1`, case-insensitive per the column collation.
- **`app.py`** — the `parse_word` branch checks `flashcard_word_exists` (via `_word_already_saved`, which swallows DB errors → "unknown" → no warning) before running the lookup. If the word exists and `force_lookup` isn't set, it renders a `duplicate_warning` instead of doing the lookup.
- **`templates/index.html`** — a Yes/No warning modal shown when `duplicate_warning` is set: **"Look up anyway"** resubmits the lookup with a hidden `force_lookup=1` (bypassing the check); **Cancel / backdrop / Escape** dismiss it.

## Automated tests

- **Added:** `tests/test_lookup_and_cards.py` (4) — existing word warns and does **not** run the lookup or open the review popup; `force_lookup=1` bypasses the warning into the review popup; a new word skips the warning; a DB error during the check degrades gracefully (proceeds, no warning). Plus `tests/test_duplicates.py` (2) — `flashcard_word_exists` true/false with the expected query. An `app_module`-fixture default (`flashcard_word_exists → False`) keeps the other lookup tests isolated from the real DB.
- **Suite result:** `pytest -m "not live"` — **114 passed**, 1 skipped, 6 deselected (was 108).

## Manual & browser verification

Local dev server + real local MySQL (an existing word, `apprehensive`):

- Looked up `apprehensive` (already in the DB) → **warning modal shown**: "You already have card(s) for "apprehensive" in the database. Look it up and add cards anyway?", with **Look up anyway** + **Cancel**; the review popup was **not** opened. → OK
- **Cancel** → modal dismissed. → OK
- **Look up anyway** / a brand-new word → proceeds to the review popup (proven at the route level with a stubbed lookup). → OK
- Console clean.

## Result

Pass. The repeated word is caught and the user is warned immediately, before any lookup — matching #145 — while the #101 save-time guard remains the backstop.
