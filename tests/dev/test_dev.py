from __future__ import annotations

import contextlib
import io
import os
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import dev  # noqa: E402


class FakeProcess:
    def __init__(self, pid: int, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return self.returncode

    def send_signal(self, signum: int) -> None:
        if signum == signal.SIGTERM:
            self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode


class DevArgumentsTests(unittest.TestCase):
    def test_defaults_are_repo_relative_and_include_all_source_roots(self) -> None:
        options = dev.parse_args([])

        self.assertEqual(options.command, "start")
        self.assertEqual(options.data_dir, dev.DEFAULT_DATA_DIRECTORY)
        self.assertEqual(options.api_port, 8080)
        self.assertEqual(options.ui_port, 3000)
        self.assertEqual(options.ui_mode, "dev")
        self.assertEqual(
            dev.source_pythonpath().split(os.pathsep),
            [str(path) for path in dev.SOURCE_ROOTS],
        )

    def test_invalid_ports_and_timeout_are_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                dev.parse_args(["start", "--api-port", "0"])
            with self.assertRaises(SystemExit):
                dev.parse_args(["start", "--ui-port", "65536"])
            with self.assertRaises(SystemExit):
                dev.parse_args(["start", "--readiness-timeout", "0"])
            with self.assertRaises(SystemExit):
                dev.parse_args(["start", "--readiness-timeout", "nan"])
            with self.assertRaises(SystemExit):
                dev.parse_args(["start", "--readiness-timeout", "inf"])
            with self.assertRaises(SystemExit):
                dev.parse_args(["start", "--readiness-timeout", "-inf"])
            with self.assertRaises(SystemExit):
                dev.parse_args(["start", "--ui-mode", "preview"])

    def test_service_commands_use_required_loopback_arguments(self) -> None:
        options = dev.parse_args(
            ["start", "--data-dir", "/tmp/monitor", "--api-port", "8181", "--ui-port", "3100"]
        )
        with mock.patch.dict(os.environ, {"UV": "uv-test", "BUN": "bun-test"}, clear=False):
            api, ui = dev.service_specs(options)

        self.assertEqual(
            api.command,
            (
                "uv-test",
                "run",
                "--project",
                str(dev.API_DIRECTORY),
                "--frozen",
                "python",
                "-m",
                "poseidon_api",
                "--data-dir",
                str(options.data_dir),
                "--host",
                "127.0.0.1",
                "--port",
                "8181",
            ),
        )
        self.assertEqual(
            ui.command,
            ("bun-test", "run", "dev", "--hostname", "127.0.0.1", "--port", "3100"),
        )
        self.assertEqual(ui.environment["POSEIDON_API_URL"], "http://127.0.0.1:8181")

    def test_production_ui_mode_uses_bun_start_with_loopback_arguments(self) -> None:
        options = dev.parse_args(["start", "--ui-mode", "production", "--ui-port", "3100"])
        with mock.patch.dict(os.environ, {"BUN": "bun-test"}, clear=False):
            _api, ui = dev.service_specs(options)

        self.assertEqual(
            ui.command,
            ("bun-test", "run", "start", "--hostname", "127.0.0.1", "--port", "3100"),
        )


class DevRuntimeTests(unittest.TestCase):
    def test_busy_port_aborts_before_launching_processes(self) -> None:
        launched: list[object] = []
        messages: list[str] = []
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((dev.LOOPBACK_HOST, 0))
            listener.listen()
            occupied_port = listener.getsockname()[1]
            self.assertFalse(dev.port_is_available(dev.LOOPBACK_HOST, occupied_port))
            options = dev.parse_args(["start", "--api-port", str(occupied_port), "--ui-port", "3100"])

            result = dev.run_dev(
                options,
                port_probe=lambda host, port: dev.port_is_available(host, port)
                if port == occupied_port
                else True,
                popen_factory=lambda *args, **kwargs: launched.append((args, kwargs)),
                printer=messages.append,
            )

        self.assertEqual(result, 1)
        self.assertEqual(launched, [])
        self.assertEqual(
            messages,
            [
                f"error: already in use: API port {occupied_port}; "
                "stop the owning process or choose another port"
            ],
        )

    def test_port_probe_rebinds_after_a_loopback_connection_closes(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            # The launcher's managed servers (uvicorn, the bun/Node UI server) bind with
            # SO_REUSEADDR. Linux only lets a SO_REUSEADDR probe bind over a TIME_WAIT entry
            # when the earlier socket also had SO_REUSEADDR; macOS allows it either way. Model
            # the launcher's own servers here so the case is the same on every platform. A
            # TIME_WAIT entry left by a socket without SO_REUSEADDR still reads as busy on
            # Linux for up to a minute; that is a documented limit of the probe, not a defect
            # this test covers.
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((dev.LOOPBACK_HOST, 0))
            listener.listen()
            port = listener.getsockname()[1]
            with socket.create_connection((dev.LOOPBACK_HOST, port)) as client:
                accepted, _address = listener.accept()
                accepted.close()

        self.assertTrue(dev.port_is_available(dev.LOOPBACK_HOST, port))

    def test_start_failure_cleans_only_started_process(self) -> None:
        options = dev.parse_args(["start"])
        api_process = FakeProcess(4312)
        calls = 0
        cleaned: list[list[dev.ManagedProcess]] = []

        def popen_factory(*args: object, **kwargs: object) -> FakeProcess:
            nonlocal calls
            calls += 1
            if calls == 1:
                return api_process
            raise OSError("missing bun")

        with self.assertRaises(dev.DevError):
            dev.start_services(
                options,
                popen_factory=popen_factory,
                cleanup=lambda processes: cleaned.append(list(processes)),
            )

        self.assertEqual(calls, 2)
        self.assertEqual([item.name for item in cleaned[0]], ["API"])
        self.assertIs(cleaned[0][0].process, api_process)

    def test_shutdown_signals_and_reaps_only_owned_processes(self) -> None:
        process = FakeProcess(4313)
        managed = dev.ManagedProcess("API", process)
        signals: list[tuple[int, int]] = []

        def signal_group(item: dev.ManagedProcess, signum: int) -> None:
            signals.append((item.process.pid, signum))
            item.process.returncode = 0

        dev.shutdown_processes(
            [managed],
            grace_seconds=0.01,
            kill_seconds=0.01,
            signal_group=signal_group,
        )

        self.assertEqual(signals, [(4313, signal.SIGTERM), (4313, signal.SIGKILL)])
        self.assertTrue(process.wait_calls)

    def test_shutdown_kills_owned_group_after_its_leader_exits(self) -> None:
        leader = FakeProcess(4314, returncode=0)
        managed = dev.ManagedProcess("API", leader)
        signals: list[tuple[int, int]] = []
        descendant_is_live = True

        def signal_group(item: dev.ManagedProcess, signum: int) -> None:
            nonlocal descendant_is_live
            signals.append((item.process.pid, signum))
            if signum == signal.SIGKILL:
                descendant_is_live = False

        dev.shutdown_processes(
            [managed],
            grace_seconds=0,
            kill_seconds=0,
            signal_group=signal_group,
        )

        self.assertEqual(signals, [(4314, signal.SIGTERM), (4314, signal.SIGKILL)])
        self.assertFalse(descendant_is_live)
        self.assertTrue(leader.wait_calls)

    def test_signal_process_group_does_not_skip_an_exited_leader(self) -> None:
        leader = dev.ManagedProcess("API", FakeProcess(4315, returncode=0))
        with mock.patch.object(dev.os, "name", "posix"), mock.patch.object(dev.os, "killpg") as killpg:
            dev.signal_process_group(leader, signal.SIGTERM)

        killpg.assert_called_once_with(4315, signal.SIGTERM)

    def test_readiness_failure_mentions_child_and_never_marks_ready(self) -> None:
        options = dev.parse_args(["start", "--readiness-timeout", "1"])
        process = dev.ManagedProcess("API", FakeProcess(4314, returncode=2))

        with self.assertRaisesRegex(dev.DevError, r"API exited before readiness \(status 2\)"):
            dev.wait_for_readiness([process], options, probe=lambda _url: False)

    def test_readiness_timeout_is_bounded(self) -> None:
        options = dev.parse_args(["start", "--readiness-timeout", "0.1"])
        process = dev.ManagedProcess("API", FakeProcess(4316))
        ticks = iter((0.0, 0.0, 0.0, 1.0))

        with self.assertRaisesRegex(dev.DevError, "did not become ready within 0.1 seconds"):
            dev.wait_for_readiness(
                [process],
                options,
                probe=lambda _url: False,
                clock=lambda: next(ticks),
                sleep=lambda _seconds: None,
            )

    def test_keyboard_interrupt_stops_started_processes(self) -> None:
        processes = [dev.ManagedProcess("API", FakeProcess(4317))]
        messages: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            options = dev.parse_args(["start", "--data-dir", str(Path(temporary) / "monitor")])
            with (
                mock.patch.object(dev, "verify_ports"),
                mock.patch.object(dev, "start_services", return_value=processes),
                mock.patch.object(dev, "wait_for_readiness"),
                mock.patch.object(dev, "monitor_processes", side_effect=KeyboardInterrupt),
                mock.patch.object(dev, "shutdown_processes") as shutdown,
            ):
                result = dev.run_dev(options, printer=messages.append)

        self.assertEqual(result, 130)
        self.assertEqual(messages[-1], "Stopping local monitor services.")
        shutdown.assert_called_once_with(processes)

    def test_start_creates_missing_nested_workspace_before_launch(self) -> None:
        messages: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "new" / "nested" / "monitor"
            options = dev.parse_args(["start", "--data-dir", str(data_dir)])

            def start_after_workspace(_options: object, _popen_factory: object) -> list[dev.ManagedProcess]:
                self.assertTrue(data_dir.is_dir())
                return []

            with (
                mock.patch.object(dev, "verify_ports"),
                mock.patch.object(dev, "start_services", side_effect=start_after_workspace),
                mock.patch.object(dev, "wait_for_readiness"),
                mock.patch.object(dev, "monitor_processes", side_effect=KeyboardInterrupt),
            ):
                result = dev.run_dev(options, printer=messages.append)

            self.assertEqual(result, 130)
            for directory in (data_dir.parent.parent, data_dir.parent, data_dir):
                self.assertEqual(directory.stat().st_mode & 0o077, 0)

    def test_workspace_creation_rejects_file_parent_and_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            parent_file = base / "not-a-directory"
            parent_file.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(dev.DevError, "workspace parent is not a directory"):
                dev.prepare_data_directory(parent_file / "monitor")
            self.assertEqual(parent_file.read_text(encoding="utf-8"), "keep")

            terminal_file = base / "plain-workspace"
            terminal_file.write_text("keep-terminal", encoding="utf-8")
            with self.assertRaisesRegex(dev.DevError, "workspace path is not a directory"):
                dev.prepare_data_directory(terminal_file)
            self.assertEqual(terminal_file.read_text(encoding="utf-8"), "keep-terminal")

            target = base / "target"
            target.mkdir()
            terminal_link = base / "monitor"
            terminal_link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(dev.DevError, "refusing symlinked workspace path"):
                dev.prepare_data_directory(terminal_link)

    def test_workspace_creation_preserves_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "monitor"
            data_dir.mkdir(mode=0o755)
            data_dir.chmod(0o755)
            marker = data_dir / "existing-data"
            marker.write_text("preserve", encoding="utf-8")
            original_mode = data_dir.stat().st_mode & 0o777

            dev.prepare_data_directory(data_dir)

            self.assertEqual(data_dir.stat().st_mode & 0o777, original_mode)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_cli_sigterm_handler_routes_to_runner_and_is_restored(self) -> None:
        options = dev.parse_args(["start"])
        previous_handler = object()
        installed: list[object] = []

        def install_handler(_signum: int, handler: object) -> None:
            installed.append(handler)

        def runner(_options: object) -> int:
            with self.assertRaises(KeyboardInterrupt):
                installed[0](signal.SIGTERM, None)  # type: ignore[operator]
            return 130

        with (
            mock.patch.object(dev.signal, "getsignal", return_value=previous_handler),
            mock.patch.object(dev.signal, "signal", side_effect=install_handler),
            mock.patch.object(dev, "run_dev", side_effect=runner),
        ):
            result = dev.run_cli(options)

        self.assertEqual(result, 130)
        self.assertEqual(len(installed), 2)
        self.assertIs(installed[1], previous_handler)


class TokenCommandTests(unittest.TestCase):
    def token_result(self, directory: Path) -> tuple[int, str, str]:
        output = io.StringIO()
        errors = io.StringIO()
        result = dev.print_token(directory, output, errors)
        return result, output.getvalue(), errors.getvalue()

    def test_token_reads_only_expected_private_access_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            token_path = directory / "access.token"
            token_path.write_text("private-token\n", encoding="utf-8")
            token_path.chmod(0o600)
            (directory / "other-secret").write_text("must-not-read", encoding="utf-8")

            result, output, errors = self.token_result(directory)

        self.assertEqual(result, 0)
        self.assertEqual(output, "private-token\n")
        self.assertEqual(errors, "")

    def test_token_rejects_missing_insecure_and_symlink_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result, output, errors = self.token_result(directory)
            self.assertEqual(result, 1)
            self.assertEqual(output, "")
            self.assertIn("access token file is missing", errors)

            token_path = directory / "access.token"
            token_path.write_text("private-token", encoding="utf-8")
            token_path.chmod(0o644)
            result, output, errors = self.token_result(directory)
            self.assertEqual(result, 1)
            self.assertEqual(output, "")
            self.assertIn("permissions", errors)

            token_path.unlink()
            target = directory / "unrelated-file"
            target.write_text("not-a-token", encoding="utf-8")
            token_path.symlink_to(target)
            result, output, errors = self.token_result(directory)
            self.assertEqual(result, 1)
            self.assertEqual(output, "")
            self.assertIn("symlinked access token", errors)

    def test_token_rejects_symlinked_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            actual = base / "actual"
            actual.mkdir()
            token_path = actual / "access.token"
            token_path.write_text("private-token", encoding="utf-8")
            token_path.chmod(0o600)
            alias = base / "alias"
            alias.symlink_to(actual, target_is_directory=True)

            options = dev.parse_args(["token", "--data-dir", str(alias)])
            result, output, errors = self.token_result(options.data_dir)

        self.assertEqual(result, 1)
        self.assertEqual(output, "")
        self.assertIn("symlinked data directory", errors)


if __name__ == "__main__":
    unittest.main()
