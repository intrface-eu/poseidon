"""Synthetic clock/storage fault injection. Not hardware safety evidence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from poseidon_siren import Budget, Scheduler, SirenDenied, SirenFault
from poseidon_siren import scheduler as implementation


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "state"

    def initialize(self, budget=Budget()):
        scheduler = Scheduler.initialize(self.directory, budget)
        self.addCleanup(scheduler.close)
        return scheduler

    def rearm(self, scheduler, now=0):
        scheduler.rearm_simulation(now, acknowledge_simulation_only=True)

    def rewrite(self, state):
        # Rehash to exercise semantic validation, not only bit-corruption checks.
        payload = implementation._canonical(state)
        (self.directory / "state.json").write_bytes(implementation._canonical({
            "payload": state, "sha256": hashlib.sha256(payload).hexdigest(),
        }))

    def test_boot_inhibit_explicit_rearm_stop_and_disabled_output(self):
        scheduler = self.initialize()
        self.assertTrue(scheduler.status["inhibited"])
        with self.assertRaisesRegex(SirenDenied, "inhibited"):
            scheduler.request(0, 250)
        for acknowledgment in [False, None, 1, "true"]:
            with self.subTest(acknowledgment=acknowledgment), self.assertRaises(SirenDenied):
                scheduler.rearm_simulation(0, acknowledge_simulation_only=acknowledgment)
        self.rearm(scheduler)
        grant = scheduler.request(0, 250)
        self.assertEqual((grant.start_ms, grant.end_ms), (0, 250))
        self.assertTrue(grant.simulation_only)
        self.assertFalse(grant.physical_output_enabled)
        scheduler.stop(0)
        self.assertTrue(scheduler.status["inhibited"])
        self.assertEqual(scheduler.status["reservations"], [[0, 250]])
        self.assertFalse(scheduler.status["physical_output_enabled"])
        for event in scheduler.status["audit"]:
            self.assertTrue(event["simulation_only"])
            self.assertFalse(event["physical_output_enabled"])
        snapshot = scheduler.status
        snapshot["reservations"].clear()
        self.assertEqual(scheduler.status["reservations"], [[0, 250]])

    def test_full_future_duration_reserved_overlap_and_cooldown(self):
        scheduler = self.initialize()
        self.rearm(scheduler)
        scheduler.request(0, 500)
        for now, reason in [(0, "overlap"), (499, "overlap"), (500, "cooldown"), (1499, "cooldown")]:
            with self.subTest(now=now), self.assertRaisesRegex(SirenDenied, reason):
                scheduler.request(now, 500)
        scheduler.request(1500, 500)
        with self.assertRaisesRegex(SirenDenied, "window_budget"):
            scheduler.request(3000, 1)
        self.assertEqual(scheduler.status["reservations"], [[0, 500], [1500, 2000]])

    def test_full_interval_not_start_counts_controls_sliding_window(self):
        scheduler = self.initialize(Budget(window_ms=100, max_on_ms=60, max_burst_ms=60, cooldown_ms=0))
        self.rearm(scheduler)
        scheduler.request(0, 40)
        with self.assertRaisesRegex(SirenDenied, "window_budget"):
            scheduler.request(40, 30)
        scheduler.request(40, 20)
        with self.assertRaisesRegex(SirenDenied, "window_budget"):
            scheduler.request(90, 60)
        scheduler.request(100, 60)
        self.assertEqual(scheduler.status["reservations"], [[0, 40], [40, 60], [100, 160]])

    def test_window_arithmetic_against_discrete_reference(self):
        rng = random.Random(31)
        for _ in range(100):
            start, intervals = 0, []
            for _ in range(8):
                start += rng.randrange(5)
                end = start + rng.randrange(1, 8)
                intervals.append([start, end])
                start = end
            window = rng.randrange(1, 30)
            occupied = {tick for a, b in intervals for tick in range(a, b)}
            reference = max(sum(tick in occupied for tick in range(end-window, end))
                            for end in range(start + window + 1))
            self.assertEqual(implementation._window_charge(intervals, window), reference)

    def test_stop_and_rearm_do_not_refund_unelapsed_reservation(self):
        scheduler = self.initialize()
        self.rearm(scheduler)
        scheduler.request(0, 500)
        scheduler.stop(1)
        self.rearm(scheduler, 1)
        with self.assertRaisesRegex(SirenDenied, "overlap"):
            scheduler.request(1, 500)
        scheduler.request(1500, 500)
        scheduler.stop(1500)
        self.rearm(scheduler, 3000)
        with self.assertRaisesRegex(SirenDenied, "window_budget"):
            scheduler.request(3000, 1)

    def test_restart_preserves_inhibit_budget_and_cooldown(self):
        scheduler = self.initialize()
        self.rearm(scheduler)
        scheduler.request(0, 500)
        scheduler.request(1500, 500)
        scheduler.close()
        with Scheduler(self.directory) as recovered:
            self.assertTrue(recovered.status["inhibited"])
            with self.assertRaisesRegex(SirenDenied, "inhibited"):
                recovered.request(1500, 1)
            self.rearm(recovered, 1500)
            with self.assertRaisesRegex(SirenDenied, "overlap"):
                recovered.request(1500, 1)
            with self.assertRaisesRegex(SirenDenied, "cooldown"):
                recovered.request(2000, 1)
            with self.assertRaisesRegex(SirenDenied, "window_budget"):
                recovered.request(3000, 1)
            recovered.request(10000, 500)
            self.assertEqual(len(recovered.status["reservations"]), 3)

    def test_backward_clock_fault_survives_restart_and_cannot_be_rearmed(self):
        scheduler = self.initialize()
        self.rearm(scheduler, 1000)
        scheduler.close()
        with Scheduler(self.directory) as recovered:
            with self.assertRaisesRegex(SirenFault, "backward_clock"):
                self.rearm(recovered, 0)
            self.assertTrue(recovered.status["inhibited"])
        with Scheduler(self.directory) as recovered:
            self.assertEqual(recovered.status["fault"], "backward_clock")
            with self.assertRaisesRegex(SirenFault, "backward_clock"):
                self.rearm(recovered, 2000)

    def test_invalid_nonfinite_and_noninteger_clocks_latch_fault(self):
        for index, now in enumerate([math.nan, math.inf, -math.inf, -1, True, 0.5, "0", None, 10**13]):
            directory = Path(self.temporary.name) / f"clock-{index}"
            with self.subTest(now=now), Scheduler.initialize(directory) as scheduler:
                with self.assertRaisesRegex(SirenFault, "invalid_clock"):
                    self.rearm(scheduler, now)
                self.assertTrue(scheduler.status["inhibited"])
                with self.assertRaises(SirenFault):
                    self.rearm(scheduler, 0)

    def test_invalid_duration_or_end_overflow_latches_fault(self):
        for index, duration in enumerate([0, -1, 501, math.nan, math.inf, True, "1", 0.1]):
            directory = Path(self.temporary.name) / f"duration-{index}"
            with self.subTest(duration=duration), Scheduler.initialize(directory) as scheduler:
                self.rearm(scheduler)
                with self.assertRaisesRegex(SirenFault, "invalid_duration"):
                    scheduler.request(0, duration)
                self.assertTrue(scheduler.status["inhibited"])
        scheduler = self.initialize()
        self.rearm(scheduler, implementation.MAX_CLOCK_MS)
        with self.assertRaisesRegex(SirenFault, "invalid_duration"):
            scheduler.request(implementation.MAX_CLOCK_MS, 1)

    def test_invalid_config_and_changed_config_do_not_start(self):
        for kwargs in [{"window_ms": 0}, {"window_ms": math.nan}, {"max_on_ms": 10001},
                       {"max_burst_ms": 1001}, {"max_burst_ms": True}, {"cooldown_ms": -1},
                       {"cooldown_ms": math.inf}, {"window_ms": 86_400_001}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Budget(**kwargs)
        scheduler = self.initialize()
        with self.assertRaises(FrozenInstanceError):
            scheduler.config.max_on_ms = 2000
        with self.assertRaises(AttributeError):
            scheduler.config = Budget(max_on_ms=2000)
        scheduler.close()
        with self.assertRaisesRegex(SirenFault, "config mismatch"):
            Scheduler(self.directory, expected_config=Budget(max_on_ms=2000))
        with Scheduler(self.directory) as recovered:
            self.assertTrue(recovered.status["inhibited"])
            self.assertEqual(recovered.config.max_on_ms, 1000)

    def test_injected_fault_stop_and_close_are_fail_closed(self):
        scheduler = self.initialize()
        self.rearm(scheduler)
        with self.assertRaisesRegex(SirenFault, "injected_simulation_fault"):
            scheduler.inject_fault(0)
        self.assertTrue(scheduler.status["inhibited"])
        with self.assertRaises(SirenFault):
            scheduler.stop(0)
        scheduler.close()
        with self.assertRaises(SirenFault):
            scheduler.request(0, 1)
        with Scheduler(self.directory) as recovered:
            self.assertEqual(recovered.status["fault"], "injected_simulation_fault")
            self.assertTrue(recovered.status["inhibited"])

    def test_exclusive_writer_and_initialize_refuses_replacement(self):
        scheduler = self.initialize()
        original = (self.directory / "state.json").read_bytes()
        with self.assertRaises(SirenFault):
            Scheduler(self.directory)
        with self.assertRaises(FileExistsError):
            Scheduler.initialize(self.directory)
        self.assertEqual((self.directory / "state.json").read_bytes(), original)
        scheduler.close()

    def test_concurrent_threads_cannot_reserve_overlapping_intervals(self):
        scheduler = self.initialize()
        self.rearm(scheduler)
        barrier = threading.Barrier(4)

        def request():
            barrier.wait(timeout=3)
            try:
                scheduler.request(0, 500)
                return "reserved"
            except SirenDenied as error:
                return str(error)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(request) for _ in range(4)]
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(results.count("reserved"), 1)
        self.assertEqual(results.count("overlap"), 3)
        self.assertEqual(scheduler.status["reservations"], [[0, 500]])

    def test_missing_state_never_initializes_or_erases_budget(self):
        with self.assertRaises(SirenFault):
            Scheduler(self.directory)
        self.assertFalse(self.directory.exists())
        scheduler = self.initialize()
        scheduler.close()
        (self.directory / "state.json").unlink()
        with self.assertRaises(SirenFault):
            Scheduler(self.directory)
        with self.assertRaises(FileExistsError):
            Scheduler.initialize(self.directory)
        self.assertFalse((self.directory / "state.json").exists())

    def test_malformed_truncated_duplicate_nonfinite_and_oversized_persistence(self):
        scheduler = self.initialize()
        scheduler.close()
        original = (self.directory / "state.json").read_bytes()
        cases = [b"", b"{", b"[]", b"null", b"\xff", original[:-1],
                 b'{"payload":{},"payload":{},"sha256":"x"}',
                 b'{"payload":{"x":NaN},"sha256":"x"}',
                 b" " * (implementation.MAX_STATE_BYTES + 1)]
        for raw in cases:
            with self.subTest(size=len(raw)):
                (self.directory / "state.json").write_bytes(raw)
                with self.assertRaises(SirenFault):
                    Scheduler(self.directory)
                self.assertEqual((self.directory / "state.json").read_bytes(), raw)

    def test_bit_corruption_checksum_and_semantic_corruption_rejected(self):
        scheduler = self.initialize()
        self.rearm(scheduler)
        scheduler.request(0, 500)
        scheduler.close()
        original = scheduler.status
        document = json.loads((self.directory / "state.json").read_bytes())
        document["payload"]["reservations"] = []
        (self.directory / "state.json").write_text(json.dumps(document))
        with self.assertRaisesRegex(SirenFault, "checksum"):
            Scheduler(self.directory)
        mutations = [
            lambda s: s.update(physical_output_enabled=True),
            lambda s: s.update(simulation_only=False),
            lambda s: s.update(version=True),
            lambda s: s.update(inhibited="false"),
            lambda s: s.update(last_now_ms=-1),
            lambda s: s.update(reservations=[]),
            lambda s: s.update(reservations=[[0, 501]]),
            lambda s: s.update(reservations=[[0, 500], [1, 2]]),
            lambda s: s.update(audit=[]),
            lambda s: s["audit"][0].update(sequence=10),
            lambda s: s["audit"][0].update(physical_output_enabled=True),
            lambda s: s["config"].update(max_on_ms=0),
            lambda s: s["config"].update(unknown=1),
        ]
        for mutate in mutations:
            state = json.loads(json.dumps(original))
            mutate(state)
            self.rewrite(state)
            with self.subTest(state=state), self.assertRaises(SirenFault):
                Scheduler(self.directory)

    def test_live_corruption_is_not_overwritten_and_latches_fault(self):
        scheduler = self.initialize()
        (self.directory / "state.json").write_bytes(b"corrupt external write")
        with self.assertRaisesRegex(SirenFault, "persistence_failure"):
            self.rearm(scheduler)
        self.assertTrue(scheduler.status["inhibited"])
        with self.assertRaises(SirenFault):
            scheduler.close()
        self.assertEqual((self.directory / "state.json").read_bytes(), b"corrupt external write")
        with self.assertRaises(SirenFault):
            Scheduler(self.directory)

    def test_symlink_state_and_lock_refused_without_touching_target(self):
        scheduler = self.initialize()
        scheduler.close()
        target = Path(self.temporary.name) / "untouched"
        target.write_text("not state")
        state_path = self.directory / "state.json"
        state_path.unlink()
        state_path.symlink_to(target)
        with self.assertRaises(SirenFault):
            Scheduler(self.directory)
        self.assertEqual(target.read_text(), "not state")
        lock_path = self.directory / "writer.lock"
        lock_path.unlink()
        lock_path.symlink_to(target)
        with self.assertRaises(SirenFault):
            Scheduler(self.directory)
        self.assertEqual(target.read_text(), "not state")

    def test_disk_full_reservation_failure_returns_no_grant_and_latches_inhibit(self):
        scheduler = self.initialize()
        self.rearm(scheduler)
        with patch.object(implementation.tempfile, "mkstemp", side_effect=OSError("synthetic disk full")):
            with self.assertRaisesRegex(SirenFault, "persistence_failure"):
                scheduler.request(0, 500)
            self.assertTrue(scheduler.status["inhibited"])
            self.assertEqual(scheduler.status["fault"], "persistence_failure")
            self.assertIsNone(scheduler.handshake_status["token"])
            self.assertFalse(scheduler.handshake_status["audit_persisted"])
        # Even the unacknowledged attempted reservation remains conservatively charged.
        scheduler.close()
        with Scheduler(self.directory) as recovered:
            self.assertEqual(recovered.status["reservations"], [[0, 500]])
            with self.assertRaises(SirenFault):
                self.rearm(recovered, 0)

    def test_replace_and_file_fsync_failures_preserve_previous_valid_snapshot(self):
        for name in ["replace", "fsync"]:
            directory = Path(self.temporary.name) / name
            scheduler = Scheduler.initialize(directory)
            original = (directory / "state.json").read_bytes()
            with patch.object(implementation.os, name, side_effect=OSError(f"synthetic {name} failure")):
                with self.assertRaises(SirenFault):
                    self.rearm(scheduler)
                self.assertTrue(scheduler.status["inhibited"])
            self.assertEqual((directory / "state.json").read_bytes(), original)
            self.assertEqual(list(directory.glob(".state-*.tmp")), [])
            scheduler.close()
            with Scheduler(directory) as recovered:
                self.assertTrue(recovered.status["inhibited"])
                self.assertEqual(recovered.status["fault"], "persistence_failure")

    def test_state_write_and_flush_failures_do_not_acknowledge_rearm(self):
        real_fdopen = implementation.os.fdopen
        for operation in ["write", "flush"]:
            directory = Path(self.temporary.name) / operation
            scheduler = Scheduler.initialize(directory)
            original = (directory / "state.json").read_bytes()

            def failing_output(fd, mode):
                handle = real_fdopen(fd, mode)
                if mode != "wb":
                    return handle
                wrapper = MagicMock(wraps=handle)
                wrapper.__enter__.return_value = wrapper
                wrapper.__exit__.side_effect = handle.__exit__
                getattr(wrapper, operation).side_effect = OSError(f"synthetic {operation} failure")
                return wrapper

            with patch.object(implementation.os, "fdopen", side_effect=failing_output):
                with self.assertRaises(SirenFault):
                    self.rearm(scheduler)
            self.assertTrue(scheduler.status["inhibited"])
            self.assertEqual((directory / "state.json").read_bytes(), original)
            self.assertEqual(list(directory.glob(".state-*.tmp")), [])
            scheduler.close()

    def test_directory_fsync_failure_after_replace_still_recovers_inhibited(self):
        scheduler = self.initialize()
        self.rearm(scheduler)
        real_fsync = implementation.os.fsync
        calls = 0

        def interrupted_fsync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic directory fsync failure")
            real_fsync(fd)

        with patch.object(implementation.os, "fsync", side_effect=interrupted_fsync):
            with self.assertRaises(SirenFault):
                scheduler.request(0, 500)
        self.assertTrue(scheduler.status["inhibited"])
        # The replacement occurred, but its durability was not acknowledged.
        with self.assertRaises(SirenFault):
            scheduler.close()
        with Scheduler(self.directory) as recovered:
            self.assertTrue(recovered.status["inhibited"])
            self.assertEqual(recovered.status["reservations"], [[0, 500]])
            self.rearm(recovered)
            with self.assertRaisesRegex(SirenDenied, "overlap"):
                recovered.request(0, 500)

    def test_initialization_and_boot_write_failures_prevent_startup(self):
        with patch.object(implementation.os, "replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(SirenFault):
                Scheduler.initialize(self.directory)
        with self.assertRaises(SirenFault):
            Scheduler(self.directory)
        directory = Path(self.temporary.name) / "valid"
        with Scheduler.initialize(directory):
            pass
        with patch.object(implementation.os, "replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(SirenFault):
                Scheduler(directory)
        with Scheduler(directory) as recovered:
            self.assertTrue(recovered.status["inhibited"])

    def test_audit_and_reservation_capacity_fault_instead_of_dropping_history(self):
        scheduler = self.initialize()
        self.rearm(scheduler)
        scheduler.request(0, 500)
        scheduler.request(1500, 500)
        with patch.object(implementation, "MAX_RESERVATIONS", 2):
            with self.assertRaisesRegex(SirenFault, "reservation_capacity"):
                scheduler.request(10000, 1)
        self.assertEqual(len(scheduler.status["reservations"]), 2)
        scheduler.close()
        directory = Path(self.temporary.name) / "audit"
        scheduler = Scheduler.initialize(directory)
        # Rearm now audits both the enable request and its acknowledgment.
        with patch.object(implementation, "MAX_AUDIT", 5):
            self.rearm(scheduler)
            with self.assertRaisesRegex(SirenFault, "audit_capacity"):
                scheduler.stop(0)
            self.assertTrue(scheduler.status["inhibited"])
            self.assertEqual(len(scheduler.status["audit"]), 5)
        scheduler.close()

    def test_abrupt_process_exit_after_commit_before_ack_preserves_full_reservation(self):
        script = """
