r"""Prove each test fails when the code it guards is broken (kuantorflow#569).

    venv/Scripts/python tools/prove_fails.py path/to/spec.py
    venv/Scripts/python tools/prove_fails.py path/to/spec.py --markdown

A test written straight after the code it tests passes by construction, so a
green run cannot tell "catches the bug" from "cannot fail". Breaking each piece
of the change and watching a test fail is the proof (kuantorflow CLAUDE.md,
*Conventions*). Every PR used to do that with a throwaway script; this is that
script written once, and it fixes the one thing those scripts got dangerously
wrong.

**It restores from the saved bytes, never from git.** The old restore was
`git checkout -- <file>`, which also throws away any uncommitted work in the
file, and has silently reverted finished work three times. Here each file is
read before it is broken and written back in a `finally`, then compared byte
for byte, so an interrupted run, a crashing test or a forgotten commit loses
nothing.

**The spec** is a plain Python file, so a break can be a string swap or a
function (an escape can be built with `chr(92)` rather than typed):

    FILES_ROOT = "kuantorflow"     # or "ai_agent", or a path
    TESTS = ["tests/test_request_log.py"]
    BREAKS = [
        ("no header", "web.py", 'response.headers["X-Request-ID"] = g.request_id', "pass"),
        ("email logged", "web.py",
         lambda text: text.replace("_current_user_id()", "_current_email()", 1)),
    ]

`TESTS` runs under pytest from this repo's root, and the failing tests are read
from pytest's summary. For anything else -- ai_agent's plain-script tests -- set
`COMMAND` (a list) and optionally `CWD`; failure is then a non-zero exit.

**What it checks besides:** the tests must pass **unbroken** first, or the
breaks prove nothing; a string break's target must occur **exactly once**; a
break that changes nothing is an error. A break that no test catches is
flagged and makes the exit code non-zero -- that is a vacuous test or a wrong
break, and either needs a look.

Exit codes: 0 every break caught; 1 a break caught nothing or was invalid;
2 the unbroken run failed.
"""

import argparse
import os
import runpy
import subprocess
import sys
from pathlib import Path

TEST_REPO = Path(__file__).resolve().parent.parent
LF, CRLF = chr(10), chr(13) + chr(10)   # see apply_break()


def _env_value(name):
    """A setting from the environment, else from this repo's `.env`."""
    if os.environ.get(name):
        return os.environ[name]
    env = TEST_REPO / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip().strip('"').strip("'")
    return None


def resolve_root(files_root):
    """Where the files a spec breaks live. The two app repos by name, found
    the way the test suite finds them; anything else is a path."""
    kuantorflow = Path(_env_value("KUANTORFLOW_PATH")
                       or TEST_REPO.parent.parent / "kuantorflow")
    if files_root == "kuantorflow":
        return kuantorflow
    if files_root == "ai_agent":
        return Path(_env_value("AI_AGENT_PATH") or kuantorflow.parent / "ai_agent")
    return Path(files_root)


def apply_break(text, change):
    """The broken text, or raise ValueError saying why the break is invalid."""
    if callable(change):
        broken = change(text)
    else:
        old, new = change
        # A spec is written with plain newlines; a file checked out on Windows
        # may hold CRLF. Match the file's own line endings.
        if CRLF in text and LF in old and CRLF not in old:
            old, new = old.replace(LF, CRLF), new.replace(LF, CRLF)
        count = text.count(old)
        if count != 1:
            raise ValueError(f"target found {count} times, expected exactly once")
        broken = text.replace(old, new, 1)
    if broken == text:
        raise ValueError("the break changed nothing")
    return broken


def _failures(output, pytest_mode, returncode):
    """What failed: pytest's test ids, or the script's first FAILED line."""
    if pytest_mode:
        found = []
        for line in output.splitlines():
            for prefix in ("FAILED ", "ERROR "):
                if line.startswith(prefix):
                    found.append(line[len(prefix):].split(" - ")[0].strip())
        if returncode and not found:
            found.append(f"exit {returncode}")
        return found
    if not returncode:
        return []
    lines = [l.strip() for l in output.splitlines() if "FAILED" in l]
    return [lines[0] if lines else f"exit {returncode}"]


def run_tests(command, cwd, pytest_mode, timeout):
    done = subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout)
    output = (done.stdout + done.stderr).decode("utf-8", "replace")
    return done.returncode, _failures(output, pytest_mode, done.returncode), output


def prove(spec, timeout=900, out=print):
    """Run every break in `spec` (a dict), and return the rows and exit code."""
    root = resolve_root(spec.get("FILES_ROOT", "kuantorflow"))
    if spec.get("COMMAND"):
        command, pytest_mode = list(spec["COMMAND"]), False
        cwd = spec.get("CWD") or root
    else:
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   *spec["TESTS"]]
        pytest_mode, cwd = True, spec.get("CWD") or TEST_REPO

    returncode, failures, output = run_tests(command, cwd, pytest_mode, timeout)
    if returncode:
        out("The tests fail before anything is broken, so a break would prove "
            "nothing:")
        out("\n".join(output.splitlines()[-15:]))
        return [], 2

    rows, code = [], 0
    for name, file, *change in spec["BREAKS"]:
        change = change[0] if len(change) == 1 else tuple(change)
        path = root / file
        original = path.read_bytes()
        try:
            broken = apply_break(original.decode("utf-8"), change)
        except ValueError as error:
            rows.append((name, file, None, str(error)))
            code = 1
            continue
        try:
            path.write_bytes(broken.encode("utf-8"))
            _, failures, _ = run_tests(command, cwd, pytest_mode, timeout)
        finally:
            path.write_bytes(original)
        if path.read_bytes() != original:
            raise RuntimeError(f"{path} was not restored exactly")
        rows.append((name, file, failures, None))
        if not failures:
            code = 1
    return rows, code


def _grouped(failures):
    """Test names, with a parametrised test's cases counted rather than
    listed: pytest prints their ids escaped, and ten of them bury the row."""
    counts = {}
    for failure in failures:
        base = failure.split("::")[-1].split("[")[0]
        counts[base] = counts.get(base, 0) + 1
    return [name if n == 1 else f"{name} ({n} cases)" for name, n in counts.items()]


def report(rows, markdown=False):
    lines = []
    if markdown:
        lines += ["| Break | Failing tests |", "|---|---|"]
        for name, file, failures, error in rows:
            if error:
                cell = f"**invalid break:** {error}"
            elif not failures:
                cell = "**nothing failed**"
            else:
                cell = ", ".join(f"`{f}`" for f in _grouped(failures))
            lines.append(f"| {name} (`{file}`) | {cell} |")
    else:
        for name, file, failures, error in rows:
            if error:
                verdict = f"INVALID: {error}"
            elif not failures:
                verdict = "NOTHING FAILED"
            else:
                verdict = f"{len(failures)} failed: " + ", ".join(_grouped(failures))
            lines.append(f"{name:32} {verdict}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Break each piece of a change, run the tests, and restore "
                    "from the saved bytes (kuantorflow#569).")
    parser.add_argument("spec", help="a Python file defining BREAKS and TESTS or COMMAND")
    parser.add_argument("--markdown", action="store_true",
                        help="print the result as a table for a PR description")
    parser.add_argument("--timeout", type=int, default=900,
                        help="seconds per test run (default 900)")
    args = parser.parse_args(argv)

    spec = runpy.run_path(args.spec)
    rows, code = prove(spec, timeout=args.timeout)
    if rows:
        print(report(rows, markdown=args.markdown))
    if code == 1:
        print("\nAt least one break caught nothing or was invalid -- a vacuous "
              "test or a wrong break.", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
