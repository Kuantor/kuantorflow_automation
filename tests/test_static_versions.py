"""Versioned static URLs, so a deploy invalidates what it changed
(kuantorflow#300).

A browser keys its cache on the URL. Nothing in the deploy tells it that
`style.css` was rewritten, so it goes on serving the copy it already holds
until its own heuristics expire it -- and what that looks like is the reason
this matters: not a broken page but a **plausible** one. Every rule that
arrived with the new file is missing at once, and the result still renders. A
button that looks like a button, sections that do not fold, a hint in the
wrong place. Nobody reports it, because nobody knows what it was meant to look
like. On 16 August it was caught only because the person looking had written
the CSS the week before.

Three properties carry the fix, and each of them can break on its own while
the other two stay green:

**Every asset a template asks for is versioned.** One un-versioned `<link>` is
the whole bug back again for that file, and the page still renders perfectly,
so nothing else would notice. That is asserted against the **rendered pages**
rather than against the template source: a helper that exists and is not
called is the failure mode here, and only the rendered output can tell the
difference.

**The version is stable while the file is not.** This is the assertion that
separates a cache-buster from a cache-*breaker*. A timestamp of `now()` or a
random token also changes when the file changes -- and on every other request
as well, which does not fix caching, it abolishes it, and would be invisible
in a browser because the page always looks right.

**A missing file still yields a usable URL.** A cache-buster must never be the
reason a page fails to render. The worst a version-less URL can do is serve a
stale copy, which is the situation being replaced; an exception takes the
whole page down.
"""

import os
import re
from pathlib import Path

import pytest


# Every `href`/`src` the page points at our own static mount.
STATIC_REF = re.compile(r'(?:href|src|content)="([^"]*?/static/[^"]+)"')


def _static_refs(html):
    return [m for m in STATIC_REF.findall(html)]


def _unversioned(html):
    return [u for u in _static_refs(html) if "v=" not in u]


# --- every asset a template asks for carries a version ----------------------

def test_the_stylesheet_is_versioned(client):
    """`style.css` is the file the incident was about, and it is the one asset
    on every single page."""
    html = client.get("/").get_data(as_text=True)

    sheets = [u for u in _static_refs(html) if u.endswith(".css")
              or ".css?" in u]
    assert sheets, "the page stopped linking a stylesheet at all"
    for url in sheets:
        assert "?v=" in url, f"unversioned stylesheet: {url}"


def test_the_scripts_are_versioned(client):
    """A stale `browse_folds.js` (#288) takes a feature away rather than
    restyling one, so JS is the half with the sharper failure."""
    html = client.get("/").get_data(as_text=True)

    scripts = [u for u in _static_refs(html) if ".js" in u]
    assert scripts, "the page stopped loading any script at all"
    for url in scripts:
        assert "?v=" in url, f"unversioned script: {url}"


# Routes that render a full page from `base.html`, which is where 10 of the 18
# call sites live. Asserted to be reachable rather than skipped on 404: a page
# that stopped existing must fail here loudly, because a silent skip is how a
# whole tier of this suite once went green while testing nothing.
FULL_PAGES = ["/", "/quiz", "/games/real_or_fake"]


@pytest.mark.parametrize("path", FULL_PAGES)
def test_no_page_asks_for_an_unversioned_asset(client, path):
    """The property stated whole, over whole rendered pages.

    Asserted on the rendered HTML rather than by grepping `templates/`: the
    failure this guards is a call site that was **missed**, and a template
    that still says `url_for('static', ...)` renders a URL that works, looks
    right and caches wrongly. Only the output distinguishes the two.
    """
    r = client.get(path)
    assert r.status_code == 200, f"{path} no longer renders ({r.status_code})"

    refs = _static_refs(r.get_data(as_text=True))
    assert refs, f"{path} references no static asset at all"
    assert not _unversioned(r.get_data(as_text=True))


def test_a_page_reached_with_no_session_is_versioned_too(fresh_client):
    """Was `test_the_gate_page_is_versioned_too`. `gate.html` was its own
    document rather than an extension of `base.html`, carried its own three
    static references, and was the page most likely to be forgotten -- the one
    a developer signed in through the fixture never looked at.

    kuantorflow#199 deleted it. What is worth keeping is the shape of the
    case: an asset served to somebody with **no session** must be versioned
    too, since a first visitor and a crawler are the readers whose cache
    nobody can clear afterwards.
    """
    html = fresh_client.get("/").get_data(as_text=True)

    assert _static_refs(html), "the page stopped referencing static assets"
    assert not _unversioned(html)


def test_the_preview_image_is_versioned_and_still_absolute(client):
    """`_preview_meta.html` asks for `_external=True`, which is the one call
    that passes something through the helper besides a filename. An Open Graph
    image has to stay an absolute URL: a relative one is not fetchable by the
    service that reads the tag."""
    html = client.get("/").get_data(as_text=True)

    images = [u for u in _static_refs(html) if "preview.jpg" in u]
    assert images, "the preview meta tags are gone"
    for url in images:
        assert url.startswith("http"), f"no longer absolute: {url}"
        assert "?v=" in url, f"unversioned: {url}"


