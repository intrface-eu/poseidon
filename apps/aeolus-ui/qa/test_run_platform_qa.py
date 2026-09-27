"""Focused runner regressions using only temporary owned processes and groups."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

RUNNER = Path(__file__).with_name("run-platform-qa.py").resolve()
spec = importlib.util.spec_from_file_location("platform_qa_runner", RUNNER)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


CHILD = """
import os, signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()))
while True:
    time.sleep(0.1)
"""


def wait_for(condition, seconds: float = 4.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Owned test process missed a bounded readiness deadline")


def force_group(pgid: int) -> None:
    """Test fallback for a group whose ID came from this test's own spawn record."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return
    wait_for(lambda: not runner.group_exists(pgid), seconds=3)


INTERRUPTION_HARNESS = r'''
import importlib.util, json, os, signal, subprocess, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("owned_runner_test", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.TERM_GRACE_SECONDS = 0.2
module.KILL_WAIT_SECONDS = 1.0
root = Path(sys.argv[2])
state = root / "groups.json"
cleanup_started = root / "cleanup-started"
child_source = """
import os, signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()))
while True: time.sleep(0.1)
"""
def fixture_session(artifacts, interrupts):
    owned = []
    try:
        for index in range(2):
            ready = root / f"child-{index}-ready"
            module.start_owned(owned, [sys.executable, "-c", child_source, str(ready)], interrupts,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            state.write_text(json.dumps({"groups": [p.pid for p in owned], "ready": False}))
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not ready.exists(): raise RuntimeError("owned fixture child not ready")
        state.write_text(json.dumps({"groups": [p.pid for p in owned], "ready": True}))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            time.sleep(0.05)
        raise RuntimeError("parent did not send the expected signal")
    finally:
        with interrupts.deferred():
            cleanup_started.write_text("cleanup protected")
            module.cleanup_all(tuple(reversed(owned)), interrupts)
module.run_session = fixture_session
os.environ["PLATFORM_QA_ARTIFACTS"] = str(root / "artifacts")
raise SystemExit(module.main())
'''