import os, sys
from poseidon_siren import Scheduler
from poseidon_siren import scheduler as module
scheduler = Scheduler.initialize(sys.argv[1])
scheduler.rearm_simulation(0, acknowledge_simulation_only=True)
write = module._atomic_write
def crash_after_commit(directory, state):
    result = write(directory, state)
    if state['audit'][-1]['action'] == 'reserve':
        os._exit(23)
    return result
module._atomic_write = crash_after_commit
scheduler.request(0, 500)
raise AssertionError('reservation must not return before injected crash')
"""
        process = subprocess.run([sys.executable, "-c", script, str(self.directory)],
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 23, process.stderr)
        with Scheduler(self.directory) as recovered:
            self.assertTrue(recovered.status["inhibited"])
            self.assertEqual(recovered.status["reservations"], [[0, 500]])
            self.rearm(recovered)
            with self.assertRaisesRegex(SirenDenied, "overlap"):
                recovered.request(0, 500)
            recovered.request(1500, 500)
            with self.assertRaisesRegex(SirenDenied, "window_budget"):
                recovered.request(3000, 1)

    def test_cli_demo_and_status_are_explicitly_synthetic(self):
        output = Path(self.temporary.name) / "demo"
        command = [sys.executable, "-m", "poseidon_siren", "demo", "--output", str(output)]
        process = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertTrue(report["simulation_only"])
        self.assertFalse(report["physical_output_enabled"])
        self.assertTrue(report["scheduler"]["inhibited"])
        self.assertEqual(report["startup_denial"], "inhibited")
        self.assertEqual(report["overlap_denial"], "overlap")
        self.assertTrue((output / "synthetic-sine.wav").is_file())
        self.assertEqual(json.loads((output / "synthetic-report.json").read_text()), report)
        status = subprocess.run([sys.executable, "-m", "poseidon_siren", "status", "--state", str(output / "scheduler")],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertTrue(json.loads(status.stdout)["inhibited"])
        repeated = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(repeated.returncode, 2)
        self.assertFalse(json.loads(repeated.stdout)["physical_output_enabled"])


if __name__ == "__main__":
    unittest.main()
