from dataclasses import dataclass, replace
import multiprocessing as mp
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from poseidon_acoustic.live_capture_cli import synthetic_demo_plan
from poseidon_acoustic.live_journal import LiveJournal, _publish, verify_live_journal
from poseidon_acoustic.live_models import (BackendFault, CapturedBlockV1, EndOfSource, SourcePlanV1,
                                          canonical, parse_canonical)
from poseidon_acoustic.live_supervisor import (LiveCaptureSupervisor, SyntheticBackendFactory,
                                             SyntheticSourceScript)


def audio_block(units=4):
    return CapturedBlockV1(b"\x10\x20" * units, units,
                           canonical({"timestamp": None, "clock_domain": "synthetic", "driver_accuracy_ns": None}))


def video_source():
    return SourcePlanV1("fake-video", "video", "synthetic", None, canonical({}), (), (), None,
                        2, 2, 25, 1, None, None, None, None, None, None, None, "synthetic")


class StalledJournal(LiveJournal):
    def append_payload(self, source_id, block):
        _publish(self.path, "payload-000000000.bin", block.payload)
        time.sleep(30)


@dataclass(frozen=True)
class RetryFactory:
    trace: str
    fail_configure: bool = False
    synthetic: bool = True

    def open(self, source, limits, admission):
        return RetryBackend(source, self.trace, self.fail_configure)


class RetryBackend:
    def __init__(self, source, trace, fail_configure):
        self.source, self.trace, self.fail_configure = source, trace, fail_configure
        self.calls = 0

    def configure(self):
        if self.fail_configure:
            raise BackendFault("configure-fault", "synthetic-driver", -19)
        return canonical({"source_id": self.source.source_id, "source_plan_sha256": self.source.sha256,
                          "format": self.source.format, "synthetic": True, "device_access_occurred": False})

    def start(self):
        Path(self.trace + "-start").write_text("synthetic-start")

    def read(self, timeout_s):
        self.calls += 1
        if self.calls <= 2:
            return None
        if self.calls == 3:
            return audio_block(1)
        raise EndOfSource()

    def close(self):
        Path(self.trace + "-close").write_text("synthetic-close")


class LiveSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plan = synthetic_demo_plan()

    def tearDown(self):
        self.temp.cleanup()

    def run_audio(self, script, plan=None, cancellation=None):
        return LiveCaptureSupervisor().run(plan or self.plan, SyntheticBackendFactory((script,)),
                                            self.root / "journal", cancellation=cancellation)

    def test_spawned_short_reads_actual_payloads_null_time_and_no_process_leak(self):
        before = {p.pid for p in mp.active_children()}
        result = self.run_audio(SyntheticSourceScript("fake-audio", (audio_block(3), audio_block(1)), 0.02))
        self.assertTrue(result.finalized, result)
        self.assertEqual(result.reason, "source-exhausted")
        self.assertEqual(result.committed_chunks, 2)
        self.assertTrue(result.owned_workers_reaped)
        self.assertFalse(result.device_access_occurred)
        self.assertEqual({p.pid for p in mp.active_children()}, before)
        view = verify_live_journal(result.journal_path)
        self.assertEqual(view.positions, (("fake-audio", 4),))
        receipt = parse_canonical((Path(result.journal_path) / "receipt-000000001.json").read_bytes())
        self.assertEqual(receipt["position"], 3)
        self.assertIsNone(receipt["utc_start"])
        self.assertIsNone(receipt["physical_uncertainty_ns"])

    def test_retry_and_partial_configuration_cleanup(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                path = self.root / str(fail)
                trace = str(self.root / ("trace-" + str(fail)))
                result = LiveCaptureSupervisor().run(self.plan, RetryFactory(trace, fail), path)
                self.assertTrue(result.finalized)
                self.assertTrue(Path(trace + "-close").exists())
                self.assertEqual(result.committed_chunks, 0 if fail else 1)
                self.assertEqual(Path(trace + "-start").exists(), not fail)
                if fail:
                    self.assertEqual(result.reason, "configure-fault")
                    self.assertEqual(parse_canonical(result.final_json)["native_code"], -19)

    def test_driver_faults_stop_seal_and_keep_unknown_loss(self):
        for fault in ("xrun", "suspend", "disconnect", "sequence-ambiguity"):
            with self.subTest(fault=fault):
                factory = SyntheticBackendFactory((SyntheticSourceScript("fake-audio", (audio_block(),), 0.02, fault),))
                result = LiveCaptureSupervisor().run(self.plan, factory, self.root / fault)
                self.assertTrue(result.finalized)
                self.assertEqual(result.reason, fault)
                final = parse_canonical(result.final_json)
                self.assertIsNone(final["physical_loss_units"])
                self.assertIsNone(final["source_tail_units"]["fake-audio"])
                self.assertIsNone(final["application_discarded_chunks"])
                self.assertFalse(final["planned_acquisition_complete"])

    def test_audio_and_video_workers_wrap_without_sync_claim(self):
        source = video_source()
        plan = replace(self.plan, sources=(self.plan.sources[0], source))
        frames = tuple(CapturedBlockV1(bytes(range(8)), 1, canonical({"timestamp_domain": "UNKNOWN", "timestamp": None}), sequence)
                       for sequence in (2**32 - 1, 0))
        factory = SyntheticBackendFactory((SyntheticSourceScript("fake-audio", (audio_block(),), 0.03),
                                           SyntheticSourceScript("fake-video", frames, 0.03)))
        result = LiveCaptureSupervisor().run(plan, factory, self.root / "av")
        self.assertTrue(result.finalized)
        self.assertEqual(result.committed_chunks, 3)
        view = verify_live_journal(result.journal_path)
        self.assertEqual(dict(view.positions), {"fake-audio": 4, "fake-video": 2})
        self.assertIsNone(parse_canonical(view.final_json)["clock_relation"])

    def test_video_gap_seals_prefix_without_invented_loss(self):
        source = video_source()
        plan = replace(self.plan, sources=(source,))
        frames = tuple(CapturedBlockV1(bytes(8), 1, canonical({}), sequence) for sequence in (8, 10))
        result = LiveCaptureSupervisor().run(plan, SyntheticBackendFactory((SyntheticSourceScript("fake-video", frames, 0.03),)), self.root / "gap")
        self.assertTrue(result.finalized)
        self.assertEqual(result.committed_chunks, 1)
        self.assertIn("sequence discontinuity", result.reason)
        self.assertIsNone(parse_canonical(result.final_json)["physical_loss_units"])

    def test_queue_pressure_stops_without_eviction(self):
        plan = replace(self.plan, limits=replace(self.plan.limits, queue_chunks=1, source_queue_bytes=64, queue_bytes=64))
        result = self.run_audio(SyntheticSourceScript("fake-audio", tuple(audio_block(32) for _ in range(100))), plan)
        self.assertTrue(result.finalized)
        self.assertIn(result.reason, ("queue-byte-budget", "queue-item-budget"))
        self.assertEqual(parse_canonical(result.final_json)["observed_queue_rejected_chunks"], 1)
        self.assertLess(result.committed_chunks, 100)
        self.assertEqual(len(list((self.root / "journal").glob("payload-*.bin"))), result.committed_chunks)
        self.assertIsNone(parse_canonical(result.final_json)["physical_loss_units"])

    def test_explicit_cancellation_closes_zero_frame_prefix(self):
        cancel = threading.Event()
        cancel.set()
        result = self.run_audio(SyntheticSourceScript("fake-audio", (audio_block(),)), cancellation=cancel)
        self.assertTrue(result.finalized)
        self.assertEqual(result.reason, "cancelled")
        self.assertEqual(result.committed_chunks, 0)
        self.assertFalse((self.root / "journal" / "start-request.json").exists())

    def test_uncooperative_source_has_bounded_shutdown_and_owned_reaping(self):
        plan = replace(self.plan, limits=replace(self.plan.limits, duration_s=0.8, shutdown_timeout_s=0.4))
        start = time.monotonic()
        result = self.run_audio(SyntheticSourceScript("fake-audio", (audio_block(),), stall_s=30), plan)
        self.assertLess(time.monotonic() - start, 5)
        self.assertTrue(result.owned_workers_reaped)
        self.assertTrue(result.finalized)
        self.assertEqual(result.reason, "shutdown-deadline")
        self.assertEqual(result.committed_chunks, 0)

    def test_stalled_writer_deadline_retains_orphan_for_file_only_recovery(self):
        plan = replace(self.plan, limits=replace(self.plan.limits, shutdown_timeout_s=0.5))
        journal = StalledJournal.create(self.root / "stalled-writer", plan)
        start = time.monotonic()
        result = LiveCaptureSupervisor().run(plan, SyntheticBackendFactory((SyntheticSourceScript("fake-audio", (audio_block(),), 0.03),)), journal)
        self.assertLess(time.monotonic() - start, 5)
        self.assertFalse(result.finalized)
        self.assertTrue(result.owned_workers_reaped)
        self.assertIn("writer-deadline", result.reason)
        recovered = LiveJournal.recover(journal.path)
        self.assertEqual(recovered.committed_chunks, 0)
        self.assertIn("payload-000000000.bin", recovered.orphan_names)
        self.assertTrue(recovered.closed)

    def test_output_limit_seals_without_rearm(self):
        plan = replace(self.plan, limits=replace(self.plan.limits, max_chunks=1))
        result = self.run_audio(SyntheticSourceScript("fake-audio", (audio_block(), audio_block()), 0.03), plan)
        self.assertTrue(result.finalized)
        self.assertEqual(result.committed_chunks, 1)
        self.assertIn("budget", result.reason)

    def test_cli_synthetic_demo_is_actual_owned_subprocess(self):
        completed = subprocess.run([sys.executable, "-m", "poseidon_acoustic.live_capture_cli", "synthetic-demo",
                                    "--output-dir", str(self.root / "cli-demo")],
                                   capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        output = parse_canonical(completed.stdout)
        self.assertEqual(output["committed_chunks"], 3)
        self.assertTrue(output["synthetic"])
        self.assertFalse(output["device_access_occurred"])


if __name__ == "__main__":
    unittest.main()
