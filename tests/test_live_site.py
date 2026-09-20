"""
Read-only smoke tests against the deployed site (SITE_URL in .env).

Run with:  pytest -m live
Skipped entirely when SITE_URL is empty. These tests never write to the
database — they only check that the site is up and open, and that the static
assets and link-preview tags are served.

**Rewritten for kuantorflow#199.** Four of these asserted the keyword gate:
that an unauthenticated visit landed on `/enter`, that a wrong keyword was
rejected, that the right one opened the site, and that the preview tags were
on the gate page. There is no gate, so those are gone — and what replaced them
is the first thing worth smoke-testing on a site that is now public: that the
front page answers a stranger, and that it answers **200 rather than a
redirect**, which is what a gate creeping back would look like from outside.
"""

import os

import pytest
import requests

SITE_URL = (os.environ.get("SITE_URL") or "").rstrip("/")
TIMEOUT = 30

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not SITE_URL, reason="SITE_URL not set in .env"),
]


def test_site_is_up_and_open():
    """No session, no keyword, no sign-in — the state every first visitor and
    every crawler is in."""
    r = requests.get(SITE_URL + "/", timeout=TIMEOUT)

    assert r.status_code == 200
    assert "Welcome to KuantorFlow" in r.text


def test_the_front_page_does_not_redirect():
    """Asserted separately, because `requests` follows redirects by default
    and the case above would pass against a gate that redirected to a page
    happening to contain the same words. This is the shape a gate returning
    by accident would have."""
    r = requests.get(SITE_URL + "/", timeout=TIMEOUT, allow_redirects=False)

    assert r.status_code == 200, (
        f"the front page answered {r.status_code} -> "
        f"{r.headers.get('Location')!r}")


def test_https_is_forced():
    if not SITE_URL.startswith("https://"):
        pytest.skip("SITE_URL is not https")
    r = requests.get(SITE_URL.replace("https://", "http://", 1) + "/",
                     timeout=TIMEOUT)
    assert r.url.startswith("https://"), "http:// should redirect to https://"


def test_robots_txt_is_served():
    """It shipped early so it would be in place *before* the site opened
    (#458). Now that it has, this is the one file whose absence cannot be
    undone by a later commit — a search engine's cache is not ours to
    clear."""
    r = requests.get(SITE_URL + "/robots.txt", timeout=TIMEOUT)

    assert r.status_code == 200
    assert "User-agent" in r.text
    assert "Disallow" in r.text


def test_static_assets_served():
    for path in ("/static/css/style.css", "/static/img/icon.jpg",
                 "/static/img/preview.jpg", "/static/img/background.jpg"):
        r = requests.get(SITE_URL + path, timeout=TIMEOUT)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_link_preview_tags_on_the_front_page():
    """They used to be checked on the gate, which was the only page a crawler
    could reach. Now it is this one."""
    r = requests.get(SITE_URL + "/", timeout=TIMEOUT)

    assert 'property="og:image"' in r.text
    assert 'property="og:title" content="KuantorFlow"' in r.text