@unittest.skipUnless(os.name == "posix", "owned process-group tests require POSIX")
class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="poseidon-runner-cleanup-test-")
        self.root = Path(self.temporary.name)
        self.owned: list[subprocess.Popen] = []
        self.timeouts = mock.patch.multiple(runner, TERM_GRACE_SECONDS=0.15, KILL_WAIT_SECONDS=1.0)
        self.timeouts.start()

    def tearDown(self) -> None:
        try:
            for process in self.owned:
                try:
                    runner.stop(process)
                except BaseException:
                    force_group(process.pid)
                    process.wait(timeout=1)
        finally:
            self.timeouts.stop()
            self.temporary.cleanup()

    def child(self, label: str) -> subprocess.Popen:
        ready = self.root / f"{label}-ready"
        process = subprocess.Popen([sys.executable, "-c", CHILD, str(ready)], start_new_session=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.owned.append(process)
        wait_for(ready.exists)
        return process

    def test_exited_leader_live_descendant_is_escalated(self) -> None:
        ready = self.root / "orphan-ready"
        leader_code = """
import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 3
while not Path(sys.argv[2]).exists() and time.monotonic() < deadline: time.sleep(0.01)
if not Path(sys.argv[2]).exists(): raise SystemExit(2)
"""
        leader = subprocess.Popen([sys.executable, "-c", leader_code, CHILD, str(ready)], start_new_session=True,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.owned.append(leader)
        self.assertEqual(leader.wait(timeout=4), 0)
        self.assertTrue(ready.exists())
        self.assertTrue(runner.group_exists(leader.pid))
        real_signal = runner.signal_owned_group
        started = time.monotonic()
        with mock.patch.object(runner, "signal_owned_group", wraps=real_signal) as sent:
            runner.stop(leader)
        self.assertIn(mock.call(leader.pid, signal.SIGKILL), sent.call_args_list)
        self.assertFalse(runner.group_exists(leader.pid))
        self.assertLess(time.monotonic() - started, 4)

    def test_cleanup_exception_does_not_skip_other_owned_groups(self) -> None:
        first, second, third = (self.child(name) for name in ("first", "second", "third"))
        actual_stop = runner.stop
        attempts: list[int] = []

        def fail_first(process):
            attempts.append(process.pid)
            if process is first:
                raise OSError("injected cleanup failure")
            actual_stop(process)

        with mock.patch.object(runner, "stop", side_effect=fail_first), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(runner.CleanupError):
                runner.cleanup_all([first, second, third], runner.Interrupts())
        self.assertEqual(attempts, [first.pid, second.pid, third.pid])
        self.assertFalse(runner.group_exists(second.pid))
        self.assertFalse(runner.group_exists(third.pid))
        actual_stop(first)
        self.assertFalse(runner.group_exists(first.pid))

    def test_cleanup_failure_overrides_a_success_return(self) -> None:
        process = self.child("success-return")
        actual_stop = runner.stop

        def late_failure(item):
            actual_stop(item)
            raise RuntimeError("injected post-cleanup failure")

        def nominal_success():
            try:
                return 0
            finally:
                runner.cleanup_all([process], runner.Interrupts())

        with mock.patch.object(runner, "stop", side_effect=late_failure), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(runner.CleanupError):
                nominal_success()
        self.assertFalse(runner.group_exists(process.pid))

    def test_interruption_after_spawn_keeps_group_registered(self) -> None:
        interrupts = runner.Interrupts()
        registered: list[subprocess.Popen] = []
        actual_popen = subprocess.Popen

        def interrupt_after_spawn(*args, **kwargs):
            process = actual_popen(*args, **kwargs)
            self.owned.append(process)
            interrupts.handle(signal.SIGTERM, None)
            return process

        with mock.patch.object(runner.subprocess, "Popen", side_effect=interrupt_after_spawn):
            with self.assertRaises(runner.Interrupted):
                runner.start_owned(registered, [sys.executable, "-c", "import time; time.sleep(20)"], interrupts,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertEqual(len(registered), 1)
        with self.assertRaises(runner.Interrupted):
            runner.cleanup_all(registered, interrupts)
        self.assertFalse(runner.group_exists(registered[0].pid))

    def test_missing_group_cleanup_is_idempotent(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        self.owned.append(process)
        self.assertEqual(process.wait(timeout=3), 0)
        runner.stop(process)
        runner.stop(process)
        self.assertFalse(runner.group_exists(process.pid))

    def test_sigint_sigterm_and_repeated_signal_unwind_all_groups(self) -> None:
        for first_signal in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=first_signal):
                root = self.root / str(first_signal)
                root.mkdir()
                wrapper = subprocess.Popen([sys.executable, "-c", INTERRUPTION_HARNESS, str(RUNNER), str(root)],
                                           start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                groups: list[int] = []
                try:
                    state = root / "groups.json"

                    def ready():
                        try:
                            return json.loads(state.read_text())["ready"]
                        except (FileNotFoundError, json.JSONDecodeError):
                            return False

                    wait_for(ready, seconds=6)
                    groups = json.loads(state.read_text())["groups"]
                    os.kill(wrapper.pid, first_signal)
                    wait_for((root / "cleanup-started").exists, seconds=3)
                    if wrapper.poll() is None:
                        os.kill(wrapper.pid, signal.SIGTERM)  # Must not break cleanup or replace the first signal.
                    _, stderr = wrapper.communicate(timeout=8)
                    self.assertEqual(wrapper.returncode, 128 + first_signal, stderr.decode())
                    for group in groups:
                        self.assertFalse(runner.group_exists(group))
                finally:
                    if not groups and (root / "groups.json").exists():
                        groups = json.loads((root / "groups.json").read_text())["groups"]
                    try:
                        runner.stop(wrapper)
                    finally:
                        for group in groups:
                            force_group(group)
                        if wrapper.stderr is not None:
                            wrapper.stderr.close()


class ConfigurationTests(unittest.TestCase):
    def test_port_selection_retries_collisions_with_a_bound(self) -> None:
        with mock.patch.object(runner, "free_port", side_effect=[12345, 12345, 12346]):
            self.assertEqual(runner.loopback_ports(), (12345, 12346))
        with mock.patch.object(runner, "free_port", return_value=12345) as choose:
            with self.assertRaises(RuntimeError):
                runner.loopback_ports()
            self.assertEqual(choose.call_count, 17)

    def test_default_commands_keep_locked_api_and_bun(self) -> None:
        api, ui, qa = runner.commands({}, Path("/owned/workspace"), 12345, 12346)
        self.assertEqual(api[:2], ["uv", "run"])
        self.assertIn("--frozen", api)
        self.assertEqual(api[-4:], ["--host", "127.0.0.1", "--port", "12345"])
        self.assertEqual(ui, ["bun", "run", "start", "--port", "12346"])
        self.assertEqual(qa[0], "bun")

    def test_explicit_interpreter_paths_are_single_argv_entries(self) -> None:
        env = {"PLATFORM_QA_API_PYTHON": "/owned Python/bin/python", "PLATFORM_QA_BUN": "/owned Bun/bin/bun"}
        api, ui, qa = runner.commands(env, Path("/owned/workspace"), 12345, 12346)
        self.assertEqual(api[:3], [env["PLATFORM_QA_API_PYTHON"], "-m", "poseidon_api"])
        self.assertNotIn("uv", api)
        self.assertEqual(ui[0], env["PLATFORM_QA_BUN"])
        self.assertEqual(qa[0], env["PLATFORM_QA_BUN"])

    def test_tranche3_mode_requires_selected_environment_and_keeps_prior_modes(self) -> None:
        env = {"PLATFORM_QA_TRANCHE3_ONLY": "1", "PLATFORM_QA_API_PYTHON": "/owned/python"}
        api, _ui, qa = runner.commands(env, Path("/owned/workspace"), 12345, 12346)
        self.assertEqual(api[0], "/owned/python")
        self.assertTrue(qa[1].endswith("tranche3-browser-qa.ts"))
        with self.assertRaises(ValueError):
            runner.commands({"PLATFORM_QA_TRANCHE3_ONLY": "1"}, Path("/owned/workspace"), 12345, 12346)
        for mode in ("PLATFORM_QA_COMPANION_ONLY", "PLATFORM_QA_LEGACY_ONLY", "PLATFORM_QA_AUTH_ONLY"):
            with self.assertRaises(ValueError):
                runner.commands({**env, mode: "1"}, Path("/owned/workspace"), 12345, 12346)
        self.assertTrue(runner.commands({"PLATFORM_QA_COMPANION_ONLY": "1"}, Path("/owned/workspace"), 12345, 12346)[2][1].endswith("companion-browser-qa.ts"))

    def test_empty_override_fails_without_runtime_fallback(self) -> None:
        with self.assertRaises(ValueError):
            runner.commands({"PLATFORM_QA_BUN": ""}, Path("/owned/workspace"), 12345, 12346)
        with self.assertRaises(ValueError):
            runner.commands({"PLATFORM_QA_API_PYTHON": ""}, Path("/owned/workspace"), 12345, 12346)

    def test_signal_handlers_are_restored(self) -> None:
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        with runner.interrupt_handlers() as interrupts:
            self.assertEqual(signal.getsignal(signal.SIGTERM), interrupts.handle)
        for sig, handler in previous.items():
            self.assertEqual(signal.getsignal(sig), handler)


if __name__ == "__main__":
    unittest.main()
