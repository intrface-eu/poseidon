from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from poseidon_acoustic.legacy_export import EpochDeclaration, FileOriginDeclaration, SegmentMapping, export_segments
from poseidon_acoustic.legacy_export_cli import run_demo
from poseidon_acoustic.legacy_export_reader import (
    ExportReadError, ExportReadLimits, file_map_resolver, validate_export_bundle,
)
from poseidon_acoustic.session import Channel, ClockMap, Session, Source, canonical, pcm16_wav, sha256
from poseidon_acoustic.replay import replay_to_store


class ExportReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = Source("audio", "pcm16-wav", "synthetic",
            (Channel("right", "synthetic right"), Channel("left", "synthetic left")),
            ClockMap("reference_seconds", "synthetic-epoch", reference_anchor_s=0.25,
                     drift_ppm=1000, anchor_uncertainty_s=0.01, drift_uncertainty_ppm=20),
            sample_rate_hz=8000, origin="synthetic reader arithmetic fixture")
        self.session = Session.create(self.root / "session", "capture-session", (self.source,))
        for index, start in enumerate((0, 8000)):
            units = 160
            samples = b"".join(struct.pack("<hh", 20000, -20000) if index == 0 else b"\0" * 4 for _ in range(units))
            self.session.append("audio", pcm16_wav(samples, 8000, 2), unit_start=start, units=units,
                source_start_s=start / 8000, source_end_s=(start + units) / 8000,
                dropped_units=100 if index else 0, gap_reason="synthetic missing interval" if index else "")
        self.session.finalize()
        self.epoch = EpochDeclaration("audio", "reference_seconds", "synthetic-epoch", "2026-01-01T00:00:00Z",
                                      0.005, "synthetic-operator", "synthetic-epoch-convention")
        self.mapping = SegmentMapping(0, "recording-first", "synthetic-site", "synthetic-zone", "synthetic-device")
        self.directory = self.root / "single"
        export_segments(self.session.directory, self.directory, source_id="audio", mappings=(self.mapping,), epoch=self.epoch)
        self.receipt = (self.directory / "export.receipt.json").read_bytes()
        self.files = {item["path"]: (self.directory / item["path"]).read_bytes() for item in json.loads(self.receipt)["files"]}

    def validate(self, receipt=None, files=None, limits=None):
        return validate_export_bundle(self.receipt if receipt is None else receipt,
            file_map_resolver(self.files if files is None else files), limits=limits or ExportReadLimits())

    def rehash(self, change):
        """Change semantics, then update every byte-hash reference to exercise real validation."""
        files = dict(self.files)
        objects = {name: json.loads(raw) for name, raw in files.items() if name.endswith(".json")}
        document = json.loads(self.receipt)
        change(objects, document, files)
        header = objects["source-header.json"]
        final = objects["source-final.json"]
        record = objects["source-receipt-000000.json"]
        binding = objects["binding-000000.json"]
        def ref(name):
            return {"path": name, "bytes": len(files[name]), "sha256": sha256(files[name])}
        files["source-header.json"] = canonical(header)
        record["header_sha256"] = sha256(files["source-header.json"])
        record["sha256"] = sha256(files["chunk-000000.wav"])
        record["bytes"] = len(files["chunk-000000.wav"])
        files["source-receipt-000000.json"] = canonical(record)
        final["header_sha256"] = sha256(files["source-header.json"])
        final["segments"][0]["receipt_sha256"] = sha256(files["source-receipt-000000.json"])
        final["segments"][0]["sha256"] = sha256(files["chunk-000000.wav"])
        files["source-final.json"] = canonical(final)
        files["recording-000000.v1.json"] = canonical(objects["recording-000000.v1.json"])
        binding["original_header"]["exported_copy"] = ref("source-header.json")
        binding["original_final"]["exported_copy"] = ref("source-final.json")
        binding["original_receipt"]["exported_copy"] = ref("source-receipt-000000.json")
        binding["original_receipt"]["record"] = record
        binding["exported_wav"] = ref("chunk-000000.wav")
        binding["original_segment"].update(sha256=sha256(files["chunk-000000.wav"]), bytes=len(files["chunk-000000.wav"]))
        binding["recording_manifest"] = ref("recording-000000.v1.json")
        files["binding-000000.json"] = canonical(binding)
        document["original_header"] = ref("source-header.json")
        document["original_final"] = ref("source-final.json")
        document["exports"][0].update(wav=ref("chunk-000000.wav"), manifest=ref("recording-000000.v1.json"), binding=ref("binding-000000.json"))
        document["files"] = [ref(name) for name in sorted(files)]
        document["bytes_excluding_receipt"] = sum(map(len, files.values()))
        return canonical(document), files

    def test_real_single_export_immutable_raw_roles_projection_and_replay(self):
        value = self.validate()
        self.assertEqual(value.capture_session_id, "capture-session")
        self.assertEqual(value.source_id, "audio")
        self.assertEqual(value.selected_index, 0)
        self.assertEqual(len(value.files), 7)
        self.assertEqual(value.manifest.recording_id, "recording-first")
        for item in value.files:
            self.assertEqual(item.data, self.receipt if item.role == "export_receipt" else self.files[item.name])
            self.assertEqual(item.sha256, sha256(item.data))
            self.assertEqual(item.size, len(item.data))
        projection = json.loads(value.projection_bytes)
        self.assertEqual([c["channel_id"] for c in projection["source"]["channels"]], ["right", "left"])
        self.assertTrue(projection["verification"]["selected_segment_bytes_verified"])
        for key in ("full_original_session_bytes_verified", "original_input_bytes_verified", "predecessor_receipt_bytes_verified",
                    "acquisition_completeness_verified", "clock_relation_verified", "epoch_declaration_verified", "origin_verified", "authorization_verified"):
            self.assertIs(projection["verification"][key], False)
        result, _ = replay_to_store(self.directory / value.file_for_role("wav").name,
                                    self.directory / value.file_for_role("manifest").name, self.root / "evidence.sqlite3")
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].provenance, "synthetic")
        with self.assertRaises(FrozenInstanceError):
            value.source_id = "mutated"
        with self.assertRaises(FrozenInstanceError):
            value.manifest.site_id = "mutated"
        with self.assertRaises(FrozenInstanceError):
            value.files[0].data = b"mutated"
        projection["source_id"] = "local detached mutation"
        self.assertEqual(json.loads(value.projection_bytes)["source_id"], "audio")

    def test_later_zero_candidate_export_preserves_gap_but_not_predecessor_verification(self):
        destination = self.root / "later"
        export_segments(self.session.directory, destination, source_id="audio",
                        mappings=(replace(self.mapping, segment_index=1, recording_id="recording-later"),), epoch=self.epoch)
        receipt = (destination / "export.receipt.json").read_bytes()
        files = {item["path"]: (destination / item["path"]).read_bytes() for item in json.loads(receipt)["files"]}
        value = self.validate(receipt, files)
        projection = json.loads(value.projection_bytes)
        self.assertEqual(projection["selected_receipt"]["missing_units"], 7840)
        self.assertEqual(projection["selected_receipt"]["dropped_units"], 100)
        self.assertFalse(projection["verification"]["predecessor_receipt_bytes_verified"])
        self.assertNotIn("source-receipt-000000.json", files)
        result, _ = replay_to_store(destination / value.file_for_role("wav").name,
                                    destination / value.file_for_role("manifest").name, self.root / "quiet.sqlite3")
        self.assertEqual(result.events, ())

    def test_reader_has_no_filesystem_recovery_writer_or_native_side_effect(self):
        resolver = file_map_resolver(self.files)
        calls = []
        def bounded(name, cap):
            calls.append((name, cap)); return resolver(name, cap)
        with patch.object(Session, "recover", side_effect=AssertionError("recovery forbidden")), \
             patch.object(Session, "__init__", side_effect=AssertionError("session construction forbidden")), \
             patch("builtins.open", side_effect=AssertionError("filesystem open forbidden")), \
             patch.object(Path, "open", side_effect=AssertionError("path open forbidden")):
            value = validate_export_bundle(self.receipt, bounded, limits=ExportReadLimits())
        self.assertEqual(len(calls), 6)
        self.assertEqual(len(value.files), 7)

    def test_map_resolver_snapshots_input_and_missing_extra_files_refused(self):
        mutable = dict(self.files); resolver = file_map_resolver(mutable)
        mutable.clear()
        self.assertEqual(validate_export_bundle(self.receipt, resolver, limits=ExportReadLimits()).source_id, "audio")
        with self.assertRaises(ExportReadError):
            file_map_resolver({})
        with self.assertRaises(ExportReadError):
            file_map_resolver({**self.files, "unexpected": b"x"})
        with self.assertRaises(ExportReadError):
            self.validate(files={name: bytearray(data) for name, data in self.files.items()})

    def test_existing_multi_export_fixture_refused_and_writer_golden_unchanged(self):
        run_demo(self.root / "multi")
        receipt = (self.root / "multi/export/export.receipt.json").read_bytes()
        self.assertEqual(sha256(receipt), "d63f5c492b948483ea25811483ea3e606f0f3b69cf75045eeae064e6b9da9804")
        with self.assertRaisesRegex(ExportReadError, "exactly one"):
            validate_export_bundle(receipt, lambda name, cap: b"", limits=ExportReadLimits())

    def test_each_raw_file_tamper_refused(self):
        for name in self.files:
            with self.subTest(name=name):
                changed = dict(self.files); changed[name] += b"x"
                with self.assertRaises(ExportReadError):self.validate(files=changed)

    def test_strict_json_duplicate_nonfinite_deep_noncanonical_and_types(self):
        for raw in (b"", b"[]\n", b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b'{"x":' + b"[" * 40 + b"0" + b"]" * 40 + b'}\n',
                    self.receipt.rstrip(), b" " + self.receipt, b"\xff", bytearray(self.receipt)):
            with self.subTest(raw=str(raw)[:60]), self.assertRaises(ExportReadError): self.validate(receipt=raw)

    def test_role_path_and_declared_size_hash_bounds_rejected_before_resolver(self):
        for change in [lambda r:r["files"][0].update(path="../outside"), lambda r:r["files"][0].update(bytes=True),
                       lambda r:r["files"][0].update(bytes=10**20), lambda r:r["files"][0].update(sha256="0"),
                       lambda r:r.update(selected_segments=True)]:
            r = json.loads(self.receipt); change(r)
            with self.assertRaises(ExportReadError):
                validate_export_bundle(canonical(r), lambda *args: self.fail("resolver must not run"), limits=ExportReadLimits())

    def test_exact_limits_and_lower_limits(self):
        self.validate(limits=ExportReadLimits())
        for key in ("wav_bytes", "manifest_bytes", "binding_bytes", "source_receipt_bytes", "source_header_bytes", "source_final_bytes", "export_receipt_bytes", "aggregate_companion_bytes"):
            with self.subTest(key=key), self.assertRaises(ExportReadError):
                self.validate(limits=replace(ExportReadLimits(), **{key: 1}))
        for value in (True, 0, -1, float("nan"), 10**20):
            with self.assertRaises(ExportReadError): ExportReadLimits(wav_bytes=value)

    def test_hash_rewritten_verification_calibration_completeness_claims_refused(self):
        for target, key, val in [("binding-000000.json", "hardware_verified", True),
                                 ("binding-000000.json", "authorization_verified", True),
                                 ("binding-000000.json", "acquisition_completeness_verified", True),
                                 ("source-header.json", "calibration", "calibrated"),
                                 ("source-final.json", "state", "source_failed")]:
            def change(objects, receipt, files):objects[target][key] = val
            raw, files = self.rehash(change)
            with self.subTest(target=target, key=key), self.assertRaises(ExportReadError):self.validate(raw, files)

    def test_hash_rewritten_clock_projection_or_channel_order_refused(self):
        changes = [
            lambda o,r,f:o["binding-000000.json"]["time"].update(combined_start_uncertainty_s="0"),
            lambda o,r,f:o["binding-000000.json"]["time"]["epoch_declaration"].update(reference_epoch="wrong"),
            lambda o,r,f:o["binding-000000.json"]["time"].update(epoch_declaration_verified=True),
            lambda o,r,f:o["source-receipt-000000.json"].update(reference_start_s=999),
            lambda o,r,f:o["binding-000000.json"]["source"]["channels"].reverse(),
        ]
        for change in changes:
            raw, files = self.rehash(change)
            with self.assertRaises(ExportReadError):self.validate(raw, files)

    def test_missing_original_clock_fields_cannot_gain_default_zero(self):
        def change(objects, receipt, files):
            objects["source-header.json"]["sources"][0]["clock"].pop("anchor_uncertainty_s")
        raw, files = self.rehash(change)
        with self.assertRaises(ExportReadError):self.validate(raw, files)

    def test_hash_rewritten_selected_frame_rate_geometry_and_counter_lies_refused(self):
        for change in [
            lambda o,r,f:o["source-receipt-000000.json"].update(units=161),
            lambda o,r,f:o["source-receipt-000000.json"].update(unit_start=2**53),
            lambda o,r,f:o["source-receipt-000000.json"].update(missing_units=1),
            lambda o,r,f:o["source-receipt-000000.json"].update(dropped_units=1),
            lambda o,r,f:o["source-header.json"]["sources"][0].update(sample_rate_hz=384001),
            lambda o,r,f:o["source-final.json"]["accounting"]["audio"].update(stored_units=0),
        ]:
            raw, files = self.rehash(change)
            with self.assertRaises(ExportReadError):self.validate(raw, files)

    def test_selected_final_membership_and_extra_fields_refused(self):
        for change in [lambda o,r,f:o["source-final.json"]["segments"][0].update(source_id="other"),
                       lambda o,r,f:o["binding-000000.json"].update(extra="must not silently drop"),
                       lambda o,r,f:r.update(extra=True)]:
            raw, files = self.rehash(change)
            with self.assertRaises(ExportReadError):self.validate(raw, files)

    def test_declared_field_origin_stays_unverified_and_bench_is_refused(self):
        source = replace(self.source, provenance="file", input_sha256="a" * 64,
                         origin="SYNTHETIC branch-coverage fixture, not field evidence")
        session = Session.create(self.root / "field-claim-session", "claim-fixture", (source,))
        session.append("audio", pcm16_wav(bytes([1, 0]) * 320, 8000, 2), unit_start=0, units=160,
                       source_start_s=0.0, source_end_s=0.02)
        session.finalize()
        origin = FileOriginDeclaration("audio", "a" * 64, "field", "synthetic-declarant", "synthetic-unverified-claim")
        destination = self.root / "field-claim-export"
        export_segments(session.directory, destination, source_id="audio", mappings=(self.mapping,), epoch=self.epoch, file_origin=origin)
        receipt = (destination / "export.receipt.json").read_bytes()
        files = {item["path"]: (destination / item["path"]).read_bytes() for item in json.loads(receipt)["files"]}
        value = self.validate(receipt, files)
        self.assertEqual(value.manifest.provenance, "field")
        projection = json.loads(value.projection_bytes)
        self.assertIs(projection["verification"]["origin_verified"], False)
        self.assertIs(projection["verification"]["original_input_bytes_verified"], False)
        self.assertIs(projection["verification"]["authorization_verified"], False)
        # A fully rehashed wrong origin cannot bypass the accepted projection rule.
        self.receipt, self.files = receipt, files
        def change(objects, doc, data):
            objects["binding-000000.json"]["provenance"]["file_origin_declaration"]["origin"] = "bench"
        changed, files = self.rehash(change)
        with self.assertRaises(ExportReadError): self.validate(changed, files)

    def test_null_epoch_uncertainty_and_forged_previous_hash_refused(self):
        for change in [lambda o,r,f:o["binding-000000.json"]["time"]["epoch_declaration"].update(uncertainty_s=None),
                       lambda o,r,f:o["source-receipt-000000.json"].update(previous_receipt_sha256="a" * 64),
                       lambda o,r,f:o["source-header.json"]["sources"][0]["clock"].update(anchor_uncertainty_s=None)]:
            raw, files = self.rehash(change)
            with self.assertRaises(ExportReadError): self.validate(raw, files)

    def test_malformed_file_map_and_resolver_errors_are_export_read_errors(self):
        invalid = dict(self.files)
        name, value = invalid.popitem(); invalid["../unsafe"] = value
        with self.assertRaises(ExportReadError): file_map_resolver(invalid)
        def failing(name, cap): raise OSError("private resolver failure")
        with self.assertRaises(ExportReadError):
            validate_export_bundle(self.receipt, failing, limits=ExportReadLimits())
        with self.assertRaises(ExportReadError):
            validate_export_bundle(self.receipt, file_map_resolver(self.files), limits=None)

    def test_original_final_preserves_writer_accepted_whitespace_and_json_encodings(self):
        final_path = self.session.directory / "segments.acquisition-v1.json"
        original = json.loads(final_path.read_bytes())
        for index, encoding in enumerate(("utf-8", "utf-16", "utf-8-sig")):
            raw_final = json.dumps(original, indent=2).encode(encoding)
            final_path.write_bytes(raw_final)
            destination = self.root / f"noncanonical-final-{index}"
            export_segments(self.session.directory, destination, source_id="audio", mappings=(self.mapping,), epoch=self.epoch)
            receipt = (destination / "export.receipt.json").read_bytes()
            files = {item["path"]: (destination / item["path"]).read_bytes() for item in json.loads(receipt)["files"]}
            value = self.validate(receipt, files)
            self.assertEqual(value.file_for_role("source_final").data, raw_final)
            self.assertEqual(value.final_sha256, sha256(raw_final))
            self.assertFalse(json.loads(value.projection_bytes)["verification"]["full_original_session_bytes_verified"])

    def test_unused_other_source_metadata_is_retained_without_payload_verification(self):
        second = replace(self.source, source_id="unused", channels=(Channel("other", "synthetic unused"),))
        session = Session.create(self.root / "unused-source", "multiple-sources", (self.source, second))
        session.append("audio", pcm16_wav(bytes([1, 0]) * 320, 8000, 2), unit_start=0, units=160,
                       source_start_s=0.0, source_end_s=0.02)
        session.finalize()
        destination = self.root / "unused-source-export"
        export_segments(session.directory, destination, source_id="audio", mappings=(self.mapping,), epoch=self.epoch)
        receipt = (destination / "export.receipt.json").read_bytes()
        files = {item["path"]: (destination / item["path"]).read_bytes() for item in json.loads(receipt)["files"]}
        value = self.validate(receipt, files)
        self.assertIn(b'"source_id":"unused"', value.file_for_role("source_header").data)
        self.assertFalse(json.loads(value.projection_bytes)["verification"]["full_original_session_bytes_verified"])

    def test_dependency_free_subprocess_no_site_packages(self):
        script = '''
import json,sys
from pathlib import Path
from poseidon_acoustic.legacy_export_reader import ExportReadLimits,file_map_resolver,validate_export_bundle
p=Path(sys.argv[1]); raw=(p/'export.receipt.json').read_bytes()
files={entry['path']:(p/entry['path']).read_bytes() for entry in json.loads(raw)['files']}
v=validate_export_bundle(raw,file_map_resolver(files),limits=ExportReadLimits())
assert len(v.files)==7
assert not any(name in sys.modules for name in ('av','ctypes','poseidon_api','poseidon_nereid.codec'))
print(v.manifest.recording_id)
'''
        result = subprocess.run([sys.executable, "-S", "-c", script, str(self.directory)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "recording-first")


if __name__ == "__main__":
    unittest.main()
