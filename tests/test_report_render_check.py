"""The render check in `reports/scripts/md_to_pdf.py` (kuantorflow#282).

Headless Edge exits before it has rendered anything, so `md_to_pdf.py` reads
the finished PDF back rather than trusting the exit code (kuantorflow#211).
Two failures have to stay apart, and the whole file is about the line between
them:

* the PDF **is** Edge's "File not found" page — a structurally valid document
  that passes every cheaper check, and once got committed as a report;
* the PDF is a real report that *writes about* that trap and quotes the
  string. Searching the whole document could not tell the two apart, and
  refused the 15 August 2026 edition twice for saying the words out loud.

What separates them is **shape**: the error page is a single page that is
almost nothing but the message (92 characters), while a report is long, has
its own headings, and mentions the string in passing. So the check is scoped
to that shape, and these tests pin both directions — because the loose version
was never wrong, only over-broad, and narrowing it must not let the thing it
was written for through.

`_read_back()` is the seam: it is the only part that touches pypdf and a file
on disk, so stubbing it lets the rules be exercised over exactly the documents
that matter, including ones no test could render on purpose.
"""

import sys
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

# The converter is build-time tooling, not part of the app, so it is not on
# `sys.path` from importing `app` — its own directory has to be added, and it
# imports its Markdown parser from `md_to_docx` next to it.
sys.path.insert(0, str(Path(KUANTORFLOW_PATH) / "reports" / "scripts"))

import md_to_pdf  # noqa: E402  (the path above has to be set first)

OUT = Path("2026-08-15-weekly-report.pdf")

# Captured from a real run: Edge printed to PDF with a file:// URI that does
# not exist. Written out rather than paraphrased, since the check is a claim
# about this exact document.
ERROR_PAGE = ("File not found\nIt may have been moved, edited, or deleted.\n"
              "ERR_FILE_NOT_FOUND\nMicrosoft Edge")

REPORT_MD = """# Weekly report, 9 - 15 August 2026

## Executive Summary

## Lessons Learned
"""

# A report's extracted text: its headings, and the trap written down in the
# section that exists to write traps down.
REPORT_TEXT = (
    "Weekly report, 9 - 15 August 2026 Executive Summary "
    + "The week's work, at the length a real report runs to. " * 20
    + "Lessons Learned "
    + "Headless Edge returns before it has rendered, and will print its own "
      "File not found page — ERR_FILE_NOT_FOUND — as a valid PDF. " * 6
)


@pytest.fixture()
def rendered(monkeypatch):
    """Pretend the finished PDF holds this many pages and this text."""
    def _rendered(pages, text):
        monkeypatch.setattr(md_to_pdf, "_read_back", lambda out: (pages, text))
    return _rendered


def _refusal(src_md, out=OUT):
    with pytest.raises(SystemExit) as exit_info:
        md_to_pdf.verify(src_md, out)
    return str(exit_info.value)


# --- the error page is still the error page -----------------------------


def test_the_error_page_is_refused_by_the_message_it_always_had(rendered):
    """The wording is load-bearing: it names the hand-off failure, which is
    what the reader has to go and fix. A generic 'did not render' would send
    them looking at their Markdown instead."""
    rendered(1, ERROR_PAGE)
    assert _refusal(REPORT_MD) == \
        "error: 2026-08-15-weekly-report.pdf is Edge's error page, not the report."


def test_the_error_page_is_caught_before_the_length_check(rendered):
    """Both rules match a 92-character document, so order decides which
    message is printed. The specific one comes first, on purpose."""
    rendered(1, ERROR_PAGE)
    assert "error page" in _refusal(REPORT_MD)
    assert "characters of text" not in _refusal(REPORT_MD)


@pytest.mark.parametrize("marker", ["ERR_FILE_NOT_FOUND", "File not found"])
def test_either_marker_alone_identifies_it(rendered, marker):
    """Edge's page carries both, but they are checked separately — a future
    Edge that drops one of them should still be caught by the other."""
    rendered(1, f"{marker}\nMicrosoft Edge")
    assert "error page" in _refusal(REPORT_MD)


# --- a report may write about it ----------------------------------------


def test_a_report_that_quotes_the_error_string_verifies(rendered):
    """kuantorflow#282, and the reason this file exists. Six pages that
    mention the string once are a report, not an error page."""
    rendered(6, REPORT_TEXT)
    assert md_to_pdf.verify(REPORT_MD, OUT) == (6, len(REPORT_TEXT))


def test_a_one_page_report_may_quote_it_too(rendered):
    """Page count alone is not the rule. Short documents get rendered here as
    well — a one-page note about the trap must not be refused for being one
    page, because what makes the error page recognisable is that the message
    is *all there is*."""
    rendered(1, REPORT_TEXT)
    assert md_to_pdf.verify(REPORT_MD, OUT) == (1, len(REPORT_TEXT))


# --- everything else the check still catches ----------------------------


def test_a_render_that_produced_almost_nothing_is_refused(rendered):
    """No marker, so the error-page rule says nothing — and the render is
    still bad. This is the general guard the narrow rule leans on."""
    rendered(1, "Weekly report, 9 - 15 August 2026")
    assert "characters of text" in _refusal(REPORT_MD)


def test_a_long_render_missing_a_heading_is_refused(rendered):
    """The strong signal, and what makes it safe for the marker rule to be
    narrow: whatever else a document says, one that lost a heading from the
    source is a bad render."""
    rendered(6, REPORT_TEXT.replace("Lessons Learned", "Lessons"))
    assert "missing 1 heading(s)" in _refusal(REPORT_MD)
    assert "Lessons Learned" in _refusal(REPORT_MD)


# --- and there is no way around it --------------------------------------


def test_nothing_can_switch_the_check_off():
    """kuantorflow#211's point, restated in kuantorflow#282: the check is not
    optional, so narrowing it must not have introduced a way past it. Read
    from the source because a flag is only ever added *somewhere* — an
    argument, an environment variable, a keyword with a default."""
    source = Path(md_to_pdf.__file__).read_text(encoding="utf-8")
    assert "environ" not in source, "an environment variable could skip it"
    assert "--skip" not in source and "--no-verify" not in source
    assert md_to_pdf.verify.__defaults__ is None, \
        "verify() grew an optional parameter"