def test_the_topic_icons_are_versioned(app_module):
    """The two builders in `icons.py`, which are the call sites outside the
    templates. A topic icon is replaced **in place** -- same name, new
    artwork -- which is precisely the case where a stale picture is not still
    a picture."""
    import icons

    with app_module.app.test_request_context("/"):
        slugs = icons._topic_icon_slugs()
        if not slugs:
            pytest.skip("no topic icons in this checkout")
        name = "Crime and justice"
        if icons.topic_slug(name) not in slugs:
            pytest.skip("the sample topic has no icon here")

        assert "?v=" in icons.topic_icon(name)


def test_the_game_icons_are_versioned(app_module):
    import icons

    with app_module.app.test_request_context("/"):
        slugs = icons._icon_slugs(icons.GAME_ICON_DIR)
        if not slugs:
            pytest.skip("no game icons in this checkout")

        assert "?v=" in icons.game_icon(sorted(slugs)[0])


# --- stable while the file is not -------------------------------------------

def test_the_version_does_not_change_between_requests(client):
    """The assertion that separates a cache-buster from a cache-breaker.

    `now()` or a random token satisfies "changes when the file changes" and
    fails this one, and the difference is invisible in a browser because such
    a page always renders correctly -- it simply never reuses anything.
    """
    first = _static_refs(client.get("/").get_data(as_text=True))
    second = _static_refs(client.get("/").get_data(as_text=True))

    assert first == second


def test_the_version_changes_when_the_file_does(app_module, tmp_path):
    """And the other half, which is the whole point of the feature.

    Driven through the helper with a real file whose mtime is moved, rather
    than through a deploy: `web.static_url` remembers per process, so this
    reaches past the cache deliberately to test the derivation itself.
    """
    import web

    asset = Path(app_module.app.static_folder) / "css" / "style.css"
    if not asset.exists():
        pytest.skip("no stylesheet in this checkout")

    before = web._static_version("css/style.css")
    was = asset.stat()
    try:
        os.utime(asset, (was.st_atime, was.st_mtime + 3600))
        web._STATIC_VERSIONS.pop("css/style.css", None)
        after = web._static_version("css/style.css")
    finally:
        os.utime(asset, (was.st_atime, was.st_mtime))
        web._STATIC_VERSIONS.pop("css/style.css", None)

    assert before and after and before != after


def test_two_different_files_get_different_versions(app_module):
    """A single per-process token -- a boot id, say -- would pass every test
    above and invalidate the entire cache on every reload, which is a worse
    trade than the bug: a deploy that touched one line of CSS would refetch
    every image on the site."""
    import web

    with app_module.app.test_request_context("/"):
        css = web._static_version("css/style.css")
        js = web._static_version("js/speech.js")

    if not css or not js:
        pytest.skip("those assets are not both present in this checkout")
    assert css != js


# --- a missing file must not take the page down -----------------------------

def test_a_missing_file_still_yields_a_usable_url(app_module):
    """The fallback, and it is not a nicety. A `KeyError` or an `OSError` here
    turns a mistyped filename -- or an asset not yet deployed -- into a 500 on
    every page that references it."""
    import web

    with app_module.app.test_request_context("/"):
        url = web.static_url("css/there-is-no-such-file.css")

    assert url.endswith("/static/css/there-is-no-such-file.css")
    assert "?v=" not in url


def test_a_missing_file_does_not_stop_a_page_rendering(app_module):
    """The same property one level up, because that is where it would be
    noticed: through a real render rather than a direct call."""
    from flask import render_template_string

    with app_module.app.test_request_context("/"):
        out = render_template_string(
            "{{ static_url('img/not-deployed-yet.webp') }}")

    assert "/static/img/not-deployed-yet.webp" in out


# --- the versioned URL is still served --------------------------------------

def test_the_versioned_url_actually_serves_the_file(client):
    """The one way this feature could break the site outright: a query string
    the static handler refuses. It does not -- Flask keys on the path -- but
    that is worth one assertion rather than an assumption, because the whole
    page would go unstyled if it were ever otherwise."""
    html = client.get("/").get_data(as_text=True)

    sheets = [u for u in _static_refs(html) if ".css" in u]
    assert sheets
    r = client.get(sheets[0])

    assert r.status_code == 200


def test_the_version_is_a_query_parameter_not_a_path(client):
    """`/static/css/style.a1b2.css` would need the file to exist under that
    name, or a rewrite rule -- and PythonAnywhere may serve `/static/` through
    its own mapping rather than Flask, where no rewrite of ours applies. The
    query string works either way, which is why it was chosen."""
    html = client.get("/").get_data(as_text=True)

    for url in _static_refs(html):
        path = url.split("?")[0]
        assert "v=" not in path, f"the version leaked into the path: {url}"
