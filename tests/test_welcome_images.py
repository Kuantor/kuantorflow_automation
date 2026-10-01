"""The welcome popup: lighter images, opened with its pictures (kuantorflow#517).

A first visitor saw the popup open as an empty frame and its pictures arrive
afterwards -- about 1.6 MB of JPEG for one popup (417 KB picture, 342 KB
background, 832 KB poster), and the popup opened the moment the script ran.

Now:

* **WebP**, made with `reports/scripts/to_webp.py`: the picture in three widths
  offered through `srcset` (640/960/1254), the popup's and the page's
  backgrounds, Mykola's avatar, and the poster (in ai_agent).
* **Fetched only when shown.** The popup's and About's pictures carry `data-src`
  until they open, so a visit with no popup downloads none of them.
* **The popup waits for its picture and background to be decoded**, at most
  2.5 s, then opens anyway.

Measured in the PR: a first visit opened the popup at 1,622 ms with both
already loaded; a repeat visit fetched none of the three; with decoding
stalled the popup still opened at 2.8 s; a 2x phone took the 640px copy and a
1.5x laptop the 960px one.
"""

import re
from pathlib import Path

import pytest

import chat

APP = Path(chat.__file__).parent
IMG = APP / "static" / "img"

# Measured when they were made; a budget, not a restatement -- a re-export
# that comes out bigger than the JPEG it replaced should fail here.
BUDGET_KB = {
    "main_image.webp": 200,
    "main_image-960.webp": 125,
    "main_image-640.webp": 65,
    "welcome_background.webp": 90,
    "background.webp": 90,
    "mykola_avatar.webp": 12,
}


@pytest.mark.parametrize("name, budget", sorted(BUDGET_KB.items()))
def test_each_webp_exists_within_its_budget(name, budget):
    path = IMG / name
    assert path.is_file(), name
    assert path.read_bytes()[8:12] == b"WEBP", f"{name} is not a WebP"
    assert path.stat().st_size <= budget * 1024, f"{name}: {path.stat().st_size // 1024} KB"


def _home(client, monkeypatch):
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    return client.get("/").get_data(as_text=True)


def test_no_page_loads_a_jpeg_any_more(client, monkeypatch):
    """The icon and the link-preview image stay JPEG on purpose: a browser
    tab icon and the apps that unfurl a shared link do not all read WebP."""
    body = _home(client, monkeypatch)
    jpegs = set(re.findall(r'(?:src|href|srcset|data-src|data-srcset)="[^"]*?([\w-]+\.jpg)', body))
    assert jpegs <= {"icon.jpg"}, jpegs
    css = (APP / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert not re.findall(r"url\([^)]*\.jpg", css), "a CSS background still points at a JPEG"


def test_the_popup_and_about_pictures_wait_to_be_shown(client, monkeypatch):
    """No `src` on them in the page: with one, every home-page visit fetches
    them, though the popup opens once a session and About almost never."""
    body = _home(client, monkeypatch)
    for img in re.findall(r"<img[^>]*main_image[^>]*>", body):
        assert " src=" not in img, img
        assert "data-src=" in img and "data-srcset=" in img, img
        assert all(w in img for w in ("640w", "960w", "1254w")), img
        assert 'sizes="(max-width: 640px) 85vw' in img, img
    poster = re.search(r'<img class="welcome-mykola-image"[^>]*>', body).group(0)
    assert 'data-src="' in poster and "mykola_poster.webp" in poster, poster


def test_the_popup_opens_once_its_pictures_are_decoded_or_after_a_timeout(client, monkeypatch):
    body = _home(client, monkeypatch)
    ready = body[body.index("function welcomeImagesReady()"):body.index("function openWelcome()")]
    assert "img.src = img.dataset.src" in ready, "the pictures never get their addresses"
    assert ".decode(" in ready and "Promise.race" in ready
    wait = int(re.search(r"var WELCOME_WAIT_MS = (\d+);", body).group(1))
    assert 1000 <= wait <= 4000, wait
    opening = body[body.index("function openWelcome()"):body.index("function closeWelcome()")]
    assert "welcomeImagesReady().then(show, show)" in opening, \
        "a failed load must still open the popup"


def test_the_popup_background_preload_is_the_stylesheets_url(client, monkeypatch):
    """One download, not two: the script asks for exactly what the CSS does,
    with no cache-busting version on it."""
    body = _home(client, monkeypatch)
    assert 'bg.src = "/static/img/welcome_background.webp";' in body


@pytest.fixture()
def agent_images(tmp_path, monkeypatch):
    folder = tmp_path / "static" / "img"
    folder.mkdir(parents=True)
    monkeypatch.setattr("chat.MYKOLA_AVAILABLE", True)
    monkeypatch.setattr("chat.AI_AGENT_PATH", str(tmp_path))
    return folder


def test_the_poster_is_served_as_webp_when_ai_agent_has_it(client, agent_images):
    (agent_images / "mykola_poster.webp").write_bytes(b"RIFF\0\0\0\0WEBPdata")
    (agent_images / "mykola_poster.jpg").write_bytes(b"\xff\xd8jpeg")
    resp = client.get("/mykola-media/mykola_poster.webp")
    assert resp.status_code == 200 and resp.data.startswith(b"RIFF")


def test_an_older_ai_agent_gets_the_jpeg_instead(client, agent_images):
    """The repos deploy in either order: until ai_agent has the WebP, the
    request for it is answered with the JPEG, which the browser shows by its
    Content-Type."""
    (agent_images / "mykola_poster.jpg").write_bytes(b"\xff\xd8jpeg")
    resp = client.get("/mykola-media/mykola_poster.webp")
    assert resp.status_code == 200 and resp.data.startswith(b"\xff\xd8")
    assert resp.mimetype == "image/jpeg"


def test_no_fallback_invents_a_file(client, agent_images):
    assert client.get("/mykola-media/nothing.webp").status_code == 404
