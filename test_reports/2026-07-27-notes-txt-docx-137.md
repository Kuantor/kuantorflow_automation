# Test Report — Notes upload: .txt and .docx besides .mht

**PR:** kuantorflow#154 (+ kuantorflow_automation#24) · **Issue:** kuantorflow#137 · **Date:** 2026-07-27

## Summary

The **Upload notes** panel now accepts `.txt` and `.docx` as well as `.mht`, and
all three formats share one Reverso copy-paste parser. Verified against the
real sample notes in `Documents/!Projects/KF_Examples` — a plain-text Reverso
copy-paste, a simple `word - translation` list, and a 80-paragraph OneNote →
Word export mixing both styles — plus 22 new offline tests. Suite: **131
passed**, was 115.

## What changed

- **`parsers.py`**
  - The Reverso state machine was lifted out of the BeautifulSoup walk into
    `_reverso_entries_from_lines()`, which consumes format-agnostic *classified
    lines* (`text` / `header` / `sense` / `field` / `terms`). Three classifiers
    feed it: `_reverso_lines_from_soup` (.mht, colours), `_reverso_lines_from_docx`
    (.docx, the same colours — Word keeps them in the runs' properties) and
    `_reverso_lines_from_text` (.txt, classified by layout since text carries no
    formatting at all).
  - `_cards_from_lines()` runs the Reverso machine and then offers every line it
    did **not** claim to the plain `word — explanation` parser, so one file may
    mix Reverso blocks and simple lines (the sample `.docx` does). Cards come
    back in document order, de-duplicated by word.
  - `_docx_paragraphs()` reads `word/document.xml` with `zipfile` +
    `ElementTree` — **no new runtime dependency** (python-docx was the
    alternative; the issue preferred the lighter route).
  - `parse_txt_preview` / `parse_docx_preview`, and `parse_notes_preview(filename, …)`
    which dispatches on the extension and raises `ValueError` for anything else.
  - Two fixes that fall out of the shared machine and also improve `.mht`:
    a single-sense entry (Reverso omits the `1.` marker) is no longer dropped,
    and a header with no part of speech leaves `pos` unset instead of labelling
    the card `other`.
  - `_entry_from_line()`: a **Cyrillic right-hand side is a translation**
    (`pursuit - преследование` → `translation_rus`), not an English explanation.
- **`app.py`** — `upload_mht`/`mht_file` → `upload_notes`/`notes_file`, dispatch
  via `parse_notes_preview`, template variable `mht_content` → `source_content`.
- **`templates/index.html`, `style.css`** — heading “Upload notes (.txt, .docx,
  .mht)”, `accept=".txt,.docx,.mht,.mhtml"`, CSS modifier `--mht` → `--source`.
- **README / CLAUDE.md** — the three formats and the shared-parser architecture.

## Automated tests

- **Added:** `tests/test_notes_formats.py` — 22 tests covering the plain-text
  Reverso copy-paste (senses aggregated, examples, terms listed one per line so
  no AI split is needed), simple lines with Cyrillic vs English right-hand
  sides, cp1251 decoding, a canned `.docx` built in-test with `zipfile` (mixed
  Reverso block + plain line, single-sense entry without a `1.` marker, the
  `1.` marker being coloured like an example but holding no content),
  extension dispatch, the unsupported-format error, and the upload route for
  `.txt`/`.docx` plus the panel's heading and `accept` strings.
- **Updated:** `tests/test_lookup_and_cards.py` — the existing `.mht` upload
  test now posts the renamed `upload_notes`/`notes_file`.
- **Suite result:** `pytest -m "not live"` — **131 passed**, 1 skipped,
  6 deselected (was 115 passed).

## Manual & browser verification

Flask dev server against local MySQL, with a real `ANTHROPIC_API_KEY` so the
glued-translation split ran for real (not stubbed).

| Check | Outcome |
|---|---|
| `LucidDream.txt` (Reverso copy-paste, no POS in the source) | 1 card, both senses aggregated into the explanation, 2 English examples, `translation_rus = вещий сон, осознанный сон, ясный сон`, 2 Russian example translations |
| `Pursuit_Haunting.txt` (simple lines) | 2 cards, each with the Cyrillic side stored as `translation_rus`, no bogus `explanation_en` |
| `Fri Jul 24 B Extremes.docx` (80 paragraphs, mixed) | 7 cards in document order: 2 from plain lines (`ex'acerbate` → translation, `exorbitant` → explanation) and 5 Reverso cards, incl. `dazzling` as **two** cards (adjective + noun) |
| Glued Ukrainian terms, live AI split | `авторитет`: `влада, адміністрація, повноваження, авторитет, експерт, фахівець, дозвіл, схвалення, авторизація`; `fount`: `джерело, фонтан` |
| OneNote noise (`From <https://reverso.net/…>`, date/time header) | ignored — no stray cards |
| Browser upload of a mixed `.txt` (real file input + **Upload & save**) | two-column review popup (940px), source pane beside 1 card, `Add All` and the #146 close cross present |
| Panel copy in the served page | heading “Upload notes (.txt, .docx, .mht)”, `accept=".txt,.docx,.mht,.mhtml"`, field `notes_file` |
| Unsupported extension (`notes.pdf`) | “Unsupported notes format: .pdf” banner, no popup |
| Database writes during all of the above | **none** — uploads only ever propose cards (verified: no rows created) |

## Result

**Pass.** No new runtime dependency, so deploying is a `git pull` + web-app
reload. Two limits worth knowing, both documented in the parser: a plain-text
Reverso block must be contiguous (a blank line ends it, which is what keeps
ordinary notes around it out of the parser), and plain text carries no part of
speech, so those cards are saved without one.
