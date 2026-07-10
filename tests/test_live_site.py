"""
Read-only smoke tests against the deployed site (SITE_URL in .env).

Run with:  pytest -m live
Skipped entirely when SITE_URL is empty. These tests never write to the
database — they only check that the site is up, the gate works, and the
static assets and link-preview tags are served.
"""

import os

import pytest
import requests

SITE_URL = (os.environ.get("SITE_URL") or "").rstrip("/")
ACCESS_KEYWORD = os.environ.get("ACCESS_KEYWORD", "password")
TIMEOUT = 30

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not SITE_URL, reason="SITE_URL not set in .env"),
]


def test_site_is_up_and_gated():
    r = requests.get(SITE_URL + "/", timeout=TIMEOUT)
    assert r.status_code == 200
    assert r.url.endswith("/enter"), "unauthenticated visit should land on the gate"
    assert "Please enter the keyword" in r.text


def test_https_is_forced():
    if not SITE_URL.startswith("https://"):
        pytest.skip("SITE_URL is not https")
    r = requests.get(SITE_URL.replace("https://", "http://", 1) + "/",
                     timeout=TIMEOUT)
    assert r.url.startswith("https://"), "http:// should redirect to https://"


def test_wrong_keyword_rejected():
    s = requests.Session()
    r = s.post(SITE_URL + "/enter",
               data={"keyword": "definitely-wrong-keyword-12345"},
               timeout=TIMEOUT)
    assert "Incorrect keyword" in r.text


def test_correct_keyword_opens_site():
    s = requests.Session()
    r = s.post(SITE_URL + "/enter", data={"keyword": ACCESS_KEYWORD},
               timeout=TIMEOUT)
    assert "Incorrect keyword" not in r.text, \
        "ACCESS_KEYWORD in .env does not match the deployed keyword"
    r = s.get(SITE_URL + "/", timeout=TIMEOUT)
    assert "Welcome to KuantorFlow" in r.text


def test_static_assets_served():
    for path in ("/static/css/style.css", "/static/img/icon.png",
                 "/static/img/preview.jpg", "/static/img/background.jpg"):
        r = requests.get(SITE_URL + path, timeout=TIMEOUT)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_link_preview_tags_on_gate():
    r = requests.get(SITE_URL + "/", timeout=TIMEOUT)  # lands on the gate
    assert 'property="og:image"' in r.text
    assert 'property="og:title" content="KuantorFlow"' in r.text
