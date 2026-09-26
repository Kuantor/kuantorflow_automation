"""The Help page serves the learner's guide (kuantorflow#460).

`/help` renders `docs/user-guide.md` inside the site's chrome, and the header
links to it from every page. The guide was already written; the risk this
ticket named is a **second copy** of it.

That risk has a history. `MYKOLA_KNOWLEDGE` hands the same file to the agent
(#310), and #310 exists because ai_agent once kept its own description of this
app, which drifted until Mykola answered "why can't I add cards?" from text
written before #125. A Help page holding its own prose would be that failure
again, in one repo, and invisible: the page and the companion would disagree,
each confidently. So the rule is **one file, two surfaces**, and most of what
is pinned here is that rule:

* the page serves the *file*, proved with a heading that exists in a temporary
  guide and nowhere else, rather than by finding text a copy might also hold;
* one declaration of where the file is (`web.USER_GUIDE`), read by both;
* no template carries the guide's words.

Three more things fail silently and are pinned for that reason: the committed
PDF going stale (it had, by a month, and still told learners to type the
keyword); a missing renderer taking the whole site down rather than one page;
and contents links pointing at anchors that do not exist.
"""

import re
import unicodedata
from pathlib import Path

import pytest


def _guide(app_module):
    import web
    return Path(web.USER_GUIDE).read_text(encoding="utf-8")


def _headings(md, level):
    return [h.strip() for h in re.findall(rf"^{'#' * level} (.+)$", md, re.M)]


@pytest.fixture()
def fresh_render(app_module, monkeypatch):
    """Empty the per-process cache, so a test sees its own guide."""
    import app
    monkeypatch.setattr(app, "_GUIDE_CACHE", {})
    return app


# --- the page is there, for anybody ------------------------------------------

def test_the_help_page_answers_a_visitor_with_no_session(fresh_client,
                                                         fresh_render):
    r = fresh_client.get("/help")

    assert r.status_code == 200
    assert "<title>Help | KuantorFlow</title>" in r.get_data(as_text=True)


def test_every_section_of_the_guide_is_on_the_page(client, fresh_render):
    body = client.get("/help").get_data(as_text=True)
    md = _guide(fresh_render)

    missing = [h for h in _headings(md, 2) + _headings(md, 3)
               if h.replace("&", "&amp;") not in body]
    assert missing == [], f"guide headings not rendered: {missing}"


# --- one file, two surfaces --------------------------------------------------

def test_the_page_serves_the_file_not_a_copy(client, fresh_render,
                                             monkeypatch, tmp_path):
    """The test the ticket asks for, made airtight: a heading that exists in
    a temporary guide and **nowhere else at all**. Finding the real guide's
    text on the page cannot tell a render from a copy; this can."""
    guide = tmp_path / "user-guide.md"
    guide.write_text("# Guide\n\n## Sentinel section 7f3a\n\nBody.\n",
                     encoding="utf-8")
    monkeypatch.setattr("web.USER_GUIDE", guide)

    body = client.get("/help").get_data(as_text=True)

    assert "Sentinel section 7f3a" in body


def test_an_edit_to_the_guide_shows_without_a_restart(client, fresh_render,
                                                      monkeypatch, tmp_path):
    """The render is cached per process, keyed on the file's mtime. A cache
    keyed on nothing would show the first version forever -- which is a stale
    copy by another name, the thing request-time rendering was chosen to
    avoid."""
    import os
    guide = tmp_path / "user-guide.md"
    guide.write_text("# Guide\n\n## First wording\n", encoding="utf-8")
    monkeypatch.setattr("web.USER_GUIDE", guide)
    client.get("/help")

    guide.write_text("# Guide\n\n## Second wording\n", encoding="utf-8")
    stat = guide.stat()
    os.utime(guide, (stat.st_atime, stat.st_mtime + 10))
    body = client.get("/help").get_data(as_text=True)

    assert "Second wording" in body
    assert "First wording" not in body


def test_mykola_and_the_page_read_one_declaration(app_module):
    """Both surfaces read `web.USER_GUIDE`. A second literal path anywhere is
    how the two would come to read different files without anything failing."""
    import chat, web

    assert chat.MYKOLA_KNOWLEDGE == [web.USER_GUIDE]
    assert Path(web.USER_GUIDE).is_file()

    root = Path(app_module.app.root_path)
    literals = [p.name for p in root.glob("*.py")
                if p.name != "web.py"
                and '"user-guide.md"' in p.read_text(encoding="utf-8")]
    assert literals == [], f"a second declaration of the guide in {literals}"


def test_no_template_carries_the_guides_words(app_module):
    """The template holds structure only. Checked against the guide's longer
    `###` headings -- a one-word heading such as *Quiz* is also an activity
    name and appears in templates for its own reasons."""
    md = _guide(app_module)
    phrases = [h for h in _headings(md, 3) if len(h.split()) >= 4]
    templates = Path(app_module.app.root_path) / "templates"
    text = "\n".join(p.read_text(encoding="utf-8")
                     for p in templates.glob("*.html"))

    assert phrases, "no multi-word headings to check against"
    copied = [h for h in phrases if h in text]
    assert copied == [], f"guide text found in a template: {copied}"


# --- contents and anchors ----------------------------------------------------

