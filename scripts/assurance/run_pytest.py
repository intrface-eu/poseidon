"""Run pytest from the lane's locked environment and reject incomplete checks.

These are digital checks only, not physical qualification or release approval.
Importing the guard itself needs only the standard library.
"""
from __future__ import annotations

import shutil
import sys
from typing import Protocol


class CollectionReport(Protocol):
    skipped: bool


class TestReport(CollectionReport, Protocol):
    when: str


class Session(Protocol):
    testscollected: int
    exitstatus: int


class AssuranceGuard:
    def __init__(self) -> None:
        self.collected = 0
        self.call_reports = 0
        self.collection_skips = 0
        self.runtest_skips = 0
        self.xfail_reports = 0
        self.basetemp: str | None = None

    def pytest_configure(self, config) -> None:
        # pytest's numbered tmp_path directories always carry a "...current" symlink
        # and, without --basetemp, a pytest-of-<user>/pytest-current one under TMPDIR.
        # Evidence manifests refuse symlinks (run lp3-stage2-004), so a given basetemp
        # is treated as session scratch and removed once the session has finished.
        self.basetemp = getattr(config.option, "basetemp", None) or None

    def pytest_collectreport(self, report: CollectionReport) -> None:
        if report.skipped:
            self.collection_skips += 1

    def pytest_runtest_logreport(self, report: TestReport) -> None:
        if report.when == "call":
            self.call_reports += 1
        if report.skipped:
            self.runtest_skips += 1
        # Pytest sets wasxfail for both expected failures and non-strict XPASS.
        # Its presence matters even when the reason is an empty string.
        if hasattr(report, "wasxfail"):
            self.xfail_reports += 1

    def incomplete_reasons(self) -> list[str]:
        reasons = []
        if self.collected == 0:
            reasons.append("no tests collected")
        if self.call_reports == 0:
            reasons.append("no test calls executed")
        if self.collection_skips:
            reasons.append(f"collection skips={self.collection_skips}")
        if self.runtest_skips:
            reasons.append(f"runtest skips={self.runtest_skips}")
        if self.xfail_reports:
            reasons.append(f"xfail/xpass reports={self.xfail_reports}")
        return reasons

    def pytest_sessionfinish(self, session: Session, exitstatus: int) -> None:
        self.collected = session.testscollected
        if exitstatus == 0 and self.incomplete_reasons():
            session.exitstatus = 1


def main(argv: list[str] | None = None) -> int:
    # No fallback or installation: missing pytest must fail in the selected lane.
    import pytest

    guard = AssuranceGuard()
    exit_code = int(pytest.main(sys.argv[1:] if argv is None else argv, plugins=[guard]))
    if guard.basetemp:
        shutil.rmtree(guard.basetemp, ignore_errors=True)
    reasons = guard.incomplete_reasons()
    if reasons:
        print(f"Assurance INCOMPLETE: {'; '.join(reasons)}.", file=sys.stderr)
    else:
        status = "PASS" if exit_code == 0 else "FAILED"
        print(
            f"Assurance {status}: collected={guard.collected}, "
            f"call_reports={guard.call_reports}, pytest_exit={exit_code}.",
            file=sys.stderr,
        )
    print("Digital checks only; no physical qualification or release approval.", file=sys.stderr)
    return exit_code if exit_code != 0 else 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())
