"""Synthetic system scenarios against real local components; no field interfaces."""
from __future__ import annotations

from array import array
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[2]
for relative in ("apps/trident/src", "apps/acoustic/src", "libs/proto-py/src"):
    sys.path.insert(0, str(ROOT / relative))

from poseidon_proto import ModelValidationError, RecordingManifest
from poseidon_trident import Hub, HubError


def synthetic_recording(identity: str = "assurance-synthetic-v1") -> tuple[bytes, bytes]:
    samples = array("h", [0] * 20 + [20000] * 20 + [0] * 20)
    if sys.byteorder != "little":
        samples.byteswap()
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(1000)
        writer.writeframes(samples.tobytes())
    wav = output.getvalue()
    manifest = RecordingManifest(
        schema_version=1, recording_id=identity, site_id="synthetic-no-field-site",
        zone_id="synthetic-zone", device_id="synthetic-file-only",
        started_at="2026-09-08T00:00:00Z", provenance="synthetic",
        wav_sha256=hashlib.sha256(wav).hexdigest(), calibration_status="uncalibrated",
    )
    return wav, manifest.to_json().encode()


class ReferenceSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="poseidon-assurance-system-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "owned-workspace"

    def test_source_bound_replay_deduplication_review_restart(self) -> None:
        wav, manifest = synthetic_recording()
        with Hub(self.root) as hub:
            first = hub.submit_recording(io.BytesIO(wav), manifest)
            self.assertEqual(first, hub.submit_recording(io.BytesIO(wav), manifest))
            self.assertTrue(hub.process_next_job())
            self.assertFalse(hub.process_next_job())
            self.assertEqual(hub.get_job(first["id"])["status"], "succeeded")
            self.assertEqual(hub.list_events()["total"], 1)
            event = hub.list_events()["items"][0]
            self.assertEqual(event["event_type"], "acoustic_candidate")
            self.assertIs(event["emission_enabled"], False)
            record = hub.get_recording("assurance-synthetic-v1")
            self.assertEqual(record["wav_sha256"], hashlib.sha256(wav).hexdigest())
            self.assertEqual(record["provenance"], "synthetic")
            self.assertIsNone(record["video"])
            review = hub.save_review(event["event_id"], "uncertain", "Synthetic test only", "Assurance fixture", 0)
            with self.assertRaises(HubError):
                hub.save_review(event["event_id"], "non_feeding", "Stale test", "Assurance fixture", 0)
        with Hub(self.root) as hub:
            persisted = hub.get_event(event["event_id"])["event"]
            self.assertEqual(persisted["review"], review)
            self.assertEqual(persisted["event_type"], "acoustic_candidate")
            self.assertIs(persisted["emission_enabled"], False)
            self.assertEqual(hub.list_events()["total"], 1)
            self.assertIs(hub.status()["emission_enabled"], False)

    def test_conflicting_provenance_does_not_replace_evidence(self) -> None:
        wav, manifest = synthetic_recording()
        conflict = json.loads(manifest)
        conflict["provenance"] = "field"
        with Hub(self.root) as hub:
            first = hub.submit_recording(io.BytesIO(wav), manifest)
            with self.assertRaises(HubError) as caught:
                hub.submit_recording(io.BytesIO(wav), json.dumps(conflict).encode())
            self.assertEqual(caught.exception.code, "recording_conflict")
            self.assertTrue(hub.process_next_job())
            self.assertEqual(hub.get_job(first["id"])["status"], "succeeded")
            self.assertEqual(hub.get_recording("assurance-synthetic-v1")["provenance"], "synthetic")

    def test_wrong_source_hash_cannot_produce_candidate(self) -> None:
        wav, manifest = synthetic_recording()
        corrupt = bytearray(wav)
        corrupt[-1] ^= 1
        with Hub(self.root) as hub:
            with self.assertRaises(HubError):
                hub.submit_recording(io.BytesIO(corrupt), manifest)
            self.assertEqual(hub.list_events()["total"], 0)
            self.assertEqual(hub.list_recordings()["total"], 0)

    def test_unknown_user_files_remain_untouched(self) -> None:
        self.root.mkdir()
        user_file = self.root / "user-evidence.bin"
        user_file.write_bytes(b"UNOWNED USER CONTENT\x00\xff")
        before = user_file.read_bytes()
        before_stat = user_file.stat()
        with self.assertRaises(HubError):
            with Hub(self.root):
                self.fail("unknown workspace accepted")
        self.assertEqual(user_file.read_bytes(), before)
        after_stat = user_file.stat()
        for attribute in ("st_ino", "st_mode", "st_size", "st_mtime_ns"):
            self.assertEqual(getattr(after_stat, attribute), getattr(before_stat, attribute))
        # Hub may retain its lock inode after refusing an unknown directory.
        self.assertLessEqual({p.name for p in self.root.iterdir()}, {user_file.name, ".hub.lock"})
        self.assertFalse((self.root / "hub.sqlite3").exists())
        self.assertFalse((self.root / "access.token").exists())

    def test_v1_manifest_rejects_schema_and_calibration_promotion(self) -> None:
        _, manifest = synthetic_recording()
        fixture = json.loads(manifest)
        self.assertEqual(RecordingManifest.from_json(manifest.decode()).to_dict(), fixture)
        for change in ({"schema_version": 2}, {"schema_version": True},
                       {"calibration_status": "calibrated"}, {"underwater_spl_db": 120},
                       {"emission_enabled": True}):
            with self.subTest(change=change), self.assertRaises(ModelValidationError):
                RecordingManifest.from_dict(fixture | change)
        with self.assertRaises(ModelValidationError):
            RecordingManifest.from_json(manifest.decode().replace('"schema_version":1', '"schema_version":1,"schema_version":1'))


if __name__ == "__main__":
    unittest.main()
