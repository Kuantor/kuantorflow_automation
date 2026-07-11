"""
Daily backup of the KuantorFlow MySQL database.

Format: a gzip-compressed SQL dump produced by mysqldump, one file per run,
named `kuantorflow_<YYYY-MM-DD_HHMMSS>.sql.gz`. A plain SQL dump is portable
and human-readable, restores with a single `mysql` command, and gzip typically
shrinks it 5-10x since SQL is highly compressible.

Configuration comes from environment variables (a local .env is loaded if
present), following the same DB_* convention as the KuantorFlow app:

    DB_USER        default: kuantorflow
    DB_PASSWORD    required
    DB_HOST        default: <DB_USER>.mysql.pythonanywhere-services.com
    DB_NAME        default: <DB_USER>$default
    MYSQLDUMP_PATH default: "mysqldump" (on PATH; e.g. Linux / PythonAnywhere)
    BACKUP_DIR     default: <this folder>/backups
    BACKUP_KEEP    default: 7  (older backups beyond this count are deleted)

Run:  python backup/backup_db.py
"""

import gzip
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BACKUP_ROOT = Path(__file__).resolve().parent
load_dotenv(BACKUP_ROOT.parent / ".env")

FILENAME_PREFIX = "kuantorflow_"
FILENAME_SUFFIX = ".sql.gz"


def backup_filename(now: datetime) -> str:
    """Timestamped backup file name, e.g. kuantorflow_2026-07-13_020000.sql.gz."""
    return f"{FILENAME_PREFIX}{now:%Y-%m-%d_%H%M%S}{FILENAME_SUFFIX}"


def select_old_backups(files, keep: int):
    """
    Given existing backup Paths, return the ones to delete so that only the
    `keep` newest remain. Ordering is by filename, which sorts chronologically
    thanks to the ISO-style timestamp.
    """
    backups = sorted(
        (f for f in files
         if f.name.startswith(FILENAME_PREFIX) and f.name.endswith(FILENAME_SUFFIX)),
        reverse=True,  # newest first
    )
    return backups[keep:] if keep >= 0 else []


def _config():
    user = os.environ.get("DB_USER", "kuantorflow")
    password = os.environ.get("DB_PASSWORD")
    if not password:
        sys.exit("Error: DB_PASSWORD is not set — see backup/README.md and .env.example")
    return {
        "user": user,
        "password": password,
        "host": os.environ.get("DB_HOST", f"{user}.mysql.pythonanywhere-services.com"),
        "name": os.environ.get("DB_NAME", f"{user}$default"),
        "mysqldump": os.environ.get("MYSQLDUMP_PATH", "mysqldump"),
        "backup_dir": Path(os.environ.get("BACKUP_DIR", BACKUP_ROOT / "backups")),
        "keep": int(os.environ.get("BACKUP_KEEP", "7")),
    }


def run_backup(cfg) -> Path:
    """Dump the database to a gzip file and prune old backups. Returns the path."""
    if shutil.which(cfg["mysqldump"]) is None and not Path(cfg["mysqldump"]).exists():
        sys.exit(
            f"Error: mysqldump not found ('{cfg['mysqldump']}'). Install MySQL client "
            "tools or set MYSQLDUMP_PATH to the full path of mysqldump."
        )

    cfg["backup_dir"].mkdir(parents=True, exist_ok=True)
    out_path = cfg["backup_dir"] / backup_filename(datetime.now())

    command = [
        cfg["mysqldump"],
        f"--user={cfg['user']}",
        f"--host={cfg['host']}",
        "--single-transaction",   # consistent snapshot without locking the tables
        "--routines",             # include stored procedures/functions
        "--triggers",             # include triggers
        "--default-character-set=utf8mb4",  # preserve Cyrillic correctly
        cfg["name"],
    ]
    # Pass the password via the environment, never on the command line
    # (command-line args are visible in the process list).
    env = {**os.environ, "MYSQL_PWD": cfg["password"]}

    # Stream mysqldump's stdout THROUGH Python into the gzip file. Passing a
    # GzipFile straight to subprocess would write to the raw file descriptor
    # and skip compression, so we pipe and copy the bytes ourselves. stderr
    # goes to a temp file (no pipe-buffer deadlock, no reader threads).
    with open(out_path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb") as gz, \
            tempfile.TemporaryFile() as errfile:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errfile, env=env)
        shutil.copyfileobj(proc.stdout, gz)
        proc.stdout.close()
        proc.wait()
        errfile.seek(0)
        stderr = errfile.read()
    if proc.returncode != 0:
        out_path.unlink(missing_ok=True)  # don't leave a truncated/empty file
        sys.exit(f"mysqldump failed (exit {proc.returncode}):\n{stderr.decode(errors='replace')}")

    size_kb = out_path.stat().st_size / 1024
    print(f"Backup written: {out_path}  ({size_kb:,.1f} KB)")

    removed = select_old_backups(cfg["backup_dir"].iterdir(), cfg["keep"])
    for old in removed:
        old.unlink()
        print(f"Removed old backup: {old.name}")
    print(f"Retention: keeping the {cfg['keep']} newest backups.")
    return out_path


if __name__ == "__main__":
    run_backup(_config())
