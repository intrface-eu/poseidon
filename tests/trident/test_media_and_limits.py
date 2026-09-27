from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from poseidon_trident import Hub, HubError
from poseidon_trident import media

from _support import active_wav, manifest_bytes, mp4_bytes, wav_bytes


class MediaAndLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"

    def test_manifest_hash_header_and_duration_fail_before_queue(self) -> None:
        valid = active_wav()
        malformed = b"not a wav file"
        too_long = wav_bytes([(0,)] * 1801, sample_rate=1)
        with Hub(self.root) as hub:
            failures = (
                (io.BytesIO(malformed), manifest_bytes(malformed), "invalid_wav", 400),
                (io.BytesIO(valid + b"changed"), manifest_bytes(valid), "wav_hash_mismatch", 400),
                (io.BytesIO(too_long), manifest_bytes(too_long), "wav_too_long", 413),
                (io.BytesIO(valid), b" " * (media.MAX_MANIFEST_BYTES + 1), "manifest_too_large", 413),
            )
            for stream, manifest, code, status in failures:
                with self.subTest(code=code):
                    with self.assertRaises(HubError) as raised:
                        hub.submit_recording(stream, manifest)
                    self.assertEqual(raised.exception.code, code)
                    self.assertEqual(raised.exception.status_code, status)
                    self.assertEqual(hub.list_jobs()["total"], 0)
                    self.assertEqual(list((self.root / "recordings").iterdir()), [])
                    self.assertEqual(list((self.root / ".staging").iterdir()), [])

    def test_streamed_byte_limits_use_actual_bytes(self) -> None:
        self.assertEqual(media.MAX_WAV_BYTES, 64 * 1024 * 1024)
        self.assertEqual(media.MAX_VIDEO_BYTES, 64 * 1024 * 1024)
        wav = active_wav()
        with Hub(self.root) as hub:
            with mock.patch.object(media, "MAX_WAV_BYTES", len(wav) - 1):
                with self.assertRaises(HubError) as raised:
                    hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
            self.assertEqual(raised.exception.code, "wav_too_large")
            self.assertEqual(raised.exception.status_code, 413)
            self.assertEqual(hub.list_jobs()["total"], 0)

            hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
            hub.process_next_job()
            video = mp4_bytes(b"123456789")
            with mock.patch.object(media, "MAX_VIDEO_BYTES", len(video) - 1):
                with self.assertRaises(HubError) as raised:
                    hub.attach_video("recording-1", io.BytesIO(video), 0.0)
            self.assertEqual(raised.exception.code, "video_too_large")
            self.assertEqual(raised.exception.status_code, 413)
            self.assertEqual(list((self.root / "videos").iterdir()), [])
            self.assertEqual(list((self.root / ".staging").iterdir()), [])

    def test_active_job_limit_is_durable(self) -> None:
        empty = wav_bytes([], sample_rate=1_000)
        with Hub(self.root) as hub:
            for index in range(32):
                job = hub.submit_recording(
                    io.BytesIO(empty),
                    manifest_bytes(empty, recording_id=f"recording-{index}"),
                )
                self.assertEqual(job["status"], "queued")
            with self.assertRaises(HubError) as raised:
                hub.submit_recording(
                    io.BytesIO(empty),
                    manifest_bytes(empty, recording_id="recording-over-limit"),
                )
            self.assertEqual(raised.exception.code, "queue_full")
            self.assertEqual(raised.exception.status_code, 429)
            self.assertEqual(hub.list_jobs(limit=200)["total"], 32)
            self.assertEqual(len(list((self.root / "recordings").iterdir())), 32)
            self.assertEqual(list((self.root / ".staging").iterdir()), [])

    def test_failed_replay_commits_no_evidence_or_recording(self) -> None:
        wav = active_wav()
        with Hub(self.root) as hub:
            job = hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
            stored_manifest = self.root / "recordings" / "recording-1" / "manifest.json"
            stored_manifest.chmod(0o600)
            stored_manifest.write_bytes(b"{}")
            stored_manifest.chmod(0o400)

            self.assertTrue(hub.process_next_job())
            failed = hub.get_job(job["id"])
            self.assertEqual(failed["status"], "failed")
            self.assertIsInstance(failed["error"], str)
            self.assertNotIn(str(self.root), failed["error"])
            self.assertEqual(hub.list_recordings()["total"], 0)
            self.assertEqual(hub.list_events()["total"], 0)
            with hub._workspace.evidence_connection(read_only=True) as connection:
                counts = tuple(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("recordings", "runs", "events")
                )
            self.assertEqual(counts, (0, 0, 0))
            self.assertTrue((self.root / "recordings" / "recording-1" / "source.wav").is_file())

    def test_waveform_combines_channel_extrema_with_correct_buckets(self) -> None:
        frames = [
            (-32768, 100),
            (1000, 32767),
            (-100, 200),
            (300, -400),
        ]
        wav = wav_bytes(frames, sample_rate=1_000)
        with Hub(self.root) as hub:
            hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
            hub.process_next_job()
            result = hub.waveform("recording-1", points=16)
            self.assertEqual(result["recording_id"], "recording-1")
            self.assertEqual(result["duration_s"], 0.004)
            self.assertEqual(result["sample_rate_hz"], 1_000)
            self.assertEqual(result["channel_count"], 2)
            self.assertEqual(result["amplitude_units"], "normalized_pcm16_full_scale")
            self.assertEqual(result["calibration_status"], "uncalibrated")
            self.assertEqual(len(result["buckets"]), 4)
            expected = [
                (0.0, 0.001, -1.0, 100 / 32768),
                (0.001, 0.002, 1000 / 32768, 32767 / 32768),
                (0.002, 0.003, -100 / 32768, 200 / 32768),
                (0.003, 0.004, -400 / 32768, 300 / 32768),
            ]
            for bucket, values in zip(result["buckets"], expected, strict=True):
                self.assertEqual(bucket["start_s"], values[0])
                self.assertEqual(bucket["end_s"], values[1])
                self.assertAlmostEqual(bucket["min"], values[2])
                self.assertAlmostEqual(bucket["max"], values[3])
            with self.assertRaises(HubError):
                hub.waveform("recording-1", points=True)

    def test_video_is_bounded_immutable_and_uses_trusted_path(self) -> None:
        wav = active_wav()
        video = mp4_bytes()
        with Hub(self.root) as hub:
            hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
            hub.process_next_job()
            metadata = hub.attach_video("recording-1", io.BytesIO(video), offset_s=-0.25)
            self.assertEqual(metadata["sha256"], hashlib.sha256(video).hexdigest())
            self.assertEqual(metadata["offset_s"], -0.25)
            self.assertEqual(metadata["alignment"], "operator_declared")
            path = hub.video_path("recording-1")
            self.assertEqual(path, self.root / "videos" / "recording-1.mp4")
            self.assertEqual(path.read_bytes(), video)
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)
            self.assertEqual(hub.get_recording("recording-1")["video"], metadata)
            with self.assertRaises(HubError) as raised:
                hub.attach_video("recording-1", io.BytesIO(mp4_bytes(b"other")), 0)
            self.assertEqual(raised.exception.code, "video_conflict")
            self.assertEqual(path.read_bytes(), video)

        with Hub(self.root) as reopened:
            self.assertEqual(reopened.video_path("recording-1").read_bytes(), video)
            self.assertEqual(reopened.get_recording("recording-1")["video"], metadata)

    def test_invalid_video_and_preexisting_symlink_are_preserved(self) -> None:
        wav = active_wav()
        outside = Path(self.temporary.name) / "outside.mp4"
        outside.write_bytes(b"outside")
        with Hub(self.root) as hub:
            hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
            hub.process_next_job()
            with self.assertRaises(HubError) as raised:
                hub.attach_video("recording-1", io.BytesIO(b"not-mp4"), 0.0)
            self.assertEqual(raised.exception.code, "invalid_video")
            self.assertEqual(list((self.root / "videos").iterdir()), [])

            target = self.root / "videos" / "recording-1.mp4"
            target.symlink_to(outside)
            with self.assertRaises(HubError) as raised:
                hub.attach_video("recording-1", io.BytesIO(mp4_bytes()), 0.0)
            self.assertEqual(raised.exception.code, "unsafe_workspace")
            self.assertTrue(target.is_symlink())
            self.assertEqual(outside.read_bytes(), b"outside")
            target.unlink()
            with self.assertRaises(HubError):
                hub.attach_video("recording-1", io.BytesIO(mp4_bytes()), offset_s=True)


if __name__ == "__main__":
    unittest.main()
