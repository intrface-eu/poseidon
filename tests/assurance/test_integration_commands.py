"""Bounded subprocess tests for the digital command wrapper; no live services."""
from __future__ import annotations

from pathlib import Path
import os
import re
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/assurance"))
import run_command
import prepare_workspace


class IntegrationCommandTests(unittest.TestCase):
    def call(self, *arguments: str, timeout: int = 10) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "scripts/assurance/run_command.py"), *arguments],
                              capture_output=True, text=True, timeout=timeout)

    def test_runs_real_program_in_selected_directory_without_shell(self) -> None:
        with tempfile.TemporaryDirectory(prefix="poseidon-command-test-") as directory:
            literal = ";touch user-file;$(false)"
            result = self.call("--timeout", "5", "--cwd", directory, "--", sys.executable, "-c",
                               "import os,sys;print(os.getcwd());print(sys.argv[1])", literal)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(Path(directory).resolve()), result.stdout)
            self.assertIn(literal, result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_preserves_nonzero_exit(self) -> None:
        result = self.call("--timeout", "5", "--", sys.executable, "-c", "raise SystemExit(7)")
        self.assertEqual(result.returncode, 7)

    def test_reports_missing_command_and_invalid_timeout(self) -> None:
        for arguments in (("--timeout", "5"), ("--timeout", "nan", "--", sys.executable),
                          ("--timeout", "0", "--", sys.executable),
                          ("--timeout", "5", "--", "/no/such/poseidon-test-executable")):
            with self.subTest(arguments=arguments):
                result = self.call(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Cannot run digital check", result.stderr)

    def test_terminates_owned_process_after_timeout(self) -> None:
        result = self.call("--timeout", "0.1", "--", sys.executable, "-c", "import time;time.sleep(60)")
        self.assertEqual(result.returncode, 124)
        self.assertIn("owned process group stopped", result.stderr)

    def test_normal_completion_stops_descendants_in_its_owned_group(self) -> None:
        source = (
            "import os,subprocess,sys;"
            "print('OWNED_GROUP='+str(os.getpgrp()),flush=True);"
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])"
        )
        try:
            result = self.call("--timeout", "3", "--", sys.executable, "-c", source, timeout=5)
        except subprocess.TimeoutExpired as exc:
            # A regression must not leave this test's exact descendant group alive.
            output = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            match = re.search(r"OWNED_GROUP=(\d+)", output)
            if match:
                try:
                    os.killpg(int(match.group(1)), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            raise
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OWNED_GROUP=", result.stdout)

    def test_cleanup_interruption_still_escalates_and_reaps(self) -> None:
        process = Mock(pid=54321)
        process.wait.side_effect = [run_command.Interrupted(signal.SIGTERM), 0]
        with patch("run_command.os.killpg") as kill_group:
            run_command.stop_owned_group(process)
        self.assertEqual(kill_group.call_args_list[1].args, (54321, signal.SIGKILL))
        self.assertEqual(process.wait.call_count, 2)

    def test_escalates_only_owned_group_when_leader_exits(self) -> None:
        process = Mock(pid=54321)
        process.wait.return_value = 0
        with patch("run_command.os.killpg") as kill_group:
            run_command.stop_owned_group(process)
        self.assertEqual(kill_group.call_args_list[0].args, (54321, signal.SIGTERM))
        self.assertEqual(kill_group.call_args_list[1].args, (54321, signal.SIGKILL))
        self.assertEqual(process.wait.call_count, 2)

    def test_cancellation_during_spawn_keeps_the_owned_group_registered(self) -> None:
        process = Mock(pid=54321)
        process.wait.return_value = 0
        previous = signal.getsignal(signal.SIGTERM)

        def spawn(*args, **kwargs):
            handler = signal.getsignal(signal.SIGTERM)
            handler(signal.SIGTERM, None)
            return process

        with patch("run_command.subprocess.Popen", side_effect=spawn), patch("run_command.os.killpg") as kill_group:
            with self.assertRaises(run_command.Interrupted):
                run_command.run(["synthetic-command"], 5)
        self.assertEqual({call.args[0] for call in kill_group.call_args_list}, {54321})
        self.assertEqual(process.wait.call_count, 2)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_reaps_owned_process_on_interruption(self) -> None:
        process = Mock(pid=54321)
        process.wait.side_effect = [run_command.Interrupted(signal.SIGTERM), 0, 0]
        with patch("run_command.subprocess.Popen", return_value=process) as popen, patch("run_command.os.killpg") as kill_group:
            with self.assertRaises(run_command.Interrupted):
                run_command.run(["synthetic-test-command"], 5)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual({call.args[0] for call in kill_group.call_args_list}, {54321})
        self.assertEqual(process.wait.call_count, 3)

    def test_configurable_grace_reaches_cleanup_and_rejects_invalid_values(self) -> None:
        process = Mock(pid=54321)
        process.wait.return_value = 0
        with patch("run_command.subprocess.Popen", return_value=process), patch("run_command.os.killpg"):
            self.assertEqual(run_command.run(["synthetic-command"], 5, term_grace=20), 0)
        self.assertEqual(process.wait.call_args_list[1].kwargs, {"timeout": 20})
        for value in ("0", "-1", "nan"):
            with self.subTest(value=value):
                result = self.call("--timeout", "5", "--term-grace", value, "--", sys.executable)
                self.assertEqual(result.returncode, 2)
                self.assertIn("termination grace", result.stderr)

    def test_preserves_signal_exit_as_shell_status(self) -> None:
        result = self.call("--timeout", "5", "--", sys.executable, "-c", "import os,signal;os.kill(os.getpid(),signal.SIGTERM)")
        self.assertEqual(result.returncode, 143)


class VerificationWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="poseidon-verification-workspace-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.workspace = self.root / ".local" / "verification"

    def test_claims_empty_workspace_and_reuses_its_marker(self) -> None:
        self.assertEqual(prepare_workspace.prepare(self.root, self.workspace), self.workspace)
        marker = self.workspace / prepare_workspace.MARKER
        before = marker.read_bytes()
        cache = self.workspace / "cache-entry"
        cache.write_bytes(b"owned cache")
        self.assertEqual(prepare_workspace.prepare(self.root, self.workspace), self.workspace)
        self.assertEqual(marker.read_bytes(), before)
        self.assertEqual(cache.read_bytes(), b"owned cache")

    def test_preserves_unknown_nonempty_workspace(self) -> None:
        self.workspace.mkdir(parents=True)
        unknown = self.workspace / "user-file"
        unknown.write_bytes(b"user bytes")
        before = unknown.stat()
        with self.assertRaises(ValueError):
            prepare_workspace.prepare(self.root, self.workspace)
        self.assertEqual(unknown.read_bytes(), b"user bytes")
        self.assertEqual(unknown.stat().st_ino, before.st_ino)
        self.assertEqual(unknown.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual({p.name for p in self.workspace.iterdir()}, {"user-file"})

    def test_rejects_outside_paths_traversal_and_symlink_ancestors(self) -> None:
        for directory in (self.root, self.root / "apps" / "cache", self.root / ".local" / ".." / "outside"):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                prepare_workspace.prepare(self.root, directory)
        (self.root / ".local").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            prepare_workspace.prepare(self.root, self.workspace)

    def test_rejects_duplicate_and_wrong_type_ownership_fields(self) -> None:
        self.workspace.mkdir(parents=True)
        marker = self.workspace / prepare_workspace.MARKER
        unknown = self.workspace / "unknown-file"
        unknown.write_bytes(b"preserve me")
        for content in (
            '{"schema_version":true,"owner":"poseidon-digital-verification"}',
            '{"schema_version":1.0,"owner":"poseidon-digital-verification"}',
            '{"schema_version":1,"owner":"another","owner":"poseidon-digital-verification"}',
        ):
            with self.subTest(content=content):
                marker.write_text(content)
                with self.assertRaises(ValueError):
                    prepare_workspace.prepare(self.root, self.workspace)
                self.assertEqual(marker.read_text(), content)
                self.assertEqual(unknown.read_bytes(), b"preserve me")

    def test_refuses_foreign_or_symlink_marker(self) -> None:
        self.workspace.mkdir(parents=True)
        marker = self.workspace / prepare_workspace.MARKER
        marker.write_text('{"schema_version":1,"owner":"another-tool"}')
        with self.assertRaises(ValueError):
            prepare_workspace.prepare(self.root, self.workspace)
        self.assertIn("another-tool", marker.read_text())
        marker.unlink()
        target = self.root / "foreign.json"
        target.write_text('{"schema_version":1,"owner":"poseidon-digital-verification"}')
        marker.symlink_to(target)
        with self.assertRaises(ValueError):
            prepare_workspace.prepare(self.root, self.workspace)
        self.assertTrue(marker.is_symlink())
        self.assertTrue(target.is_file())


if __name__ == "__main__":
    unittest.main()
