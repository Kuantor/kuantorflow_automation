# Test reports

Per-PR verification reports for **significant** KuantorFlow changes (issue
[kuantorflow#103](https://github.com/Kuantor/kuantorflow/issues/103)) — a
durable record of what was tested and how, kept alongside the automated
suite.

## When a report is written

- **Significant PRs** (a real feature or a non-trivial bug fix — the settings
  platform, providers, duplicate prevention, language visibility, Reset Auth,
  and the like): a report is written and committed.
- **Small PRs** (docs, a one-line copy tweak, a pure-CSS nudge): **no report
  by default** — one is written only if the task explicitly asks for it.

## Format

Each report is a Markdown file plus a rendered PDF, both committed:

```
test_reports/YYYY-MM-DD-<short-slug>.md
test_reports/YYYY-MM-DD-<short-slug>.pdf
```

`YYYY-MM-DD` is the date the report was written; `<short-slug>` names the
feature and its issue, e.g. `2026-07-18-reset-auth-98`.

Start from [`_TEMPLATE.md`](_TEMPLATE.md), which lays out the sections:
PR/issue links, a one-line summary, what changed, tests added/updated with
before/after counts, manual & browser verification (the exact checks and
their outcomes), and the final result.

## Rendering the PDF

Reuse the report tooling committed in the kuantorflow repo
(`reports/scripts/md_to_pdf.py`, headless-Edge rendering — no LibreOffice
needed). From this repo, with the kuantorflow virtualenv:

```bash
KF=../../kuantorflow          # path to the kuantorflow checkout
"$KF"/venv/Scripts/python "$KF"/reports/scripts/md_to_pdf.py \
    test_reports/2026-07-18-reset-auth-98.md
```

The PDF lands next to the `.md`. Commit both.
