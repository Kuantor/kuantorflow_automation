"""Visits: a check-in from the browser (kuantorflow#598).

The foundation for #599 (an email when a signed-in learner's visit ends) and
#600 (a daily count of visitors, robots excluded). Page loads alone cannot say
how long somebody spent, cannot tell one anonymous visitor from another, and
cannot tell a person from a robot, so:

* **`static/js/visit.js`**, on every page, posts to `POST /visit/ping` about
  once a minute **while the tab is visible**, with the seconds it was visible;
  the first check-in waits until the page has been in front for ~5 s, and a
  hidden tab sends what it has with `sendBeacon` and stops. Run here in Node
  with a fake clock and a fake document;
* **the route** gives the browser a random visitor number in its session,
  refuses robots by user agent, caps the seconds a check-in may claim, claims
  no quota, and writes **no `requests.log` line**;
* **`utils.record_visit()`** keeps one row per visit (real MySQL:
  `test_visits_db.py`).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH, TEST_USER_ID

BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
SCRIPT = Path(KUANTORFLOW_PATH) / "static" / "js" / "visit.js"


@pytest.fixture()
def recorded(monkeypatch):
    calls = []
    monkeypatch.setattr("utils.record_visit", lambda **kw: calls.append(kw))
    return calls


def _ping(client, body=None, agent=BROWSER, **kw):
    return client.post("/visit/ping", data=json.dumps(body if body is not None else
                                                       {"active": 5, "page": True}),
                       headers={"User-Agent": agent}, **kw)


# --- the route --------------------------------------------------------------

def test_an_anonymous_check_in_is_recorded_under_a_random_number(client, recorded):
    assert _ping(client, content_type="application/json").status_code == 204

    (call,) = recorded
    assert re.fullmatch(r"[0-9a-f]{16}", call["visitor"])
    assert call["user_id"] is None
    assert call["active"] == 5 and call["page"] is True


def test_the_number_stays_for_the_browser_session(client, recorded):
    _ping(client)
    _ping(client, {"active": 60, "page": False})

    assert recorded[0]["visitor"] == recorded[1]["visitor"]
    assert recorded[1]["page"] is False


def test_another_browser_is_another_visitor(app_module, recorded):
    with app_module.app.test_client() as one, app_module.app.test_client() as two:
        _ping(one)
        _ping(two)

    assert recorded[0]["visitor"] != recorded[1]["visitor"]


def test_a_signed_in_check_in_carries_the_account(user_client, recorded):
    _ping(user_client)

    assert recorded[0]["user_id"] == TEST_USER_ID


def test_a_beacon_without_a_json_content_type_is_read(client, recorded):
    """`sendBeacon` sends what it is given; the route does not insist."""
    _ping(client, {"active": 12, "page": False}, content_type="text/plain")

    assert recorded[0]["active"] == 12


@pytest.mark.parametrize("sent,kept", [(5000, 70), (-4, 0), ("lots", 0), (None, 0), (7.6, 8)])
def test_the_seconds_are_capped_and_cleaned(client, recorded, sent, kept, app_module):
    _ping(client, {"active": sent, "page": False})

    assert recorded[0]["active"] == kept
    assert app_module.MAX_PING_SECONDS == 70


@pytest.mark.parametrize("agent", [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Mozilla/5.0 (compatible; YandexBot/3.0)",
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/141.0 Safari/537.36",
    "python-requests/2.32.3",
    "curl/8.7.1",
    "Wget/1.21",
    "facebookexternalhit/1.1",
    "Some Crawler 1.0",
    "a-spider",
    "Mozilla/5.0 (compatible; Yahoo! Slurp)",
    "",
])
def test_a_robot_is_not_recorded(client, recorded, agent):
    assert _ping(client, agent=agent).status_code == 204
    assert recorded == []


def test_a_real_browser_is_not_mistaken_for_a_robot(client, recorded):
    for agent in (BROWSER,
                  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
                  "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
                  "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"):
        _ping(client, agent=agent)

    assert len(recorded) == 3


def test_only_post(client, recorded):
    assert client.get("/visit/ping").status_code == 405
    assert recorded == []


def test_it_claims_no_quota(client, recorded, monkeypatch):
    def claimed(*a, **k):
        raise AssertionError("a check-in must not claim a ceiling")
    monkeypatch.setattr("utils.claim_action", claimed)
    monkeypatch.setattr("utils.claim_pools", claimed)

    assert _ping(client).status_code == 204


def test_it_writes_no_request_line(client, recorded, action_logs):
    _ping(client)
    client.get("/")

    text = (action_logs / "requests.log").read_text(encoding="utf-8")
    assert "path=/visit/ping" not in text and "path=/ " in text + " "


def test_a_failed_write_is_still_a_quiet_204(client, monkeypatch):
    def down(**kw):
        raise RuntimeError("db unreachable")
    monkeypatch.setattr("utils.record_visit", down)

    assert _ping(client).status_code == 204


# --- the pages load the script ----------------------------------------------

def test_every_page_loads_the_check_in(client):
    for path in ("/", "/help"):
        body = client.get(path).get_data(as_text=True)
        assert re.search(r'<script src="[^"]*js/visit\.js[^"]*" data-url="/visit/ping" defer>', body), path


def test_the_deck_pages_inherit_it():
    """The card deck and Fill the gap render `deck.html`, which extends
    `base.html`, so they carry the check-in without a tag of their own."""
    templates = Path(KUANTORFLOW_PATH) / "templates"
    for name in ("deck.html", "cards.html", "game_fill_the_gap.html"):
        text = (templates / name).read_text(encoding="utf-8")
        assert re.match(r'\{% extends "(base|deck)\.html" %\}', text), name


# --- the script, in Node ----------------------------------------------------

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
let t = 0; const timers = []; const sent = []; const on = {};
const setTimeout = (fn, ms) => { timers.push({id: timers.length + 1, at: t + ms, fn, live: true}); return timers.length; };
const clearTimeout = (id) => { const x = timers[id - 1]; if (x) x.live = false; };
function advance(ms) {
  const end = t + ms;
  for (;;) {
    const due = timers.filter(x => x.live && x.at <= end).sort((a, b) => a.at - b.at)[0];
    if (!due) break;
    t = due.at; due.live = false; due.fn();
  }
  t = end;
}
const document = {visibilityState: 'visible', currentScript: {dataset: {url: '/visit/ping'}},
                  addEventListener: (e, f) => (on[e] = on[e] || []).push(f)};
const window = {addEventListener: (e, f) => (on['w:' + e] = on['w:' + e] || []).push(f)};
class Blob { constructor(parts) { this.body = parts.join(''); } }
const navigator = {sendBeacon: (url, blob) => { sent.push({how: 'beacon', at: t, ...JSON.parse(blob.body)}); return true; }};
const fetch = (url, opts) => { sent.push({how: 'fetch', at: t, ...JSON.parse(opts.body)}); return Promise.resolve(); };
const ctx = {document, window, navigator, Blob, fetch, setTimeout, clearTimeout, JSON, Math,
             Date: {now: () => t}, console};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const fire = (e) => (on[e] || []).forEach(f => f());
const hide = () => { document.visibilityState = 'hidden'; fire('visibilitychange'); };
const show = () => { document.visibilityState = 'visible'; fire('visibilitychange'); };
const pagehide = () => (on['w:pagehide'] || []).forEach(f => f());
const S = process.argv[2];
"""

