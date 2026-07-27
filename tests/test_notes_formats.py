"""Notes uploads in .txt and .docx as well as .mht (kuantorflow#137).

All three formats share one Reverso state machine; only the line classifier
differs (colours for .mht/.docx, layout for plain text). A file may mix
Reverso copy-pastes with simple 'word — translation' lines.
"""

import io
import zipfile
from xml.sax.saxutils import escape

import pytest

import parsers

# --- fixtures ---------------------------------------------------------------

# A Reverso copy-paste as plain text: header, "N." markers that carry the
# explanation on the same line, the English example, its translation, then the
# translation terms one per line.
LUCID_TXT = """lucid dream
1. (awareness) dream where you know you are dreaming
In a lucid dream, she flew over mountains.
Во вещем сне она летала над горами.
вещий сон
осознанный сон
ясный сон
2. (dreams) dream you can control events in
He changed the story in his lucid dream.
Он изменил сюжет в своем осознанном сне.
"""

SIMPLE_TXT = """pursuit - преследование, стремление

haunting - преследующий, навязчивый
"""

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(paragraphs):
    """A minimal .docx: paragraphs of (text, colour) runs, colour may be None."""
    body = []
    for runs in paragraphs:
        xml = "".join(
            "<w:r>{}<w:t xml:space='preserve'>{}</w:t></w:r>".format(
                f"<w:rPr><w:color w:val='{colour}'/></w:rPr>" if colour else "",
                escape(text))
            for text, colour in runs
        )
        body.append(f"<w:p>{xml}</w:p>")
    document = (
        f"<?xml version='1.0' encoding='UTF-8'?>"
        f"<w:document xmlns:w='{W}'><w:body>{''.join(body)}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))
    return buffer.getvalue()


# The same Reverso entry as .docx: Word keeps Reverso's colours on the runs.
REVERSO_DOCX = _docx([
    [("exorbitant - extremely high (price)", None)],   # a plain line too
    [("fount ", "222C31"), ("Существительное", "607D8B")],
    [("1.", "546D79")],                                 # marker, example colour
    [("(water source) natural spring or fountain", "222C31")],
    [("The village was built near a fount.", "546D79")],
    [("Село було побудоване біля джерела.", "0A6CC2")],
    [("джерелофонтан", "2E3C43")],
    [("From <", "595959"), ("https://www.reverso.net/x", None)],
])


@pytest.fixture(autouse=True)
def no_ai_split(monkeypatch):
    """The glued-translation split calls Claude; keep these tests offline."""
    monkeypatch.setattr(parsers, "_split_glued_translations",
                        lambda strings: {s: [s] for s in strings})


# --- plain text -------------------------------------------------------------

def test_txt_reverso_copy_paste():
    cards, source = parsers.parse_txt_preview(LUCID_TXT.encode("utf-8"),
                                              topic="dreams")
    assert len(cards) == 1
    card = cards[0]
    assert card["word"] == "lucid dream" and card["topic"] == "dreams"
    assert card["pos"] is None          # plain text carries no part of speech
    # both senses aggregated, the "N." marker stripped off the explanation
    assert card["explanation_en"] == (
        "(awareness) dream where you know you are dreaming; "
        "(dreams) dream you can control events in")
    assert card["examples_en"] == [
        "In a lucid dream, she flew over mountains.",
        "He changed the story in his lucid dream.",
    ]
    # terms are listed one per line, so they arrive already separated
    assert card["translation_rus"] == "вещий сон, осознанный сон, ясный сон"
    assert card["examples_rus"] == [
        "Во вещем сне она летала над горами.",
        "Он изменил сюжет в своем осознанном сне.",
    ]
    assert "lucid dream" in source      # source shown beside the cards


def test_txt_simple_lines_keep_cyrillic_as_translation():
    cards, _ = parsers.parse_txt_preview(SIMPLE_TXT.encode("utf-8"), topic="vocab")
    assert [c["word"] for c in cards] == ["pursuit", "haunting"]
    assert cards[0]["translation_rus"] == "преследование, стремление"
    assert "explanation_en" not in cards[0], "Cyrillic is a translation, not a definition"


def test_txt_english_right_hand_side_is_still_an_explanation():
    cards, _ = parsers.parse_txt_preview(b"ubiquitous - present everywhere", "t")
    assert cards[0]["explanation_en"] == "present everywhere"
    assert "translation_rus" not in cards[0]


def test_txt_decoding_falls_back_to_cp1251():
    cards, _ = parsers.parse_txt_preview("pursuit - погоня".encode("cp1251"), "t")
    assert cards[0]["translation_rus"] == "погоня"


def test_txt_without_entries_yields_nothing():
    cards, _ = parsers.parse_txt_preview(b"just some prose with no separator", "t")
    assert cards == []


# --- .docx ------------------------------------------------------------------

def test_docx_reverso_and_plain_lines_in_one_file():
    cards, source = parsers.parse_docx_preview(REVERSO_DOCX, topic="vocab")
    assert [c["word"] for c in cards] == ["exorbitant", "fount"]  # document order
    assert cards[0]["explanation_en"] == "extremely high (price)"
    fount = cards[1]
    assert fount["pos"] == "noun"                       # Существительное mapped
    assert fount["explanation_en"] == "(water source) natural spring or fountain"
    # the "1." marker is coloured like an example but holds no content
    assert fount["examples_en"] == ["The village was built near a fount."]
    assert fount["translation_ukr"] == "джерелофонтан"  # split is stubbed here
    assert len(fount["examples_ukr"]) == 1
    assert "natural spring" in source
    assert "reverso.net" in source                      # source shown verbatim


def test_docx_single_sense_without_a_marker():
    """Reverso omits '1.' when a word has only one sense."""
    data = _docx([
        [("renowned ", "222C31"), ("Прилагательное", "607D8B")],
        [("(famous person) widely known", "222C31")],
        [("She is renowned for her discoveries.", "546D79")],
        [("відомий", "2E3C43")],
    ])
    cards, _ = parsers.parse_docx_preview(data, topic="vocab")
    assert len(cards) == 1
    assert cards[0]["word"] == "renowned" and cards[0]["pos"] == "adjective"
    assert cards[0]["explanation_en"] == "(famous person) widely known"
    assert cards[0]["translation_ukr"] == "відомий"     # Ukrainian detected


def test_docx_without_entries_yields_nothing():
    cards, _ = parsers.parse_docx_preview(_docx([[("just prose", None)]]), "t")
    assert cards == []


# --- dispatch ---------------------------------------------------------------

@pytest.mark.parametrize("filename", ["notes.txt", "NOTES.TXT"])
def test_parse_notes_preview_dispatches_on_the_extension(filename):
    cards, _ = parsers.parse_notes_preview(filename, SIMPLE_TXT.encode("utf-8"), "t")
    assert [c["word"] for c in cards] == ["pursuit", "haunting"]


def test_parse_notes_preview_rejects_other_formats():
    with pytest.raises(ValueError):
        parsers.parse_notes_preview("notes.doc", b"", "t")


# --- the upload route -------------------------------------------------------

def _upload(client, data, filename):
    return client.post(
        "/",
        data={"action": "upload_notes", "topic": "vocab",
              "notes_file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    ).get_data(as_text=True)


def test_txt_upload_shows_the_review_popup(client, saved):
    body = _upload(client, LUCID_TXT.encode("utf-8"), "notes.txt")
    assert saved == [], "an upload must not save anything before review"
    assert "Review the cards parsed from your file" in body
    assert body.count('class="proposal-card"') == 1
    assert 'name="word" value="lucid dream"' in body


def test_docx_upload_shows_the_review_popup(client, saved):
    body = _upload(client, REVERSO_DOCX, "notes.docx")
    assert saved == []
    assert body.count('class="proposal-card"') == 2
    assert 'name="word" value="fount"' in body


def test_unsupported_upload_is_reported(client, saved):
    body = _upload(client, b"anything", "notes.pdf")
    assert saved == []
    assert "Unsupported notes format" in body
    assert 'id="proposal-modal"' not in body


def test_empty_upload_reports_no_entries(client, saved):
    body = _upload(client, b"nothing parseable here", "notes.txt")
    assert "No vocabulary entries found in that file." in body
    assert 'id="proposal-modal"' not in body


def test_upload_panel_lists_the_three_formats(client):
    body = client.get("/").get_data(as_text=True)
    assert "Upload notes (.txt, .docx, .mht)" in body
    assert 'accept=".txt,.docx,.mht,.mhtml"' in body
    assert 'name="notes_file"' in body
