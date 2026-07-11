"""
Restore a KuantorFlow backup produced by backup_db.py.

Decompresses a .sql.gz dump and pipes it into `mysql`, recreating the tables
and data. Uses the same DB_* configuration as backup_db.py.

Usage:
    python backup/restore_db.py backup/backups/kuantorflow_2026-07-13_020000.sql.gz

WARNING: this overwrites the current contents of the target database. It asks
for confirmation unless you pass --yes.
"""

import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKUP_ROOT = Path(__file__).resolve().parent
load_dotenv(BACKUP_ROOT.parent / ".env")


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
        "mysql": os.environ.get("MYSQL_PATH", "mysql"),
    }


def main(argv) -> None:
    args = [a for a in argv if a != "--yes"]
    assume_yes = "--yes" in argv
    if len(args) != 1:
        sys.exit("Usage: python backup/restore_db.py <backup.sql.gz> [--yes]")

    dump_path = Path(args[0])
    if not dump_path.exists():
        sys.exit(f"Error: file not found: {dump_path}")

    cfg = _config()
    if shutil.which(cfg["mysql"]) is None and not Path(cfg["mysql"]).exists():
        sys.exit(
            f"Error: mysql client not found ('{cfg['mysql']}'). "
            "Set MYSQL_PATH to the full path of the mysql executable."
        )

    if not assume_yes:
        answer = input(
            f"This will OVERWRITE database '{cfg['name']}' on {cfg['host']} "
            f"with {dump_path.name}. Type 'yes' to continue: "
        )
        if answer.strip().lower() != "yes":
            sys.exit("Aborted.")

    command = [cfg["mysql"], f"--user={cfg['user']}", f"--host={cfg['host']}", cfg["name"]]
    env = {**os.environ, "MYSQL_PWD": cfg["password"]}

    with gzip.open(dump_path, "rb") as gz:
        proc = subprocess.run(command, stdin=gz, stderr=subprocess.PIPE, env=env, check=False)
    if proc.returncode != 0:
        sys.exit(f"Restore failed (exit {proc.returncode}):\n{proc.stderr.decode(errors='replace')}")
    print(f"Restored '{cfg['name']}' from {dump_path.name}.")


if __name__ == "__main__":
    main(sys.argv[1:])
