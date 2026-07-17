r"""Pass the KuantorFlow keyword gate ('Enter keyword' screen) for testing.

The whole site sits behind a keyword gate (app.py before_request), so every
scripted or manual test session has to get past /enter first. This module is
the one place that knows how:

    from gate import enter_gate

    session = enter_gate()                          # deployed site (SITE_URL)
    session = enter_gate("http://localhost:5000")   # local dev server

The returned requests.Session carries the gate cookie, so every following
request on it lands on the real pages instead of redirecting to /enter.

The keyword comes from ACCESS_KEYWORD in this repo's gitignored .env (the
same variable the live tests use). Note that a *local* dev server checks the
keyword from kuantorflow's own .env — if the two differ, pass the right one
explicitly: enter_gate("http://localhost:5000", keyword="...").

Run directly for a quick smoke check of the deployed site (or any URL):

    .\venv\Scripts\python gate.py                       # SITE_URL from .env
    .\venv\Scripts\python gate.py http://localhost:5000
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Same .env the test suite loads (conftest.py) — makes the module usable from
# standalone scripts too, not only under pytest.
load_dotenv(Path(__file__).with_name(".env"))

TIMEOUT = 30


def enter_gate(base_url=None, keyword=None, session=None, timeout=TIMEOUT):
    """Return a requests.Session that is already through the keyword gate.

    base_url  defaults to SITE_URL from .env (the deployed site).
    keyword   defaults to ACCESS_KEYWORD from .env.
    session   an existing requests.Session to authenticate, if you have one.

    Raises RuntimeError with a clear message when the gate rejects the
    keyword — better than every caller discovering it later as a puzzling
    redirect to /enter.
    """
    base_url = (base_url or os.environ.get("SITE_URL") or "").rstrip("/")
    if not base_url:
        raise RuntimeError("No base_url given and SITE_URL is not set in .env")
    keyword = keyword or os.environ.get("ACCESS_KEYWORD", "password")

    s = session or requests.Session()
    r = s.post(base_url + "/enter", data={"keyword": keyword}, timeout=timeout)
    r.raise_for_status()
    if "Incorrect keyword" in r.text:
        raise RuntimeError(
            f"The gate at {base_url}/enter rejected the keyword — check "
            "ACCESS_KEYWORD in .env (a local dev server checks the keyword "
            "from kuantorflow's own .env, which may differ)."
        )
    return s


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else None
    s = enter_gate(url)
    target = (url or os.environ.get("SITE_URL", "")).rstrip("/")
    page = s.get(target + "/", timeout=TIMEOUT)
    ok = "Welcome to KuantorFlow" in page.text
    print(f"Gate passed at {target} — index page {'OK' if ok else 'UNEXPECTED'}")
    sys.exit(0 if ok else 1)
