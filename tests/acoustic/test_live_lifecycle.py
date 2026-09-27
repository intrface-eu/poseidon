"""Real, synthetic-only coordinators. Each fixture owns one bounded process group."""
from dataclasses import asdict, dataclass, replace
import json
import multiprocessing as mp
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from poseidon_acoustic.live_capture_cli import main, synthetic_demo_plan
from poseidon_acoustic.live_journal import JournalFault, LiveJournal, verify_live_journal
from poseidon_acoustic.live_models import CapturedBlockV1, LiveValidationError, canonical
from poseidon_acoustic.live_supervisor import ClosedCaptureResult, LiveCaptureSupervisor


def _block():
    return CapturedBlockV1(b"01", 1, canonical({}))


def _config(plan):
    source = plan.sources[0]
    return canonical({"source_id": source.source_id, "source_plan_sha256": source.sha256,
                      "format": source.format, "synthetic": True, "device_access_occurred": False})


def _mark(root, name, data=None):
    (Path(root) / name).write_text(json.dumps(data if data is not None else {"pid": os.getpid()}))


def _window(root, name):
    _mark(root, "window-" + name)
    deadline = time.monotonic() + 10
    while not (Path(root) / "release").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("fixture window timeout: " + name)
        time.sleep(0.01)


def _parent_refused(journal, label):
    operations = (
        lambda: journal.record_configuration("fake-audio", _config(journal.plan)),
        journal.record_start_request,
        lambda: journal.record_started("fake-audio", 42),
        lambda: journal.append_payload("fake-audio", _block()),
        lambda: journal.finalize("stale-parent"),
    )
    for operation in operations:
        try:
            operation()
        except JournalFault:
            pass
        else:
            raise AssertionError("stale parent mutation accepted: " + label)
    if journal._owner_fd is not None:
        try:
            LiveJournal.recover(journal.path)
        except JournalFault as exc:
            assert "active owner" in str(exc), str(exc)
        else:
            raise AssertionError("passive lease allowed competing recovery: " + label)
    _mark(journal.path.parent, "refused-" + label,
          {"transferred": journal._transferred, "passive_fd": journal._owner_fd is not None})


class TransferJournal(LiveJournal):
    def record_configuration(self, source_id, canonical_metadata):
        super().record_configuration(source_id, canonical_metadata)
        if self.fixture_mode == "writer-crash":
            os._exit(31)  # Genuine writer crash after committed configuration.

    def __getstate__(self):
        state = super().__getstate__()
        _parent_refused(self, "transfer")
        if self.fixture_mode == "writer-transfer":
            _window(self.path.parent, "writer-transfer")
        return state


@dataclass(frozen=True)
class LifecycleFactory:
    root: str
    mode: str
    synthetic: bool = True

    def open(self, source, limits, admission):
        if admission is not None:
            raise AssertionError("synthetic fixture received device admission")
        return LifecycleBackend(source, self.root, self.mode)


class LifecycleBackend:
    def __init__(self, source, root, mode):
        self.source, self.root, self.mode = source, root, mode

    def configure(self):
        if self.mode == "source-configure":
            _window(self.root, "source-configure")
        return canonical({"source_id": self.source.source_id, "source_plan_sha256": self.source.sha256,
                          "format": self.source.format, "synthetic": True, "device_access_occurred": False})

    def start(self):
        _mark(self.root, "active")

    def read(self, timeout_s):
        time.sleep(min(timeout_s, 0.01))
        return None

    def close(self):
        _mark(self.root, "backend-closed")
        if self.mode == "backend-close-error":
            raise RuntimeError("synthetic backend close failure")


