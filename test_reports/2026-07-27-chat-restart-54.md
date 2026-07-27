# Test Report — Automatic chat restart after a break

**PR:** kuantorflow#156 (+ ai_agent#60, kuantorflow_automation#26) · **Issue:** ai_agent#54 · **Date:** 2026-07-27

## Summary

A conversation left idle longer than the learner's `restart_chat_interval`
(hours; **2** by default, `0` = never) is restarted when they return: Mykola
reviews their last three exchanges, welcomes them back, and a new chat-log
file is opened. Verified end-to-end against the running app with a real Claude
recap; 30 new offline tests. Suite: **180 passed**, was 150.

## What changed

Three repos, because the feature straddles them.

- **ai_agent** — `recap(…, away_hours=None)`. Given the gap, the prompt tells
  Mykola the learner has been away *about 5 hours* and asks him to open by
  acknowledging it in one warm sentence. `build_recap_prompt()` and
  `describe_gap()` are module level so the wording is checkable without an API
  call. The parameter is optional, so an older KuantorFlow keeps working.
- **kuantorflow**
  - `settings_store` — `restart_chat_interval: 2`, validated through a new
    `RANGES` table (0–24, whole numbers only; booleans and fractions rejected).
  - `POST /mykola/restart-check` — the decision endpoint. Reads the user's
    threshold, measures the break, and on a restart mints a chat id, asks
    Mykola for a recap of the last three exchanges, opens the new log file and
    returns all of it. Every failure path answers `{"restart": false}`.
  - `_last_exchanges(3)` splits chat logs on their timestamp headers, so the
    restart reviews the last three *messages* rather than the last three log
    *files* the welcome-back recap uses.
  - `_agent_kwargs(method, away_hours=…)` — feature-detected, like the existing
    `user_name` / `hidden_languages` kwargs.
  - Widget: asks the server on load whenever a conversation was restored,
    sending its own last-message stamp; on a restart it wipes the thread,
    adopts the new chat id and shows the recap. `newChat()` now shares the
    same `startFreshChat()` helper.
  - Settings popup: full-width fieldset with the 1–24 slider, a live `N h`
    readout and the **Never restart chat automatically** checkbox that greys
    the slider out.

## Automated tests

- **Added:** `tests/test_chat_restart.py` — 30 tests: the setting's default and
  validation table, saving 0 through `POST /settings`, the endpoint's five
  answers (within interval, past it, disabled, no history, Mykola
  unavailable), a clock-skewed future stamp being ignored, only the last three
  exchanges reaching the agent, the new log file's content, the break being
  measured from the newest log for signed-in users, a failing recap still
  restarting, anonymous restarts without a recap, feature detection against an
  older `recap()`, and the Settings markup at 0 / 9 hours.
- **Added (ai_agent):** `check_recap_prompt()` in `test_agent_prompt.py` —
  `describe_gap()` wording and that the break sentence appears only with
  `away_hours`.
- **Fixed a pre-existing leak:** the suite's chat tests were writing real files
  into the kuantorflow checkout's `mykola_logs/`. A new autouse `chat_logs`
  fixture redirects `app.LOG_DIR` to a temp directory, like `settings_dir` and
  `action_logs` already do. 17 stray files from today's runs were removed.
- **Suite result:** `pytest -m "not live"` — **180 passed**, 1 skipped,
  6 deselected (was 150).

## Manual & browser verification

Dev server + local MySQL. Server-side flow driven as a signed-in user (session
cookie signed with the app's own key), with a five-hour-old chat log seeded for
the probe user:

| Check | Outcome |
|---|---|
| Last message 10 minutes ago | `{"restart": false, "away_hours": 0.17}` |
| Last message 5 hours ago (threshold 2) | `restart: true`, `away_hours: 5.0`, new `chat_id` |
| The recap itself (real Claude call) | *"Welcome back, Restart — good to see you again after your little interlude. When last we spoke, you saved the splendid word **resilient**…"* — covers exactly the last three exchanges, opens with the break |
| New chat-log file | created, starting `--- Chat restarted automatically after 5.0h away ---` followed by the recap |
| Interval set to 0 | `{"restart": false, "reason": "disabled"}` |
| Browser: stale conversation in `localStorage` (3 messages, 5h old), page reloaded | thread wiped to Mykola's greeting, new `chat_id` adopted, history cleared, `lastMessageAt` reset |
| Browser: second page load | no second restart — the chat id stayed put |
| Settings popup (anonymous) | slider min 1 / max 24 / value 2, readout "2 h", full-width row, everything disabled by the #102 read-only freeze |

The probe user's log directory and config file were deleted afterwards, and
the anonymous restart's marker file removed from the shared log dir.

## Result

**Pass.** Deploy note: both repos should be pulled, but either order works —
`away_hours` is feature-detected, so a new KuantorFlow against an old ai_agent
simply gets a recap without the break sentence.
