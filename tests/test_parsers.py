"""Offline parser checks: MHT extraction and DB text/list round-tripping."""

from parsers import _entry_from_line, parse_mht_file
from utils import _to_list

MHT = """From: <Saved by Windows Internet Explorer>
Subject: Vocabulary
MIME-Version: 1.0
Content-Type: multipart/related; boundary="----=_NextPart_01D"

------=_NextPart_01D
Content-Type: text/html; charset="utf-8"
Content-Transfer-Encoding: 8bit

<html><body>
<p>resilient — able to recover quickly from difficulties</p>
<p>ubiquitous - present everywhere at the same time</p>
<li>meticulous: showing great attention to detail</li>
<p>Just a plain sentence without a separator that spans some words.</p>
<p>resilient — duplicate entry should be skipped</p>
</body></html>
------=_NextPart_01D--
"""


def test_mht_extraction():
    entries = parse_mht_file(MHT.encode("utf-8"), topic="vocab")
    assert [e["word"] for e in entries] == ["resilient", "ubiquitous", "meticulous"]
    assert entries[2]["explanation_en"] == "showing great attention to detail"
    assert all(e["topic"] == "vocab" for e in entries)


def test_entry_from_line_rejects_plain_text():
    assert _entry_from_line("", "t") is None
    assert _entry_from_line("no separator here", "t") is None


def test_to_list_round_trip():
    assert _to_list(None) == []
    assert _to_list('["a", "b"]') == ["a", "b"]
    assert _to_list('["Привіт", "Ще один"]') == ["Привіт", "Ще один"]
    assert _to_list("line one\nline two") == ["line one", "line two"]
    assert _to_list("single example") == ["single example"]
    assert _to_list("[not json") == ["[not json"]
