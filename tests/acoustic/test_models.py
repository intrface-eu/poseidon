from __future__ import annotations

import json
import unittest

from poseidon_proto import (
    AcousticCandidateEvent,
    ModelValidationError,
    RecordingManifest,
)


class RecordingManifestTests(unittest.TestCase):
    def valid_data(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "recording_id": "recording-1",
            "site_id": "site.alpha",
            "zone_id": "zone_1",
            "device_id": "device-1",
            "started_at": "2026-01-02T03:04:05.123456+01:30",
            "provenance": "field",
            "wav_sha256": "a" * 64,
            "calibration_status": "uncalibrated",
        }

    def test_manifest_round_trip_and_fingerprint_are_deterministic(self) -> None:
        manifest = RecordingManifest.from_dict(self.valid_data())
        round_tripped = RecordingManifest.from_json(manifest.to_json())
        self.assertEqual(round_tripped, manifest)
        self.assertEqual(round_tripped.fingerprint(), manifest.fingerprint())
        self.assertEqual(json.loads(manifest.to_json())["schema_version"], 1)

    def test_manifest_rejects_bool_schema_version(self) -> None:
        data = self.valid_data()
        data["schema_version"] = True
        with self.assertRaises(ModelValidationError):
            RecordingManifest.from_dict(data)

    def test_manifest_rejects_bad_identifiers_timezone_and_hash(self) -> None:
        for field, value in (
            ("recording_id", ""),
            ("site_id", "site/escape"),
            ("zone_id", "zone space"),
            ("device_id", "-device"),
            ("started_at", "2026-01-02T03:04:05"),
            ("started_at", "2026-02-30T03:04:05Z"),
            ("wav_sha256", "A" * 64),
            ("wav_sha256", "a" * 63),
            ("calibration_status", "calibrated"),
        ):
            with self.subTest(field=field, value=value):
                data = self.valid_data()
                data[field] = value
                with self.assertRaises(ModelValidationError):
                    RecordingManifest.from_dict(data)

    def test_manifest_rejects_unknown_and_duplicate_json_fields(self) -> None:
        data = self.valid_data()
        data["claim"] = "predator"
        with self.assertRaises(ModelValidationError):
            RecordingManifest.from_dict(data)
        duplicate = '{"schema_version":1,"schema_version":1}'
        with self.assertRaises(ModelValidationError):
            RecordingManifest.from_json(duplicate)

    def test_manifest_rejects_oversized_json_integer_without_leaking_value_error(self) -> None:
        oversized = '{"schema_version":' + "9" * 5_000 + "}"
        with self.assertRaisesRegex(ModelValidationError, "exceeds supported limits"):
            RecordingManifest.from_json(oversized)


class AcousticCandidateEventTests(unittest.TestCase):
    def valid_data(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "event_id": "evt_abc",
            "recording_id": "recording-1",
            "site_id": "site-1",
            "zone_id": "zone-1",
            "device_id": "device-1",
            "event_type": "acoustic_candidate",
            "source": "replay",
            "provenance": "synthetic",
            "start_frame": 20,
            "end_frame": 40,
            "start_time_s": 0.02,
            "end_time_s": 0.04,
            "sample_rate_hz": 1000,
            "channel_count": 2,
            "normalized_peak_max": 0.75,
            "normalized_rms_max": 0.5,
            "amplitude_units": "normalized_pcm16_full_scale",
            "calibration_status": "uncalibrated",
            "detector_version": "normalized-rms-v1",
            "detector_config_id": "cfg_abc",
            "run_id": "run_abc",
            "emission_enabled": False,
        }

    def test_event_round_trip_has_no_classifier_claim(self) -> None:
        event = AcousticCandidateEvent.from_dict(self.valid_data())
        self.assertEqual(AcousticCandidateEvent.from_json(event.to_json()), event)
        serialized = event.to_dict()
        self.assertNotIn("confidence", serialized)
        self.assertNotIn("species", serialized)
        self.assertNotIn("predator", serialized)
        self.assertFalse(serialized["emission_enabled"])

    def test_event_rejects_bool_numeric_nonfinite_and_huge_numeric_values(self) -> None:
        cases = (
            ("start_frame", True),
            ("end_frame", 10**400),
            ("sample_rate_hz", False),
            ("start_time_s", True),
            ("normalized_peak_max", float("nan")),
            ("normalized_rms_max", float("inf")),
            ("normalized_rms_max", 10**400),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                data = self.valid_data()
                data[field] = value
                with self.assertRaises(ModelValidationError):
                    AcousticCandidateEvent.from_dict(data)

    def test_event_rejects_inconsistent_frame_times_and_enabled_emission(self) -> None:
        for field, value in (
            ("end_frame", 20),
            ("start_time_s", 0.03),
            ("normalized_rms_max", 0.8),
            ("event_type", "shell_crack"),
            ("emission_enabled", True),
        ):
            with self.subTest(field=field):
                data = self.valid_data()
                data[field] = value
                with self.assertRaises(ModelValidationError):
                    AcousticCandidateEvent.from_dict(data)


if __name__ == "__main__":
    unittest.main()