def test_the_contents_list_is_the_top_level_sections(client, fresh_render):
    """Only the `##` sections, derived from the guide. All thirty-odd `###`
    headings in a list above the text would push the guide below the fold on
    a phone -- what #452 had just removed from the topic page."""
    body = client.get("/help").get_data(as_text=True)
    contents = body[body.index('class="help-contents"'):]
    contents = contents[:contents.index("</nav>")]

    assert len(re.findall(r"<a ", contents)) == len(
        _headings(_guide(fresh_render), 2))


def test_every_contents_link_lands_on_an_anchor(client, fresh_render):
    body = client.get("/help").get_data(as_text=True)
    contents = body[body.index('class="help-contents"'):]
    targets = re.findall(r'href="#([^"]+)"', contents[:contents.index("</nav>")])
    ids = set(re.findall(r'id="([^"]+)"', body))

    assert targets, "the contents list links to nothing"
    assert [t for t in targets if t not in ids] == []


def test_every_feature_heading_has_an_anchor(client, fresh_render):
    """Every `###` can be linked to, even though the contents list stops at
    `##` -- one heading per feature is the unit a learner would link."""
    body = client.get("/help").get_data(as_text=True)

    assert len(re.findall(r"<h3 id=", body)) == len(
        _headings(_guide(fresh_render), 3))


# --- the link, on every page ---------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/quiz", "/games/scrambled", "/help"])
def test_the_header_links_to_help_on_every_page(client, fresh_render, path):
    body = client.get(path).get_data(as_text=True)
    header = body[body.index('class="site-header"'):body.index("</header>")]

    assert 'href="/help"' in header, f"no Help link in the header of {path}"


def test_help_is_marked_current_only_on_the_help_page(client, fresh_render):
    def header(path):
        body = client.get(path).get_data(as_text=True)
        return body[body.index('class="site-header"'):body.index("</header>")]

    assert 'aria-current="page"' in header("/help")
    assert 'aria-current="page"' not in header("/")


def test_the_guide_describes_the_header_it_now_has(app_module):
    """A feature a learner would notice is a guide change (CLAUDE.md), and
    here the guide being corrected is the one the page serves."""
    md = _guide(app_module)
    line = next(l for l in md.splitlines() if "The header carries" in l)

    assert "**Help**" in line, line


# --- the PDF -----------------------------------------------------------------

def test_the_pdf_is_offered_and_downloads(client, fresh_render):
    body = client.get("/help").get_data(as_text=True)
    r = client.get("/help/user-guide.pdf")

    assert 'href="/help/user-guide.pdf"' in body
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:5] == b"%PDF-"


def test_the_pdf_is_not_stale(app_module):
    """Every section of the guide appears in the committed PDF.

    It is a build artefact, and it had drifted a month behind -- still telling
    learners to type a keyword the site no longer asks for. Checked on
    headings because they are what a stale PDF loses first and read back
    reliably.

    Text is **NFKC-normalised** first, and that is load-bearing: the renderer
    sets `fl` as one ligature glyph, so "flashcard" reads back as "ﬂashcard"
    and two real headings looked missing until it was.
    """
    from pypdf import PdfReader
    import web

    def norm(s):
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s))

    pdf = Path(web.USER_GUIDE_PDF)
    text = norm(" ".join(p.extract_text() for p in PdfReader(pdf).pages))
    md = _guide(app_module)

    missing = [h for h in _headings(md, 2) + _headings(md, 3)
               if norm(h) not in text]
    assert missing == [], (
        f"the PDF lacks {missing}; regenerate it with "
        "reports/scripts/md_to_pdf.py docs/user-guide.md docs/user-guide.pdf")


# --- a missing renderer costs this page, not the site ------------------------

def test_without_the_renderer_the_page_offers_the_pdf(client, fresh_render,
                                                      monkeypatch):
    """`markdown` is the one dependency #460 adds. Imported inside the route,
    a deploy that misses its `pip install` loses `/help` alone -- which says
    so and offers the PDF -- rather than failing at import and taking every
    page with it."""
    import builtins
    real_import = builtins.__import__

    def no_markdown(name, *args, **kwargs):
        if name == "markdown":
            raise ImportError("No module named 'markdown'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_markdown)
    help_page = client.get("/help")
    index = client.get("/")

    assert help_page.status_code == 200
    body = help_page.get_data(as_text=True)
    assert "can&rsquo;t be shown right now" in body
    assert 'href="/help/user-guide.pdf"' in body
    assert index.status_code == 200, "the rest of the site went down with it"


def test_no_module_imports_the_renderer_at_the_top(app_module):
    """The structural half of the case above. A top-level `import markdown`
    would pass every other test here on a machine that has it installed."""
    root = Path(app_module.app.root_path)
    top_level = [p.name for p in root.glob("*.py")
                 if re.search(r"^(import markdown|from markdown )",
                              p.read_text(encoding="utf-8"), re.M)]

    assert top_level == [], f"imported at module level in {top_level}"


def test_the_renderer_is_a_declared_dependency(app_module):
    reqs = (Path(app_module.app.root_path) / "requirements.txt").read_text(
        encoding="utf-8")

    assert re.search(r"^markdown==", reqs, re.M | re.I)
