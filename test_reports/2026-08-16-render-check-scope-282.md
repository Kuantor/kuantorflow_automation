# Test Report — The render check may be quoted

**PR:** kuantorflow#285 + kuantorflow_automation#81 · **Issue:** kuantorflow#282 · **Date:** 2026-08-16

## Summary

`md_to_pdf.py` reads the finished PDF back and refuses Edge's own error page (kuantorflow#211). It searched the whole document for the error string, so a report that *wrote about* the trap was refused for quoting it. The check is now scoped to the error page's shape — a single page that is almost nothing but the message — and this report, which quotes `ERR_FILE_NOT_FOUND` and Edge's `File not found` in the sentence you are reading, renders and verifies. Under the old rule it could not have been written.

## What changed

- `verify()` asks `_is_error_page(pages, text)`: one page, under the "it did not render" floor, and carrying a marker. Longer documents are judged by the heading check that follows, which is the stronger signal — a render missing headings from the source is a bad render whatever else it says.
- No flag, no environment variable, no optional parameter. kuantorflow#211's rule is unchanged; only its scope moved.
- `reports/README.md` loses the instruction to reword a sentence rather than reach for a flag. The scope is now recorded in the module docstring and `reports/scripts/README.md`.

## Automated tests

- **Added:** `tests/test_report_render_check.py` — 8 tests, 9 cases, over a stubbed `_read_back()`. Both directions: the error page is still refused by the same message and before the length check; a six-page report that quotes the string verifies, and so does a one-page one; the near-empty render and the missing-heading render still fail; nothing can switch the check off.
- **Against unpatched `main`** (a worktree, tests unchanged): **3 fail** — and they are the three that describe the bug.
- **Suite result:** `pytest -m "not live"` — **957 passed**, 74 skipped (opt-in `db`).

## Manual & CLI verification

- **A real error page.** Edge printed to PDF with a `file://` URI that does not exist → 1 page, 92 characters, refused with `error: errorpage.pdf is Edge's error page, not the report.` — the wording it always had.
- **The report that was refused.** The 15 August edition with the literal string put back into its process section → `verified: 6 page(s), 15214 characters of text`. That is the render rejected twice in kuantorflow#280.
- **This report.** Rendered with the patched converter; it quotes both markers above.
- `docs/check_catalog.py` is clean on the new file. It reports 36 problems that predate this branch — seven undocumented files and several drifted counts, left alone deliberately and worth their own ticket.

## Result

**Pass.** All four acceptance criteria met: a report may quote the string, a real error page is still refused with the same message, no skip flag exists (asserted from the source), and the workaround note is out of the process doc.
