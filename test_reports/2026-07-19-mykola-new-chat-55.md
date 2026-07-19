# Test Report — Mykola widget "New Chat" button

**PR:** kuantorflow#<pending> · kuantorflow_automation#<pending> · **Issue:** Kuantor/ai_agent#55 · **Date:** 2026-07-19

## Summary

Added a small "New Chat" (＋) button to the Mykola chat widget that starts a fresh conversation and, for signed-in visitors, re-runs the welcome-back recap. Verified end-to-end in the browser (including a real API round-trip) and with 3 new tests; offline suite 97 → **100 passed**.

## What changed

- A small, unobtrusive header button (＋), styled to match the existing max/min/close controls.
- `newChat()` clears the thread and `uiMessages`, restores the opening greeting, and resets `chatId` to `null` so the next message mints a new server-side log — past exchanges stay logged, so nothing is lost.
- For signed-in visitors it also resets the recap guard and re-runs `requestRecap()` (Mykola's review of recent conversations), exactly as at the start of a new session. Anonymous visitors get the clean reset only (they have no recap).
- The opening greeting is now built once (Jinja + `tojson`) and reused by `newChat()` and the state-restore path — also fixing a latent bug where a Google display name containing an apostrophe would have broken the inline JS string.

## Automated tests

- **Added:** `tests/test_mykola_widget.py` — 3 tests: the button + `newChat()` handler + click wiring render in the widget; the recap re-run appears inside `newChat()` for a signed-in visitor; and does **not** for an anonymous visitor (extracted from the `newChat` function body specifically).
- **Suite result:** `pytest -m "not live"` — **100 passed**, 1 skipped, 6 deselected (was 97).

## Manual & browser verification

Local dev server, anonymous visitor, desktop:

- Opened the widget → **New Chat button present**, glyph ＋, title "New chat — start over", 29×29 px (identical to the sibling header buttons). → OK
- Sent a real message ("Say hi in one word.") → got Mykola's reply; thread = 3 messages (greeting, user, Mykola), `history` length 2, a `chatId` assigned. → OK
- Clicked **New Chat** → thread back to **1 message (the greeting)**, `history` empty, **`chatId` null** (next message starts a new log), input re-focused. → OK
- Console: no errors.

Signed-in recap re-run was validated by test (the recap path reuses the existing, already-proven `requestRecap()` used on panel open).

## Result

Pass. The button starts a fresh conversation as specified — small and unobtrusive, non-destructive to the server-side logs, with the recap re-run for signed-in visitors.
