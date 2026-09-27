from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from poseidon_acoustic.session import (
    AudioBlock, CapacityExceeded, Channel, ClockMap, FINAL, HALT, HEADER,
    LinuxPiCaptureAdapter, Session, SessionError, Source, canonical, capture_audio,
    file_sha256, load_json, pcm16_wav, publish, read_bounded, sha256,
    synthetic_audio, wav_blocks,
)


ROOT = Path(__file__).resolve().parents[2]


def audio_source(**changes):
    return replace(Source("audio-1", "pcm16-wav", "synthetic", (Channel("ch-0", "synthetic PCM"),),
                          ClockMap("reference_seconds", "test-session", reference_anchor_s=3,
                                   drift_ppm=100, anchor_uncertainty_s=0.01, drift_uncertainty_ppm=20),
                          sample_rate_hz=1000, origin="synthetic unit fixture"), **changes)


def add(session, start=0, units=100, **changes):
    fields = {"unit_start": start, "units": units, "source_start_s": start / 1000,
              "source_end_s": (start + units) / 1000}
    fields.update(changes)
    return session.append("audio-1", pcm16_wav(b"\x01\x00" * units, 1000, 1), **fields)


class ClockTests(unittest.TestCase):
    def test_platform_clock_fixture_maps_exactly_but_requires_separate_epoch(self):
        relation = load_json(ROOT / "contracts/v1/fixtures/clock-relation.valid.json")
        clock = ClockMap.from_relation(relation, reference_epoch="operator-declared-fixture-start")
        self.assertEqual(clock.relation(), relation)
        self.assertEqual(clock.source_domain, "synthetic-audio-monotonic")
        self.assertEqual(clock.reference_domain, "synthetic-video-monotonic")
        self.assertEqual(clock.method, "operator_declared")
        self.assertIsNone(clock.evidence_ref)
        self.assertAlmostEqual(clock.at(10)[0], 10.1201)
        self.assertAlmostEqual(clock.at(10)[1], 0.02005)
        self.assertNotIn("reference_epoch", relation)
        for epoch in (None, "", " "):
            with self.assertRaises(SessionError):
                ClockMap.from_relation(relation, reference_epoch=epoch)
        for change in ({"drift_ppm": -1e6}, {"drift_ppm": float("nan")},
                       {"anchor_uncertainty_s": -1}, {"method": "shared_clock"},
                       {"source_domain": relation["reference_domain"]}):
            with self.assertRaises(SessionError):
                ClockMap.from_relation({**relation, **change}, reference_epoch="explicit-test-epoch")

    def test_mapping_sign_and_uncertainty_either_side_of_anchor(self):
        clock = ClockMap("reference_seconds", "session-alpha", 100, 20, 1000, 0.2, 500)
        self.assertEqual(clock.at(100), (20, 0.2))
        self.assertAlmostEqual(clock.at(110)[0], 30.01)
        self.assertAlmostEqual(clock.at(90)[0], 9.99)
        self.assertAlmostEqual(clock.at(90)[1], 0.205)
        self.assertEqual(clock.at(110)[1], clock.at(90)[1])

    def test_nan_infinity_wrong_types_and_negative_uncertainty(self):
        for field in ("source_anchor_s", "reference_anchor_s", "drift_ppm", "anchor_uncertainty_s", "drift_uncertainty_ppm"):
            for value in (float("nan"), float("inf"), True, "1", 10**1000):
                with self.subTest(field=field, value=str(value)[:10]), self.assertRaises(SessionError):
                    ClockMap("reference_seconds", "epoch", **{field: value})
        for field in ("anchor_uncertainty_s", "drift_uncertainty_ppm"):
            with self.assertRaises(SessionError):
                ClockMap("reference_seconds", "epoch", **{field: -1})
        for drift in (-1e6, -2e6):
            with self.assertRaises(SessionError):
                ClockMap("reference_seconds", "epoch", drift_ppm=drift)

    def test_empty_reference_domain_and_overflow_rejected(self):
        with self.assertRaises(SessionError):
            ClockMap("", "epoch")
        with self.assertRaises(SessionError):
            ClockMap("ref", "epoch", reference_anchor_s=1e308, drift_ppm=1e308).at(1e308)

    def test_source_and_channels_are_frozen_and_validated(self):
        source = audio_source()
        with self.assertRaises(FrozenInstanceError):
            source.source_id = "other"
        with self.assertRaises(FrozenInstanceError):
            source.channels[0].channel_id = "other"
        for change in ({"channels": []}, {"sample_rate_hz": 0}, {"input_sha256": "bad"},
                       {"source_id": "../escape"}, {"channels": (source.channels[0],) * 2},
                       {"source_origin_s": float("nan")}):
            with self.subTest(change=change), self.assertRaises(SessionError):
                replace(source, **change)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session = Session.create(self.root / "session", "test-session", (audio_source(),))

    def test_roundtrip_finalized_segments_and_idempotent_finalization(self):
        first = add(self.session)
        add(self.session, 100)
        final = self.session.finalize()
        self.assertEqual(final["state"], "finalized")
        self.assertEqual(final["accounting"]["audio-1"]["stored_units"], 200)
        self.assertEqual(first["reference_start_s"], 3)
        self.assertAlmostEqual(first["reference_end_s"], 3.10001)
        before = (self.session.directory / FINAL).read_bytes()
        self.assertEqual(Session(self.session.directory).finalize(), final)
        self.assertEqual(before, (self.session.directory / FINAL).read_bytes())
        self.assertTrue(self.session.recover()["finalized"])
        with self.assertRaises(SessionError):
            add(self.session, 200)

    def test_direct_append_validates_wav_payload_against_source_and_receipt(self):
        payloads = [pcm16_wav(bytes(20), 1000, 1), pcm16_wav(bytes(200), 8000, 1),
                    pcm16_wav(bytes(400), 1000, 2), pcm16_wav(bytes(200), 1000, 1)[:-1], b"not a WAV"]
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setparams((1, 1, 1000, 100, "NONE", "not compressed"))
            writer.writeframes(bytes(100))
        payloads.append(buffer.getvalue())
        for payload in payloads:
            with self.subTest(payload_size=len(payload)), self.assertRaises(SessionError):
                self.session.append("audio-1", payload, unit_start=0, units=100,
                                    source_start_s=0, source_end_s=0.1)
        self.assertEqual(self.session.recover()["receipts"], [])

    def test_recovery_revalidates_wav_even_if_payload_digest_was_rewritten(self):
        record = add(self.session)
        payload = pcm16_wav(bytes(20), 1000, 1)
        (self.session.directory / record["path"]).write_bytes(payload)
        record.update(sha256=sha256(payload), bytes=len(payload))
        (self.session.directory / "chunk-000000.json").write_bytes(canonical(record))
        with self.assertRaisesRegex(SessionError, "WAV payload"):
            self.session.recover()

    def test_direct_pgm_append_requires_canonical_format(self):
        source = Source("camera", "pgm8", "synthetic", (Channel("gray", "test image"),),
                        ClockMap("reference_seconds", "test-session"))
        session = Session.create(self.root / "pgm", "pgm", (source,))
        for data in (b"junk", b"P5\n2 2\n255\n\x00", b"P5\n9999999 9999999\n255\n"):
            with self.assertRaises(SessionError):
                session.append("camera", data, unit_start=0, units=1, source_start_s=0, source_end_s=0.25)
        session.append("camera", b"P5\n1 1\n255\n\x00", unit_start=0, units=1,
                       source_start_s=0, source_end_s=0.25)
        self.assertEqual(len(session.finalize()["segments"]), 1)

    def test_nonregular_existing_writer_lock_refused_before_open(self):
        os.mkfifo(self.session.directory / ".writer.lock")
        with patch("poseidon_acoustic.session.os.open") as opened, self.assertRaises(SessionError):
            self.session.recover()
        opened.assert_not_called()

    def test_gap_and_drop_accounting(self):
        add(self.session)
        record = add(self.session, 150, dropped_units=40, gap_reason="simulated buffer gap; 10 unexplained")
        self.assertEqual((record["missing_units"], record["dropped_units"], record["unexplained_missing_units"]), (50, 40, 10))
        self.assertAlmostEqual(record["gap_source_s"], 0.05)
        self.assertEqual(self.session.finalize()["accounting"]["audio-1"]["missing_units"], 50)

    def test_initial_gap_requires_reason_and_is_counted(self):
        with self.assertRaises(SessionError):
            add(self.session, 100)
        add(self.session, 100, dropped_units=100, gap_reason="simulated late start")
        self.assertEqual(self.session.finalize()["accounting"]["audio-1"]["dropped_units"], 100)

    def test_backwards_overlap_unknown_source_nan_and_wrong_duration(self):
        add(self.session)
        for change in ({"start": 50}, {"start": 150}, {"start": 100, "dropped_units": 1},
                       {"start": 100, "source_end_s": float("nan")},
                       {"start": 100, "source_end_s": 0.3}, {"start": True}):
            with self.subTest(change=change), self.assertRaises(SessionError):
                add(self.session, **change)
        with self.assertRaises(SessionError):
            self.session.append("other", b"x", unit_start=0, units=1, source_start_s=0, source_end_s=1)
        self.assertEqual(len(self.session.recover()["receipts"]), 1)

    def test_header_identity_change_detected(self):
        add(self.session)
        header = load_json(self.session.directory / HEADER)
        header["sources"][0]["channels"][0]["channel_id"] = "substitution"
        (self.session.directory / HEADER).write_bytes(canonical(header))
        with self.assertRaisesRegex(SessionError, "identity changed"):
            self.session.recover()
        with self.assertRaisesRegex(SessionError, "metadata mismatch"):
            Session(self.session.directory).recover()

    def test_checksum_corruption_refuses_recovery_without_deletion(self):
        record = add(self.session)
        target = self.session.directory / record["path"]
        target.write_bytes(target.read_bytes()[:-1] + b"\xff")
        with self.assertRaisesRegex(SessionError, "checksum"):
            self.session.recover()
        self.assertTrue(target.exists())
        self.assertFalse((self.session.directory / FINAL).exists())

    def test_missing_middle_or_tail_receipt_detected_by_chain_or_final(self):
        add(self.session)
        add(self.session, 100)
        self.session.finalize()
        (self.session.directory / "chunk-000001.json").unlink()
        with self.assertRaises(SessionError):
            self.session.recover()

    def test_receipt_path_traversal_and_metadata_nan_rejected(self):
        add(self.session)
        path = self.session.directory / "chunk-000000.json"
        original = load_json(path)
        for changed in (dict(original, path="../outside.wav"), dict(original, units=True),
                        dict(original, reference_start_s=999)):
            path.write_bytes(canonical(changed))
            with self.assertRaises(SessionError):
                self.session.recover()

    def test_final_manifest_corruption_rejected(self):
        add(self.session)
        self.session.finalize()
        final = load_json(self.session.directory / FINAL)
        final["segments"] = []
        (self.session.directory / FINAL).write_bytes(canonical(final))
        with self.assertRaises(SessionError):
            self.session.recover()

    def test_payload_published_before_receipt_failure_is_preserved_as_orphan(self):
        real_publish = publish
        def fail_receipt(directory, name, data):
            if name == "chunk-000001.json":
                raise OSError("injected receipt write failure")
            real_publish(directory, name, data)
        add(self.session)
        with patch("poseidon_acoustic.session.publish", side_effect=fail_receipt), self.assertRaises(OSError):
            add(self.session, 100)
        recovered = Session(self.session.directory).recover()
        self.assertEqual(len(recovered["receipts"]), 1)
        self.assertEqual(recovered["manifest"]["uncommitted_files"], ["chunk-000001.wav"])
        with self.assertRaises(SessionError):
            add(self.session, 100)
        final = self.session.finalize()
        self.assertEqual(final["state"], "recovered_incomplete")
        self.assertTrue((self.session.directory / "chunk-000001.wav").exists())

    def test_failed_payload_link_retains_staging_and_can_finalize(self):
        with patch("poseidon_acoustic.session.os.link", side_effect=OSError("injected link failure")), self.assertRaises(OSError):
            add(self.session)
        recovered = self.session.recover()
        self.assertEqual(len(recovered["manifest"]["uncommitted_files"]), 1)
        self.assertIn(".pending-", recovered["manifest"]["uncommitted_files"][0])
        self.assertEqual(self.session.finalize()["state"], "recovered_incomplete")

    def test_failed_final_link_can_be_recovered_without_replacing_pending_evidence(self):
        add(self.session)
        with patch("poseidon_acoustic.session.os.link", side_effect=OSError("injected finalize failure")), self.assertRaises(OSError):
            self.session.finalize()
        pending = tuple(self.session.directory.glob(FINAL + ".pending-*"))
        self.assertEqual(len(pending), 1)
        before = pending[0].read_bytes()
        self.assertEqual(self.session.finalize()["state"], "recovered_incomplete")
        self.assertEqual(pending[0].read_bytes(), before)
        self.assertTrue(self.session.recover()["finalized"])

    def test_committed_staging_hardlink_alias_does_not_invalidate_finalization(self):
        add(self.session)
        self.session.finalize()
        final = self.session.directory / FINAL
        os.link(final, self.session.directory / (FINAL + ".pending-interrupted"))
        self.assertTrue(self.session.recover()["finalized"])
        self.assertEqual(self.session.recover()["manifest"]["uncommitted_files"], [])

    def test_byte_capacity_halts_and_never_evicts_committed_audio(self):
        session = Session.create(self.root / "bounded", "bounded", (audio_source(),), max_bytes=18000, max_chunks=4)
        first = add(session)
        before = (session.directory / first["path"]).read_bytes()
        with self.assertRaises(CapacityExceeded):
            add(session, 100, 4000)
        self.assertEqual(before, (session.directory / first["path"]).read_bytes())
        self.assertEqual(session.finalize()["state"], "capacity_halted")
        self.assertLessEqual(sum(p.stat().st_size for p in session.directory.iterdir()), 18000)
        with self.assertRaises(SessionError):
            add(session, 100)

    def test_chunk_capacity_halts(self):
        session = Session.create(self.root / "one", "one", (audio_source(),), max_chunks=1)
        add(session)
        with self.assertRaises(CapacityExceeded):
            add(session, 100)
        self.assertEqual(session.finalize()["halt"]["reason"], "chunk_capacity")

    def test_existing_directory_and_invalid_budget_never_overwrite(self):
        with self.assertRaises(FileExistsError):
            Session.create(self.session.directory, "again", (audio_source(),))
        for budget in (0, True, 100, -1):
            with self.assertRaises(SessionError):
                Session.create(self.root / "invalid", "invalid", (audio_source(),), max_bytes=budget)
        self.assertFalse((self.root / "invalid").exists())

    def test_reference_precision_loss_is_not_a_zero_length_segment(self):
        source = audio_source(clock=ClockMap("reference_seconds", "epoch", reference_anchor_s=1e30))
        session = Session.create(self.root / "precision", "precision", (source,))
        with self.assertRaisesRegex(SessionError, "numeric precision"):
            add(session)
        self.assertEqual(session.recover()["receipts"], [])

    def test_finalized_orphan_snapshot_detects_later_byte_changes(self):
        path = self.session.directory / "preserved-orphan.bin"
        path.write_bytes(b"before")
        manifest = self.session.finalize()
        self.assertEqual(manifest["uncommitted_artifacts"][0]["sha256"], sha256(b"before"))
        path.write_bytes(b"after!")
        with self.assertRaises(SessionError):
            self.session.recover()

    def test_workspace_file_and_external_byte_growth_budgets(self):
        session = Session.create(self.root / "count", "count", (audio_source(),), max_chunks=1)
        for index in range(40):
            (session.directory / f"orphan-{index}").write_bytes(b"")
        with self.assertRaisesRegex(SessionError, "file count"):
            session.recover()
        session = Session.create(self.root / "bytes", "bytes", (audio_source(),), max_bytes=18000, max_chunks=1)
        (session.directory / "large-orphan").write_bytes(bytes(18001))
        with self.assertRaisesRegex(SessionError, "storage budget"):
            session.recover()
        self.assertEqual((session.directory / "large-orphan").stat().st_size, 18001)

    def test_multi_source_reference_domain_must_match(self):
        second = audio_source(source_id="audio-2", clock=ClockMap("unix_seconds", "UTC"))
        with self.assertRaises(SessionError):
            Session.create(self.root / "mixed", "mixed", (audio_source(), second))
        second = audio_source(source_id="audio-2")
        session = Session.create(self.root / "two", "two", (audio_source(), second))
        self.assertEqual(len(session.sources), 2)

    def test_symlink_workspace_and_entries_rejected(self):
        link = self.root / "alias"
        link.symlink_to(self.session.directory, target_is_directory=True)
        with self.assertRaises(SessionError):
            Session(link)
        (self.session.directory / "escape").symlink_to(self.root / "outside")
        with self.assertRaises(SessionError):
            self.session.recover()

    def test_concurrent_writer_refused(self):
        with (self.session.directory / ".writer.lock").open("wb") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with self.assertRaisesRegex(SessionError, "another session writer"):
                add(self.session)

    def test_unknown_or_partial_files_preserved_and_reported(self):
        path = self.session.directory / "unknown-evidence.bin"
        path.write_bytes(b"do not evict")
        result = self.session.finalize()
        self.assertEqual(result["uncommitted_files"], [path.name])
        self.assertEqual(path.read_bytes(), b"do not evict")

    def test_input_failure_is_not_reported_as_complete(self):
        def failing():
            yield AudioBlock(0, 100, b"\x00\x00" * 100)
            raise SessionError("injected source disconnect")
        with self.assertRaises(SessionError):
            capture_audio(self.session, "audio-1", failing())
        self.assertEqual(self.session.finalize()["state"], "source_failed")
        self.assertEqual(len(self.session.recover()["receipts"]), 1)