def _fixture(mode, root, shutdown_timeout_s):
    """Executed as a standalone interpreter; never from the test coordinator."""
    from multiprocessing import popen_spawn_posix, process as process_module, resource_tracker
    from poseidon_acoustic import live_supervisor as supervisor_module
    root = Path(root)
    prior = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}
    seen = []

    def old_handler(signum, frame):
        seen.append(signum)

    for signum in prior:
        signal.signal(signum, old_handler)
    journal = None
    result = None
    launch = popen_spawn_posix.Popen._launch
    start = process_module.BaseProcess.start
    join = process_module.BaseProcess.join
    reap = supervisor_module._reap
    launched = []
    join_failed = False

    def launch_window(popen, process):
        launch(popen, process)
        launched.append({"pid": popen.pid, "name": process.name})
        _mark(root, "owned-pids", {"workers": launched, "tracker": resource_tracker._resource_tracker._pid})
        label = "writer" if process.name == "poseidon-live-writer" else "source"
        if mode == label + "-spawn":
            # The OS child exists, but BaseProcess.start has NOT assigned _popen.
            _parent_refused(journal, "spawn")
            _window(root, mode)

    def start_failure(process):
        label = "writer" if process.name == "poseidon-live-writer" else "source"
        if mode == label + "-fail-before":
            raise RuntimeError("injected pre-spawn failure")
        start(process)
        if mode == label + "-fail-after":
            _parent_refused(journal, "failed-spawn")
            raise RuntimeError("injected post-spawn failure")

    def join_failure(process, timeout=None):
        nonlocal join_failed
        if mode == "cleanup-error" and process.name == "poseidon-live-audio" and not join_failed:
            join_failed = True
            raise RuntimeError("injected first source join failure")
        return join(process, timeout)

    def reap_window(process, deadline):
        if mode == "cleanup-signals" and process.name == "poseidon-live-audio":
            _window(root, "cleanup-signals")
        if journal._transferred:
            _parent_refused(journal, "cleanup")
        stopped = reap(process, deadline)
        if mode == "cleanup-step-error" and process.name == "poseidon-live-audio":
            raise RuntimeError("injected completed source cleanup reporting failure")
        return stopped

    try:
        plan = synthetic_demo_plan()
        plan = replace(plan, limits=replace(plan.limits, duration_s=6.0, shutdown_timeout_s=shutdown_timeout_s))
        journal = TransferJournal.create(root / "journal", plan)
        journal.fixture_mode = mode
        with mock.patch.object(popen_spawn_posix.Popen, "_launch", launch_window), \
             mock.patch.object(process_module.BaseProcess, "start", start_failure), \
             mock.patch.object(process_module.BaseProcess, "join", join_failure), \
             mock.patch.object(supervisor_module, "_reap", reap_window):
            result = LiveCaptureSupervisor().run(plan, LifecycleFactory(str(root), mode), journal)
        _parent_refused(journal, "after-run")
        assert journal._owner_fd is None
        try:
            LiveCaptureSupervisor().run(plan, LifecycleFactory(str(root), mode), journal)
        except JournalFault:
            pass
        else:
            raise AssertionError("stale parent journal resumed after run/failure")
        assert all(signal.getsignal(signum) is old_handler for signum in prior)
        assert seen == [], "prior handlers ran before cleanup completed"
        signal.raise_signal(signal.SIGTERM)
        signal.raise_signal(signal.SIGINT)
        assert seen == [signal.SIGTERM, signal.SIGINT]
        output = asdict(result)
        output["final_json"] = None if result.final_json is None else result.final_json.decode("ascii")
        output["handlers_restored"] = True
        output["join_failure_exercised"] = join_failed
        _mark(root, "result", output)
    finally:
        for signum, handler in prior.items():
            signal.signal(signum, handler)
        if journal is not None:
            journal.close_owner()


def _group_members(group):
    listing = subprocess.run(["ps", "-axo", "pid=,pgid=,command="], capture_output=True,
                             text=True, check=True, timeout=3).stdout
    rows = []
    for line in listing.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) >= 2 and int(parts[1]) == group:
            rows.append(line.strip())
    return rows


def _wait_file(path, process, deadline):
    while not path.exists():
        if process.poll() is not None:
            raise AssertionError("fixture exited before " + path.name)
        if time.monotonic() >= deadline:
            raise AssertionError("fixture deadline waiting for " + path.name)
        time.sleep(0.01)


