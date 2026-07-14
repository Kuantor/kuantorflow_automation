#!/usr/bin/env python3
"""Dump the text of any .pptx / .docx to plain UTF-8 — no dependencies.

Office files are ZIP archives of XML. This reads them with the standard
library only (no python-pptx / markitdown needed), which makes it a handy
first step whenever you need to *read* a deck or document — e.g. to plan a
merge or feed the content to something else.

Usage:
    python ooxml_extract.py deck.pptx
    python ooxml_extract.py speech.docx --out speech.txt
    python ooxml_extract.py *.pptx *.docx          # several at once

For a .pptx it prints one block per slide (with the media each slide
references); for a .docx it prints the paragraphs in order.
"""
import argparse
import os
import re
import sys
import zipfile


def _unescape(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'").replace("&apos;", "'"))


def docx_text(path):
    z = zipfile.ZipFile(path)
    xml = z.read("word/document.xml").decode("utf-8", "replace")
    out = []
    for para in re.split(r"</w:p>", xml):
        t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.S))
        t = _unescape(t).strip()
        if t:
            out.append(t)
    return "\n".join(out)


def pptx_text(path):
    z = zipfile.ZipFile(path)
    names = sorted(
        (n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
        key=lambda n: int(re.search(r"(\d+)", n).group()),
    )
    lines = []
    for n in names:
        num = re.search(r"(\d+)", os.path.basename(n)).group()
        xml = z.read(n).decode("utf-8", "replace")
        texts = [_unescape(t) for t in re.findall(r"<a:t>(.*?)</a:t>", xml, re.S)]
        rels = "ppt/slides/_rels/" + os.path.basename(n) + ".rels"
        imgs = []
        if rels in z.namelist():
            r = z.read(rels).decode("utf-8", "replace")
            imgs = re.findall(r'Target="\.\./media/([^"]+)"', r)
        lines.append(f"\n===== SLIDE {num} | images: {imgs} =====")
        lines.extend("  " + t for t in texts if t.strip())
    return "\n".join(lines)


def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return docx_text(path)
    if ext == ".pptx":
        return pptx_text(path)
    raise ValueError(f"Unsupported file type: {ext} (expected .pptx or .docx)")


def main():
    ap = argparse.ArgumentParser(description="Dump .pptx/.docx text to plain UTF-8.")
    ap.add_argument("files", nargs="+", help="One or more .pptx / .docx files")
    ap.add_argument("--out", help="Write to this file instead of stdout")
    args = ap.parse_args()

    chunks = []
    for f in args.files:
        header = f"########## {os.path.basename(f)} ##########"
        chunks.append(header + "\n" + extract(f))
    text = "\n\n".join(chunks)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"written: {args.out}")
    else:
        # force UTF-8 so Windows consoles don't choke on smart quotes/dashes
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
