"""Every picture in static/img is one the app actually asks for (kuantorflow#361).

`Copilot_20260826_023410+3.jpg` rode into the repository inside kuantorflow#353,
a commit about translation providers, because a `git add` of the directory swept
up an export that happened to be sitting in it. Nothing referenced it, nothing
served it, and it stayed for a day being downloaded by nobody — an artwork
export is a few hundred kilobytes, and the next one would be just as quiet.

Names, not bytes: this asks whether each file is spoken for, and says which one
is not. Two directories are exempt and the reason is in the test.
"""

from pathlib import Path

import pytest

from conftest import KUANTORFLOW_PATH

APP = Path(KUANTORFLOW_PATH)
IMG = APP / "static" / "img"

# Where a filename could be written down. Nothing under static/img itself: a
# picture referenced only by another picture is still unreferenced.
SEARCHED = [APP / "templates", APP / "static" / "css", APP / "static" / "js"]
SEARCHED_FILES = list(APP.glob("*.py"))

# Referenced by slug at run time — `img/topics/<slug>.webp` and
# `img/games/<slug>.webp` are built in app.py from the topic name and the
# activity, so no filename of theirs appears anywhere to be matched. Their
# own completeness is test_topic_icons.py's question, not this one.
BY_SLUG = {"topics", "games"}


def _haystack():
    text = []
    for root in SEARCHED:
        for path in root.rglob("*"):
            if path.is_file():
                text.append(path.read_text(encoding="utf-8", errors="ignore"))
    for path in SEARCHED_FILES:
        text.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(text)


def _top_level_images():
    return sorted(p for p in IMG.iterdir()
                  if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg",
                                                          ".png", ".webp",
                                                          ".gif", ".svg"})


def test_there_are_images_to_check():
    """The guard that stops this file passing by finding nothing."""
    assert len(_top_level_images()) >= 5


@pytest.mark.parametrize("name", [p.name for p in _top_level_images()])
def test_every_top_level_image_is_referenced(name):
    assert name in _haystack(), (
        f"static/img/{name} is not named in any template, stylesheet, script "
        "or module — either something should be using it, or it was committed "
        "by accident, as #361's was"
    )


def test_the_directories_referenced_by_slug_are_still_only_those_two():
    """If a third one appears, this file is quietly not covering it."""
    assert {p.name for p in IMG.iterdir() if p.is_dir()} == BY_SLUG


def test_the_replaced_artwork_is_in_place():
    """kuantorflow#361's two files, by the names the app asks for.

    Not a hash: the point is that the names the stylesheet and the gate spell
    out still resolve to a real picture, which is what an artwork swap can get
    wrong — a rename that leaves `background_new.jpg` behind, or an image
    deleted with nothing put in its place.
    """
    for name in ("background.jpg", "hi_there.jpg"):
        assert (IMG / name).is_file()
        assert (IMG / name).stat().st_size > 1024

    leftovers = [p.name for p in IMG.iterdir() if "_new" in p.name]
    assert leftovers == [], f"the source files should have been renamed: {leftovers}"


# --- the gate's picture, which is the one a visitor waits for ---------------

# `.gate-card` is `max-width: 420px` with `padding: 2rem 2.2rem`, so the
# widest it can ever paint a full-width child is 420 - 2 x 35.2px.
CARD_CONTENT_PX = 420 - 2 * 2.2 * 16


def _jpeg_size(path):
    """(width, height) read out of a JPEG's frame header.

    By hand because there is no Pillow in this venv and one assertion does not
    justify adding it: the frame marker carries the dimensions in a fixed
    place, and everything before it can be skipped by its own length.
    """
    data = path.read_bytes()
    assert data[:2] == b"\xff\xd8", f"{path.name} is not a JPEG"
    frames = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            i += 2
            continue
        if marker in frames:
            return (int.from_bytes(data[i + 7:i + 9], "big"),
                    int.from_bytes(data[i + 5:i + 7], "big"))
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    raise AssertionError(f"no frame header found in {path.name}")


def test_the_gate_picture_is_sized_for_the_card_it_fills():
    """Between once and twice the width it can be painted at (kuantorflow#361).

    It is the first image anybody loads, on the page that exists to be got
    past, so both mistakes cost something real. Below the card's own width it
    is upscaled and soft; far above it, bytes are spent on detail no screen
    resolves — the 1536px original was 408KB for a 350px slot, twenty times
    the file it replaced.
    """
    width, height = _jpeg_size(IMG / "hi_there.jpg")

    assert CARD_CONTENT_PX <= width <= 2 * CARD_CONTENT_PX + 16, (
        f"hi_there.jpg is {width}px wide; the gate card paints it at "
        f"{CARD_CONTENT_PX:.1f}px, so it wants roughly {2 * CARD_CONTENT_PX:.0f}px"
    )
    assert abs(width / height - 1.5) < 0.01, "resized proportionally"


def test_the_gate_picture_fills_the_card_like_the_controls():
    """No `max-width` on `.gate-image` (kuantorflow#361).

    The keyword field and the Enter button are both `width: 100%` of the same
    content box; capped at 220px the picture sat as a stamp above them.
    Measured in a browser at 1280x800 and 375x812: all three come out at
    349.6px and 256.9px respectively, sharing a left edge.
    """
    import re

    css = (APP / "static" / "css" / "style.css").read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    block = re.search(r"\.gate-image\s*\{(.*?)\}", stripped, re.S)

    assert block, ".gate-image has no rule at all"
    declarations = " ".join(block.group(1).split())
    assert "width: 100%" in declarations
    assert "max-width" not in declarations, (
        "a max-width here is what made the picture a stamp above two "
        "full-width controls"
    )
