from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from poseidon_acoustic.detector import DetectorConfig, detect_wav
from poseidon_acoustic.errors import InputError
from poseidon_acoustic.replay import replay_to_store

from _support import (
    file_sha256,
    manifest_for,
    mono_windows,
    write_manifest,
    write_pcm16_wav,
    write_pcm8_wav,
)


class DetectorTests(unittest.TestCase):
    def test_two_candidates_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp) / "two.wav"
            write_pcm16_wav(wav, mono_windows(0, 20_000, 20_000, 0, 0, 20_000, 0))
            manifest = manifest_for(wav)
            config = DetectorConfig()
            first = detect_wav(wav, manifest, config)
            second = detect_wav(wav, manifest, config)
            self.assertEqual(first, second)
            self.assertEqual(
                [(event.start_frame, event.end_frame) for event in first.events],
                [(20, 60), (100, 120)],
            )
            self.assertEqual(len({event.event_id for event in first.events}), 2)
            self.assertTrue(all(event.event_type == "acoustic_candidate" for event in first.events))

    def test_silence_has_no_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp) / "silence.wav"
            write_pcm16_wav(wav, mono_windows(0, 0, 0))
            result = detect_wav(wav, manifest_for(wav), DetectorConfig())
            self.assertEqual(result.events, ())

    def test_stereo_antiphase_does_not_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp) / "antiphase.wav"
            frames = [(20_000, -20_000) for _ in range(40)]
            write_pcm16_wav(wav, frames)
            result = detect_wav(wav, manifest_for(wav), DetectorConfig())
            self.assertEqual(len(result.events), 1)
            self.assertEqual((result.events[0].start_frame, result.events[0].end_frame), (0, 40))
            self.assertEqual(result.events[0].channel_count, 2)
            self.assertGreater(result.events[0].normalized_rms_max, 0.6)

    def test_final_partial_window_and_eof_event_use_end_exclusive_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            wav = Path(temp) / "partial.wav"
            frames = [(0,)] * 20 + [(20_000,)] * 25
            write_pcm16_wav(wav, frames)
            result = detect_wav(wav, manifest_for(wav), DetectorConfig())
            self.assertEqual(len(result.events), 1)
            event = result.events[0]
            self.assertEqual((event.start_frame, event.end_frame), (20, 45))
            self.assertEqual(event.end_time_s, 0.045)
            self.assertEqual(result.frame_count, 45)

    def test_rejects_unsupported_sample_width_and_channel_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pcm8 = root / "pcm8.wav"
            write_pcm8_wav(pcm8, bytes([128] * 40))
            with self.assertRaisesRegex(InputError, "16-bit"):
                detect_wav(pcm8, manifest_for(pcm8), DetectorConfig())

            nine_channels = root / "nine.wav"
            write_pcm16_wav(nine_channels, [(0,) * 9 for _ in range(20)], channels=9)
            with self.assertRaisesRegex(InputError, "channel count"):
                detect_wav(nine_channels, manifest_for(nine_channels), DetectorConfig())

    def test_truncated_pcm_is_rejected_before_database_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav = root / "truncated.wav"
            write_pcm16_wav(wav, mono_windows(20_000, 20_000))
            wav.write_bytes(wav.read_bytes()[:-1])
            manifest = manifest_for(wav)
            manifest_path = root / "manifest.json"
            write_manifest(manifest_path, manifest)
            database = root / "evidence.sqlite3"
            with self.assertRaisesRegex(InputError, "incomplete|truncated"):
                replay_to_store(wav, manifest_path, database, DetectorConfig())
            self.assertFalse(database.exists())

    def test_manifest_hash_mismatch_is_rejected_before_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav = root / "source.wav"
            write_pcm16_wav(wav, mono_windows(20_000))
            manifest = manifest_for(wav)
            data = manifest.to_dict()
            data["wav_sha256"] = "0" * 64
            from poseidon_proto import RecordingManifest

            manifest_path = root / "manifest.json"
            write_manifest(manifest_path, RecordingManifest.from_dict(data))
            database = root / "evidence.sqlite3"
            with self.assertRaisesRegex(InputError, "SHA-256"):
                replay_to_store(wav, manifest_path, database, DetectorConfig())
            self.assertFalse(database.exists())
            self.assertNotEqual(file_sha256(wav), "0" * 64)


class DetectorConfigTests(unittest.TestCase):
    def test_rejects_invalid_thresholds(self) -> None:
        for value in (True, False, 0, -0.1, 1.01, float("nan"), float("inf"), -float("inf"), 10**400):
            with self.subTest(value=value):
                with self.assertRaises(InputError):
                    DetectorConfig(threshold=value)

    def test_rejects_invalid_windows(self) -> None:
        for value in (True, False, 0, -1, 10_001, float("nan"), float("inf"), 10**400):
            with self.subTest(value=value):
                with self.assertRaises(InputError):
                    DetectorConfig(window_ms=value)

    def test_different_config_has_distinct_identity(self) -> None:
        first = DetectorConfig(threshold=0.2, window_ms=20)
        second = DetectorConfig(threshold=0.3, window_ms=20)
        self.assertNotEqual(first.config_id(1_000), second.config_id(1_000))


if __name__ == "__main__":
    unittest.main()
