# Database backup

Daily backup of the KuantorFlow MySQL database (`kuantorflow` locally,
`<username>$default` on PythonAnywhere).

## Format

Each run produces one **gzip-compressed SQL dump** from `mysqldump`:

```
backups/kuantorflow_2026-07-13_020000.sql.gz
```

Why this format:

- **SQL dump** — portable, human-readable, and restored with a single command;
  the standard MySQL backup format.
- **gzip** — SQL text compresses ~5-10×, so backups stay small.
- **Timestamped filename** — sorts chronologically and makes retention trivial.

The dump uses `--single-transaction` (a consistent snapshot without locking
the tables), includes routines and triggers, and forces `utf8mb4` so the
Ukrainian/Russian text is preserved.

## Configuration

Set these in the repo's `.env` (gitignored) — same `DB_*` convention as the
KuantorFlow app (see `.env.example`):

| Variable | Default | Notes |
|---|---|---|
| `DB_USER` | `kuantorflow` | |
| `DB_PASSWORD` | — | **required** |
| `DB_HOST` | `<DB_USER>.mysql.pythonanywhere-services.com` | set `localhost` for local |
| `DB_NAME` | `<DB_USER>$default` | set `kuantorflow` for local |
| `MYSQLDUMP_PATH` | `mysqldump` | full path if not on `PATH` (Windows) |
| `BACKUP_DIR` | `backup/backups` | where dumps are written |
| `BACKUP_KEEP` | `7` | keep this many newest backups |

The password is passed to `mysqldump` via the `MYSQL_PWD` environment variable,
never on the command line (so it doesn't show up in the process list).

## Running

```bash
# Local (Windows) example .env:
#   DB_HOST=localhost
#   DB_NAME=kuantorflow
#   MYSQLDUMP_PATH=C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe
python backup/backup_db.py
```

Restore a dump (overwrites the target database — asks for confirmation):

```bash
python backup/restore_db.py backups/kuantorflow_2026-07-13_020000.sql.gz
```

## Scheduling the daily backup on PythonAnywhere

On PythonAnywhere the DB host/name default to the account values, so the
server `.env` only needs `DB_PASSWORD` (and `DB_USER` if the account name
isn't `kuantorflow`). Add a **daily scheduled task** (Tasks tab) running:

```
python3 /home/kuantorflow/kuantorflow_automation/backup/backup_db.py
```

Pick a quiet UTC time (e.g. 02:00). Each night it writes a fresh
`.sql.gz` and prunes anything beyond `BACKUP_KEEP`.

> Backups themselves are gitignored (`backups/*.sql.gz`) — they hold real
> data and don't belong in the repository. To keep an off-site copy, download
> them periodically or copy them out of the PythonAnywhere account.
