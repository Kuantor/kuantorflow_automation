"""KuantorFlow's CLAUDE.md stays a short core that points at the detail
(kuantorflow#550, #566).

CLAUDE.md is loaded into every session. It had grown to 1,319 lines (~23k
tokens), 71% of it module history and 23% deploy-day notes, so the rules that
matter every time competed with history that matters on one day. #566 moved the
history, verbatim, to `docs/dev/design-notes.md` and the runbook to
`docs/dev/deploy.md`, and #550 put a "Verifying your work" block at the top.

Pinned here, so the split does not quietly undo itself or rot:

* the core stays **under its budget** (it regrows one ticket at a time);
* its **links resolve**, and every section it cites **exists** in the notes;
* every section of the notes is **in the core's index**, so a new one is found;
* the verifying block names a **test-repo layout that exists** and the
  **switch the database tier really reads**.
"""

import re
from pathlib import Path

from conftest import KUANTORFLOW_PATH

APP = Path(KUANTORFLOW_PATH)
TESTS = Path(__file__).parent
CORE_BUDGET = 300           # lines; the split left it at about 240

CORE = (APP / "CLAUDE.md").read_text(encoding="utf-8")
NOTES = (APP / "docs" / "dev" / "design-notes.md").read_text(encoding="utf-8")


def _section(text, heading):
    start = text.index(f"## {heading}")
    end = text.find("\n## ", start + 3)
    return text[start:end if end != -1 else None]


def _headings(text):
    return re.findall(r"^## (.+)$", text, re.M)


def _italics(text):
    """The *italic* spans, which in the rules section are the citations.
    Unwrapped first, since a span may cross a line break, and with **bold**
    removed, since its asterisks would otherwise pair up as italics."""
    flat = " ".join(text.split())
    # Code spans pair up left to right; one holding an asterisk
    # (`*_ANON_DAILY`) is code, not emphasis, so it goes.
    flat = re.sub(r"`[^`]*`", lambda m: " " if "*" in m.group(0) else m.group(0),
                  flat)
    flat = re.sub(r"\*\*.+?\*\*", " ", flat)
    return re.findall(r"\*([^*]+?)\*", flat)


def test_the_core_stays_under_its_budget():
    lines = len(CORE.splitlines())

    assert lines <= CORE_BUDGET, (
        f"CLAUDE.md is {lines} lines. History and per-ticket notes belong in "
        "docs/dev/design-notes.md or docs/dev/deploy.md; the core keeps the "
        "rule and one line of why.")


def test_its_links_resolve():
    """Every relative link resolves, and both on-demand documents are linked."""
    links = set(re.findall(r"\]\(([^)#:]+)(?:#[^)]*)?\)", CORE))

    assert {"docs/dev/design-notes.md", "docs/dev/deploy.md"} <= links
    missing = [link for link in links if not (APP / link).is_file()]
    assert missing == [], f"links to files that do not exist: {missing}"


def test_every_cited_section_exists():
    """Each rule names its section in the notes; a renamed heading would leave
    the pointer leading nowhere."""
    rules = _section(CORE, "The rules that hold every time")
    headings = set(_headings(NOTES))

    cited = set(_italics(rules))
    assert cited, "the rules section cites no sections at all"
    assert cited - headings == set(), f"cited but not in the notes: {cited - headings}"


def test_every_section_is_in_the_index():
    rules = _section(CORE, "The rules that hold every time")
    cited = set(_italics(rules))

    missing = [h for h in _headings(NOTES) if h not in cited]
    assert missing == [], f"sections the core never mentions: {missing}"


def test_the_verifying_block_comes_first_and_names_what_exists():
    assert CORE.index("## Verifying your work") < CORE.index("## Three-repo")
    block = _section(CORE, "Verifying your work")

    assert "../automation/kuantorflow_automation" in block
    for name in re.findall(r"`(test_[a-z_]+\.py)`", block):
        assert (TESTS / name).is_file(), f"the block names {name}, which is gone"


def test_the_database_switch_is_the_one_the_tier_reads():
    """The block tells a session to set `RUN_DB_ROUNDTRIP=1`. If the db tests
    ever read another name, every one of them would skip, silently."""
    switch = re.search(r"\b([A-Z_]+)=1 venv", _section(CORE, "Verifying your work"))
    assert switch, "no database switch in the block"

    readers = [p.name for p in TESTS.glob("*_db.py")
               if switch.group(1) in p.read_text(encoding="utf-8")]
    assert readers, f"no *_db.py test reads {switch.group(1)}"


def test_the_runbook_kept_the_key_rotation_warning():
    """The deploy passage the key-route test pins moved with the runbook; the
    core keeps the short form."""
    runbook = (APP / "docs" / "dev" / "deploy.md").read_text(encoding="utf-8")

    for text in (CORE, runbook):
        at = text.index("ANTHROPIC_API_KEY` belongs in")
        assert "rotating **both files**" in text[at:at + 1600]
