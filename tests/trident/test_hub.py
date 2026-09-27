from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from poseidon_trident import Hub, HubError

from _support import active_wav, manifest_bytes


class HubFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"

    def test_empty_status_token_and_close(self) -> None:
        hub = Hub(self.root)
        token = hub.access_token()
        status = hub.status()
        self.assertEqual(status["mode"], "monitor_only")
        self.assertIs(status["emission_enabled"], False)
        self.assertEqual(status["state"], "ready")
        self.assertGreaterEqual(status["uptime_s"], 0.0)
        self.assertEqual(status["recordings"], 0)
        self.assertEqual(status["events"], 0)
        self.assertEqual(status["jobs"], {"queued": 0, "running": 0, "failed": 0})
        self.assertEqual(len(token), 43)
        self.assertEqual((self.root / "access.token").stat().st_mode & 0o777, 0o600)
        hub.close()
        hub.close()
        with self.assertRaises(HubError) as raised:
            hub.status()
        self.assertEqual(raised.exception.code, "hub_closed")

    def test_real_import_process_and_paginated_catalog(self) -> None:
        wav = active_wav()
        manifest = manifest_bytes(wav)
        with Hub(self.root) as hub:
            job = hub.submit_recording(io.BytesIO(wav), manifest)
            self.assertEqual(job["status"], "queued")
            self.assertEqual(job["recording_id"], "recording-1")
            self.assertIsNone(job["error"])
            self.assertEqual(hub.list_recordings()["total"], 0)
            self.assertTrue(hub.process_next_job())
            self.assertFalse(hub.process_next_job())

            completed = hub.get_job(job["id"])
            self.assertEqual(completed["status"], "succeeded")
            page = hub.list_jobs(limit=1, offset=0)
            self.assertEqual(page["total"], 1)
            self.assertEqual(page["items"], [completed])

            recording_page = hub.list_recordings(limit=1, offset=0)
            self.assertEqual(recording_page["total"], 1)
            recording = recording_page["items"][0]
            self.assertEqual(recording["recording_id"], "recording-1")
            self.assertEqual(recording["wav_sha256"], hashlib.sha256(wav).hexdigest())
            self.assertEqual(recording["duration_s"], 0.06)
            self.assertEqual(recording["sample_rate_hz"], 1_000)
            self.assertEqual(recording["channel_count"], 1)
            self.assertEqual(recording["event_count"], 1)
            self.assertEqual(recording["reviewed_count"], 0)
            self.assertIsNone(recording["video"])
            self.assertNotIn("path", recording)

            events = hub.list_events(limit=1, offset=0)
            self.assertEqual(events["total"], 1)
            event = events["items"][0]
            self.assertEqual(event["recording_id"], "recording-1")
            self.assertEqual(event["event_type"], "acoustic_candidate")
            self.assertEqual(event["source"], "replay")
            self.assertIs(event["emission_enabled"], False)
            self.assertIsNone(event["review"])
            detail = hub.get_event(event["event_id"])
            self.assertEqual(detail["event"], event)
            self.assertEqual(detail["recording"]["recording_id"], "recording-1")

            status = hub.status()
            self.assertEqual(status["recordings"], 1)
            self.assertEqual(status["events"], 1)
            self.assertEqual(status["jobs"], {"queued": 0, "running": 0, "failed": 0})

    def test_demo_reuses_one_synthetic_identity(self) -> None:
        with Hub(self.root) as hub:
            first = hub.submit_demo()
            second = hub.submit_demo()
            self.assertEqual(first, second)
            self.assertEqual(hub.list_jobs()["total"], 1)
            self.assertTrue(hub.process_next_job())
            third = hub.submit_demo()
            self.assertEqual(third["id"], first["id"])
            self.assertEqual(third["status"], "succeeded")
            recording = hub.get_recording("synthetic-demo-recording-v1")
            self.assertEqual(recording["provenance"], "synthetic")
            self.assertEqual(recording["event_count"], 2)

    def test_identical_duplicate_reuses_job_and_conflict_is_atomic(self) -> None:
        wav = active_wav()
        manifest = manifest_bytes(wav)
        conflict = manifest_bytes(wav, site_id="other-site")
        with Hub(self.root) as hub:
            first = hub.submit_recording(io.BytesIO(wav), manifest)
            duplicate = hub.submit_recording(io.BytesIO(wav), manifest)
            self.assertEqual(duplicate, first)
            with self.assertRaises(HubError) as raised:
                hub.submit_recording(io.BytesIO(wav), conflict)
            self.assertEqual(raised.exception.code, "recording_conflict")
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(hub.list_jobs()["total"], 1)
            self.assertEqual(
                {path.name for path in (self.root / "recordings").iterdir()},
                {"recording-1"},
            )
            self.assertEqual(list((self.root / ".staging").iterdir()), [])

    def test_reviews_are_append_only_filterable_and_revision_checked(self) -> None:
        wav = active_wav()
        with Hub(self.root) as hub:
            hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
            hub.process_next_job()
            event_id = hub.list_events()["items"][0]["event_id"]
            first = hub.save_review(
                event_id,
                "uncertain",
                "Needs another pass",
                "Operator A",
                0,
            )
            self.assertEqual(first["revision"], 1)
            second = hub.save_review(
                event_id,
                "non_feeding",
                "Transient handling noise",
                "Operator A",
                1,
            )
            self.assertEqual(second["revision"], 2)
            with self.assertRaises(HubError) as raised:
                hub.save_review(event_id, "uncertain", "stale", "Operator B", 1)
            self.assertEqual(raised.exception.code, "review_conflict")
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(hub.list_events(review="unreviewed")["total"], 0)
            filtered = hub.list_events(review="non_feeding")
            self.assertEqual(filtered["total"], 1)
            self.assertEqual(filtered["items"][0]["review"], second)
            self.assertEqual(hub.get_recording("recording-1")["reviewed_count"], 1)

        with Hub(self.root) as reopened:
            event = reopened.get_event(event_id)["event"]
            self.assertEqual(event["review"], second)
            with reopened._workspace.connect(read_only=True) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM review_history WHERE event_id = ?", (event_id,)
                ).fetchone()[0]
            self.assertEqual(count, 2)

    def test_public_validation_and_not_found_errors(self) -> None:
        with Hub(self.root) as hub:
            cases = (
                lambda: hub.list_jobs(limit=True),
                lambda: hub.list_recordings(offset=-1),
                lambda: hub.list_events(review="detector_says_yes"),
                lambda: hub.get_job("../secret"),
                lambda: hub.waveform("missing", points=15),
                lambda: hub.save_review(
                    "evt_" + "a" * 64,
                    "confirmed_feeding",
                    "",
                    "Operator",
                    0,
                ),
            )
            for operation in cases:
                with self.subTest(operation=operation):
                    with self.assertRaises(HubError) as raised:
                        operation()
                    self.assertIn(raised.exception.status_code, (400, 404))
                    self.assertIsInstance(raised.exception.code, str)
                    self.assertIsInstance(raised.exception.message, str)
            with self.assertRaises(HubError) as raised:
                hub.get_recording("missing")
            self.assertEqual(raised.exception.status_code, 404)
            with self.assertRaises(HubError) as raised:
                hub.video_path("missing")
            self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
