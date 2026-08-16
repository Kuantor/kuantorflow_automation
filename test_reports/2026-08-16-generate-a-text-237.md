# Test Report — Generate a text from your own words

**PR:** kuantorflow#306 (+ kuantorflow_automation#90) · **Issue:** kuantorflow#237 · **Date:** 2026-08-16

## Summary

Claude writes a short passage using words from the selected topics, and the words are found in it by matching and shown in bold. Verified against the real deck and the real API; the suite runs with the call stubbed.

## What changed

- `textgen.py` — the call: model constant, `max_tokens` = words × 1.5, a prompt carrying the bare words only, failure logged through `applog`.
- `games.py` — `find_word()` / `mark_words()`, the stem-tolerant matcher #235 also needs; `Words` bounds, so the picker's box means questions for a quiz and words of prose here.
- `text_generation_usage` + `claim_text_generation()` — per-account and site-wide daily ceilings, claimed before the call (#200).
- The round, its template and CSS; `read_a_text` loses its `ticket`.

## Automated tests

- **Added:** `test_generated_text.py` (34), `test_word_matching.py` (32), `test_generation_limits_db.py` (8). **Updated:** three hardcoded table lists/counts in the two `apply_schema` files.
- **Suite:** `pytest -q` — **1105 passed**, 74 skipped. `RUN_DB_ROUNDTRIP=1` — **1187 passed**, 0 failed. The DB run was done because this adds a table and a query, and it caught one failure the offline run could not see.

## Manual & browser verification

- 150 words over *Crime and justice* → 12 of 14 words highlighted; `prosecute`/`guilty` correctly reported unused, the text having said "prosecutors"/"guilt".
- 220 words over three topics → 220 words back, 13 of 16 used.
- Two refreshes and a server restart → text still shown, still one `GENERATE` line.
- Anonymous ceiling → second text refused, sign-in offered, first text kept, no API call.
- No `ANTHROPIC_API_KEY` → tile hidden, 404 on picker and round, other games fine.
- Ceilings on local MySQL: per-account and site-wide refusals, anonymous counted only site-wide, refused claims not advancing the row.
- `apply_schema.py --dry-run` → one pending step; re-run says `nothing to do`.

## Result

Pass. One deliberate departure from the ticket: the everybody row is keyed `user_id = 0`, not NULL — MySQL treats NULLs in a unique key as distinct, so the NULL row would have been re-inserted per generation rather than incremented.
