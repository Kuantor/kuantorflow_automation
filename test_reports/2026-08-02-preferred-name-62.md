# Test Report — Mykola remembers what to call you

**PRs:** [ai_agent#65](https://github.com/Kuantor/ai_agent/pull/65) + [kuantorflow#188](https://github.com/Kuantor/kuantorflow/pull/188) + [kuantorflow_automation#43](https://github.com/Kuantor/kuantorflow_automation/pull/43) · **Issue:** [ai_agent#62](https://github.com/Kuantor/ai_agent/issues/62) · **Date:** 2026-08-02

## Summary

Telling Mykola *"call me Ann"* now sticks: a `set_preferred_name` tool in the
agent, a saver injected by KuantorFlow that writes `users.preferred_name`.
Verified against the **live model**, not only the handler — the tool is
reached for, the name is used from the next message, and "go back to my proper
name" clears it. **464 offline tests pass** (was 449), plus the agent repo's
own scripts. No schema change: the column shipped unused with #148.

## What changed

**ai_agent**

- `SET_PREFERRED_NAME_TOOL` + `TOOLS`, and `_run_set_preferred_name()`
  returning a JSON status the model relays — including its refusals.
- `_run_tool()` dispatches on the block name; the loop no longer assumes every
  `tool_use` is a card.
- `clean_preferred_name()` — collapses whitespace (removing the newlines an
  injection needs) and caps at 40 characters.
- `_personalized_system()` uses the name **whole** rather than its first token.
- `MykolaAgent(name_saver=…)`, with **no standalone fallback**: this repo has
  no notion of an account.

**kuantorflow**

- `utils.set_preferred_name()`; `app._save_preferred_name_from_chat()` injected
  in `get_mykola()`, feature-detected alongside `card_saver`.
- The saver refuses anonymous learners by raising, updates the session copy so
  the name applies from the next message, and logs `PREFERRED-NAME`.

## Automated tests

- **Added:** `kuantorflow_automation/tests/test_preferred_name.py` — 15 tests:
  who may store a name, clearing writing `None`, a missing account reported,
  the session updated (and the rest of the identity preserved), both log
  lines, injection only when the agent accepts it, an older agent still
  building, and the exact `UPDATE` with `NULL` bound when clearing.
- **Added:** `ai_agent/test_preferred_name.py` — a plain assert script, matching
  that repo's convention: cleaning, capping, newline stripping, saving,
  clearing, both refusal paths, dispatch, and that the constructor still
  accepts `name_saver` by that name (the host feature-detects on it).
- **Suite result:** `pytest -m "not live"` — **464 passed, 6 skipped**
  (was 449 passed, 6 skipped). `python test_preferred_name.py` and
  `python test_agent_prompt.py` both pass in `ai_agent`.

## Manual verification — against the live model

The handler can be unit-tested; whether the model *reaches for the tool*
cannot. Four real conversations, with a stand-in `name_saver` recording calls:

1. **"Actually, Anna Maria is a bit of a mouthful — please call me Ann."**
   → *"Splendid — Ann it shall be from now on."* `name_saver` received `"Ann"`.
2. **"What did I ask you to call me?"** (next message, new name passed in)
   → *"You asked me to call you **Ann** — the short form of Anna Maria, which
   you rather sensibly deemed a mouthful."*
3. **"On reflection, go back to my proper name please."**
   → *"Of course — your proper name is restored, Anna Maria."* `name_saver`
   received `None`, not the string "Anna Maria".
4. **Anonymous learner** (saver raises) → *"I should very much like to, Ann —
   but… without an account there is nowhere for me to keep the note. If you
   sign in with Google, I shall remember it faithfully thereafter. In the
   meantime… I shall call you Ann for the remainder of our conversation."*
   And with **no saver injected at all** (older KuantorFlow), the same honest
   refusal. Nothing was claimed that had not been stored.

No database was touched by any of this: the saver was a stand-in that recorded
its argument.

## Result

**Pass**, against every acceptance criterion in the issue: the tool exists with
the saver injected by the host; "call me X" persists and is used from the next
message; "use my real name again" clears to `NULL`; an anonymous learner gets a
graceful in-character refusal; stored values are capped and newline-free; and a
KuantorFlow that does not inject the saver still works.

Worth noting:

- **A behaviour change rode along**: `_personalized_system()` no longer
  truncates the name to its first token. That guard was redundant once the
  value is collapsed and capped, and it silently overruled #148 — Mykola was
  addressing *Anna Maria* as "Anna" while the site called her Anna Maria.
- **Not verified through the browser widget.** The chat endpoint passes
  `user_name` from the session and the saver was exercised directly; a
  full-stack run needs a real Google sign-in.
- **The Settings text field** for the same column (noted in kuantorflow#148)
  is still unbuilt — this is the AI route only.