class AudioInputTests(unittest.TestCase):
    def test_synthetic_pcm_is_repeatable_and_chunk_partition_independent(self):
        first = list(synthetic_audio(frames=33, channels=2, chunk_frames=8))
        second = list(synthetic_audio(frames=33, channels=2, chunk_frames=13))
        self.assertEqual(b"".join(b.pcm for b in first), b"".join(b.pcm for b in second))
        self.assertEqual(sum(b.units for b in first), 33)
        self.assertNotEqual(first[0].pcm, next(synthetic_audio(frames=8, channels=2, seed=8)).pcm)

    def test_pcm16_wav_streaming_roundtrip_and_stereo_identity(self):
        pcm = b"".join(b.pcm for b in synthetic_audio(frames=33, channels=2))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.wav"
            path.write_bytes(pcm16_wav(pcm, 8000, 2))
            blocks = list(wav_blocks(path, sample_rate_hz=8000, channels=2, chunk_frames=7))
            self.assertEqual(len(blocks), 5)
            self.assertEqual(b"".join(b.pcm for b in blocks), pcm)
            self.assertEqual(file_sha256(path), sha256(path.read_bytes()))

    def test_truncated_wrong_rate_width_and_input_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.wav"
            valid = pcm16_wav(b"\x00\x00" * 30, 8000, 1)
            path.write_bytes(valid[:-1])
            with self.assertRaises(SessionError):
                list(wav_blocks(path, sample_rate_hz=8000, channels=1))
            path.write_bytes(valid)
            for options in ({"sample_rate_hz": 16000}, {"channels": 2}, {"max_frames": 2}, {"chunk_frames": 0}):
                config = {"sample_rate_hz": 8000, "channels": 1, **options}
                with self.assertRaises(SessionError):
                    list(wav_blocks(path, **config))
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as writer:
                writer.setparams((1, 1, 8000, 10, "NONE", "not compressed"))
                writer.writeframes(bytes(10))
            path.write_bytes(buffer.getvalue())
            with self.assertRaises(SessionError):
                list(wav_blocks(path, sample_rate_hz=8000, channels=1))

    def test_partial_final_pcm_frame_marks_source_failed_not_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = bytearray(pcm16_wav(bytes(60), 1000, 1))
            struct.pack_into("<I", payload, 4, len(payload) - 8 + 1)
            struct.pack_into("<I", payload, 40, 61)
            payload.append(1)
            path = root / "partial.wav"
            path.write_bytes(payload)
            session = Session.create(root / "session", "partial", (audio_source(),))
            with self.assertRaisesRegex(SessionError, "incomplete final PCM frame"):
                capture_audio(session, "audio-1", wav_blocks(path, sample_rate_hz=1000, channels=1))
            recovery = session.recover()
            self.assertFalse(recovery["finalized"])
            self.assertEqual(recovery["manifest"]["halt"]["reason"], "source_error")
            self.assertEqual(session.finalize()["state"], "source_failed")
            self.assertTrue(path.exists())

    def test_symlinks_fifo_and_oversized_reads_refused_before_open(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "file"
            path.write_bytes(b"abc")
            (root / "link").symlink_to(path)
            os.mkfifo(root / "fifo")
            for name in ("link", "fifo"):
                with patch("poseidon_acoustic.session.os.open") as opened, self.assertRaises(SessionError):
                    read_bounded(root / name)
                opened.assert_not_called()
            with self.assertRaises(SessionError):
                read_bounded(path, 2)
            with self.assertRaises(SessionError):
                file_sha256(path, max_bytes=2)

    def test_duplicate_nonfinite_and_oversized_json_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '[' * 10000):
                path.write_text(text)
                with self.assertRaises(SessionError):
                    load_json(path)

    def test_live_boundary_never_opens_anything(self):
        with patch("poseidon_acoustic.session.os.open") as opened, self.assertRaises(PermissionError):
            LinuxPiCaptureAdapter().open("/dev/not-a-real-device", authorized=True)
        opened.assert_not_called()

    def test_cli_demo_reproducible_recover_and_live_refusal(self):
        def run(*args):
            return subprocess.run([sys.executable, "-m", "poseidon_acoustic.session_cli", *args],
                                  cwd=ROOT, text=True, capture_output=True, timeout=30)
        with tempfile.TemporaryDirectory() as temp:
            roots = [Path(temp) / "a", Path(temp) / "b"]
            for root in roots:
                completed = run("demo", "--output-dir", str(root))
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(len(json.loads(completed.stdout)["segments"]), 4)
            self.assertEqual({p.name: p.read_bytes() for p in roots[0].iterdir()},
                             {p.name: p.read_bytes() for p in roots[1].iterdir()})
            self.assertEqual(run("recover", "--session", str(roots[0])).returncode, 0)
            self.assertEqual(run("demo", "--output-dir", str(roots[0])).returncode, 2)
            live = run("live")
            self.assertEqual(live.returncode, 2)
            self.assertNotIn("Traceback", live.stderr)


if __name__ == "__main__":
    unittest.main()
