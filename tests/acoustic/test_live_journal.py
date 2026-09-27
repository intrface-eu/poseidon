from dataclasses import replace
import multiprocessing as mp
import os
from pathlib import Path
import pickle
import stat
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from poseidon_acoustic.live_capture_cli import synthetic_demo_plan
from poseidon_acoustic.live_journal import JournalFault, LiveJournal, verify_live_journal
from poseidon_acoustic.live_models import CapturedBlockV1, canonical, parse_canonical


def configured(path, plan=None):
    plan = plan or synthetic_demo_plan()
    journal = LiveJournal.create(path, plan)
    for source in plan.sources:
        journal.record_configuration(source.source_id, canonical({
            "source_id": source.source_id, "source_plan_sha256": source.sha256, "format": source.format,
            "synthetic": True, "device_access_occurred": False}))
    journal.record_start_request()
    for source in plan.sources:
        journal.record_started(source.source_id, 42)
    return journal


def block(units=3, **raw):
    return CapturedBlockV1(b"\x01\x02" * units, units, canonical(raw))


def crash_after_publication(path, point):
    from poseidon_acoustic import live_journal as module
    journal = configured(path)
    original = module._publish
    def publication(directory, name, data):
        original(directory, name, data)
        if name.startswith(point):
            os._exit(23)
    module._publish = publication
    journal.append_payload("fake-audio", block())
    journal.finalize("interrupted-fixture")


class LiveJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "journal"

    def tearDown(self):
        self.temp.cleanup()

    def test_configuration_before_start_and_no_overwrite(self):
        journal = LiveJournal.create(self.path, synthetic_demo_plan())
        with self.assertRaises(JournalFault):
            journal.record_start_request()
        with self.assertRaises(JournalFault):
            journal.append_payload("fake-audio", block())
        with self.assertRaises(FileExistsError):
            LiveJournal.create(self.path, synthetic_demo_plan())

    def test_incremental_append_one_finalize_scan_short_reads_nulls(self):
        journal = configured(self.path)
        with mock.patch("poseidon_acoustic.live_journal.verify_live_journal", side_effect=AssertionError("runtime scan")):
            first = journal.append_payload("fake-audio", block(3, timestamp=None, driver_accuracy_ns=None))
            second = journal.append_payload("fake-audio", block(1, timestamp=None, driver_accuracy_ns=0))
        record = parse_canonical(second.canonical_bytes)
        self.assertEqual(record["position"], 3)
        self.assertEqual(record["previous_receipt_sha256"], first.receipt_sha256)
        self.assertEqual(record["raw"]["driver_accuracy_ns"], 0)
        for key in ("utc_start", "utc_end", "physical_uncertainty_ns", "clock_relation", "physical_loss_units", "exposure_end"):
            self.assertIsNone(record[key])
        self.assertFalse(record["device_access_occurred"])
        view = journal.finalize("controlled-stop")
        self.assertEqual(journal.integrity_scans, 1)
        self.assertEqual(view.positions, (("fake-audio", 4),))
        self.assertTrue(view.closed)
        self.assertEqual(verify_live_journal(self.path), view)
        self.assertFalse(parse_canonical(view.final_json)["planned_acquisition_complete"])

    def test_repeated_and_absent_timestamp_claims_not_interpolated(self):
        journal = configured(self.path)
        for timestamp in (None, 7, 7, None):
            receipt = journal.append_payload("fake-audio", block(timestamp=timestamp, clock_domain="raw-host"))
            self.assertEqual(parse_canonical(receipt.canonical_bytes)["raw"]["timestamp"], timestamp)
        self.assertEqual(journal.finalize("fixture").committed_chunks, 4)

    def test_clock_reset_stops_without_guessing(self):
        journal = configured(self.path)
        journal.append_payload("fake-audio", block(clock_domain="monotonic", clock_generation=1))
        with self.assertRaisesRegex(JournalFault, "clock"):
            journal.append_payload("fake-audio", block(clock_domain="monotonic", clock_generation=2))
        with self.assertRaises(JournalFault):
            journal.append_payload("fake-audio", block(clock_domain="monotonic", clock_generation=1))
        view = journal.finalize("clock-discontinuity")
        self.assertEqual(view.committed_chunks, 1)
        self.assertIsNone(parse_canonical(view.final_json)["physical_loss_units"])

    def test_frame_byte_mismatch_does_not_commit(self):
        journal = configured(self.path)
        with self.assertRaises(JournalFault):
            journal.append_payload("fake-audio", CapturedBlockV1(b"123", 1, canonical({})))
        self.assertEqual(journal.finalize("bad-return").committed_chunks, 0)

    def test_payload_orphan_is_retained_not_adopted(self):
        from poseidon_acoustic import live_journal as module
        journal = configured(self.path)
        original = module._publish
        def fail_receipt(path, name, data):
            if name.startswith("receipt-"):
                raise OSError("injected storage failure")
            return original(path, name, data)
        with mock.patch.object(module, "_publish", side_effect=fail_receipt):
            with self.assertRaises(OSError):
                journal.append_payload("fake-audio", block())
        with self.assertRaisesRegex(JournalFault, "active owner"):
            LiveJournal.recover(self.path)
        journal.close_owner()
        view = LiveJournal.recover(self.path)
        self.assertEqual(view.committed_chunks, 0)
        self.assertIn("payload-000000000.bin", view.orphan_names)
        self.assertEqual((self.path / "payload-000000000.bin").read_bytes(), block().payload)
        self.assertEqual(LiveJournal.recover(self.path), view)

    def test_checksum_tamper_retains_only_verified_prefix(self):
        journal = configured(self.path)
        journal.append_payload("fake-audio", block())
        journal.append_payload("fake-audio", block())
        (self.path / "payload-000000001.bin").write_bytes(b"xxxxxx")
        view = journal.finalize("tamper-found")
        self.assertEqual(view.committed_chunks, 1)
        self.assertIn("integrity", view.integrity_error)
        self.assertIn("receipt-000000001.json", view.orphan_names)
        self.assertEqual(verify_live_journal(self.path).committed_chunks, 1)

    def test_missing_receipt_and_unknown_files_preserved(self):
        journal = configured(self.path)
        for _ in range(3):
            journal.append_payload("fake-audio", block())
        (self.path / "receipt-000000001.json").unlink()
        (self.path / ".pending-fixture").write_bytes(b"retained-partial")
        with self.assertRaisesRegex(JournalFault, "active owner"):
            LiveJournal.recover(self.path)
        journal.close_owner()
        view = LiveJournal.recover(self.path)
        self.assertEqual(view.committed_chunks, 1)
        self.assertIn("missing receipt", view.integrity_error)
        self.assertIn(".pending-fixture", view.orphan_names)
        self.assertTrue((self.path / "receipt-000000002.json").exists())

    def test_chunk_count_and_output_reserve_stop_without_eviction(self):
        plan = synthetic_demo_plan()
        plan = replace(plan, limits=replace(plan.limits, max_chunks=1))
        journal = configured(self.path, plan)
        journal.append_payload("fake-audio", block())
        before = (self.path / "payload-000000000.bin").read_bytes()
        with self.assertRaisesRegex(JournalFault, "budget"):
            journal.append_payload("fake-audio", block())
        self.assertTrue((self.path / ".reserve").exists())
        view = journal.finalize("budget")
        self.assertTrue(view.closed)
        self.assertFalse((self.path / ".reserve").exists())
        self.assertEqual((self.path / "payload-000000000.bin").read_bytes(), before)

    def test_full_storage_budget_preserves_final_capacity(self):
        journal = configured(self.path)
        journal.used_bytes = journal.plan.limits.output_bytes - journal.plan.limits.reserve_bytes
        with self.assertRaisesRegex(JournalFault, "budget"):
            journal.append_payload("fake-audio", block())
        self.assertTrue(journal.finalize("storage-exhaustion").closed)

    def test_symlink_payload_is_not_followed(self):
        journal = configured(self.path)
        journal.append_payload("fake-audio", block())
        payload = self.path / "payload-000000000.bin"
        payload.unlink()
        payload.symlink_to(Path(self.temp.name) / "outside")
        view = journal.finalize("symlink")
        self.assertEqual(view.committed_chunks, 0)
        self.assertIsNotNone(view.integrity_error)

    def test_real_process_interruptions_payload_receipt_final(self):
        for point, count in (("payload-", 0), ("receipt-", 1), ("final.json", 1)):
            with self.subTest(point=point):
                path = Path(self.temp.name) / point.replace(".", "-")
                process = mp.get_context("spawn").Process(target=crash_after_publication, args=(path, point))
                try:
                    process.start()
                    process.join(5)
                    self.assertFalse(process.is_alive())
                    self.assertEqual(process.exitcode, 23)
                    view = LiveJournal.recover(path)
                    self.assertEqual(view.committed_chunks, count)
                    self.assertTrue(view.closed)
                    if point == "payload-":
                        self.assertIn("payload-000000000.bin", view.orphan_names)
                finally:
                    if process.is_alive():
                        process.kill()
                        process.join(2)
                    process.close()

    def test_final_inventory_and_claim_tampering_is_not_a_valid_seal(self):
        journal = configured(self.path)
        journal.append_payload("fake-audio", block())
        journal.finalize("controlled-stop")
        final_path = self.path / "final.json"
        original = final_path.read_bytes()
        final = parse_canonical(original)
        final["physical_uncertainty_ns"] = 0
        final_path.write_bytes(canonical(final))
        self.assertFalse(verify_live_journal(self.path).closed)
        final_path.write_bytes(original)
        (self.path / "post-final-artifact").write_bytes(b"unexpected")
        view = verify_live_journal(self.path)
        self.assertFalse(view.closed)
        self.assertIn("post-final-artifact", view.orphan_names)
        self.assertIsNotNone(view.integrity_error)

    def test_receipt_boolean_index_is_not_an_integer(self):
        journal = configured(self.path)
        journal.append_payload("fake-audio", block())
        path = self.path / "receipt-000000000.json"
        record = parse_canonical(path.read_bytes())
        record["index"] = False
        path.write_bytes(canonical(record))
        view = verify_live_journal(self.path)
        self.assertEqual(view.committed_chunks, 0)
        self.assertIsNotNone(view.integrity_error)

    def test_nonregular_artifact_metadata_refused_before_any_open(self):
        from poseidon_acoustic.live_journal import _read
        for mode in (stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFLNK):
            with self.subTest(mode=mode), \
                 mock.patch("poseidon_acoustic.live_journal.os.lstat", return_value=SimpleNamespace(st_mode=mode, st_size=0)), \
                 mock.patch("poseidon_acoustic.live_journal.os.open") as opening:
                with self.assertRaisesRegex(JournalFault, "before open"):
                    _read(self.path, "intent.json", 65536)
                opening.assert_not_called()

    def test_unknown_reserve_replacements_are_never_consumed_or_deleted(self):
        for kind in ("content", "size", "symlink", "dangling"):
            with self.subTest(kind=kind):
                path = Path(self.temp.name) / ("reserve-" + kind)
                journal = configured(path)
                reserve = path / ".reserve"
                reserve.unlink()
                if kind == "content":
                    reserve.write_bytes(b"x" * journal.plan.limits.reserve_bytes)
                elif kind == "size":
                    reserve.write_bytes(b"unknown evidence")
                elif kind == "symlink":
                    target = Path(self.temp.name) / "external-zero-file"
                    target.write_bytes(bytes(journal.plan.limits.reserve_bytes))
                    reserve.symlink_to(target)
                else:
                    reserve.symlink_to(Path(self.temp.name) / "absent-target")
                before = os.lstat(reserve)
                with self.assertRaisesRegex(JournalFault, "active owner"):
                    LiveJournal.recover(path)
                journal.close_owner()
                for operation in (verify_live_journal, LiveJournal.recover):
                    with self.assertRaisesRegex(JournalFault, "reserve"):
                        operation(path)
                    after = os.lstat(reserve)
                    self.assertEqual((before.st_ino, before.st_mode, before.st_size),
                                     (after.st_ino, after.st_mode, after.st_size))
                    self.assertFalse((path / "final.json").exists())
                if kind == "content":
                    self.assertEqual(reserve.read_bytes(), b"x" * journal.plan.limits.reserve_bytes)

    def test_reserve_replacement_after_scan_is_retained_at_seal(self):
        journal = configured(self.path)
        reserve = self.path / ".reserve"
        def scan_then_replace(path):
            view = verify_live_journal(path)
            reserve.write_bytes(b"not the reserved zero artifact")
            return view
        with mock.patch("poseidon_acoustic.live_journal.verify_live_journal", side_effect=scan_then_replace):
            with self.assertRaisesRegex(JournalFault, "reserve"):
                journal.finalize("fixture")
        self.assertEqual(reserve.read_bytes(), b"not the reserved zero artifact")
        self.assertFalse((self.path / "final.json").exists())

    def test_recovery_locks_before_scanning_and_releases_stopped_prefix(self):
        journal = configured(self.path)
        journal.append_payload("fake-audio", block())
        with mock.patch("poseidon_acoustic.live_journal.verify_live_journal") as scan:
            with self.assertRaisesRegex(JournalFault, "active owner"):
                LiveJournal.recover(self.path)
            scan.assert_not_called()
        journal.close_owner()
        view = LiveJournal.recover(self.path)
        self.assertTrue(view.closed)
        self.assertEqual(view.committed_chunks, 1)
        before = {p.name: p.read_bytes() for p in self.path.iterdir()}
        for operation in (lambda: journal.append_payload("fake-audio", block()),
                          lambda: journal.finalize("stale")):
            with self.assertRaises(JournalFault):
                operation()
        self.assertEqual({p.name: p.read_bytes() for p in self.path.iterdir()}, before)

    def test_owner_lock_cannot_be_pickled_outside_actual_spawn(self):
        journal = configured(self.path)
        with self.assertRaisesRegex(JournalFault, "process spawn"):
            pickle.dumps(journal)
        self.assertFalse(journal._transferred)
        self.assertEqual(journal.append_payload("fake-audio", block()).index, 0)

    def test_failed_descriptor_transfer_burns_mutation_but_keeps_passive_lease(self):
        journal = configured(self.path)
        with mock.patch("multiprocessing.context.get_spawning_popen", return_value=object()), \
             mock.patch("multiprocessing.reduction.DupFd", side_effect=OSError("injected fd reduction failure")):
            with self.assertRaises(OSError):
                journal.__getstate__()
        self.assertTrue(journal._transferred)
        with self.assertRaisesRegex(JournalFault, "active owner"):
            LiveJournal.recover(self.path)
        with self.assertRaisesRegex(JournalFault, "transferred"):
            journal.append_payload("fake-audio", block())
        journal.close_owner()
        self.assertTrue(LiveJournal.recover(self.path).closed)

    def test_replaced_directory_or_lock_rejects_stale_writer(self):
        for artifact in ("directory", "lock"):
            with self.subTest(artifact=artifact):
                path = Path(self.temp.name) / artifact
                journal = configured(path)
                if artifact == "directory":
                    path.rename(Path(self.temp.name) / "old-directory")
                    replacement = LiveJournal.create(path, journal.plan)
                    self.addCleanup(replacement.close_owner)
                else:
                    (path / ".owner.lock").rename(Path(self.temp.name) / "old-lock")
                    (path / ".owner.lock").touch()
                with self.assertRaisesRegex(JournalFault, "replaced"):
                    journal.append_payload("fake-audio", block())
                with self.assertRaisesRegex(JournalFault, "replaced"):
                    journal.finalize("stale")
                journal.close_owner()

    def test_recovery_rechecks_lock_and_directory_after_scan(self):
        for artifact in ("directory", "lock"):
            with self.subTest(artifact=artifact):
                path = Path(self.temp.name) / ("scan-" + artifact)
                journal = configured(path)
                journal.close_owner()

                def scan_then_replace(selected):
                    view = verify_live_journal(selected)
                    if artifact == "directory":
                        selected.rename(Path(self.temp.name) / "replaced-scanned-directory")
                        selected.mkdir()
                        (selected / ".owner.lock").touch()
                    else:
                        (selected / ".owner.lock").rename(Path(self.temp.name) / "replaced-scanned-lock")
                        (selected / ".owner.lock").touch()
                    return view

                with mock.patch("poseidon_acoustic.live_journal.verify_live_journal", side_effect=scan_then_replace):
                    with self.assertRaisesRegex(JournalFault, "replaced"):
                        LiveJournal.recover(path)
                self.assertFalse((path / "final.json").exists())

    def test_nonregular_owner_lock_refused_before_open(self):
        from poseidon_acoustic.live_journal import _open_owner
        journal = configured(self.path)
        journal.close_owner()
        lock = self.path / ".owner.lock"
        lock.unlink()
        target = Path(self.temp.name) / "other"
        target.touch()
        lock.symlink_to(target)
        with mock.patch("poseidon_acoustic.live_journal.os.open") as opening:
            with self.assertRaisesRegex(JournalFault, "before open"):
                _open_owner(self.path)
            opening.assert_not_called()
        self.assertTrue(lock.is_symlink())

    def test_synthetic_configuration_claim_rejected(self):
        journal = LiveJournal.create(self.path, synthetic_demo_plan())
        source = journal.plan.sources[0]
        with self.assertRaises(JournalFault):
            journal.record_configuration(source.source_id, canonical({"source_id": source.source_id,
                "source_plan_sha256": source.sha256, "format": source.format,
                "synthetic": True, "device_access_occurred": True}))


if __name__ == "__main__":
    unittest.main()
