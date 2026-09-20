# kuantorflow_automation

Automated testing of the [KuantorFlow](https://github.com/Kuantor/kuantorflow)
project, with database backup — the regression suite that guards the app's
behavior, smoke tests for the deployed site, and a daily backup of the
MySQL database.

## Two layers of tests

| Layer | What it does | Needs |
|---|---|---|
| **App tests** (`tests/test_*.py` except live) | Import the Flask app from the kuantorflow repo and exercise routes with the database and external services stubbed. Fully offline, never writes anywhere. | The kuantorflow repo checked out next door |
| **Live site tests** (`tests/test_live_site.py`, marker `live`) | Read-only HTTP checks against the deployed site: it's up and **open** (200, not a redirect), HTTPS is forced, `robots.txt`, the static assets and the link-preview tags are served. | `SITE_URL` in `.env` |

Covered by the app tests: that the site is open (#199), the lookup review popup
(`/cards/add`), MHT upload, card deletion with confirmation, quiz grading
in both languages (variant/case/ё-tolerance), topic chips, error banners,
Open Graph preview tags, and the MHT/text parsers.

## Setup

```powershell
cd C:\Users\38050\Documents\!Projects\automation\kuantorflow_automation
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
copy .env.example .env    # then edit .env: SITE_URL, KUANTORFLOW_PATH, DB_*
```

`.env` is gitignored — no credential reaches the repository.

The app tests locate the kuantorflow repo via `KUANTORFLOW_PATH` in `.env`;
by default they expect it at `..\..\kuantorflow` (i.e. `!Projects\kuantorflow`).

## Running

```powershell
.\venv\Scripts\pytest -m "not live"   # app tests only (offline, fast)
.\venv\Scripts\pytest -m live         # smoke-test the deployed site
.\venv\Scripts\pytest                 # everything
```

A typical pre-deployment routine: run `-m "not live"` before pushing app
changes, and `-m live` right after clicking Reload on PythonAnywhere.

## There is no keyword gate

The site used to sit behind an 'Enter keyword' screen, and `gate.py` was the
one helper that knew how to get a scripted session past it. **kuantorflow#199
removed the gate**, so `gate.py` and `enter_gate()` are gone: a scripted
session just makes the request.

```python
import requests

session = requests.Session()
session.get("https://kuantorflow.pythonanywhere.com/")
```

`ACCESS_KEYWORD` is no longer read from `.env` by anything. What bounds the
site now is a daily ceiling on each paid action rather than a shared password
— `tests/test_the_site_is_open.py` is where that is asserted, and it is
`test_access_gate.py` inverted rather than deleted.

## Database backup

`backup/` holds a daily backup script for the MySQL `kuantorflow` database.
Each run writes a gzip-compressed `mysqldump` (`.sql.gz`), keeps the newest
few, and can be scheduled nightly on PythonAnywhere. See
[`backup/README.md`](backup/README.md) for the format, configuration, and the
PythonAnywhere scheduled-task setup.

```powershell
.\venv\Scripts\python backup/backup_db.py    # write one backup now
```
