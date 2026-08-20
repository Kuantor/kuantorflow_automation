# Manual Test Plan — Speech

**Covers:** kuantorflow#268 (the speech helper and the rate setting) and #272 (*Listen and type*) · **Date:** 2026-08-20

## Why this exists

The pytest suite cannot hear anything, and a headless browser generally has no voices at all. Everything either side of the audio is covered automatically — the setting sanitises and clamps, the round grades server-side, the page carries the right markup — but **whether a word is actually spoken, in the right voice, at the right speed, is only ever established by a person with speakers on**.

That is not a theoretical gap. Two bugs in this area reached a merged branch with the whole suite green, and both were found by playing the app:

- the availability probe read `window.kfSpeech` before the deferred module had loaded, so every browser was told it had no English voice;
- the Settings slider snapped back to the middle on reopening, because `form.reset()` restores page-load defaults.

Neither was visible to a test that checks markup. Assume this class of bug is what you are hunting.

## Before you start

Sign in — the rate slider is deliberately dead for anonymous visitors (#102), so a signed-out session cannot exercise most of section A.

Two things worth knowing in the browser console:

- `window.kfSpeech.voices()` prints the voice list the module chose from.
- `document.body.dataset.speechRate` is the value speech.js reads on every press.

## A. The rate setting (#268)

| # | Do this | Expect |
|---|---|---|
| A1 | Set 50%, save, press a speaker | Noticeably slower. ✅ *confirmed* |
| A2 | Change the rate and press again **without reloading** | New speed applies at once. ✅ *confirmed* |
| A3 | Set 150%, save, press | Faster, and still intelligible |
| A4 | Save 50%, close the popup, reopen it | Slider **and** the number both read 50% |
| A5 | Drag to 80%, close **without** saving, reopen | Shows the saved value, not 80% |
| A6 | Save 6 in *Cards per round*, reopen the popup | Shows 6, not 10 — same bug class as A4 |
| A7 | Sign out, open Settings | Slider greyed and unmovable |
| A8 | Set a rate, then hard-reload the page | Rate survives; it is stored per account |

## B. Listen and type (#272)

| # | Do this | Expect |
|---|---|---|
| B1 | Open a round | Play buttons and boxes only — **no words on screen** |
| B2 | Press play | The word is spoken |
| B3 | Press play four times quickly | You hear it once more, not four times over |
| B4 | Load the round and wait, touching nothing | Silence. Nothing may speak without a press |
| B5 | Type answers with capitals, a trailing full stop, a hyphen typed as a space | All marked correct |
| B6 | Type a homophone (*their* for *there*) | Marked **wrong** — this is the exercise |
| B7 | Submit | Results show each word with its meaning or translation |
| B8 | Press a speaker on the results page | Speaks, at the rate set in Settings |
| B9 | Change the rate mid-round, return, press play | New speed, without restarting the round |

## C. The speaker button elsewhere (#283)

The rate lives inside `speak()`, so **every** caller should obey it. Each of these was only tested as a mechanism, not per surface.

| # | Do this | Expect |
|---|---|---|
| C1 | Card deck — press the speaker on a card | Speaks at the set rate |
| C2 | Card deck — press the speaker | The card must **not** flip |
| C3 | Flashcard list — press a speaker | Speaks at the set rate |
| C4 | Look up a word, press the speaker in the review popup | Speaks at the set rate |

## D. Browsers and devices

Voice availability is a property of the browser, not of the app, and it is the one thing the server genuinely cannot know.

| # | Where | Expect |
|---|---|---|
| D1 | Chrome | Speaks; `voices()` lists an `en-GB` or `en-US` voice |
| D2 | Edge | Speaks |
| D3 | Firefox | Speaks, or shows the no-voice panel if none are installed |
| D4 | iPhone / iPad Safari | First **press** speaks. Nothing autoplays |
| D5 | Any browser with no English voice | *Listen and type* shows its panel and offers other activities; speaker buttons disappear rather than sitting there dead |
| D6 | An English word while the browser's default voice is Ukrainian or Russian | Read by an English voice, not through Cyrillic phonology |

D5 is hard to stage deliberately. A Linux machine with no speech packages is the usual way; failing that, it is the one case worth leaving to production.

## E. Judgement calls — only you can decide these

- **Is 150% still usable, or gibberish?** If gibberish, the ceiling is wrong and should come down.
- **Does 50% distort the word?** Some engines stretch phonemes badly below about 70%. If so, the floor should come up.
- **Is dictation at a slow rate a fairer test, or a different one?** A word slowed to half speed is arguably not the word a learner will meet in conversation.
- **Are multi-word expressions good listening questions?** *Take for granted* was kept deliberately, on the theory that catching the unstressed middle is the harder and better skill. Worth confirming it does not just sound mangled.

## F. Known limits — not bugs

- **Two tabs.** Save a rate in one; the other keeps its old value until reloaded. The value is rendered per page load, and a cross-tab sync was judged not worth the machinery.
- **The word is in the page source.** `speechSynthesis` needs the text in the browser, so a learner who opens view-source can read the answers. Inherent rather than an oversight; nothing in the round is scored or recorded.
- **Voice quality varies wildly.** This is a listening exercise, not a pronunciation reference — a dictionary is better for the latter, and the guide says so.

## Recording what you find

Report a failure by its number, plus the browser and what `window.kfSpeech.voices()` printed. That list is almost always the fastest way to narrow a speech bug, because it separates *"the app chose badly"* from *"the browser had nothing to choose from"*.
