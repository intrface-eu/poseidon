"""Synthetic runner regressions; not product, physical, or release evidence."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/assurance"
sys.path.insert(0, str(SCRIPTS))
from run_pytest import AssuranceGuard


class UnittestRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="poseidon-suite-runners-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, name: str, source: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")

    def run_suite(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "run_unittest.py"), *args],
            cwd=self.root,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def case(self, body: str, decorator: str = "") -> None:
        self.put("test_synthetic.py", (
            "import unittest\n\nclass SyntheticTests(unittest.TestCase):\n"
            + (f"    {decorator}\n" if decorator else "")
            + "    def test_synthetic(self):\n"
            + textwrap.indent(body + "\n", "        ")
        ))

    def assert_rejected(self, result: subprocess.CompletedProcess[str], *details: str) -> None:
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Assurance PASS", result.stdout + result.stderr)
        for detail in details:
            self.assertIn(detail, result.stderr)

    def test_real_pass_shows_verbose_output_and_actual_count(self) -> None:
        self.case("self.assertEqual(2 + 2, 4)")
        result = self.run_suite("-s", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("test_synthetic (test_synthetic.SyntheticTests.test_synthetic) ... ok", result.stderr)
        self.assertIn("Ran 1 test", result.stderr)
        self.assertIn("Assurance PASS: tests_run=1", result.stderr)
        self.assertIn("no physical qualification or release approval", result.stderr)

    def test_real_assertion_failure(self) -> None:
        self.case("self.fail('synthetic failure')")
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance FAILED", "failures=1", "synthetic failure")

    def test_real_runtime_error(self) -> None:
        self.case("raise RuntimeError('synthetic error')")
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance FAILED", "errors=1", "RuntimeError: synthetic error")

    def test_real_skip(self) -> None:
        self.case("self.fail('must not execute')", "@unittest.skip('synthetic missing input')")
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance INCOMPLETE", "skipped=1", "synthetic missing input")

    def test_real_subtest_skip(self) -> None:
        self.case("with self.subTest(part='synthetic'):\n    self.skipTest('synthetic subtest skip')")
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance INCOMPLETE", "skipped=1")

    def test_real_module_skip(self) -> None:
        self.put("test_synthetic.py", "import unittest\nraise unittest.SkipTest('synthetic collection skip')\n")
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance INCOMPLETE", "skipped=1", "synthetic collection skip")

    def test_real_expected_failure(self) -> None:
        self.case("self.fail('synthetic expected failure')", "@unittest.expectedFailure")
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance INCOMPLETE", "expected_failures=1")

    def test_real_unexpected_success(self) -> None:
        self.case("self.assertTrue(True)", "@unittest.expectedFailure")
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance INCOMPLETE", "unexpected_successes=1")

    def test_real_empty_suite(self) -> None:
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance INCOMPLETE", "tests_run=0", "Ran 0 tests")

    def test_real_discovery_import_error(self) -> None:
        self.put("test_synthetic.py", "raise ImportError('synthetic discovery error')\n")
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance FAILED", "errors=1", "ImportError: synthetic discovery error")

    def test_real_discovery_syntax_error(self) -> None:
        self.put("test_synthetic.py", "def invalid syntax\n")
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance FAILED", "errors=1", "SyntaxError")

    def test_pass_does_not_mask_a_skip(self) -> None:
        self.case("self.assertTrue(True)")
        self.put("test_skipped.py", "import unittest\nraise unittest.SkipTest('synthetic skipped module')\n")
        self.assert_rejected(self.run_suite("-s", str(self.root)), "Assurance INCOMPLETE", "tests_run=2", "skipped=1")

    def test_pattern_and_top_level_flags(self) -> None:
        self.put("synthetic_package/__init__.py", "")
        self.put("synthetic_package/check_synthetic.py", "import unittest\nclass SyntheticTests(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
        self.put("synthetic_package/test_excluded.py", "raise AssertionError('pattern was ignored')\n")
        for flags in (("-s", "-p", "-t"), ("--start-directory", "--pattern", "--top-level-directory")):
            with self.subTest(flags=flags):
                result = self.run_suite(flags[0], str(self.root / "synthetic_package"), flags[1], "check*.py", flags[2], str(self.root))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Assurance PASS: tests_run=1", result.stderr)
                self.assertIn("synthetic_package.check_synthetic", result.stderr)

    def test_declared_minimum_count_cannot_pass_with_a_subset(self) -> None:
        self.case("self.assertTrue(True)")
        self.assert_rejected(self.run_suite("-s", str(self.root), "--min-tests", "2"),
                             "Assurance INCOMPLETE", "tests_run=1", "required_minimum=2")
        self.assertEqual(self.run_suite("-s", str(self.root), "--min-tests", "1").returncode, 0)
        for value in ("0", "-1", "true"):
            with self.subTest(value=value):
                result = self.run_suite("-s", str(self.root), "--min-tests", value)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Assurance PASS", result.stderr)

    def test_start_directory_required(self) -> None:
        result = self.run_suite()
        self.assertEqual(result.returncode, 2)
        self.assertIn("required", result.stderr)
        self.assertNotIn("Assurance PASS", result.stderr)

    def test_rejects_a_second_positional_root(self) -> None:
        result = self.run_suite("-s", str(self.root), str(self.root))
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_guard_import_needs_no_site_packages_or_pytest(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "-S", "-c",
             "import runpy, sys; runpy.run_path(sys.argv[1]); assert 'pytest' not in sys.modules",
             str(SCRIPTS / "run_pytest.py")],
            cwd=self.root, capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


@dataclass
class FakeCollectionReport:
    skipped: bool = False


@dataclass
class FakeTestReport:
    when: str = "call"
    skipped: bool = False


@dataclass
class FakeXfailReport(FakeTestReport):
    wasxfail: str = "synthetic expected outcome"


@dataclass
class FakeSession:
    testscollected: int = 1
    exitstatus: int = 0


class PytestGuardTests(unittest.TestCase):
    """Hook-level tests only; these fake objects do not execute pytest."""

    def finish(self, guard: AssuranceGuard, collected: int = 1, exitstatus: int = 0) -> FakeSession:
        session = FakeSession(collected, exitstatus)
        guard.pytest_sessionfinish(session, exitstatus)
        return session

    def test_executed_non_skipping_check_keeps_success(self) -> None:
        guard = AssuranceGuard()
        guard.pytest_collectreport(FakeCollectionReport())
        for when in ("setup", "call", "teardown"):
            guard.pytest_runtest_logreport(FakeTestReport(when))
        self.assertEqual(self.finish(guard).exitstatus, 0)
        self.assertEqual(guard.call_reports, 1)
        self.assertEqual(guard.incomplete_reasons(), [])

    def test_empty_collection_rejects_nominal_success(self) -> None:
        guard = AssuranceGuard()
        self.assertEqual(self.finish(guard, collected=0).exitstatus, 1)
        self.assertIn("no tests collected", guard.incomplete_reasons())

    def test_collect_only_is_not_an_executed_suite(self) -> None:
        guard = AssuranceGuard()
        self.assertEqual(self.finish(guard).exitstatus, 1)
        self.assertEqual(guard.incomplete_reasons(), ["no test calls executed"])

    def test_collection_skip_rejected_even_with_executed_check(self) -> None:
        guard = AssuranceGuard()
        guard.pytest_collectreport(FakeCollectionReport(skipped=True))
        guard.pytest_runtest_logreport(FakeTestReport())
        self.assertEqual(self.finish(guard).exitstatus, 1)
        self.assertEqual(guard.incomplete_reasons(), ["collection skips=1"])

    def test_runtime_skip_in_any_phase_rejected(self) -> None:
        for when in ("setup", "call", "teardown"):
            with self.subTest(when=when):
                guard = AssuranceGuard()
                guard.pytest_runtest_logreport(FakeTestReport())
                guard.pytest_runtest_logreport(FakeTestReport(when, skipped=True))
                self.assertEqual(self.finish(guard, collected=2).exitstatus, 1)
                self.assertIn("runtest skips=1", guard.incomplete_reasons())

    def test_xfail_and_xpass_rejected_including_empty_reason(self) -> None:
        for skipped in (False, True):
            for reason in ("", "synthetic expected outcome"):
                with self.subTest(skipped=skipped, reason=reason):
                    guard = AssuranceGuard()
                    guard.pytest_runtest_logreport(FakeXfailReport(skipped=skipped, wasxfail=reason))
                    self.assertEqual(self.finish(guard).exitstatus, 1)
                    self.assertIn("xfail/xpass reports=1", guard.incomplete_reasons())

    def test_preserves_normal_nonzero_exit_codes(self) -> None:
        for exitstatus in (1, 2, 3, 4, 5):
            with self.subTest(exitstatus=exitstatus):
                guard = AssuranceGuard()
                guard.pytest_runtest_logreport(FakeTestReport())
                self.assertEqual(self.finish(guard, exitstatus=exitstatus).exitstatus, exitstatus)
                self.assertEqual(guard.incomplete_reasons(), [])

    def test_incomplete_check_does_not_replace_existing_failure_exit(self) -> None:
        for exitstatus in (1, 2, 3, 4, 5):
            with self.subTest(exitstatus=exitstatus):
                guard = AssuranceGuard()
                guard.pytest_collectreport(FakeCollectionReport(skipped=True))
                self.assertEqual(self.finish(guard, collected=0, exitstatus=exitstatus).exitstatus, exitstatus)
                self.assertIn("collection skips=1", guard.incomplete_reasons())


if __name__ == "__main__":
    unittest.main()
