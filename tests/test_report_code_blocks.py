"""Fenced code blocks in the report converters (kuantorflow#586).

`reports/scripts/md_to_docx.py`'s `parse_markdown()`, which `md_to_pdf.py`
shares, had no code blocks at all: a fenced block was read as a paragraph, so
its lines were joined with spaces, the fence's label (`bash`, `powershell`)
became the first word, and the backticks were read as inline code marks. The
committed spaced-repetition report printed the dry run and the real run of
`rebuild_schedule.py` as one line -- a wrong command to copy.

A fence (``` or ~~~, labelled or not) is now a `code` block that keeps its
lines exactly, with no inline parsing inside and no label, and both emitters
draw it as monospace lines.
"""

import sys
from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

sys.path.insert(0, str(Path(KUANTORFLOW_PATH) / "reports" / "scripts"))

import md_to_docx  # noqa: E402
import md_to_pdf  # noqa: E402

FENCE = "`" * 3
LF = chr(10)

TWO_COMMANDS = LF.join([
    "Run the rebuild:",
    "",
    FENCE + "bash",
    "venv/bin/python scripts/rebuild_schedule.py --dry-run",
    "venv/bin/python scripts/rebuild_schedule.py",
    FENCE,
    "",
    "Then **reload** the app.",
])


def _code_blocks(blocks):
    return [b for b in blocks if b[0] == "code"]


# --- parsing ----------------------------------------------------------------

def test_a_labelled_fence_is_one_code_block_with_its_lines():
    blocks = md_to_docx.parse_markdown(TWO_COMMANDS)

    (code,) = _code_blocks(blocks)
    assert code[1] == ["venv/bin/python scripts/rebuild_schedule.py --dry-run",
                       "venv/bin/python scripts/rebuild_schedule.py"]


def test_the_label_is_dropped():
    blocks = md_to_docx.parse_markdown(TWO_COMMANDS)
    text = repr(blocks)
    assert "bash" not in text and FENCE not in text


def test_the_text_after_a_fence_is_a_paragraph_again():
    blocks = md_to_docx.parse_markdown(TWO_COMMANDS)
    assert blocks[0][0] == "p" and blocks[-1][0] == "p"
    assert {"text": "reload", "bold": True} in blocks[-1][1]


@pytest.mark.parametrize("opening, closing", [
    (FENCE, FENCE), ("~~~", "~~~"), (FENCE + "powershell", FENCE),
    ("  " + FENCE + "python", "  " + FENCE)])
def test_every_fence_spelling_works(opening, closing):
    blocks = md_to_docx.parse_markdown(LF.join([opening, "a = 1", "b = 2", closing]))
    assert blocks == [("code", ["a = 1", "b = 2"])]


def test_markdown_inside_a_block_stays_literal():
    lines = ["**not bold**", "| not | a table |", "- not a bullet", "# not a title",
             "`not code`", "---", "~~~"]   # the other fence character does not close it
    blocks = md_to_docx.parse_markdown(LF.join([FENCE] + lines + [FENCE]))
    assert blocks == [("code", lines)]


def test_blank_lines_and_indentation_inside_a_block_are_kept():
    lines = ["def f():", "    return 1", "", "print(f())"]
    blocks = md_to_docx.parse_markdown(LF.join([FENCE + "python"] + lines + [FENCE]))
    assert blocks == [("code", lines)]


def test_an_indented_fence_takes_its_indent_off_its_lines():
    """CommonMark: inside a list, say, the fence's own indent is not code."""
    blocks = md_to_docx.parse_markdown(LF.join(
        ["  " + FENCE + "bash", "  ls -la", "    deeper", "  " + FENCE]))
    assert blocks == [("code", ["ls -la", "  deeper"])]


def test_an_unclosed_fence_runs_to_the_end_rather_than_vanishing():
    blocks = md_to_docx.parse_markdown(LF.join([FENCE + "bash", "ls", "pwd"]))
    assert blocks == [("code", ["ls", "pwd"])]


# --- rendering --------------------------------------------------------------

def test_the_pdf_html_draws_each_line_on_its_own_line():
    html = md_to_pdf.blocks_to_html(md_to_docx.parse_markdown(TWO_COMMANDS))

    pre = html.split("<pre", 1)[1].split("</pre>", 1)[0]
    assert ("--dry-run" + LF + "venv/bin/python scripts/rebuild_schedule.py") in pre
    assert "bash" not in html


def test_the_pdf_html_escapes_a_block():
    blocks = md_to_docx.parse_markdown(LF.join([FENCE, "a < b && c > d", FENCE]))
    assert "a &lt; b &amp;&amp; c &gt; d" in md_to_pdf.blocks_to_html(blocks)


def test_the_pdf_styles_a_block_as_wrapping_monospace():
    css = md_to_pdf.CSS
    rule = css.split("pre", 1)[1].split("}", 1)[0]
    assert "monospace" in rule and "pre-wrap" in rule


def test_the_docx_keeps_each_line_in_monospace(tmp_path):
    import docx
    out = tmp_path / "out.docx"
    md_to_docx.build_docx(md_to_docx.parse_markdown(TWO_COMMANDS), str(out))

    paragraphs = docx.Document(str(out)).paragraphs
    texts = [p.text for p in paragraphs]
    first = texts.index("venv/bin/python scripts/rebuild_schedule.py --dry-run")
    assert texts[first + 1] == "venv/bin/python scripts/rebuild_schedule.py"
    assert all(r.font.name == "Consolas"
               for p in paragraphs[first:first + 2] for r in p.runs)
    assert not any("bash" in t for t in texts)


# --- the report that shipped with the bug ------------------------------------

def test_the_spaced_repetition_report_has_its_commands_apart():
    from pypdf import PdfReader
    pdf = Path(KUANTORFLOW_PATH) / "reports" / "2026-09-28-spaced-repetition.pdf"
    text = LF.join(page.extract_text() for page in PdfReader(str(pdf)).pages)

    assert "bash venv" not in text
    assert "rebuild_schedule.py --dry-run venv/bin/python" not in text
