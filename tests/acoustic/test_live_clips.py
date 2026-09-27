"""Synthetic file fixtures only. No native backend, device, service or subprocess."""
from dataclasses import fields, replace
import math
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest import mock
import wave

from poseidon_acoustic import live_clips as clips
from poseidon_acoustic.detector import DetectorConfig, detect_wav
from poseidon_acoustic.live_capture_cli import synthetic_demo_plan
from poseidon_acoustic.live_clips import (
    ClipLimits, LiveClipError, LiveClipPublicationUncertain, detect_live_journal, extract_live_clips,
)
from poseidon_acoustic.live_journal import LiveJournal, verify_live_journal
from poseidon_acoustic.live_models import CapturedBlockV1, SourcePlanV1, canonical, digest, parse_canonical

from _support import manifest_for, write_pcm16_wav


def pcm(frames):
    return b"".join(struct.pack("<" + "h" * len(frame), *frame) for frame in frames)


def bump_times(path):
    """Push a file's inode timestamps forward so a same-length rewrite is visible to stat().

    Coarse inode timestamps on Linux ext4 can leave the stat identity (size, mtime_ns,
    ctime_ns) unchanged after a same-length rewrite inside one kernel tick. The tests below
    assert that a timestamp-visible rewrite is detected on every platform; a content change
    that stat cannot see is still refused by the hash recheck before any manifest is written
    (see test_hash_recheck_refuses_mismatched_read_bytes_even_if_stats_same).
    """
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns + 1_000_000, st.st_mtime_ns + 1_000_000))


class LiveClipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "journal"
        self.output = self.root / "clips"
        self.config = DetectorConfig(threshold=0.2, window_ms=4)

    def fixture(self, chunks=None, *, channels=1, video=False, seal=True, path=None,
                sequences=None, raws=None, orphan=None, capture_id="clip-synthetic"):
        chunks = chunks if chunks is not None else [[(20_000,)] * 8]
        base = synthetic_demo_plan()
        source = replace(base.sources[0], sample_rate_hz=1000,
                         channels=tuple(f"synthetic-{i}" for i in range(channels)),
                         channel_roles=tuple(f"fixture-{i}" for i in range(channels)))
        sources = (source,)
        if video:
            sources += (SourcePlanV1("fake-video", "video", "synthetic", None, canonical({}), (), (), None,
                                     2, 2, 25, 1, None, None, None, None, None, None, None, "synthetic"),)
        plan = replace(base, capture_id=capture_id, sources=sources,
                       limits=replace(base.limits, chunk_frames=512, max_chunk_bytes=8192,
                                      source_queue_bytes=8192, queue_bytes=8192, max_chunks=1024,
                                      output_bytes=4 * 1024 * 1024))
        journal = LiveJournal.create(path or self.path, plan)
        self.addCleanup(journal.close_owner)
        for item in plan.sources:
            journal.record_configuration(item.source_id, canonical({
                "source_id": item.source_id, "source_plan_sha256": item.sha256, "format": item.format,
                "synthetic": True, "device_access_occurred": False}))
        journal.record_start_request()
        for item in plan.sources:
            journal.record_started(item.source_id, 42)
        for index, frames in enumerate(chunks):
            raw = {"clock_domain": "synthetic", "clock_generation": None,
                   "timestamp_type": "unknown", "timestamp": None, "driver_accuracy_ns": 0}
            if raws is not None:
                raw.update(raws[index])
            journal.append_payload(source.source_id, CapturedBlockV1(
                pcm(frames), len(frames), canonical(raw), None if sequences is None else sequences[index]))
            if video:
                journal.append_payload("fake-video", CapturedBlockV1(bytes(range(8)), 1,
                                       canonical({"clock_domain": "video-unknown", "timestamp": 7}), index))
        if orphan:
            for name, data in orphan.items():
                (journal.path / name).write_bytes(data)
        if seal:
            self.assertIsNone(journal.finalize("synthetic-test-stop").integrity_error)
        return journal

    def extract(self, **kwargs):
        return extract_live_clips(self.path, self.output, "fake-audio", self.config, **kwargs)

    def detect(self, **kwargs):
        return detect_live_journal(self.path, "fake-audio", self.config, **kwargs)

    def inventory(self):
        return {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
                for p in self.path.iterdir()}

    def document(self, result):
        return parse_canonical(result.manifest_json, maximum=1024 * 1024)

    def test_exact_stereo_pcm_hashes_spans_and_null_clocks(self):
        frames = [(0, 0)] * 4 + [(20_000, -20_000)] * 8 + [(0, 0)] * 4
        self.fixture([frames[:3], frames[3:9], frames[9:]], channels=2, video=True)
        before = self.inventory()
        result = self.extract(pre_frames=2, post_frames=2)
        doc = self.document(result)
        self.assertEqual(self.inventory(), before)
        self.assertEqual(result.manifest_sha256, digest((self.output / "manifest.json").read_bytes()))
        self.assertEqual(doc["selected_event_count"], 1)
        clip = doc["clips"][0]
        self.assertEqual((clip["event"]["start_frame"], clip["event"]["end_frame"]), (4, 12))
        self.assertEqual((clip["source_start_frame"], clip["source_end_frame"]), (2, 14))
        expected = pcm(frames[2:14])
        wav = (self.output / clip["wav_name"]).read_bytes()
        self.assertEqual(wav[44:], expected)
        self.assertEqual(len(wav), len(expected) + 44)
        self.assertEqual(clip["wav_sha256"], digest(wav))
        self.assertEqual(clip["pcm_sha256"], digest(expected))
        with wave.open(str(self.output / clip["wav_name"]), "rb") as reader:
            self.assertEqual((reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getnframes()),
                             (2, 2, 1000, 12))
            self.assertEqual(reader.readframes(12), expected)
        self.assertEqual([s["receipt_index"] for s in clip["segments"]], [0, 2, 4])
        self.assertEqual([(s["clip_frame_start"], s["clip_frame_end"]) for s in clip["segments"]],
                         [(0, 1), (1, 7), (7, 12)])
        for segment in clip["segments"]:
            receipt_bytes = (self.path / segment["receipt_name"]).read_bytes()
            payload = (self.path / segment["payload_name"]).read_bytes()
            receipt = parse_canonical(receipt_bytes)
            self.assertEqual(segment["receipt_sha256"], digest(receipt_bytes))
            self.assertEqual(segment["payload_sha256"], digest(payload))
            self.assertEqual(segment["configuration_sha256"], receipt["configuration_sha256"])
            self.assertEqual(segment["copied_pcm_sha256"], digest(payload[segment["payload_byte_start"]:segment["payload_byte_end"]]))
            self.assertEqual(segment["raw"]["driver_accuracy_ns"], 0)
            for key in ("utc_start", "utc_end", "physical_uncertainty_ns", "clock_relation", "exposure_start", "exposure_end"):
                self.assertIsNone(segment[key])
        for key in ("utc_start", "utc_end", "physical_uncertainty_ns", "clock_relation"):
            self.assertIsNone(doc[key])
            self.assertIsNone(getattr(result.detection, key))
        for name, checksum in doc["journal_artifact_sha256"].items():
            self.assertEqual(checksum, digest((self.path / name).read_bytes()))
        self.assertEqual(doc["channels"], ["synthetic-0", "synthetic-1"])
        self.assertEqual(doc["channel_roles"], ["fixture-0", "fixture-1"])
        self.assertFalse(doc["extraction_device_access_occurred"])
        self.assertFalse(doc["emission_enabled"])
        self.assertEqual(doc["provenance"], "synthetic")
        self.assertNotIn("recording_id", doc)
        self.assertNotIn("site_id", doc)

    def test_detector_parity_with_independent_synthetic_replay_vectors(self):
        # Both fixtures are built from these synthetic vectors independently.
        # No live journal is assigned a RecordingManifest or invented UTC.
        cases = [([(0,)] * 20, 1),
                 ([(0,)] * 4 + [(20_000,)] * 9, 1),
                 ([(-32768, 32767)] * 8 + [(0, 0)] * 4 + [(0, 24000)] * 3, 2),
                 ([(0,)] * 4 + [(20_000,)] * 8 + [(0,)] * 8 + [(-22000,)] * 4, 1)]
        for i, (frames, channel_count) in enumerate(cases):
            with self.subTest(i=i):
                path = self.root / f"parity-{i}"
                self.fixture([frames[:3], frames[3:10], frames[10:]], channels=channel_count, path=path)
                local = detect_live_journal(path, "fake-audio", self.config)
                replay = self.root / f"independent-synthetic-{i}.wav"
                write_pcm16_wav(replay, frames, channels=channel_count)
                reference = detect_wav(replay, manifest_for(replay), self.config)
                actual = [(e.start_frame, e.end_frame, e.normalized_peak_max, e.normalized_rms_max) for e in local.events]
                expected = [(e.start_frame, e.end_frame, e.normalized_peak_max, e.normalized_rms_max) for e in reference.events]
                self.assertEqual(actual, expected)
                self.assertNotEqual(local.run_id, reference.run_id)
                self.assertNotEqual(local.detector_config_id, reference.detector_config_id)

    def test_detector_window_rounding_and_threshold_equality(self):
        self.fixture([[(16384,)] * 5])
        result = detect_live_journal(self.path, "fake-audio", DetectorConfig(threshold=0.5, window_ms=2.5))
        self.assertEqual([(e.start_frame, e.end_frame) for e in result.events], [(0, 5)])
        self.assertEqual(result.events[0].normalized_rms_max, 0.5)
        self.assertEqual(parse_canonical(result.detector_config_json)["window_frames"], 2)

    def test_determinism_and_source_bound_event_selection(self):
        self.fixture([[(20000,)] * 4 + [(0,)] * 4 + [(21000,)] * 4])
        result = self.detect()
        self.assertEqual(result, self.detect())
        event = result.events[1]
        extracted = self.extract(event_ids=(event.event_id,))
        doc = self.document(extracted)
        self.assertEqual(doc["detected_event_count"], 2)
        self.assertEqual(doc["selected_event_count"], 1)
        self.assertEqual(doc["clips"][0]["event"]["event_id"], event.event_id)
        expected_run = "liverun_" + digest(canonical({
            "journal_intent_sha256": doc["journal_intent_sha256"], "journal_final_sha256": doc["journal_final_sha256"],
            "source_id": "fake-audio", "source_plan_sha256": doc["source_plan_sha256"],
            "detector_config_id": doc["detector_config_id"]}))
        self.assertEqual(result.run_id, expected_run)
        self.assertEqual(event.event_id, "liveevt_" + digest(canonical({
            "run_id": expected_run, "source_id": "fake-audio", "start_frame": 8, "end_frame": 12})))

    def test_foreign_journal_config_and_forged_event_ids_refused(self):
        self.fixture()
        original = self.detect()
        other = self.fixture(path=self.root / "foreign", capture_id="other-synthetic")
        foreign = detect_live_journal(other.path, "fake-audio", self.config)
        changed = detect_live_journal(self.path, "fake-audio", DetectorConfig(threshold=0.3, window_ms=4))
        for event_id in (foreign.events[0].event_id, changed.events[0].event_id, "liveevt_" + "0" * 64):
            with self.subTest(event=event_id), self.assertRaisesRegex(LiveClipError, "does not belong"):
                self.extract(event_ids=(event_id,))
        self.assertFalse(self.output.exists())
        final = parse_canonical((self.path / "final.json").read_bytes())
        final["reason"] = "different-valid-stop"
        (self.path / "final.json").write_bytes(canonical(final))
        self.assertTrue(verify_live_journal(self.path).closed)
        with self.assertRaisesRegex(LiveClipError, "does not belong"):
            self.extract(event_ids=(original.events[0].event_id,))

    def test_recovered_prefix_preserves_orphans_tails_and_window_clipping(self):
        journal = self.fixture(seal=False, orphan={"payload-000000001.bin": pcm([(32767,)] * 8),
                                                  ".pending-synthetic": b"partial-synthetic"})
        journal.close_owner()
        recovered = LiveJournal.recover(self.path)
        self.assertTrue(recovered.closed)
        self.assertIsNone(recovered.integrity_error)
        before = self.inventory()
        result = self.extract(pre_frames=5, post_frames=7)
        doc = self.document(result)
        clip = doc["clips"][0]
        self.assertEqual(self.inventory(), before)
        self.assertEqual(clip["frame_count"], 8)
        self.assertEqual(clip["pre_window_clipped_frames"], 5)
        self.assertEqual(clip["post_window_clipped_frames"], 7)
        self.assertEqual(clip["included_pre_frames"], 0)
        self.assertEqual(clip["included_post_frames"], 0)
        self.assertEqual(doc["journal_final"]["reason"], "recovery-incomplete")
        self.assertEqual(doc["journal_final"], parse_canonical(recovered.final_json))
        self.assertEqual(doc["orphan_names"], [".pending-synthetic", "payload-000000001.bin"])
        self.assertFalse(doc["orphan_bytes_adopted"])
        self.assertFalse(doc["journal_final"]["planned_acquisition_complete"])
        self.assertIsNone(doc["journal_final"]["physical_loss_units"])
        self.assertEqual(doc["journal_final"]["source_tail_units"], {"fake-audio": None})
        self.assertEqual((self.output / clip["wav_name"]).read_bytes()[44:], pcm([(20000,)] * 8))

    def test_unsealed_refuses_without_recovery_or_writer_ownership(self):
        self.fixture(seal=False)
        before = self.inventory()
        with mock.patch.object(LiveJournal, "recover", side_effect=AssertionError("recovery forbidden")), \
             mock.patch("poseidon_acoustic.live_journal._open_owner", side_effect=AssertionError("ownership forbidden")):
            with self.assertRaisesRegex(LiveClipError, "sealed or recovered"):
                self.extract()
        self.assertEqual(self.inventory(), before)
        self.assertFalse(self.output.exists())

    def test_sealed_reader_does_not_acquire_held_writer_lock_or_call_replay(self):
        import fcntl
        self.fixture()
        with (self.path / ".owner.lock").open("rb") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with mock.patch.object(LiveJournal, "recover", side_effect=AssertionError("recovery forbidden")), \
                 mock.patch("poseidon_acoustic.live_journal._open_owner", side_effect=AssertionError("ownership forbidden")), \
                 mock.patch("poseidon_acoustic.detector.detect_wav", side_effect=AssertionError("replay forbidden")):
                self.assertEqual(self.detect().frame_count, 8)
                self.extract()

    def test_all_source_integrity_checked_even_when_video_not_selected(self):
        self.fixture(video=True)
        (self.path / "payload-000000001.bin").write_bytes(b"changed!")
        with self.assertRaisesRegex(LiveClipError, "receipt"):
            self.extract()
        self.assertFalse(self.output.exists())

    def test_corrupt_recovered_prefix_is_never_accepted(self):
        journal = self.fixture([[(20000,)] * 4, [(20000,)] * 4], seal=False)
        (self.path / "payload-000000001.bin").write_bytes(b"changed!")
        journal.close_owner()
        recovered = LiveJournal.recover(self.path)
        self.assertIsNotNone(recovered.integrity_error)
        with self.assertRaisesRegex(LiveClipError, "integrity error"):
            self.extract()
        self.assertFalse(self.output.exists())

    def test_payload_missing_changed_or_truncated_refused(self):
        self.fixture()
        path = self.path / "payload-000000000.bin"
        original = path.read_bytes()
        for mutation in (None, b"x" * len(original), original[:-1]):
            with self.subTest(mutation=mutation):
                if mutation is None:
                    path.unlink()
                else:
                    path.write_bytes(mutation)
                with self.assertRaises(LiveClipError):
                    self.extract()
                path.write_bytes(original)
        self.assertFalse(self.output.exists())

    def test_metadata_binding_and_claim_tampering_refused(self):
        self.fixture()
        mutations = [
            ("receipt-000000000.json", "index", False),
            ("receipt-000000000.json", "position", 1),
            ("receipt-000000000.json", "source_id", "foreign"),
            ("receipt-000000000.json", "payload_sha256", "0" * 64),
            ("config-fake-audio.json", "device_access_occurred", True),
            ("intent.json", "utc_start", "2026-01-01T00:00:00Z"),
            ("final.json", "physical_uncertainty_ns", 0),
            ("final.json", "planned_acquisition_complete", True),
            ("final.json", "committed_chunks", True),
            ("final.json", "orphan_count", False),
            ("final.json", "clock_relation", {}),
        ]
        for name, key, value in mutations:
            with self.subTest(name=name, key=key):
                path = self.path / name
                original = path.read_bytes()
                document = parse_canonical(original)
                document[key] = value
                path.write_bytes(canonical(document))
                with self.assertRaises(LiveClipError):
                    self.extract()
                path.write_bytes(original)
        self.assertFalse(self.output.exists())

    def test_sequence_wrap_valid_but_coherently_rehashed_gap_refused(self):
        self.fixture([[(20000,)] * 4, [(20000,)] * 4], sequences=(2**32 - 1, 0))
        self.assertEqual(self.detect().frame_count, 8)
        receipt_path = self.path / "receipt-000000001.json"
        record = parse_canonical(receipt_path.read_bytes())
        record["sequence"] = 1
        receipt_path.write_bytes(canonical(record))
        final_path = self.path / "final.json"
        final = parse_canonical(final_path.read_bytes())
        final["last_receipt_sha256"] = digest(receipt_path.read_bytes())
        final_path.write_bytes(canonical(final))
        with self.assertRaisesRegex(LiveClipError, "sequence discontinuity"):
            self.extract()

    def test_coherently_rehashed_clock_generation_change_refused(self):
        self.fixture([[(20000,)] * 4, [(20000,)] * 4])
        receipt_path = self.path / "receipt-000000001.json"
        record = parse_canonical(receipt_path.read_bytes())
        record["raw"]["clock_generation"] = 2
        receipt_path.write_bytes(canonical(record))
        final_path = self.path / "final.json"
        final = parse_canonical(final_path.read_bytes())
        final["last_receipt_sha256"] = digest(receipt_path.read_bytes())
        final_path.write_bytes(canonical(final))
        with self.assertRaisesRegex(LiveClipError, "clock"):
            self.extract()

    def test_unknown_repeated_regressing_raw_timestamps_not_interpolated(self):
        self.fixture([[(20000,)] * 4] * 4, raws=[{"timestamp": t} for t in (None, 7, 7, 3)])
        result = self.extract()
        doc = self.document(result)
        self.assertEqual([s["raw"]["timestamp"] for s in doc["clips"][0]["segments"]], [None, 7, 7, 3])
        self.assertIsNone(doc["clock_relation"])
        self.assertIsNone(doc["physical_uncertainty_ns"])
        self.assertIn("not-physical-continuity", doc["position_meaning"])

    def test_missing_receipt_and_post_seal_artifact_refused(self):
        self.fixture([[(20000,)] * 4] * 3)
        path = self.path / "receipt-000000001.json"
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(LiveClipError, "outside intact"):
            self.extract()
        path.write_bytes(original)
        (self.path / "new-unreported-orphan").write_bytes(b"unknown")
        with self.assertRaisesRegex(LiveClipError, "final prefix"):
            self.extract()

    def test_unknown_and_video_source_refused(self):
        self.fixture(video=True)
        for source_id in ("fake-video", "foreign", "", True, 10**400, None):
            with self.subTest(source=source_id), self.assertRaises(LiveClipError):
                detect_live_journal(self.path, source_id, self.config)

    def test_empty_intact_prefix_and_silence_publish_no_wavs(self):
        for i, chunks in enumerate(([], [[(0,)] * 8])):
            path = self.root / f"empty-{i}"
            self.fixture(chunks, path=path)
            result = extract_live_clips(path, self.root / f"empty-output-{i}", "fake-audio", self.config)
            doc = self.document(result)
            self.assertEqual(doc["clips"], [])
            self.assertEqual(doc["detected_event_count"], 0)
            self.assertEqual(list(result.output_dir.glob("*.wav")), [])

    def test_invalid_padding_limits_and_selectors_refused_before_input_read(self):
        values = (True, False, -1, 1.5, math.nan, math.inf, 10**400, "1", None)
        with mock.patch.object(clips, "_Snapshot", side_effect=AssertionError("input read")):
            for value in values:
                for name in ("pre_frames", "post_frames"):
                    with self.subTest(name=name, value=value), self.assertRaises(LiveClipError):
                        self.extract(**{name: value})
            for value in ([], (), ("liveevt_" + "0" * 64,) * 2, (True,), "event", ("bad",),
                          ("liveevt_" + "g" * 64,), ("liveevt_" + "0" * 64,) * 65):
                with self.subTest(selector=value), self.assertRaises(LiveClipError):
                    self.extract(event_ids=value)
            for field in fields(ClipLimits):
                for value in (True, 0, -1, math.nan, math.inf, 10**400):
                    with self.subTest(limit=field.name, value=value), self.assertRaises(LiveClipError):
                        ClipLimits(**{field.name: value})
            with self.assertRaises(LiveClipError):
                self.extract(limits={})
            with self.assertRaises(LiveClipError):
                extract_live_clips(self.path, self.output, "fake-audio", {})

    def test_tampered_frozen_config_refused(self):
        config = DetectorConfig()
        object.__setattr__(config, "threshold", math.nan)
        with self.assertRaises(LiveClipError):
            extract_live_clips(self.path, self.output, "fake-audio", config)

    def test_input_and_scan_and_entry_caps_apply_before_file_allocation(self):
        self.fixture(orphan={"unadopted-large.bin": b"x" * 5000})
        files = list(self.path.iterdir())
        total = sum(p.stat().st_size for p in files)
        scan_cost = 2 * sum(p.stat().st_size + 1 for p in files)
        choices = (ClipLimits(max_input_bytes=total - 1), ClipLimits(max_scan_bytes=scan_cost - 1),
                   ClipLimits(max_journal_entries=len(files) - 1))
        for limits in choices:
            with self.subTest(limits=limits), \
                 mock.patch.object(clips._Snapshot, "read", side_effect=AssertionError("allocation before bound")):
                with self.assertRaisesRegex(LiveClipError, "budget"):
                    self.extract(limits=limits)
        self.assertFalse(self.output.exists())

    def test_declared_huge_max_chunks_does_not_drive_scan_loop(self):
        journal = self.fixture(seal=False)
        # A fresh valid empty plan with a high declaration still reads only the
        # bounded present artifact inventory; this is not a million-step scan.
        journal.close_owner()
        plan = replace(journal.plan, limits=replace(journal.plan.limits, max_chunks=1_000_000))
        path = self.root / "large-declaration"
        empty = LiveJournal.create(path, plan)
        self.addCleanup(empty.close_owner)
        empty.finalize("synthetic-empty")
        result = detect_live_journal(path, "fake-audio", self.config)
        self.assertEqual(result.events, ())

    def test_per_file_cap_refuses_before_open_even_for_unadopted_orphan(self):
        self.fixture()
        path = self.path / "oversized.bin"
        with path.open("wb") as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        with mock.patch.object(clips._Snapshot, "read", side_effect=AssertionError("read")):
            with self.assertRaisesRegex(LiveClipError, "size bound before open"):
                self.extract()

    def test_event_cap_refuses_instead_of_silent_truncation(self):
        self.fixture([[(20000,)] * 4 + [(0,)] * 4 + [(20000,)] * 4])
        with self.assertRaisesRegex(LiveClipError, "event count budget"):
            self.extract(limits=ClipLimits(max_events=1))
        self.assertFalse(self.output.exists())

    def test_full_wav_and_frame_caps_apply_before_wav_allocation(self):
        self.fixture()
        for limits in (ClipLimits(max_clip_bytes=8 * 2 + 43), ClipLimits(max_clip_frames=7)):
            with self.subTest(limits=limits), \
                 mock.patch.object(clips, "_wav_header", side_effect=AssertionError("WAV allocated")):
                with self.assertRaisesRegex(LiveClipError, "excerpt frame/full WAV"):
                    self.extract(limits=limits)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.document(self.extract(limits=ClipLimits(max_clip_bytes=60)))["clips"][0]["wav_bytes"], 60)

    def test_output_aggregate_counts_all_wavs_and_manifest(self):
        self.fixture([[(20000,)] * 4 + [(0,)] * 4 + [(20000,)] * 4])
        # Each four-frame mono WAV is 52 bytes; PCM alone would fit 100 bytes.
        with mock.patch.object(clips, "_wav_header", side_effect=AssertionError("WAV allocated")):
            with self.assertRaisesRegex(LiveClipError, "aggregate"):
                self.extract(limits=ClipLimits(max_output_bytes=100))
        for limits in (ClipLimits(max_output_bytes=104), ClipLimits(max_manifest_bytes=200)):
            with self.subTest(limits=limits), self.assertRaisesRegex(LiveClipError, "manifest/aggregate"):
                self.extract(limits=limits)
        self.assertFalse(self.output.exists())

    def test_streamed_manifest_bound_before_large_serialization(self):
        with self.assertRaisesRegex(LiveClipError, "manifest/aggregate"):
            clips._bounded_canonical({"synthetic": ["x" * 1000] * 1000}, 2048)
        document = {"z": [None, True, "unicode-☃"], "a": 4.0}
        self.assertEqual(clips._bounded_canonical(document, len(canonical(document))), canonical(document))

    def test_outputs_never_overwritten(self):
        self.fixture()
        self.output.mkdir()
        marker = self.output / "owned-by-other"
        marker.write_bytes(b"untouched")
        with mock.patch.object(clips, "_detect", side_effect=AssertionError("unneeded detection")):
            with self.assertRaisesRegex(LiveClipError, "already exists"):
                self.extract()
        self.assertEqual(marker.read_bytes(), b"untouched")
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_source_output_overlap_and_symlink_parent_aliases_refused(self):
        self.fixture()
        alias = self.root / "alias"
        alias.symlink_to(self.path, target_is_directory=True)
        for destination in (self.path, self.path / "output", alias / "output", self.root):
            with self.subTest(destination=destination), self.assertRaisesRegex(LiveClipError, "overlap"):
                extract_live_clips(self.path, destination, "fake-audio", self.config)
        self.assertFalse((self.path / "output").exists())
        source_parent_alias = self.root / "parent-alias"
        source_parent_alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(LiveClipError, "overlap"):
            extract_live_clips(source_parent_alias / "journal", self.path / "output", "fake-audio", self.config)

    def test_regular_file_only_symlink_fifo_directory_refusal(self):
        self.fixture()
        payload = self.path / "payload-000000000.bin"
        original = payload.read_bytes()
        target = self.root / "outside.bin"
        target.write_bytes(original)
        for kind in ("symlink", "fifo", "directory"):
            with self.subTest(kind=kind):
                payload.unlink()
                if kind == "symlink":
                    payload.symlink_to(target)
                elif kind == "fifo":
                    os.mkfifo(payload)
                else:
                    payload.mkdir()
                with mock.patch.object(clips._Snapshot, "read", side_effect=AssertionError("nonregular opened")):
                    with self.assertRaisesRegex(LiveClipError, "regular files"):
                        self.extract()
                if kind == "directory":
                    payload.rmdir()
                else:
                    payload.unlink()
                payload.write_bytes(original)
        self.assertEqual(target.read_bytes(), original)

    def test_source_change_during_copy_never_publishes_success_manifest(self):
        self.fixture()
        original = clips._write_new
        def write_then_mutate(fd, name, data):
            original(fd, name, data)
            if name.endswith(".wav"):
                path = self.path / "payload-000000000.bin"
                path.write_bytes(b"x" * path.stat().st_size)
        with mock.patch.object(clips, "_write_new", side_effect=write_then_mutate):
            with self.assertRaisesRegex(LiveClipError, "changed"):
                self.extract()
        self.assertFalse((self.output / "manifest.json").exists())

    def test_source_change_and_restore_detected_by_identity(self):
        self.fixture()
        original = clips._write_new
        def write_then_restore(fd, name, data):
            original(fd, name, data)
            if name.endswith(".wav"):
                path = self.path / "config-fake-audio.json"
                raw = path.read_bytes()
                path.write_bytes(b"x" * len(raw))
                # Same-length rewrite, then restore. Coarse inode timestamps on Linux ext4 can
                # leave stat identity equal within one kernel tick, so advance the timestamps at
                # both steps: the test asserts detection of a timestamp-visible rewrite on every
                # platform, while content changes stay refused by the hash recheck before any
                # manifest is written.
                bump_times(path)
                path.write_bytes(raw)
                bump_times(path)
        with mock.patch.object(clips, "_write_new", side_effect=write_then_restore):
            with self.assertRaisesRegex(LiveClipError, "changed"):
                self.extract()
        self.assertFalse((self.output / "manifest.json").exists())

    def test_every_source_artifact_is_rechecked_before_manifest(self):
        self.fixture(video=True, orphan={"unadopted.bin": b"orphan"})
        original = clips._Snapshot.read
        calls = {}
        def counted(snapshot, name):
            calls[name] = calls.get(name, 0) + 1
            return original(snapshot, name)
        with mock.patch.object(clips._Snapshot, "read", counted):
            self.extract()
        self.assertEqual(set(calls), {p.name for p in self.path.iterdir()})
        self.assertTrue(all(value == 2 for value in calls.values()))

    def test_hash_recheck_refuses_mismatched_read_bytes_even_if_stats_same(self):
        self.fixture()
        original = clips._Snapshot.read
        calls = {}
        def corrupt_second(snapshot, name):
            result = original(snapshot, name)
            calls[name] = calls.get(name, 0) + 1
            if name == "payload-000000000.bin" and calls[name] == 2:
                return b"z" * len(result)
            return result
        with mock.patch.object(clips._Snapshot, "read", corrupt_second):
            with self.assertRaisesRegex(LiveClipError, "bytes changed"):
                self.extract()
        self.assertFalse((self.output / "manifest.json").exists())

    def test_final_recheck_detects_changes_to_files_checked_earlier(self):
        self.fixture()
        original = clips._Snapshot.read
        calls = {}
        def mutate_late(snapshot, name):
            result = original(snapshot, name)
            calls[name] = calls.get(name, 0) + 1
            if name == "start-request.json" and calls[name] == 2:
                path = self.path / "intent.json"
                data = path.read_bytes()
                path.write_bytes(data)
                # Identical-bytes rewrite: only mtime/ctime can move, and coarse inode timestamps
                # on Linux ext4 can leave stat identity equal within one kernel tick. Advance them
                # so the test asserts detection of a timestamp-visible rewrite on every platform
                # (see bump_times; content changes stay refused by the hash recheck).
                bump_times(path)
            return result
        with mock.patch.object(clips._Snapshot, "read", mutate_late):
            with self.assertRaisesRegex(LiveClipError, "changed"):
                self.extract()
        self.assertFalse((self.output / "manifest.json").exists())

    def test_initial_read_change_detected_before_detection(self):
        self.fixture()
        original = clips._Snapshot.read
        def mutate_initial(snapshot, name):
            raw = original(snapshot, name)
            if name == "payload-000000000.bin":
                path = self.path / name
                path.write_bytes(b"x" * len(raw))
                # Coarse inode timestamps on Linux ext4 can leave stat identity equal within one
                # kernel tick after a same-length rewrite. The test asserts detection of a
                # timestamp-visible rewrite on every platform; content changes remain refused by
                # the hash recheck before any manifest is written.
                bump_times(path)
            return raw
        with mock.patch.object(clips._Snapshot, "read", mutate_initial), \
             mock.patch.object(clips, "_detect", side_effect=AssertionError("unverified detection")):
            with self.assertRaisesRegex(LiveClipError, "changed"):
                self.extract()
        self.assertFalse(self.output.exists())

    def test_output_mutation_or_write_failure_never_commits_manifest(self):
        self.fixture()
        original = clips._write_new
        def corrupt_output(fd, name, data):
            original(fd, name, data)
            if name.endswith(".wav"):
                (self.output / name).write_bytes(b"x" * len(data))
        with mock.patch.object(clips, "_write_new", side_effect=corrupt_output):
            with self.assertRaisesRegex(LiveClipError, "output bytes changed"):
                self.extract()
        self.assertFalse((self.output / "manifest.json").exists())
        self.output = self.root / "write-failed"
        with mock.patch.object(clips, "_write_new", side_effect=OSError("synthetic disk fault")):
            with self.assertRaisesRegex(LiveClipError, "disk fault"):
                self.extract()
        self.assertFalse((self.output / "manifest.json").exists())

    def test_output_parent_swap_does_not_write_into_source_alias(self):
        self.fixture()
        parent = self.root / "destination-parent"
        parent.mkdir()
        destination = parent / "new-clips"
        displaced = self.root / "displaced-parent"
        original = clips._write_new
        changed = False
        def replace_parent(fd, name, data):
            nonlocal changed
            original(fd, name, data)
            if not changed:
                changed = True
                parent.rename(displaced)
                parent.symlink_to(self.path, target_is_directory=True)
        with mock.patch.object(clips, "_write_new", side_effect=replace_parent):
            with self.assertRaisesRegex(LiveClipError, "output directory changed"):
                extract_live_clips(self.path, destination, "fake-audio", self.config)
        self.assertFalse((self.path / "new-clips").exists())
        self.assertFalse((displaced / "new-clips" / "manifest.json").exists())

    def test_source_directory_substitution_before_output_open_cannot_mutate_source(self):
        self.fixture()
        before = self.inventory()
        original = os.mkdir
        displaced = self.root / "displaced-new-output"
        def substitute(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == self.output.name and kwargs.get("dir_fd") is not None:
                self.output.rename(displaced)
                self.path.rename(self.output)
            return result
        with mock.patch.object(clips.os, "mkdir", side_effect=substitute), \
             mock.patch.object(clips, "_write_new", side_effect=AssertionError("source write")):
            with self.assertRaisesRegex(LiveClipError, "identity overlap"):
                self.extract()
        self.output.rename(self.path)
        # The injected directory rename changes ctime, not any artifact bytes.
        self.assertEqual(self.inventory(), before)
        self.assertFalse((self.path / "manifest.json").exists())

    def test_noncanonical_duplicate_nonfinite_and_unclosed_final_refused(self):
        self.fixture()
        path = self.path / "final.json"
        original = path.read_bytes()
        for raw in (original.rstrip(b"\n"), b'{"kind":"final","kind":"final"}\n',
                    b'{"kind":NaN}\n', canonical({**parse_canonical(original), "writer_closed": False}),
                    canonical({**parse_canonical(original), "schema": "foreign-journal"})):
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                with self.assertRaises(LiveClipError):
                    self.extract()
        path.write_bytes(original)
        self.assertFalse(self.output.exists())

    def test_output_and_parent_fsync_failure_retract_owned_receipt(self):
        self.fixture()
        before = self.inventory()
        original = os.fsync
        for selected in ("output", "parent"):
            with self.subTest(selected=selected):
                self.output = self.root / ("fsync-failed-" + selected)
                failed = False
                def fail_once(fd):
                    nonlocal failed
                    target = self.output if selected == "output" else self.output.parent
                    info = os.fstat(fd)
                    if not failed and stat.S_ISDIR(info.st_mode) and info.st_ino == target.stat().st_ino:
                        failed = True
                        raise OSError("synthetic " + selected + " directory fsync failure")
                    return original(fd)
                with mock.patch.object(clips.os, "fsync", side_effect=fail_once):
                    with self.assertRaises(LiveClipError) as raised:
                        self.extract()
                self.assertTrue(failed)
                self.assertNotIsInstance(raised.exception, LiveClipPublicationUncertain)
                self.assertIn("fsync failure", str(raised.exception))
                self.assertFalse((self.output / "manifest.json").exists())
                self.assertTrue((self.output / "clip-000.wav").exists())
                self.assertEqual(self.inventory(), before)

    def test_persistent_fsync_failure_reports_uncertain_durability_after_retraction(self):
        self.fixture()
        before = self.inventory()
        original = os.fsync
        def fail_directories(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("synthetic persistent directory fsync failure")
            return original(fd)
        with mock.patch.object(clips.os, "fsync", side_effect=fail_directories):
            with self.assertRaises(LiveClipPublicationUncertain) as raised:
                self.extract()
        self.assertEqual(raised.exception.publication_state, "uncertain")
        self.assertEqual(raised.exception.output_dir, self.output.resolve())
        self.assertIn("publication uncertain", str(raised.exception))
        self.assertIn("persistent", raised.exception.publication_error)
        self.assertIn("persistent", raised.exception.cleanup_error)
        # Absence is observed now; durable absence cannot be claimed after fsync fails.
        self.assertFalse((self.output / "manifest.json").exists())
        self.assertTrue((self.output / "clip-000.wav").exists())
        self.assertEqual(self.inventory(), before)

    def test_pending_unlink_failure_retracts_only_owned_success_receipt(self):
        self.fixture()
        before = self.inventory()
        original = os.unlink
        def fail_pending(path, *args, **kwargs):
            if path == ".pending-manifest.json":
                raise OSError("synthetic pending unlink failure")
            return original(path, *args, **kwargs)
        with mock.patch.object(clips.os, "unlink", side_effect=fail_pending):
            with self.assertRaises(LiveClipError) as raised:
                self.extract()
        self.assertNotIsInstance(raised.exception, LiveClipPublicationUncertain)
        self.assertFalse((self.output / "manifest.json").exists())
        self.assertTrue((self.output / ".pending-manifest.json").exists())
        self.assertTrue((self.output / "clip-000.wav").exists())
        self.assertEqual(self.inventory(), before)

    def test_retraction_unlink_failure_reports_uncertain_and_retains_evidence(self):
        self.fixture()
        before = self.inventory()
        original = os.unlink
        def fail_receipt_unlinks(path, *args, **kwargs):
            if path in (".pending-manifest.json", "manifest.json"):
                raise OSError("synthetic receipt unlink failure: " + path)
            return original(path, *args, **kwargs)
        with mock.patch.object(clips.os, "unlink", side_effect=fail_receipt_unlinks):
            with self.assertRaises(LiveClipPublicationUncertain) as raised:
                self.extract()
        self.assertIn("manifest.json", raised.exception.cleanup_error)
        self.assertTrue((self.output / "manifest.json").exists())
        self.assertTrue((self.output / ".pending-manifest.json").exists())
        self.assertEqual((self.output / "manifest.json").stat().st_ino,
                         (self.output / ".pending-manifest.json").stat().st_ino)
        self.assertTrue((self.output / "clip-000.wav").exists())
        self.assertEqual(self.inventory(), before)

    def test_foreign_receipt_replacement_is_not_deleted_on_publication_failure(self):
        self.fixture()
        before = self.inventory()
        original = os.fsync
        replaced = False
        foreign = b"foreign synthetic receipt, not owned by this extraction"
        def replace_then_fail(fd):
            nonlocal replaced
            if not replaced and stat.S_ISDIR(os.fstat(fd).st_mode):
                replaced = True
                (self.output / "manifest.json").rename(self.output / ".displaced-owned-manifest.json")
                (self.output / "manifest.json").write_bytes(foreign)
                raise OSError("synthetic publication failure with foreign replacement")
            return original(fd)
        with mock.patch.object(clips.os, "fsync", side_effect=replace_then_fail), \
             mock.patch.object(clips.os, "unlink", wraps=os.unlink) as unlinks:
            with self.assertRaises(LiveClipPublicationUncertain) as raised:
                self.extract()
        self.assertIn("unknown receipt; retained", raised.exception.cleanup_error)
        self.assertEqual((self.output / "manifest.json").read_bytes(), foreign)
        self.assertTrue((self.output / ".displaced-owned-manifest.json").exists())
        self.assertTrue((self.output / "clip-000.wav").exists())
        self.assertFalse(any(call.args[0] == "manifest.json" for call in unlinks.call_args_list))
        self.assertEqual(self.inventory(), before)

    def test_changed_owned_inode_bytes_are_retained_as_uncertain_evidence(self):
        self.fixture()
        before = self.inventory()
        original = os.fsync
        changed = False
        foreign = b"changed-in-place synthetic receipt"
        def change_then_fail(fd):
            nonlocal changed
            if not changed and stat.S_ISDIR(os.fstat(fd).st_mode):
                changed = True
                (self.output / "manifest.json").write_bytes(foreign)
                raise OSError("synthetic publication failure after in-place change")
            return original(fd)
        with mock.patch.object(clips.os, "fsync", side_effect=change_then_fail):
            with self.assertRaises(LiveClipPublicationUncertain):
                self.extract()
        self.assertEqual((self.output / "manifest.json").read_bytes(), foreign)
        self.assertEqual(self.inventory(), before)

    def test_replacement_during_retraction_check_is_protected(self):
        self.fixture()
        before = self.inventory()
        original_unlink = os.unlink
        original_verify = clips._verify_output
        foreign = b"foreign replacement during synthetic cleanup check"
        def fail_pending(path, *args, **kwargs):
            if path == ".pending-manifest.json":
                raise OSError("synthetic pending unlink failure")
            return original_unlink(path, *args, **kwargs)
        def replace_after_read(fd, name, expected):
            identity = original_verify(fd, name, expected)
            if name == "manifest.json":
                (self.output / "manifest.json").rename(self.output / ".displaced-owned-manifest.json")
                (self.output / "manifest.json").write_bytes(foreign)
            return identity
        with mock.patch.object(clips.os, "unlink", side_effect=fail_pending), \
             mock.patch.object(clips, "_verify_output", side_effect=replace_after_read):
            with self.assertRaises(LiveClipPublicationUncertain) as raised:
                self.extract()
        self.assertIn("changed during retraction", raised.exception.cleanup_error)
        self.assertEqual((self.output / "manifest.json").read_bytes(), foreign)
        self.assertTrue((self.output / ".pending-manifest.json").exists())
        self.assertEqual(self.inventory(), before)

    def test_error_after_link_creation_still_retracts_owned_receipt(self):
        self.fixture()
        before = self.inventory()
        original = os.link
        def link_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("synthetic error immediately after receipt link")
        with mock.patch.object(clips.os, "link", side_effect=link_then_fail):
            with self.assertRaises(LiveClipError) as raised:
                self.extract()
        self.assertNotIsInstance(raised.exception, LiveClipPublicationUncertain)
        self.assertFalse((self.output / "manifest.json").exists())
        self.assertTrue((self.output / ".pending-manifest.json").exists())
        self.assertEqual(self.inventory(), before)

    def test_detection_final_recheck_refuses_mutation_without_output(self):
        self.fixture()
        original = clips._detect
        def mutate_after_detection(*args):
            result = original(*args)
            (self.path / "new-artifact").write_bytes(b"synthetic")
            return result
        with mock.patch.object(clips, "_detect", side_effect=mutate_after_detection):
            with self.assertRaisesRegex(LiveClipError, "changed"):
                self.detect()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
