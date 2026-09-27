"""Run Bun unit tests with bounded execution and non-skipping JUnit evidence.

Bun 1.3.14 does not distinguish test.failing from ordinary passes in JUnit;
this guard can reject expected outcomes only when the report represents them.
Digital checks only; no physical qualification or release approval.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import signal
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET

import run_command

MAX_REPORT_BYTES = 8 * 1024 * 1024
BAD_COUNTS = {
    "skip", "skips", "skipped", "failure", "failures", "error", "errors",
    "todo", "todos", "pending", "disabled", "ignored", "notrun",
    "xfail", "xfails", "xpass", "xpasses", "expectedfailures", "unexpectedsuccesses",
}
ALLOWED_CHILDREN = {
    "testsuites": {"testsuite", "testsuites"},
    "testsuite": {"testsuite", "testcase", "properties", "system-out", "system-err"},
    "testcase": {"properties", "system-out", "system-err"},
    "properties": {"property"},
    "property": set(),
    "system-out": set(),
    "system-err": set(),
}


def count(value: str, field: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or len(value) > 10:
        raise ValueError(f"invalid JUnit {field} count: {value[:40]!r}")
    return int(value)


def validate_junit(report: Path) -> int:
    # A command cannot substitute a symlink, directory or blocking FIFO for XML.
    descriptor = os.open(report, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("JUnit report must be a regular file")
        if metadata.st_size > MAX_REPORT_BYTES:
            raise ValueError("JUnit report exceeds size limit")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read(MAX_REPORT_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("JUnit report exceeds size limit")
    # Bun emits UTF-8. Reject DTD/entity declarations before the XML parser runs;
    # rejecting NULs also prevents alternate-width encodings bypassing this check.
    text = data.decode("utf-8")
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("JUnit DTDs, entities and alternate-width encodings are forbidden")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"malformed JUnit report: {exc}") from exc
    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError("JUnit root must be testsuites or testsuite")
    totals: dict[ET.Element, int] = {}
    # Bottom-up counts avoid recursion and reconcile each declared suite count,
    # rather than trusting the root total or double-counting nested suites.
    for element in reversed(list(root.iter())):
        if element.tag not in ALLOWED_CHILDREN:
            raise ValueError(f"JUnit contains incomplete or unsupported result element: {element.tag}")
        if any(child.tag not in ALLOWED_CHILDREN[element.tag] for child in element):
            raise ValueError(f"invalid JUnit children under {element.tag}")
        actual = 1 if element.tag == "testcase" else sum(totals[child] for child in element)
        totals[element] = actual
        for key, value in element.attrib.items():
            normalized = key.lower().replace("_", "").replace("-", "")
            if normalized == "tests" and count(value, key) != actual:
                raise ValueError(f"JUnit tests count mismatch: declared={value}, actual={actual}")
            if normalized in BAD_COUNTS and count(value, key) != 0:
                raise ValueError(f"JUnit incomplete checks: {key}={value}")
            if normalized in {"status", "result", "outcome"} and value.lower() not in {
                "pass", "passed", "success", "successful", "run", "completed",
            }:
                raise ValueError(f"JUnit incomplete or unknown outcome: {key}={value}")
    if totals[root] == 0:
        raise ValueError("JUnit report contains no testcases")
    return totals[root]


def run(bun: str, cwd: Path, timeout: float) -> int:
    with tempfile.TemporaryDirectory(prefix="poseidon-bun-junit-") as directory:
        report = Path(directory) / "results.xml"
        command = [bun, "run", "--cwd", str(cwd), "test", "--reporter=junit", f"--reporter-outfile={report}"]
        exit_code = run_command.run(command, timeout)
        if exit_code != 0:
            print(f"Assurance FAILED: Bun exit={exit_code}.", file=sys.stderr)
            return exit_code
        try:
            tests = validate_junit(report)
        except (ValueError, OSError) as exc:
            print(f"Assurance INCOMPLETE: {exc}", file=sys.stderr)
            return 1
        print(f"Assurance PASS: Bun JUnit testcases={tests}; report contains no skipped, failed or incomplete outcomes.", file=sys.stderr)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bun", default="bun")
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)

    def interrupt(signum: int, _frame: object) -> None:
        raise run_command.Interrupted(signum)

    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        return run(args.bun, args.cwd, args.timeout)
    except run_command.Interrupted as exc:
        print(f"Assurance INTERRUPTED: {exc}", file=sys.stderr)
        return 128 + exc.signum
    except (ValueError, OSError) as exc:
        print(f"Cannot run Bun digital check: {exc}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        print("Digital checks only; no physical qualification or release approval.", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
