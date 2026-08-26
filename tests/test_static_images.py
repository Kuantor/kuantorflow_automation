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
