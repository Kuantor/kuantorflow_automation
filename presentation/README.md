# Presentation tooling

Reusable helpers for building KuantorFlow talk decks and reading existing
Office files. Distilled from a real presentation build so the *next* deck is
quick to assemble; no one talk's content is baked in.

## Scripts

### `ooxml_extract.py` — read any `.pptx` / `.docx`
Stdlib only, no dependencies. Dumps the text of a slide deck or document to
plain UTF-8 — the first step when you need to *read* source material (e.g. to
plan a merge) without installing `markitdown` or `python-pptx`.

```bash
python ooxml_extract.py deck.pptx                 # one block per slide (+ media refs)
python ooxml_extract.py speech.docx --out out.txt # paragraphs, to a file
python ooxml_extract.py *.pptx *.docx             # several at once
```

### `deck_kit.py` — build a branded deck fast
A small `python-pptx` library: the KuantorFlow blue/gold theme plus tested
16:9 layouts (title, content rows, code panel, full-bleed image, closing) and
speaker-notes support.

```python
from deck_kit import Deck
d = Deck()
d.title_slide("My Talk", "A subtitle", eyebrow="SERIES")
s = d.content_slide("Section", "Three things")
d.rows(s, [("First", "why it matters"), ("Second", "..."), ("Third", "...")])
d.notes(s, "What I'll say over this slide.")
d.code_slide("Example", "A snippet", "print('hi')", "One-line takeaway.")
d.closing_slide("Thanks!", subtitle="...", bullets=["a", "b"], footer="deck_kit.py")
d.save("out.pptx")
```

Run it directly to regenerate a sample deck that exercises every layout — it
doubles as living documentation and a smoke test:

```bash
python deck_kit.py        # writes deck_kit_demo.pptx
```

## Dependencies

- `ooxml_extract.py`: none (standard library).
- `deck_kit.py`: `python-pptx` (and `Pillow`, used only by `pic_fit` for image
  sizing). Install with `pip install python-pptx Pillow`.

## Notes

- Decks are 16:9 (13.333" × 7.5") by default; pass `Deck(width_in, height_in)`
  to change.
- These tools don't render — to preview a generated `.pptx`, open it in
  PowerPoint (or convert with LibreOffice if you have it).
