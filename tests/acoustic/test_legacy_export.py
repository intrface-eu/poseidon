from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from poseidon_proto import RecordingManifest, canonical_json
from poseidon_acoustic.detector import DetectorConfig, detect_wav
from poseidon_acoustic.legacy_export import (
    COMMIT, EpochDeclaration, ExportError, FileOriginDeclaration, SegmentMapping, export_segments,
)
from poseidon_acoustic.legacy_export_cli import main, run_demo
from poseidon_acoustic.replay import replay_to_store
from poseidon_acoustic.session import (
    FINAL, HEADER, CapacityExceeded, Channel, ClockMap, Session, SessionError, Source,
    canonical, file_sha256, load_json, pcm16_wav, publish, sha256,
)
from poseidon_acoustic.store import list_event_json


class LegacyExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS /var and /tmp are system symlinks; pass the actual owned path.
        self.root = Path(self.temp.name).resolve()
        self.source = Source(
            "audio-1", "pcm16-wav", "synthetic",
            (Channel("right", "synthetic right PCM"), Channel("left", "synthetic left PCM")),
            ClockMap("reference_seconds", "test-start", reference_anchor_s=0.25,
                     drift_ppm=1000, anchor_uncertainty_s=0.01, drift_uncertainty_ppm=20),
            sample_rate_hz=8000, origin="synthetic integer PCM fixture",
        )
        self.epoch = EpochDeclaration("audio-1", "reference_seconds", "test-start",
                                      "2026-01-01T00:00:00Z", 0.005, "fixture-operator", "fixture-epoch-note")
        self.mapping = SegmentMapping(0, "recording-0", "site-test", "zone-test", "device-test")

    def append(self, session, source=None, *, start=0, units=160, amplitude=20000, **kw):
        source = self.source if source is None else source
        # Distinct sample signs in the two channels catch silent reordering.
        pcm = b"".join(struct.pack("<h", amplitude if ch % 2 == 0 else -amplitude)
                       for _ in range(units) for ch in range(len(source.channels)))
        return session.append(source.source_id, pcm16_wav(pcm, source.sample_rate_hz, len(source.channels)),
                              unit_start=start, units=units,
                              source_start_s=source.source_origin_s + start / source.sample_rate_hz,
                              source_end_s=source.source_origin_s + (start + units) / source.sample_rate_hz, **kw)

    def session(self, name="session", source=None, *, finalize=True, **kw):
        source = self.source if source is None else source
        session = Session.create(self.root / name, "test-session", (source,), **kw)
        self.append(session, source)
        if finalize:
            session.finalize()
        return session

    def export(self, session, name="export", **kw):
        options = dict(source_id="audio-1", mappings=(self.mapping,), epoch=self.epoch)
        options.update(kw)
        return export_segments(session.directory, self.root / name, **options)

    def binding(self, name="export", index=0):
        return load_json(self.root / name / f"binding-{index:06d}.json")

    def test_real_replay_store_candidate_ids_provenance_and_byte_binding(self):
        session = self.session()
        original = {p.name: p.read_bytes() for p in session.directory.iterdir()}
        result = self.export(session)
        output = self.root / "export"
        self.assertEqual(result, load_json(output / COMMIT))
        self.assertEqual(result["state"], "export_committed")
        item = result["exports"][0]
        manifest = RecordingManifest.from_dict(load_json(output / item["manifest"]["path"]))
        self.assertEqual(set(manifest.to_dict()), RecordingManifest.FIELDS)
        wav = output / item["wav"]["path"]
        self.assertEqual(wav.read_bytes(), original["chunk-000000.wav"])
        self.assertEqual(file_sha256(wav), manifest.wav_sha256)
        binding = self.binding()
        self.assertEqual(canonical(binding["source"]), canonical(asdict(self.source)))
        self.assertEqual([c["channel_id"] for c in binding["source"]["channels"]], ["right", "left"])
        self.assertEqual(binding["mapping"], asdict(self.mapping))
        self.assertFalse(binding["bytes_transformed"])
        for key, name in (("original_header", HEADER), ("original_final", FINAL),
                          ("original_receipt", "chunk-000000.json")):
            copied = binding[key]["exported_copy"]
            self.assertEqual(copied["sha256"], sha256(original[name]))
            self.assertEqual((output / copied["path"]).read_bytes(), original[name])
        for artifact in result["files"]:
            data = (output / artifact["path"]).read_bytes()
            self.assertEqual(len(data), artifact["bytes"])
            self.assertEqual(sha256(data), artifact["sha256"])
        self.assertEqual(result["bytes_excluding_receipt"], sum(f["bytes"] for f in result["files"]))
        self.assertEqual({p.name: p.read_bytes() for p in session.directory.iterdir()}, original)
        database = self.root / "evidence.sqlite3"
        detected, saved = replay_to_store(wav, output / item["manifest"]["path"], database)
        direct = detect_wav(wav, manifest, DetectorConfig())
        self.assertEqual(detected, direct)
        self.assertEqual(len(detected.events), 1)
        event = detected.events[0]
        identity = canonical_json({"run_id": detected.run_id, "start_frame": 0, "end_frame": 160})
        self.assertEqual(event.event_id, "evt_" + hashlib.sha256(identity.encode()).hexdigest())
        self.assertEqual((event.recording_id, event.site_id, event.zone_id, event.device_id),
                         ("recording-0", "site-test", "zone-test", "device-test"))
        self.assertEqual(event.provenance, "synthetic")
        self.assertEqual(event.calibration_status, "uncalibrated")
        self.assertFalse(event.emission_enabled)
        self.assertFalse(saved.already_present)
        _, second_save = replay_to_store(wav, output / item["manifest"]["path"], database)
        self.assertTrue(second_save.already_present)
        self.assertEqual(json.loads(list_event_json(database)[0])["event_id"], event.event_id)
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_clock_drift_epoch_uncertainty_and_gap_are_not_erased(self):
        session = self.session(finalize=False)
        self.append(session, start=8000, dropped_units=100,
                    gap_reason="fixture missing interval, only 100 drops explained")
        session.finalize()
        self.export(session, mappings=(replace(self.mapping, segment_index=1, recording_id="later"),))
        binding = self.binding(index=1)
        time = binding["time"]
        self.assertEqual(time["started_at"], "2026-01-01T00:00:01.251000Z")
        self.assertEqual(time["epoch_declaration"], asdict(self.epoch))
        self.assertAlmostEqual(float(time["combined_start_uncertainty_s"]), 0.01502)
        self.assertFalse(time["resampled_for_clock_drift"])
        self.assertNotEqual(time["reference_ended_at"], time["nominal_wav_ended_at"])
        self.assertIn("not drift-corrected", time["v1_candidate_offsets"])
        record = binding["original_receipt"]["record"]
        self.assertEqual((record["missing_units"], record["dropped_units"], record["unexplained_missing_units"]),
                         (7840, 100, 7740))
        self.assertEqual(binding["source"]["clock"], asdict(self.source.clock))
        self.assertFalse(binding["acquisition_completeness_verified"])
        self.assertIn("trailing_extent_not_attested", binding["capture_extent"])

    def test_submicrosecond_start_rounding_is_explicit(self):
        source = replace(self.source, clock=replace(self.source.clock, reference_anchor_s=0.1234567))
        self.export(self.session(source=source))
        time = self.binding()["time"]
        self.assertEqual(time["started_at"], "2026-01-01T00:00:00.123457Z")
        self.assertAlmostEqual(float(time["started_at_rounding_error_s"]), 0.0000003)
        self.assertAlmostEqual(float(time["combined_start_uncertainty_s"]), 0.0150003)

    def test_negative_reference_time_uses_accepted_epoch_not_source_clock(self):
        source = replace(self.source, source_origin_s=10,
                         clock=replace(self.source.clock, source_anchor_s=10, reference_anchor_s=-2))
        self.export(self.session(source=source))
        self.assertEqual(self.binding()["time"]["started_at"], "2025-12-31T23:59:58.000000Z")

    def test_measured_relation_evidence_is_preserved_not_verified(self):
        source = replace(self.source, clock=replace(self.source.clock, method="measured_reference", evidence_ref="bench-note"))
        self.export(self.session(source=source))
        binding = self.binding()
        self.assertEqual(binding["source"]["clock"]["method"], "measured_reference")
        self.assertEqual(binding["source"]["clock"]["evidence_ref"], "bench-note")
        self.assertFalse(binding["time"]["clock_relation_verified"])

    def test_wrong_epoch_source_domain_or_epoch_refused_before_output(self):
        session = self.session()
        for change in ({"source_id": "wrong"}, {"reference_domain": "wrong"}, {"reference_epoch": "wrong"}):
            with self.subTest(change=change), self.assertRaisesRegex(ExportError, "epoch declaration does not match"):
                self.export(session, epoch=replace(self.epoch, **change))
        self.assertFalse((self.root / "export").exists())

    def test_utc_dates_must_be_explicit_valid_and_unambiguous(self):
        for value in ("2026-01-01", "2026-01-01T00:00:00", "2026-01-01T00:00:00-00:00",
                      "2026-01-01T01:00:00+01:00", "2026-02-29T00:00:00Z", "2026-12-31T23:59:60Z",
                      "0000-01-01T00:00:00Z", "10000-01-01T00:00:00Z", "2026-01-01T24:00:00Z",
                      "2026-01-01T00:00:00.0000001Z", "20260101T000000Z", None):
            with self.subTest(value=value), self.assertRaises(ExportError):
                replace(self.epoch, epoch_utc=value)
        epoch = replace(self.epoch, epoch_utc="2024-02-29T00:00:00+00:00")
        self.export(self.session(), epoch=epoch)
        self.assertEqual(self.binding()["time"]["started_at"], "2024-02-29T00:00:00.250000Z")

    def test_invalid_epoch_uncertainty_and_missing_evidence_refused(self):
        for change in ({"uncertainty_s": -1}, {"uncertainty_s": float("nan")},
                       {"uncertainty_s": float("inf")}, {"uncertainty_s": True},
                       {"uncertainty_s": 10**1000}, {"evidence_ref": ""}, {"declared_by": " "}):
            with self.subTest(change=str(change)[:80]), self.assertRaises(SessionError):
                replace(self.epoch, **change)
        with self.assertRaisesRegex(ExportError, "explicit UTC epoch"):
            self.export(self.session(), epoch=None)

    def test_utc_overflow_and_uncertainty_envelope_refused(self):
        session = self.session()
        for epoch in (replace(self.epoch, epoch_utc="9999-12-31T23:59:59.999999Z"),
                      replace(self.epoch, epoch_utc="0001-01-01T00:00:00Z", uncertainty_s=1),
                      replace(self.epoch, uncertainty_s=1e308)):
            with self.subTest(epoch=epoch.epoch_utc), self.assertRaisesRegex(ExportError, "range"):
                self.export(session, epoch=epoch)
        self.assertFalse((self.root / "export").exists())

    def test_submicrosecond_date_underflow_is_not_rounded_into_range(self):
        source = replace(self.source, clock=replace(self.source.clock, reference_anchor_s=-0.0000001,
                                                    anchor_uncertainty_s=0, drift_uncertainty_ppm=0))
        epoch = replace(self.epoch, epoch_utc="0001-01-01T00:00:00Z", uncertainty_s=0)
        with self.assertRaisesRegex(ExportError, "range"):
            self.export(self.session(source=source), epoch=epoch)
        self.assertFalse((self.root / "export").exists())

    def test_reference_seconds_out_of_date_range_refused(self):
        source = replace(self.source, clock=replace(self.source.clock, reference_anchor_s=400000000000))
        with self.assertRaisesRegex(ExportError, "range"):
            self.export(self.session(source=source))

    def test_tiny_drift_scaled_interval_cannot_round_to_empty_v1_interval(self):
        source = replace(self.source, clock=replace(self.source.clock, drift_ppm=-999999.999))
        with self.assertRaisesRegex(ExportError, "ambiguous"):
            self.export(self.session(source=source))

    def test_synthetic_provenance_cannot_be_redeclared_field(self):
        declaration = FileOriginDeclaration("audio-1", "a" * 64, "field", "operator", "claim-note")
        with self.assertRaisesRegex(ExportError, "synthetic source"):
            self.export(self.session(), file_origin=declaration)

    def file_source(self):
        return replace(self.source, provenance="file", origin="operator-declared input WAV", input_sha256="a" * 64)

    def field_origin(self):
        return FileOriginDeclaration("audio-1", "a" * 64, "field", "test-operator", "origin-evidence/not-a-permit")

    def test_file_origin_needs_independent_declaration_and_rejects_bench(self):
        session = self.session(source=self.file_source())
        for origin in (None, replace(self.field_origin(), origin="bench")):
            with self.subTest(origin=origin), self.assertRaises(ExportError):
                self.export(session, file_origin=origin)
        self.assertFalse((self.root / "export").exists())
        with self.assertRaisesRegex(ExportError, "field or bench"):
            replace(self.field_origin(), origin="unknown")

    def test_field_origin_keeps_claim_reference_not_authorization(self):
        session = self.session(source=self.file_source())
        exported = self.export(session, file_origin=self.field_origin())
        binding = self.binding()
        self.assertEqual(binding["provenance"]["file_origin_declaration"], asdict(self.field_origin()))
        self.assertEqual(binding["provenance"]["original_provenance"], "file")
        self.assertFalse(binding["provenance"]["origin_verified"])
        self.assertFalse(binding["provenance"]["authorization_verified"])
        self.assertFalse(binding["hardware_verified"])
        self.assertFalse(binding["time"]["epoch_declaration_verified"])
        item = exported["exports"][0]
        result, _ = replay_to_store(self.root / "export" / item["wav"]["path"],
                                    self.root / "export" / item["manifest"]["path"], self.root / "field.sqlite3")
        self.assertEqual(result.events[0].provenance, "field")
        self.assertEqual(result.events[0].calibration_status, "uncalibrated")

    def test_wrong_file_origin_identity_or_input_hash_refused(self):
        session = self.session(source=self.file_source())
        for change in ({"source_id": "other"}, {"input_sha256": "b" * 64}):
            with self.subTest(change=change), self.assertRaisesRegex(ExportError, "disagrees"):
                self.export(session, file_origin=replace(self.field_origin(), **change))
        session = self.session("no-input-checksum", replace(self.file_source(), input_sha256=None))
        with self.assertRaisesRegex(ExportError, "original input SHA-256"):
            self.export(session, file_origin=self.field_origin())

    def test_unknown_original_provenance_refused(self):
        session = self.session()
        header = load_json(session.directory / HEADER)
        header["sources"][0]["provenance"] = "unknown"
        (session.directory / HEADER).write_bytes(canonical(header))
        with self.assertRaisesRegex(SessionError, "unsupported media or provenance"):
            self.export(session)

    def test_missing_source_or_clock_fields_are_not_filled_from_defaults(self):
        for index, (container, field) in enumerate((("source", "origin"), ("clock", "method"),
                                                     ("clock", "drift_uncertainty_ppm"))):
            session = Session.create(self.root / f"missing-{index}", "test-session", (self.source,))
            header = load_json(session.directory / HEADER)
            target = header["sources"][0] if container == "source" else header["sources"][0]["clock"]
            del target[field]
            (session.directory / HEADER).write_bytes(canonical(header))
            session = Session(session.directory)
            self.append(session)
            session.finalize()
            with self.subTest(field=field), self.assertRaisesRegex(ExportError, "metadata fields missing"):
                self.export(session)

    def test_wide_or_fast_source_is_not_mixed_or_downsampled(self):
        sources = (replace(self.source, channels=tuple(Channel(f"ch-{i}", "synthetic") for i in range(9))),
                   replace(self.source, sample_rate_hz=384001))
        for index, source in enumerate(sources):
            with self.subTest(index=index), self.assertRaisesRegex(ExportError, "v1 limit"):
                self.export(self.session(f"wide-{index}", source))
        self.assertFalse((self.root / "export").exists())

    def test_v1_max_rate_and_channels_are_accepted_unchanged(self):
        source = replace(self.source, sample_rate_hz=384000,
                         channels=tuple(Channel(f"ch-{i}", "synthetic") for i in range(8)))
        session = self.session(source=source)
        item = self.export(session)["exports"][0]
        result, _ = replay_to_store(self.root / "export" / item["wav"]["path"],
                                    self.root / "export" / item["manifest"]["path"], self.root / "max.sqlite3")
        self.assertEqual((result.sample_rate_hz, result.channel_count, result.frame_count), (384000, 8, 160))

    def test_pgm_source_refused_without_conversion(self):
        source = replace(self.source, media="pgm8", channels=self.source.channels[:1], sample_rate_hz=None)
        session = Session.create(self.root / "pgm", "image-session", (source,))
        session.append("audio-1", b"P5\n1 1\n255\n\x80", unit_start=0, units=1, source_start_s=0, source_end_s=1)
        session.finalize()
        with self.assertRaisesRegex(ExportError, "only PCM16"):
            self.export(session)

    def test_inconsistent_wav_rate_channels_or_encoding_rejected_by_real_recovery(self):
        for index, (offset, value) in enumerate(((24, struct.pack("<I", 16000)),
                                                (22, struct.pack("<H", 1)),
                                                (34, struct.pack("<H", 8)))):
            session = self.session(f"mismatch-{index}")
            wav = session.directory / "chunk-000000.wav"
            data = bytearray(wav.read_bytes())
            data[offset:offset + len(value)] = value
            wav.write_bytes(data)
            with self.subTest(offset=offset), self.assertRaisesRegex(SessionError, "WAV payload"):
                self.export(session)

    def test_unfinalized_sessions_refused_without_finalizing_them(self):
        session = self.session(finalize=False)
        with self.assertRaises((OSError, SessionError)):
            self.export(session)
        self.assertFalse((session.directory / FINAL).exists())
        self.assertFalse((self.root / "export").exists())

    def test_abnormal_final_states_are_refused_and_unknown_original_preserved(self):
        for state in ("source_failed", "capacity_halted", "recovered_incomplete"):
            session = self.session(state, finalize=False, max_chunks=1)
            if state == "source_failed":
                session.abort_source()
            elif state == "capacity_halted":
                with self.assertRaises(CapacityExceeded):
                    self.append(session, start=160)
            else:
                (session.directory / "unknown.original").write_bytes(b"retain this unrelated artifact")
            self.assertEqual(session.finalize()["state"], state)
            originals = {p.name: p.read_bytes() for p in session.directory.iterdir()}
            with self.subTest(state=state), self.assertRaisesRegex(ExportError, "normal finalized state"):
                self.export(session)
            self.assertEqual(originals, {p.name: p.read_bytes() for p in session.directory.iterdir()})
        self.assertFalse((self.root / "export").exists())

    def test_duplicate_selection_ids_and_existing_output_refused(self):
        session = self.session(finalize=False)
        self.append(session, start=160)
        session.finalize()
        for mappings in ((self.mapping, self.mapping),
                         (self.mapping, replace(self.mapping, segment_index=1))):
            with self.subTest(mappings=mappings), self.assertRaisesRegex(ExportError, "duplicate"):
                self.export(session, mappings=mappings)
        self.export(session)
        (self.root / "export" / "unknown.txt").write_bytes(b"not ours to delete")
        before = {p.name: p.read_bytes() for p in (self.root / "export").iterdir()}
        with self.assertRaisesRegex(ExportError, "already exists"):
            self.export(session)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / "export").iterdir()})

    def test_unknown_segment_source_or_cross_source_selection_refused(self):
        other = replace(self.source, source_id="audio-2")
        session = Session.create(self.root / "multi", "multi-session", (self.source, other))
        self.append(session)
        self.append(session, other)
        session.finalize()
        for options in ({"source_id": "missing"},
                        {"mappings": (replace(self.mapping, segment_index=1),)},
                        {"mappings": (replace(self.mapping, segment_index=2),)}):
            with self.subTest(options=options), self.assertRaises(SessionError):
                self.export(session, **options)
        self.assertFalse((self.root / "export").exists())

    def test_export_limits_include_all_metadata_and_commit_receipt(self):
        session = self.session()
        for kw in ({"max_bytes": 100}, {"max_bytes": True}, {"max_bytes": 256 * 1024 * 1024 + 1},
                   {"max_segments": 257}, {"max_segments": 0}, {"mappings": ()}):
            with self.subTest(kw=kw), self.assertRaises(SessionError):
                self.export(session, **kw)
        result = self.export(session, "measured")
        payload_size = result["bytes_excluding_receipt"]
        with self.assertRaisesRegex(ExportError, "including commit receipt"):
            self.export(session, max_bytes=payload_size + 100)
        self.assertFalse((self.root / "export").exists())
        session = self.session("two", finalize=False)
        self.append(session, start=160)
        session.finalize()
        with self.assertRaisesRegex(ExportError, "segment budget"):
            self.export(session, max_segments=1,
                        mappings=(self.mapping, replace(self.mapping, segment_index=1, recording_id="r-1")))

    def test_leaf_and_parent_symlinks_devices_and_nested_output_refused(self):
        session = self.session()
        (self.root / "alias").symlink_to(session.directory, target_is_directory=True)
        with self.assertRaisesRegex(ExportError, "not a symlink"):
            export_segments(self.root / "alias", self.root / "export", source_id="audio-1",
                            mappings=(self.mapping,), epoch=self.epoch)
        (self.root / "out-link").symlink_to(self.root, target_is_directory=True)
        for output in (self.root / "out-link" / "new", self.root / "out-link", session.directory / "nested"):
            with self.subTest(output=output), self.assertRaises(ExportError):
                export_segments(session.directory, output, source_id="audio-1", mappings=(self.mapping,), epoch=self.epoch)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ExportError):
            export_segments(session.directory, fifo, source_id="audio-1", mappings=(self.mapping,), epoch=self.epoch)
        wav = session.directory / "chunk-000000.wav"
        original = self.root / "original.wav"
        wav.rename(original)
        wav.symlink_to(original)
        with self.assertRaisesRegex(SessionError, "nonregular"):
            self.export(session)
        self.assertTrue(original.exists())

    def test_fifo_in_source_refused_without_open_or_hang(self):
        session = self.session()
        os.mkfifo(session.directory / "unknown-fifo")
        with self.assertRaisesRegex(SessionError, "nonregular"):
            self.export(session)

    def test_tampered_header_final_receipt_or_segment_refused(self):
        for index, name in enumerate((HEADER, FINAL, "chunk-000000.json", "chunk-000000.wav")):
            session = self.session(f"tamper-{index}")
            path = session.directory / name
            data = path.read_bytes()
            if name.endswith("wav"):
                altered = data[:-1] + bytes([data[-1] ^ 1])
            else:
                value = json.loads(data)
                value["tampered"] = True
                altered = canonical(value)
            path.write_bytes(altered)
            with self.subTest(name=name), self.assertRaises(SessionError):
                self.export(session)
            self.assertEqual(path.read_bytes(), altered)
        self.assertFalse((self.root / "export").exists())

    def test_tamper_during_copy_leaves_no_bundle_commit(self):
        session = self.session()
        changed = False

        def tamper(directory, name, data):
            nonlocal changed
            publish(directory, name, data)
            if not changed:
                path = session.directory / "chunk-000000.wav"
                wav = path.read_bytes()
                path.write_bytes(wav[:-1] + bytes([wav[-1] ^ 1]))
                changed = True

        with patch("poseidon_acoustic.legacy_export.publish", side_effect=tamper):
            with self.assertRaises(SessionError):
                self.export(session)
        self.assertTrue(changed)
        self.assertFalse((self.root / "export" / COMMIT).exists())

    def test_output_tamper_or_write_failure_leaves_no_bundle_commit(self):
        session = self.session()

        def tamper(directory, name, data):
            publish(directory, name, data)
            if name.endswith(".wav"):
                (directory / name).write_bytes(b"changed after copy")

        with patch("poseidon_acoustic.legacy_export.publish", side_effect=tamper):
            with self.assertRaisesRegex(ExportError, "output changed"):
                self.export(session)
        self.assertFalse((self.root / "export" / COMMIT).exists())
        with patch("poseidon_acoustic.legacy_export.publish", side_effect=OSError("injected write failure")):
            with self.assertRaisesRegex(OSError, "injected"):
                self.export(session, "write-failure")
        self.assertFalse((self.root / "write-failure" / COMMIT).exists())

    def test_commit_sync_failure_retracts_only_own_receipt(self):
        session = self.session()
        from poseidon_acoustic.legacy_export import _sync_directory
        triggered = False

        def fail_once(path):
            nonlocal triggered
            if (path / COMMIT).exists() and not triggered:
                triggered = True
                raise OSError("injected commit sync failure")
            return _sync_directory(path)

        with patch("poseidon_acoustic.legacy_export._sync_directory", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "injected commit sync"):
                self.export(session)
        self.assertTrue(triggered)
        self.assertFalse((self.root / "export" / COMMIT).exists())
        self.assertTrue((self.root / "export" / "chunk-000000.wav").exists())
        self.assertTrue((self.root / "export" / ".export-receipt.pending").exists())

    def test_zero_candidate_source_is_a_valid_stored_recording(self):
        session = Session.create(self.root / "quiet", "quiet-session", (self.source,))
        self.append(session, amplitude=0)
        session.finalize()
        item = self.export(session)["exports"][0]
        result, saved = replay_to_store(self.root / "export" / item["wav"]["path"],
                                        self.root / "export" / item["manifest"]["path"], self.root / "quiet.sqlite3")
        self.assertEqual(result.events, ())
        self.assertFalse(saved.already_present)
        with closing(sqlite3.connect(self.root / "quiet.sqlite3")) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_demo_is_deterministic_and_has_real_two_and_zero_candidate_replays(self):
        first, second = run_demo(self.root / "demo-1"), run_demo(self.root / "demo-2")
        self.assertEqual(first, second)
        self.assertEqual([item["candidate_count"] for item in first["replay"]], [2, 0])
        for folder in ("session", "export"):
            one = {p.name: p.read_bytes() for p in (self.root / "demo-1" / folder).iterdir()}
            two = {p.name: p.read_bytes() for p in (self.root / "demo-2" / folder).iterdir()}
            self.assertEqual(one, two)
        for name in ("events.ndjson", "demo-result.json"):
            self.assertEqual((self.root / "demo-1" / name).read_bytes(), (self.root / "demo-2" / name).read_bytes())
        events = [json.loads(line) for line in (self.root / "demo-1" / "events.ndjson").read_text().splitlines()]
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["provenance"] == "synthetic" and e["recording_id"] == "synthetic-export-0" for e in events))
        with self.assertRaisesRegex(ExportError, "already exists"):
            run_demo(self.root / "demo-1")

    def cli_args(self, session):
        return ["export", "--session", str(session.directory), "--output-dir", str(self.root / "cli-export"),
                "--source-id", "audio-1", "--site-id", "site-test", "--zone-id", "zone-test", "--device-id", "device-test",
                "--segment", "0=recording-0", "--reference-domain", "reference_seconds", "--reference-epoch", "test-start",
                "--epoch-utc", "2026-01-01T00:00:00Z", "--epoch-uncertainty-s", "0.005",
                "--epoch-declared-by", "fixture-operator", "--epoch-evidence-ref", "fixture-epoch-note"]

    def test_cli_export_and_demo_work_as_real_module_processes(self):
        session = self.session()
        commands = (self.cli_args(session), ["demo", "--output-dir", str(self.root / "cli-demo")])
        for args in commands:
            result = subprocess.run([sys.executable, "-m", "poseidon_acoustic.legacy_export_cli", *args],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsInstance(json.loads(result.stdout), dict)
        self.assertTrue((self.root / "cli-export" / COMMIT).exists())
        self.assertEqual(load_json(self.root / "cli-demo" / "demo-result.json")["candidate_count"], 2)

    def test_cli_refusals_are_exit_two_without_traceback_or_output(self):
        session = self.session()
        args = self.cli_args(session)
        for extra in (["--file-origin", "field"], ["--segment", "bad-selection"],
                      ["--epoch-utc", "2026-02-30T00:00:00Z"]):
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(main(args + extra), 2)
                self.assertIn("error:", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
        self.assertFalse((self.root / "cli-export").exists())


if __name__ == "__main__":
    unittest.main()