class LiveLifecycleTests(unittest.TestCase):
    def fixture(self, mode, signum=None, *, competing=False, shutdown_timeout_s=3.0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / "stdout").open("wb") as stdout, (root / "stderr").open("wb") as stderr:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--fixture", mode, str(root),
                                            str(shutdown_timeout_s)],
                                           stdout=stdout, stderr=stderr, start_new_session=True)
                try:
                    deadline = time.monotonic() + 18
                    if signum is not None:
                        marker = "window-" + mode if mode in ("writer-transfer", "writer-spawn", "source-spawn", "source-configure") else "active"
                        _wait_file(root / marker, process, deadline)
                        if competing:
                            # Independent interpreter, no inherited journal descriptor.
                            command = [sys.executable, "-m", "poseidon_acoustic.live_capture_cli", "recover",
                                       "--journal", str(root / "journal")]
                            denied = subprocess.run(command, capture_output=True, timeout=4)
                            self.assertEqual(denied.returncode, 2, denied.stdout)
                            self.assertIn(b"active owner", denied.stderr)
                            self.assertFalse((root / "journal" / "final.json").exists())
                        os.kill(process.pid, signum)
                        if mode == "cleanup-signals":
                            _wait_file(root / "window-cleanup-signals", process, deadline)
                            for repeated in (signal.SIGINT, signal.SIGTERM, signal.SIGINT):
                                os.kill(process.pid, repeated)
                                time.sleep(0.02)
                        (root / "release").touch()
                    process.wait(timeout=max(0.1, deadline - time.monotonic()))
                    self.assertEqual(process.returncode, 0, (root / "stderr").read_text())
                    # Resource tracker exits once the coordinator's final pipe closes.
                    end = time.monotonic() + 3
                    members = _group_members(process.pid)
                    while members and time.monotonic() < end:
                        time.sleep(0.03)
                        members = _group_members(process.pid)
                    self.assertEqual(members, [], "orphan owned writer/source/resource-tracker")
                    result = json.loads((root / "result").read_text())
                    self.assertEqual(result["owned_workers_reaped"], mode != "cleanup-step-error", result)
                    self.assertTrue(result["handlers_restored"])
                    self.assertTrue(result["synthetic"])
                    self.assertFalse(result["device_access_occurred"])
                    self.assertTrue((root / "refused-after-run").exists())
                    if mode != "writer-fail-before":
                        self.assertTrue((root / "refused-transfer").exists())
                        transfer = json.loads((root / "refused-transfer").read_text())
                        self.assertTrue(transfer["transferred"])
                        self.assertTrue(transfer["passive_fd"])
                    if mode == "cleanup-error":
                        self.assertTrue(result["join_failure_exercised"])
                    view = LiveJournal.recover(root / "journal")
                    self.assertTrue(view.closed)
                    return result
                finally:
                    # Only this fixture's new session/process group, never name matching.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)

    def test_sigterm_and_sigint_during_active_capture_refuse_competing_recovery(self):
        for signum in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=signum):
                result = self.fixture("active", signum, competing=True)
                self.assertEqual(result["reason"], "cancelled")
                self.assertTrue(result["finalized"], result)

    def test_signal_during_actual_writer_and_source_spawn_windows(self):
        for mode in ("writer-transfer", "writer-spawn", "source-spawn", "source-configure"):
            for signum in (signal.SIGTERM, signal.SIGINT):
                with self.subTest(mode=mode, signal=signum):
                    result = self.fixture(mode, signum, competing=True)
                    self.assertTrue(result["finalized"], result)
                    self.assertEqual(result["committed_chunks"], 0)

    def test_partial_spawn_failures_burn_parent_authority_and_reap(self):
        for mode in ("writer-fail-before", "writer-fail-after", "source-fail-before", "source-fail-after"):
            with self.subTest(mode=mode):
                self.fixture(mode)

    def test_real_writer_crash_releases_lease_for_stopped_prefix_recovery(self):
        # This test asserts the writer-deadline path, so the short deadline is intentional.
        result = self.fixture("writer-crash", shutdown_timeout_s=0.3)
        self.assertFalse(result["finalized"], result)
        self.assertIn("writer-deadline", result["reason"])

    def test_repeated_signals_remain_deferred_during_cleanup(self):
        self.fixture("cleanup-signals", signal.SIGTERM)

    def test_cleanup_exception_does_not_skip_other_owned_processes(self):
        self.fixture("cleanup-error", signal.SIGINT)
        self.fixture("backend-close-error", signal.SIGTERM)
        result = self.fixture("cleanup-step-error", signal.SIGTERM)
        self.assertIn("cleanup-failure", result["reason"])
        self.assertTrue(result["finalized"], result)
        self.assertFalse(result["owned_workers_reaped"], result)

    def test_cli_never_reports_success_with_unreaped_workers(self):
        import contextlib
        import io
        for reason in ("cancelled", "duration-deadline", "source-exhausted"):
            result = ClosedCaptureResult("synthetic", reason, 0, True, True, False, False, b"{}\n")
            with self.subTest(reason=reason), mock.patch.object(LiveCaptureSupervisor, "run", return_value=result), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["synthetic-demo", "--output-dir", "unused"]), 2)

    def test_handlers_restore_on_setup_failure_and_nonmain_thread_refuses_before_resources(self):
        prior = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}
        with tempfile.TemporaryDirectory() as directory:
            plan = synthetic_demo_plan()
            factory = LifecycleFactory(directory, "active")
            def setup_failure(*args):
                for signum in prior:
                    self.assertNotEqual(signal.getsignal(signum), prior[signum])
                    signal.raise_signal(signum)  # Deferred before the first owned resource.
                raise OSError("injected journal setup failure")

            with mock.patch.object(LiveJournal, "create", side_effect=setup_failure):
                with self.assertRaises(OSError):
                    LiveCaptureSupervisor().run(plan, factory, Path(directory) / "journal")
            self.assertEqual({signum: signal.getsignal(signum) for signum in prior}, prior)
            errors = []

            def run():
                try:
                    LiveCaptureSupervisor().run(plan, factory, Path(directory) / "thread")
                except ValueError as exc:
                    errors.append(exc)

            thread = threading.Thread(target=run)
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], LiveValidationError)
            self.assertIn("main-thread", str(errors[0]))
            self.assertFalse((Path(directory) / "thread").exists())


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--fixture":
        _fixture(sys.argv[2], sys.argv[3], float(sys.argv[4]))
    else:
        unittest.main()
