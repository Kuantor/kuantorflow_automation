"""A pipe inside a table cell in the report converters (kuantorflow#588).

`parse_markdown()` split every table row on every `|`, so a cell could not
hold one at all: `\\|`, GitHub's way of writing a pipe in a cell, split too and
left a stray backslash behind. Now it follows GitHub: only an unescaped `|`
separates cells, and `\\|` becomes a literal `|` -- inside backticks as well.
An unescaped pipe inside backticks still splits, as it does on GitHub, so a
file reads the same there and in our PDFs.
"""

import sys
from pathlib import Path

from conftest import KUANTORFLOW_PATH

sys.path.insert(0, str(Path(KUANTORFLOW_PATH) / "reports" / "scripts"))

import md_to_docx  # noqa: E402
import md_to_pdf  # noqa: E402

BS, LF = chr(92), chr(10)
HEADER = "| What | Notes |" + LF + "|---|---|" + LF


def _row(line):
    """The cells of the table's one body row, each as its runs."""
    ((kind, rows),) = md_to_docx.parse_markdown(HEADER + line)
    assert kind == "table"
    return rows[1]


def _texts(cells):
    return ["".join(r["text"] for r in cell) for cell in cells]


def test_an_escaped_pipe_is_a_pipe_not_a_column():
    assert _texts(_row("| a | x " + BS + "| y |")) == ["a", "x | y"]


def test_an_escaped_pipe_inside_backticks_is_a_pipe_in_the_code():
    cells = _row("| `grep A" + BS + "|B` | text |")

    assert cells[0] == [{"text": "grep A|B", "code": True}]
    assert _texts(cells) == ["grep A|B", "text"]


def test_no_backslash_is_left_behind():
    cells = _texts(_row("| one " + BS + "| two " + BS + "| three | end |"))
    assert cells == ["one | two | three", "end"]
    assert not any(BS in c for c in cells)


def test_an_escaped_pipe_at_the_end_of_a_row_stays_in_the_cell():
    """No closing separator: the row ends in the escaped pipe, which is the
    cell's text, not a separator to strip."""
    assert _texts(_row("| a | b " + BS + "|")) == ["a", "b |"]


def test_an_ordinary_row_is_unchanged():
    assert _texts(_row("| **bold** | `code` and text |")) == ["bold", "code and text"]


def test_a_backslash_not_before_a_pipe_is_kept():
    """A Windows path ends in a backslash; a space before the separator means
    it is not an escape, and the cell keeps it."""
    assert _texts(_row("| C:" + BS + "Users" + BS + " | next |")) == \
        ["C:" + BS + "Users" + BS, "next"]


def test_an_unescaped_pipe_in_backticks_still_splits_as_on_github():
    """GitHub splits it too; the way to keep it is to escape it, there and
    here, so a file reads the same in both."""
    assert len(_row("| `a|b` | c |")) == 3


def test_the_pdf_row_has_as_many_cells_as_the_header():
    table = HEADER + "| `grep A" + BS + "|B` | text |"
    html = md_to_pdf.blocks_to_html(md_to_docx.parse_markdown(table))

    assert html.count("<th>") == 2 and html.count("<td>") == 2
    assert "<code>grep A|B</code>" in html
