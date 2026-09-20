# CLAUDE.md — kuantorflow_automation

Guidance for Claude Code (and contributors) working in this repo.

## What this is

The **quality & ops** repo for
[KuantorFlow](https://github.com/Kuantor/kuantorflow): the pytest regression
suite, the database backup/restore scripts, and maintenance tooling. It
imports the KuantorFlow Flask app from a sibling checkout.

## Layout

| Path | What |
|---|---|
| `tests/` | Offline app tests (import `app`, DB/network stubbed) + live smoke tests (marker `live`). |
| `conftest.py` | Fixtures: `client` (a plain anonymous client — it used to enter the keyword, and since kuantorflow#199 it is the same object as `fresh_client`; both are kept because several hundred tests name one or the other), `user_client` (also signed in), `saved` (captures `save_flashcard`), autouse `settings_dir` (per-test temp), `app_module`. Shared helpers too: `in_other()` and `browse_panel()` — **cut the index page's deck out with the latter**, never by slicing to a landmark, because the games panel reuses `.topic-tile` and an unscoped search counts five activities as topics. |
| `backup/` | `backup_db.py` (gzip `mysqldump`, retention) + `restore_db.py`. |
| `maintenance/` | `dedup_flashcards.py` (remove pre-existing duplicate cards), `block_user.py`, `delete_account.py`, `backfill_examples.py` (fill `examples_en` on cards saved before kuantorflow#225). Repairs for data that predates a fix: each calls the app's own functions rather than writing SQL, and each is a dry run until `--apply`. |
| `test_reports/` | Per-PR verification reports (`.md` + `.pdf`). |
| `docs/` | The test catalog. |
| `presentation/` | Reusable python-pptx deck tooling. |

## Run

```bash
venv/Scripts/pytest -m "not live"   # offline app tests (fast, no DB/network)
venv/Scripts/pytest tests/test_live_site.py   # smoke-test the deployed site
```

**The live check is named by path, not by `-m live`, and is run from here
rather than on PythonAnywhere.** The marker deselects *after* collection, so
`-m live` imports all 58 app-level modules and dies on a machine without the
app's dependencies; and a smoke check run on the deployment host may never
leave its own network. `SITE_URL` must be set or all six skip in yellow and
exit 0. `tests/test_live_tests_need_no_app.py` keeps the live tier free of the
app -- two autouse fixtures used to import one for every test in the suite.

The app is imported via `KUANTORFLOW_PATH` in a gitignored `.env` (defaults to
a sibling `../../kuantorflow`). `.env` also holds `SITE_URL` and `DB_*` for
the live/backup tooling. It used to hold `ACCESS_KEYWORD` too; kuantorflow#199
removed the gate and nothing reads it now.

**A green default run is not the whole suite.** The `db`-marked tests — roughly
67 of them, against a real local MySQL — are **skipped unless you opt in**:

```bash
RUN_DB_ROUNDTRIP=1 venv/Scripts/pytest -q
```

They need `DB_HOST=localhost` and `DB_*` configured, and each creates and drops
its **own** scratch database, never touching the configured one. Run them for
anything that touches schema, SQL or a migration: on 2026-08-04 they caught
three genuine failures in `test_apply_schema_db.py` that the offline run could
not see, because only a real database exercises them. The offline suite passing
says nothing about those paths.

`KUANTORFLOW_PATH` is also how you baseline. Before assuming that failures come
from *the tests* rather than *the change*, run the unchanged suite against a
worktree of kuantorflow `main` — copy the gitignored `.env` into it, or two
unrelated tests fail on a missing Google sign-in link and it looks like a
regression.

## Conventions

- **Parallel PRs.** These tests are opened *alongside* a KuantorFlow feature PR
  — a `tests/…` branch here, opened together with the code PR there.
- **Significant PRs get a report.** Write a Markdown + PDF verification report
  into `test_reports/` (see its `README.md`; render the PDF with KuantorFlow's
  `reports/scripts/md_to_pdf.py`). Small PRs are exempt unless asked.
- **There is no gate to pass** since kuantorflow#199. `gate.py` and
  `enter_gate()` are deleted; a scripted site test just makes the request.
  `tests/test_the_site_is_open.py` holds the inverted assertions.
- Keep the **test catalog** in `docs/` current when tests are added/renamed.
- Isolation: tests never write to a real DB or the real `settings/` dir (the
  `settings_dir` fixture + stubbed DB helpers see to that). **Never commit
  secrets** — `.env` is gitignored.

## Backup / dedup on PythonAnywhere

The production MySQL is only reachable from **inside** PythonAnywhere, so clone
this repo there to run `backup/backup_db.py` (schedule it) and anything in
`maintenance/` against the live DB.

On PythonAnywhere the three repos sit **flat in the home directory**, where this
repo's path fallbacks — which count directories upward for the nested local
layout — resolve one level short. `KUANTORFLOW_PATH=$HOME/kuantorflow` in the
`.env` there is what makes `block_user.py`, `delete_account.py` and
`backfill_examples.py` able to import the app at all.
