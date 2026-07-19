# Test Report — Mykola widget "New Chat" button

**PR:** kuantorflow#<pending> · kuantorflow_automation#<pending> · **Issue:** Kuantor/ai_agent#55 · **Date:** 2026-07-19

## Summary

Added a "New Chat" button (a ✎ compose-pencil glyph) to the Mykola chat widget. Clicking it opens a **Yes/No confirmation** ("Do you really want to start a new conversation?"); on Yes it starts a fresh conversation and, for signed-in visitors, re-runs the welcome-back recap. Verified end-to-end in the browser (including a real API round-trip) and with 3 new tests; offline suite 97 → **100 passed**.

## What changed

- A small, unobtrusive header button, styled to match the existing max/min/close controls. (Iterated on the glyph: a supplied `new_chat.png` reload icon read as an unwanted ring, so it was dropped in favour of a ✎ pencil glyph.)
- The pencil opens a **confirmation dialog** (Yes/No, matching the app's card-delete and Reset Auth confirms), layered above the widget panel (z-index 400 > 200). Yes resets; No / backdrop / Escape cancel.
- `newChat()` (run on Yes) clears the thread and `uiMessages`, restores the opening greeting, and resets `chatId` to `null` so the next message mints a new server-side log — past exchanges stay logged, so nothing is lost.
- For signed-in visitors it also resets the recap guard and re-runs `requestRecap()` (Mykola's review of recent conversations), exactly as at the start of a new session. Anonymous visitors get the clean reset only (they have no recap).
- The opening greeting is now built once (Jinja + `tojson`) and reused by `newChat()` and the state-restore path — also fixing a latent bug where a Google display name containing an apostrophe would have broken the inline JS string.

## Automated tests

- **Added:** `tests/test_mykola_widget.py` — 3 tests: the pencil button + the confirmation dialog markup (question, Yes/No) render and the pencil opens the confirm while `newChat()` runs on Yes; the recap re-run appears inside `newChat()` for a signed-in visitor; and does **not** for an anonymous visitor (extracted from the `newChat` function body specifically).
- **Suite result:** `pytest -m "not live"` — **100 passed**, 1 skipped, 6 deselected (was 97).

## Manual & browser verification

Local dev server, anonymous visitor, desktop:

- Opened the widget → **New Chat pencil present**, ✎ glyph, 29×29 px (identical to the sibling header buttons). → OK
- Sent a real message → got Mykola's reply; a multi-message thread with `history` and a `chatId` assigned. → OK
- Clicked the pencil → **confirmation dialog shown** ("Do you really want to start a new conversation?"), z-index 400 above the panel (200); the thread was **not** reset yet. → OK
- Clicked **No** → dialog closed, thread unchanged. → OK
- Clicked the pencil → **Yes** → thread back to **1 message (the greeting)**, `chatId` null (next message starts a new log), input re-focused. → OK
- Console: no errors.

Signed-in recap re-run was validated by test (the recap path reuses the existing, already-proven `requestRecap()` used on panel open).

## Result

Pass. The button starts a fresh conversation as specified — small and unobtrusive, non-destructive to the server-side logs, with the recap re-run for signed-in visitors.