SCENARIOS = {
    # A glance: hidden after 4 s, never checks in -- no visit at all.
    "glance": "advance(4000); hide(); advance(600000);",
    # Read for two minutes: the first check-in at 5 s, then every minute.
    "reading": "advance(125000);",
    # Read 30 s, switch away: the hidden tab sends its 25 s and goes quiet.
    "switch away": "advance(30000); hide(); advance(600000); show(); advance(61000);",
    # 3 s, away, back for 2 s: five seconds in front, so it checks in then.
    "split first": "advance(3000); hide(); advance(10000); show(); advance(2000);",
    # Leaving the page: hidden then pagehide sends once, not twice.
    "leaving": "advance(20000); hide(); pagehide();",
}


def _run(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed; the script is checked in a browser")
    script = HARNESS + SCENARIOS[scenario] + "\nconsole.log(JSON.stringify(sent));"
    out = subprocess.run([node, "-e", script, str(SCRIPT), scenario],
                         capture_output=True, text=True, check=True)
    return [(s["how"], s["at"], s["active"], s["page"]) for s in json.loads(out.stdout)]


def test_a_glance_is_not_a_visit():
    assert _run("glance") == []


def test_reading_checks_in_at_five_seconds_then_every_minute():
    assert _run("reading") == [("fetch", 5000, 5, True), ("fetch", 65000, 60, False),
                               ("fetch", 125000, 60, False)]


def test_a_hidden_tab_sends_what_it_has_and_stops():
    assert _run("switch away") == [
        ("fetch", 5000, 5, True),
        ("beacon", 30000, 25, False),
        ("fetch", 30000 + 600000 + 60000, 60, False)]


def test_the_first_five_seconds_may_be_split():
    assert _run("split first") == [("fetch", 15000, 5, True)]


def test_leaving_sends_once():
    sent = _run("leaving")

    assert [s[0] for s in sent] == ["fetch", "beacon"]
    assert sent[1][2] == 15


def test_the_privacy_section_says_visits_are_counted():
    guide = (Path(KUANTORFLOW_PATH) / "docs" / "user-guide.md").read_text(encoding="utf-8")
    start = guide.index("## Privacy: what the site keeps")
    privacy = guide[start:guide.index("\n## ", start + 3)].lower()

    assert "visits are counted" in privacy and "random number" in privacy
    assert "robots are left out" in privacy
    assert "the record of your visits" in privacy
