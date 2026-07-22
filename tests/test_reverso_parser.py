"""Reverso copy-paste .mht parsing (kuantorflow#134).

The parser detects OneNote copy-pastes of Reverso dictionary entries by their
colour-coded structure, builds one card per word+POS (senses aggregated), and
splits the glued translation strings with Claude. The AI split is stubbed
here; the split function's own parsing/fallback is tested via an injected
fake `anthropic` module (the real package isn't in this venv).
"""

import sys
import types

import parsers


def _reverso_mht(html_body):
    """Wrap an HTML body in a minimal OneNote-style .mht envelope."""
    return (
        b"From: <saved>\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/related; boundary="----=_B"\r\n\r\n'
        b"------=_B\r\n"
        b'Content-Type: text/html; charset="utf-8"\r\n'
        b"Content-Transfer-Encoding: 8bit\r\n\r\n"
        + html_body.encode("utf-8")
        + b"\r\n------=_B--\r\n"
    )


INQUISITIVE = """<html><body>
<p><span style="font-size:15pt;color:#222C31">inquisitive </span><span style="color:#607D8B">Прилагательное</span></p>
<p style="color:#546D79">1.</p>
<p style="color:#222C31">(<span style="font-style:italic">curious</span>) eager to learn or know</p>
<p style="color:#546D79;font-size:10.5pt">Her inquisitive mind sought new information.</p>
<p style="color:#0A6CC2">Её любознательный ум искал информацию</p>
<p style="color:#2E3C43">любознательныйпытливый</p>
<p style="color:#546D79">2.</p>
<p style="color:#222C31">(nosy) excessively curious</p>
<p style="color:#546D79;font-size:10.5pt">Her inquisitive nature led her to eavesdrop.</p>
<p style="color:#0A6CC2">Её любопытный характер</p>
<p style="color:#2E3C43">любопытныйназойливый</p>
</body></html>"""


def _stub_split(monkeypatch, table=None):
    table = table or {
        "любознательныйпытливый": ["любознательный", "пытливый"],
        "любопытныйназойливый": ["любопытный", "назойливый"],
    }
    monkeypatch.setattr(
        parsers, "_split_glued_translations",
        lambda strings: {s: table.get(s, [s]) for s in strings},
    )


# --- the parser -------------------------------------------------------------

def test_reverso_detected_and_parsed(monkeypatch):
    _stub_split(monkeypatch)
    cards, source = parsers.parse_mht_preview(_reverso_mht(INQUISITIVE), topic="vocab")
    assert len(cards) == 1
    c = cards[0]
    assert c["word"] == "inquisitive" and c["pos"] == "adjective"  # POS mapped
    assert c["topic"] == "vocab"
    # both senses' explanations aggregated, parentheses tidied
    assert "(curious) eager to learn or know" in c["explanation_en"]
    assert c["explanation_en"].count(";") == 1
    assert c["examples_en"] == [
        "Her inquisitive mind sought new information.",
        "Her inquisitive nature led her to eavesdrop.",
    ]
    # glued translations split + de-duplicated across senses
    assert c["translation_rus"] == "любознательный, пытливый, любопытный, назойливый"
    assert len(c["examples_rus"]) == 2
    assert "любознательный ум" in source          # readable source preserved


def test_reverso_one_card_per_pos(monkeypatch):
    """A word appearing under two parts of speech yields two distinct cards."""
    monkeypatch.setattr(parsers, "_split_glued_translations",
                        lambda s: {x: [x] for x in s})
    body = """<html><body>
<p><span style="color:#222C31">run </span><span style="color:#607D8B">Глагол</span></p>
<p style="color:#546D79">1.</p>
<p style="color:#222C31">to move fast</p>
<p style="color:#2E3C43">бежать</p>
<p><span style="color:#222C31">run </span><span style="color:#607D8B">Существительное</span></p>
<p style="color:#546D79">1.</p>
<p style="color:#222C31">an act of running</p>
<p style="color:#2E3C43">пробежка</p>
</body></html>"""
    cards, _ = parsers.parse_mht_preview(_reverso_mht(body))
    assert {(c["word"], c["pos"]) for c in cards} == {("run", "verb"), ("run", "noun")}


def test_reverso_ukrainian_pos_and_language(monkeypatch):
    monkeypatch.setattr(parsers, "_split_glued_translations",
                        lambda s: {x: [x] for x in s})
    body = """<html><body>
<p><span style="color:#222C31">book </span><span style="color:#607D8B">Іменник</span></p>
<p style="color:#546D79">1.</p>
<p style="color:#222C31">a written work</p>
<p style="color:#0A6CC2">Ця книжка є дуже цікавою</p>
<p style="color:#2E3C43">книга</p>
</body></html>"""
    cards, _ = parsers.parse_mht_preview(_reverso_mht(body))
    assert cards[0]["pos"] == "noun"                 # Іменник -> noun
    assert cards[0]["translation_ukr"] == "книга"    # Ukrainian letters detected
    assert "translation_rus" not in cards[0]


def test_non_reverso_mht_falls_back_to_line_parser():
    body = "<html><body><p>ubiquitous - present everywhere</p></body></html>"
    cards, _ = parsers.parse_mht_preview(_reverso_mht(body))
    assert len(cards) == 1 and cards[0]["word"] == "ubiquitous"
    assert cards[0]["explanation_en"] == "present everywhere"
    assert "examples_en" not in cards[0]             # line parser has no examples


# --- the AI split helper ----------------------------------------------------

def _inject_fake_anthropic(monkeypatch, reply=None, raises=False):
    fake = types.ModuleType("anthropic")

    class Messages:
        def create(self, **kwargs):
            block = types.SimpleNamespace(type="text", text=reply)
            return types.SimpleNamespace(content=[block])

    class Anthropic:
        def __init__(self, *a, **k):
            if raises:
                raise RuntimeError("no API key")
            self.messages = Messages()

    fake.Anthropic = Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)


def test_split_glued_translations_parses_model_reply(monkeypatch):
    _inject_fake_anthropic(
        monkeypatch, reply='{"0": ["верховный правитель", "владыка"]}')
    out = parsers._split_glued_translations(["верховный правительвладыка"])
    assert out == {"верховный правительвладыка": ["верховный правитель", "владыка"]}


def test_split_glued_translations_falls_back_on_error(monkeypatch):
    _inject_fake_anthropic(monkeypatch, raises=True)
    out = parsers._split_glued_translations(["абвгдежз"])
    assert out == {"абвгдежз": ["абвгдежз"]}          # whole string kept, no crash
