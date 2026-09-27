"""Synthetic Bun runner regressions using only the standard library, not UI coverage."""
from __future__ import annotations

from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/assurance"))
import run_bun_tests as runner

PASS_XML = '<testsuites tests="1" failures="0" skipped="0"><testsuite tests="1"><testcase name="synthetic pass" /></testsuite></testsuites>'


class JunitGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="poseidon-bun-guard-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.report = self.root / "synthetic.xml"

    def validate(self, text: str) -> int:
        self.report.write_text(text, encoding="utf-8")
        return runner.validate_junit(self.report)

    def test_accepts_real_bun_report_shape(self) -> None:
        self.assertEqual(self.validate(PASS_XML), 1)

    def test_accepts_single_suite_without_optional_counts(self) -> None:
        self.assertEqual(self.validate('<testsuite><testcase name="one" /><testcase name="two" /></testsuite>'), 2)

    def test_reconciles_nested_suites_without_double_counting(self) -> None:
        xml = '<testsuites tests="2"><testsuite tests="2"><testcase /><testsuite tests="1"><testcase /></testsuite></testsuite></testsuites>'
        self.assertEqual(self.validate(xml), 2)

    def test_allows_metadata_and_escaped_output(self) -> None:
        xml = '<testsuite tests="1"><properties><property name="fixture" value="synthetic" /></properties><testcase status="run"><system-out>&lt;skipped&gt;</system-out><system-err /></testcase></testsuite>'
        self.assertEqual(self.validate(xml), 1)

    def test_rejects_missing_and_empty_reports(self) -> None:
        with self.assertRaises(FileNotFoundError):
            runner.validate_junit(self.report)
        with self.assertRaisesRegex(ValueError, "malformed"):
            self.validate("")

    def test_rejects_zero_testcases(self) -> None:
        with self.assertRaisesRegex(ValueError, "no testcases"):
            self.validate('<testsuites tests="0"><testsuite tests="0" /></testsuites>')

    def test_rejects_malformed_xml_and_wrong_root(self) -> None:
        for xml in ('<testsuite>', '<notjunit><testcase /></notjunit>', '<testcase />'):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                self.validate(xml)

    def test_rejects_failure_skip_todo_and_expected_outcome_elements(self) -> None:
        for outcome in ('failure', 'error', 'skipped', 'todo', 'pending', 'disabled', 'xfail', 'xpass', 'expectedFailure', 'unexpectedSuccess'):
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                self.validate(f'<testsuite tests="1" failures="0" skipped="0"><testcase><{outcome} /></testcase></testsuite>')

    def test_rejects_nonzero_incomplete_counters_without_result_elements(self) -> None:
        for field in ('failures', 'errors', 'skipped', 'todo', 'disabled', 'pending', 'xfail', 'xpass', 'expected_failures', 'unexpected-successes'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "incomplete"):
                self.validate(f'<testsuite {field}="1"><testcase /></testsuite>')

    def test_rejects_nonpassing_status_attributes(self) -> None:
        for field in ('status', 'result', 'outcome'):
            for outcome in ('skipped', 'todo', 'xfail', 'xpass', 'notrun', 'failed', 'unknown'):
                with self.subTest(field=field, outcome=outcome), self.assertRaisesRegex(ValueError, "outcome"):
                    self.validate(f'<testsuite><testcase {field}="{outcome}" /></testsuite>')

    def test_rejects_root_and_child_count_mismatches(self) -> None:
        for xml in (
            '<testsuites tests="2"><testsuite tests="1"><testcase /></testsuite></testsuites>',
            '<testsuites tests="1"><testsuite tests="2"><testcase /></testsuite></testsuites>',
            '<testsuite tests="0"><testcase /></testsuite>',
        ):
            with self.subTest(xml=xml), self.assertRaisesRegex(ValueError, "count mismatch"):
                self.validate(xml)

    def test_rejects_malformed_counts(self) -> None:
        for field in ('tests', 'skipped'):
            for value in ('-1', '1.0', 'true', '', 'nan', ' 1 ', '12345678901234567890'):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "invalid JUnit"):
                    self.validate(f'<testsuite {field}="{value}"><testcase /></testsuite>')

    def test_rejects_hidden_or_misplaced_testcases(self) -> None:
        for xml in (
            '<testsuites><testcase /></testsuites>',
            '<testsuite><properties><testcase /></properties></testsuite>',
            '<testsuite><testcase><testcase /></testcase></testsuite>',
            '<testsuite><system-out><testcase /></system-out></testsuite>',
        ):
            with self.subTest(xml=xml), self.assertRaisesRegex(ValueError, "children"):
                self.validate(xml)

    def test_rejects_dtd_and_entities_before_parsing(self) -> None:
        xml = '<!DOCTYPE testsuite [<!ENTITY x "synthetic">]><testsuite><testcase name="&x;" /></testsuite>'
        self.report.write_text(xml)
        with patch.object(runner.ET, "fromstring") as parse, self.assertRaisesRegex(ValueError, "forbidden"):
            runner.validate_junit(self.report)
        parse.assert_not_called()

    def test_rejects_alternate_width_and_invalid_utf8(self) -> None:
        for content in (PASS_XML.encode('utf-16'), PASS_XML.encode('utf-16-le'), b'\xff\xfeinvalid'):
            with self.subTest(content=content[:10]):
                self.report.write_bytes(content)
                with self.assertRaises(ValueError):
                    runner.validate_junit(self.report)

    def test_rejects_oversized_report_before_parsing(self) -> None:
        self.report.write_text(PASS_XML)
        with patch.object(runner, "MAX_REPORT_BYTES", 32), patch.object(runner.ET, "fromstring") as parse:
            with self.assertRaisesRegex(ValueError, "size limit"):
                runner.validate_junit(self.report)
            parse.assert_not_called()

    def test_rejects_symlink_without_touching_target(self) -> None:
        target = self.root / "unknown-file.xml"
        target.write_text(PASS_XML)
        self.report.symlink_to(target)
        with self.assertRaises(OSError):
            runner.validate_junit(self.report)
        self.assertEqual(target.read_text(), PASS_XML)

    def test_closes_report_descriptor_on_accept_and_rejection(self) -> None:
        self.report.write_text(PASS_XML)
        with patch.object(runner.os, 'close', wraps=os.close) as close:
            self.assertEqual(runner.validate_junit(self.report), 1)
            close.assert_called_once()
        with self.assertRaises(OSError):
            os.fstat(close.call_args.args[0])
        self.report.unlink()
        self.report.mkdir()
        with patch.object(runner.os, 'close', wraps=os.close) as close:
            with self.assertRaises(ValueError):
                runner.validate_junit(self.report)
            close.assert_called_once()
        with self.assertRaises(OSError):
            os.fstat(close.call_args.args[0])

    def test_rejects_directory_and_fifo_without_blocking(self) -> None:
        self.report.mkdir()
        with self.assertRaises((ValueError, OSError)):
            runner.validate_junit(self.report)
        self.report.rmdir()
        os.mkfifo(self.report)
        with self.assertRaisesRegex(ValueError, "regular file"):
            runner.validate_junit(self.report)


class BunInvocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = io.StringIO()
        self.capture = redirect_stderr(self.output)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)
        self.reports: list[Path] = []

    def report_path(self, command: list[str]) -> Path:
        report = Path(command[-1].split("=", 1)[1])
        self.assertFalse(report.exists())
        self.reports.append(report)
        return report

    def fake_pass(self, command: list[str], timeout: float) -> int:
        self.report_path(command).write_text(PASS_XML)
        return 0

    def assert_temporary_cleanup(self) -> None:
        self.assertTrue(self.reports)
        for report in self.reports:
            self.assertFalse(report.parent.exists())

    def test_exact_command_timeout_and_new_report_per_invocation(self) -> None:
        cwd = Path('/synthetic directory;$(false)')
        with patch.object(runner.run_command, 'run', side_effect=self.fake_pass) as execute:
            for _ in range(2):
                self.assertEqual(runner.run('/synthetic bun', cwd, 7), 0)
        for call in execute.call_args_list:
            command, timeout = call.args
            self.assertEqual(command[:-1], ['/synthetic bun', 'run', '--cwd', str(cwd), 'test', '--reporter=junit'])
            self.assertTrue(command[-1].startswith('--reporter-outfile='))
            self.assertEqual(timeout, 7)
        self.assertNotEqual(self.reports[0], self.reports[1])
        self.assert_temporary_cleanup()
        self.assertIn('Assurance PASS: Bun JUnit testcases=1', self.output.getvalue())

    def test_preserves_nonzero_exit_without_trusting_report(self) -> None:
        for code in (1, 7, 124, 130, 143):
            def fail(command: list[str], timeout: float) -> int:
                self.report_path(command).write_text('malformed synthetic XML')
                return code
            with self.subTest(code=code), patch.object(runner.run_command, 'run', side_effect=fail), patch.object(runner, 'validate_junit') as validate:
                self.assertEqual(runner.run('synthetic-bun', Path('/synthetic'), 5), code)
                validate.assert_not_called()
        self.assert_temporary_cleanup()
        self.assertNotIn('Assurance PASS', self.output.getvalue())

    def test_nominal_success_missing_malformed_or_empty_report_fails(self) -> None:
        for xml in (None, '', '<testsuite>', '<testsuite tests="0" />'):
            def incomplete(command: list[str], timeout: float) -> int:
                report = self.report_path(command)
                if xml is not None:
                    report.write_text(xml)
                return 0
            with self.subTest(xml=xml), patch.object(runner.run_command, 'run', side_effect=incomplete):
                self.assertEqual(runner.run('synthetic-bun', Path('/synthetic'), 5), 1)
        self.assert_temporary_cleanup()
        self.assertIn('Assurance INCOMPLETE', self.output.getvalue())
        self.assertNotIn('Assurance PASS', self.output.getvalue())

    def test_cleanup_on_execution_exception(self) -> None:
        def fail(command: list[str], timeout: float) -> int:
            self.report_path(command)
            raise OSError('synthetic execution error')
        with patch.object(runner.run_command, 'run', side_effect=fail), self.assertRaises(OSError):
            runner.run('synthetic-bun', Path('/synthetic'), 5)
        self.assert_temporary_cleanup()

    def test_cli_defaults_and_restores_signal_handlers(self) -> None:
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        with patch.object(runner.run_command, 'run', side_effect=self.fake_pass) as execute:
            self.assertEqual(runner.main(['--cwd', '/synthetic']), 0)
        self.assertEqual(execute.call_args.args[0][0], 'bun')
        self.assertEqual(execute.call_args.args[1], 180)
        self.assertEqual({sig: signal.getsignal(sig) for sig in previous}, previous)
        self.assert_temporary_cleanup()
        self.assertIn('no physical qualification or release approval', self.output.getvalue())

    def test_cli_signal_handlers_raise_interrupted_and_restore_after_cleanup(self) -> None:
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        for signum in previous:
            def interrupt(command: list[str], timeout: float) -> int:
                self.report_path(command)
                handler = signal.getsignal(signum)
                self.assertTrue(callable(handler))
                handler(signum, None)
                raise AssertionError('signal handler did not interrupt')
            with self.subTest(signum=signum), patch.object(runner.run_command, 'run', side_effect=interrupt):
                self.assertEqual(runner.main(['--bun', 'synthetic-bun', '--cwd', '/synthetic', '--timeout', '5']), 128 + signum)
            self.assertEqual({sig: signal.getsignal(sig) for sig in previous}, previous)
        self.assert_temporary_cleanup()
        self.assertIn('Assurance INTERRUPTED', self.output.getvalue())

    def test_cli_restores_handlers_on_execution_error(self) -> None:
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        with patch.object(runner.run_command, 'run', side_effect=OSError('synthetic missing bun')):
            self.assertEqual(runner.main(['--cwd', '/synthetic']), 2)
        self.assertEqual({sig: signal.getsignal(sig) for sig in previous}, previous)
        self.assertIn('Cannot run Bun digital check', self.output.getvalue())

    def test_cli_requires_working_directory(self) -> None:
        with self.assertRaises(SystemExit) as error:
            runner.main([])
        self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
