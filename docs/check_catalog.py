"""Check docs/test-catalog.md against the suite it documents (issue #14).

Run from the repo root:

    venv\\Scripts\\python docs\\check_catalog.py

The catalog is only worth having if it is true, and it goes stale silently —
it once claimed 94 tests while the suite had grown past 500. Counting the `|`
rows is not enough either: a parametrized test is one row and several cases.
So this checks four things against `pytest --collect-only`:

1. every test file has a section;
2. every test function is named in **its own** section, not merely somewhere
   in the document;
3. no row names a test that does not exist (a rename leaves both behind);
4. the counts in each heading match what pytest actually collects.

Exits non-zero and prints every problem, so it can gate a pull request.
"""

import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "test-catalog.md"
TESTS = ROOT / "tests"

# "## test_x.py — title (12 cases)" or "(9 tests, 14 cases)" or "(1 case, ...)"
HEADING_COUNTS = re.compile(r"\((?:(\d+) tests, )?(\d+) cases?")


def collected_cases() -> dict[str, int]:
    """How many cases pytest collects per file."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        if "::" in line:
            name = re.split(r"[/\\]", line.split("::")[0])[-1]
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        sys.exit(f"could not collect any tests:\n{result.stdout}\n{result.stderr}")
    return counts


def sections(text: str) -> dict[str, str]:
    found = {}
    for chunk in re.split(r"(?=^## test_)", text, flags=re.M):
        match = re.match(r"## (test_\w+\.py)", chunk)
        if match:
            found[match.group(1)] = chunk
    return found


def main() -> int:
    doc = sections(DOC.read_text(encoding="utf-8"))
    cases = collected_cases()
    problems = []

    for path in sorted(TESTS.glob("test_*.py")):
        section = doc.get(path.name)
        if section is None:
            problems.append(f"{path.name}: no section in the catalog")
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [node.name for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)
                     and node.name.startswith("test")]

        for name in functions:
            if f"`{name}`" not in section:
                problems.append(f"{path.name}: {name} is not documented")

        for row in re.findall(r"^\| `(test_\w+)`", section, flags=re.M):
            if row not in functions:
                problems.append(f"{path.name}: `{row}` is documented but does "
                                "not exist (renamed or deleted?)")

        heading = section.splitlines()[0]
        counts = HEADING_COUNTS.search(heading)
        if not counts:
            problems.append(f"{path.name}: heading states no case count")
            continue
        if int(counts.group(2)) != cases.get(path.name, 0):
            problems.append(f"{path.name}: heading says {counts.group(2)} cases, "
                            f"pytest collects {cases.get(path.name, 0)}")
        if counts.group(1):
            if int(counts.group(1)) != len(functions):
                problems.append(f"{path.name}: heading says {counts.group(1)} "
                                f"tests, the file defines {len(functions)}")
        elif len(functions) != cases.get(path.name, 0):
            problems.append(
                f"{path.name}: parametrized ({len(functions)} functions, "
                f"{cases.get(path.name, 0)} cases) — the heading needs both "
                "numbers")

    for name in doc:
        if not (TESTS / name).exists():
            problems.append(f"{name}: has a section but no such test file")

    print(f"{len(doc)} sections, {sum(cases.values())} cases collected")
    for problem in problems:
        print("  PROBLEM:", problem)
    print("catalog is current" if not problems
          else f"{len(problems)} problem(s) — update docs/test-catalog.md")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
