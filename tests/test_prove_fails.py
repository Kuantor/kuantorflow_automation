"""`tools/prove_fails.py`, the break-and-restore tool (kuantorflow#569).

Every PR proves its tests fail by breaking each piece of the change. The tool
does that once, correctly: it restores each file **from its saved bytes, never
from git**, refuses a break whose target is not there exactly once, refuses to
start when the tests fail unbroken, and flags a break that no test catches.

Each test here runs the tool against a tiny throwaway project in a temp
directory -- a module and a test file -- so nothing in either app repo is
touched.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "prove_fails.py"
LF, CR = chr(10), chr(13)


def _tool():
    spec = importlib.util.spec_from_file_location("prove_fails", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = LF.join([
    "def add(a, b):",
    "    return a + b",
    "",
    "",
    "def greet(name):",
    "    return 'hello ' + name",
    "",
    "",
    "UNUSED = 1",
    "",
])

TESTS = LF.join([
    "import mod",
    "",
    "",
    "def test_add():",
    "    assert mod.add(2, 3) == 5",
    "",
    "",
    "def test_greet():",
    "    assert mod.greet('x') == 'hello x'",
    "",
])


@pytest.fixture()
def project(tmp_path):
    (tmp_path / "mod.py").write_text(MODULE, encoding="utf-8", newline="")
    (tmp_path / "test_mod.py").write_text(TESTS, encoding="utf-8", newline="")
    return tmp_path


def _spec(project, *breaks):
    return {"FILES_ROOT": str(project), "CWD": str(project),
            "TESTS": ["test_mod.py"], "BREAKS": list(breaks)}


def _quiet(*args, **kwargs):
    pass


# --- catching, flagging, refusing -------------------------------------------

def test_a_caught_break_names_the_test_that_failed(project):
    rows, code = _tool().prove(
        _spec(project, ("add subtracts", "mod.py", "a + b", "a - b")), out=_quiet)

    ((name, file, failures, error),) = rows
    assert error is None and code == 0
    assert [f.split("::")[-1] for f in failures] == ["test_add"]


def test_a_break_nothing_catches_is_flagged(project):
    rows, code = _tool().prove(
        _spec(project, ("unused changed", "mod.py", "UNUSED = 1", "UNUSED = 2")),
        out=_quiet)

    assert rows[0][2] == [] and code == 1


@pytest.mark.parametrize("target, times", [("not in the file", 0),
                                           ("return", 2)])
def test_a_target_not_there_exactly_once_is_refused(project, target, times):
    before = (project / "mod.py").read_bytes()
    rows, code = _tool().prove(_spec(project, ("bad", "mod.py", target, "x")),
                               out=_quiet)

    assert rows[0][3] == f"target found {times} times, expected exactly once"
    assert code == 1
    assert (project / "mod.py").read_bytes() == before


def test_a_break_that_changes_nothing_is_refused(project):
    rows, code = _tool().prove(_spec(project, ("noop", "mod.py", lambda t: t)),
                               out=_quiet)

    assert rows[0][3] == "the break changed nothing" and code == 1


def test_failing_unbroken_tests_stop_everything(project):
    (project / "mod.py").write_text(MODULE.replace("a + b", "a * b"),
                                    encoding="utf-8")
    said = []
    rows, code = _tool().prove(
        _spec(project, ("add subtracts", "mod.py", "a * b", "a - b")),
        out=said.append)

    assert rows == [] and code == 2
    assert "before anything is broken" in said[0]


# --- restoring --------------------------------------------------------------

def test_the_file_is_restored_byte_for_byte(project):
    before = (project / "mod.py").read_bytes()
    _tool().prove(_spec(project, ("add subtracts", "mod.py", "a + b", "a - b"),
                        ("greet broken", "mod.py",
                         lambda t: t.replace("hello", "bye", 1))), out=_quiet)

    assert (project / "mod.py").read_bytes() == before


def test_the_file_is_restored_when_the_test_run_crashes(project, monkeypatch):
    tool = _tool()
    before = (project / "mod.py").read_bytes()
    calls = []

    def crash_on_the_break(command, cwd, pytest_mode, timeout):
        calls.append(1)
        if len(calls) == 2:                       # the first is the unbroken run
            assert (project / "mod.py").read_bytes() != before, "it was broken"
            raise KeyboardInterrupt
        return 0, [], ""

    monkeypatch.setattr(tool, "run_tests", crash_on_the_break)
    with pytest.raises(KeyboardInterrupt):
        tool.prove(_spec(project, ("add subtracts", "mod.py", "a + b", "a - b")),
                   out=_quiet)

    assert (project / "mod.py").read_bytes() == before


def test_it_never_calls_git():
    source = TOOL.read_text(encoding="utf-8")

    assert '"git"' not in source and "'git'" not in source


def test_a_multi_line_target_matches_a_crlf_file(project):
    """A spec is written with plain newlines; a file checked out on Windows
    holds CRLF. Found on the tool's first real run, against parsers.py."""
    crlf = MODULE.replace(LF, CR + LF)
    (project / "mod.py").write_bytes(crlf.encode("utf-8"))
    rows, code = _tool().prove(
        _spec(project, ("add body gone", "mod.py",
                        "def add(a, b):" + LF + "    return a + b",
                        "def add(a, b):" + LF + "    return 0")), out=_quiet)

    assert rows[0][3] is None and code == 0
    assert (project / "mod.py").read_bytes() == crlf.encode("utf-8")


# --- plain-script commands and the report -----------------------------------

def test_a_plain_script_is_judged_by_its_exit_code(project):
    (project / "check.py").write_text(LF.join([
        "import mod",
        "if mod.add(2, 3) != 5:",
        "    print('FAILED: add is wrong')",
        "    raise SystemExit(1)",
        "print('1 check passed')",
        "",
    ]), encoding="utf-8")
    spec = {"FILES_ROOT": str(project), "CWD": str(project),
            "COMMAND": [sys.executable, "check.py"],
            "BREAKS": [("add subtracts", "mod.py", "a + b", "a - b"),
                       ("greet broken", "mod.py", "'hello '", "'bye '")]}

    rows, code = _tool().prove(spec, out=_quiet)

    assert rows[0][2] == ["FAILED: add is wrong"]
    assert rows[1][2] == [], "the script does not check greet"
    assert code == 1


def test_the_markdown_report_is_a_table(project, tmp_path_factory):
    spec_file = tmp_path_factory.mktemp("spec") / "spec.py"
    spec_file.write_text(LF.join([
        f"FILES_ROOT = {str(project)!r}",
        f"CWD = {str(project)!r}",
        "TESTS = ['test_mod.py']",
        "BREAKS = [('add subtracts', 'mod.py', 'a + b', 'a - b'),",
        "          ('unused changed', 'mod.py', 'UNUSED = 1', 'UNUSED = 2')]",
        "",
    ]), encoding="utf-8")

    done = subprocess.run([sys.executable, str(TOOL), str(spec_file), "--markdown"],
                          capture_output=True, text=True, encoding="utf-8")

    assert done.returncode == 1, "one break caught nothing"
    assert "| Break | Failing tests |" in done.stdout
    assert "| add subtracts (`mod.py`) | `test_add` |" in done.stdout
    assert "| unused changed (`mod.py`) | **nothing failed** |" in done.stdout


def test_parametrised_cases_are_counted_not_listed():
    grouped = _tool()._grouped(["t.py::test_x[a]", "t.py::test_x[b]",
                                "t.py::test_y"])

    assert grouped == ["test_x (2 cases)", "test_y"]
