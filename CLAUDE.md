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
| `conftest.py` | Fixtures: `client` (through the gate), `user_client` (also signed in), `saved` (captures `save_flashcard`), autouse `settings_dir` (per-test temp), `app_module`. |
| `gate.py` | `enter_gate()` — the one helper for getting a scripted session past the keyword gate. |
| `backup/` | `backup_db.py` (gzip `mysqldump`, retention) + `restore_db.py`. |
| `maintenance/` | `dedup_flashcards.py` (remove pre-existing duplicate cards). |
| `test_reports/` | Per-PR verification reports (`.md` + `.pdf`). |
| `docs/` | The test catalog. |
| `presentation/` | Reusable python-pptx deck tooling. |

## Run

```bash
venv/Scripts/pytest -m "not live"   # offline app tests (fast, no DB/network)
venv/Scripts/pytest -m live         # smoke-test the deployed site
```

The app is imported via `KUANTORFLOW_PATH` in a gitignored `.env` (defaults to
a sibling `../../kuantorflow`). `.env` also holds `SITE_URL`, the real
`ACCESS_KEYWORD`, and `DB_*` for the live/backup tooling.

**A green default run is not the whole suite.** The `db`-marked tests — roughly
27 of them, against a real local MySQL — are **skipped unless you opt in**:

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
- **Pass the gate with `gate.py`** in any scripted site test — don't re-hand-roll
  the `/enter` POST.
- Keep the **test catalog** in `docs/` current when tests are added/renamed.
- Isolation: tests never write to a real DB or the real `settings/` dir (the
  `settings_dir` fixture + stubbed DB helpers see to that). **Never commit
  secrets** — `.env` is gitignored.

## Backup / dedup on PythonAnywhere

The production MySQL is only reachable from **inside** PythonAnywhere, so clone
this repo there to run `backup/backup_db.py` (schedule it) and
`maintenance/dedup_flashcards.py` against the live DB.
