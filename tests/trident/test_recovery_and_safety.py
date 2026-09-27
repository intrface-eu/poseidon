from __future__ import annotations

import io
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from poseidon_trident import Hub, HubError
import poseidon_trident.hub as hub_module

from _support import active_wav, manifest_bytes


class RecoveryConcurrencyAndSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"

    def test_token_and_queued_job_persist_across_restart(self) -> None:
        wav = active_wav()
        first = Hub(self.root)
        token = first.access_token()
        job = first.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
        first.close()

        with Hub(self.root) as second:
            self.assertEqual(second.access_token(), token)
            self.assertEqual(second.get_job(job["id"])["status"], "queued")
            self.assertTrue(second.process_next_job())
            self.assertEqual(second.get_job(job["id"])["status"], "succeeded")

    def test_interrupted_running_job_is_reclaimed_after_restart(self) -> None:
        wav = active_wav()
        with Hub(self.root) as hub:
            job = hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
        connection = sqlite3.connect(self.root / "hub.sqlite3")
        try:
            connection.execute(
                "UPDATE jobs SET status = 'running' WHERE id = ?", (job["id"],)
            )
            connection.commit()
        finally:
            connection.close()

        with Hub(self.root) as restarted:
            self.assertEqual(restarted.get_job(job["id"])["status"], "queued")
            self.assertTrue(restarted.process_next_job())
            self.assertEqual(restarted.get_job(job["id"])["status"], "succeeded")
            self.assertEqual(restarted.list_recordings()["total"], 1)

    def test_one_workspace_owner_lock(self) -> None:
        first = Hub(self.root)
        try:
            with self.assertRaises(HubError) as raised:
                Hub(self.root)
            self.assertEqual(raised.exception.code, "workspace_locked")
            self.assertEqual(raised.exception.status_code, 409)
        finally:
            first.close()
        with Hub(self.root) as reopened:
            self.assertEqual(reopened.status()["state"], "ready")

    def test_concurrent_claims_process_each_job_once(self) -> None:
        wav = active_wav()
        with Hub(self.root) as hub:
            jobs = [
                hub.submit_recording(
                    io.BytesIO(wav),
                    manifest_bytes(wav, recording_id=f"recording-{index}"),
                )
                for index in range(2)
            ]
            barrier = threading.Barrier(3)
            results: list[bool] = []
            errors: list[Exception] = []

            def worker() -> None:
                try:
                    barrier.wait()
                    results.append(hub.process_next_job())
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(results, [True, True])
            self.assertEqual(
                [hub.get_job(job["id"])["status"] for job in jobs],
                ["succeeded", "succeeded"],
            )
            self.assertEqual(hub.list_recordings()["total"], 2)
            self.assertEqual(hub.list_events()["total"], 2)

    def test_methods_remain_available_while_worker_runs(self) -> None:
        wav = active_wav()
        with Hub(self.root) as hub:
            job = hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
            started = threading.Event()
            release = threading.Event()
            real_replay = hub_module.replay_to_store

            def paused_replay(*args, **kwargs):
                started.set()
                if not release.wait(timeout=10):
                    raise RuntimeError("test worker release timed out")
                return real_replay(*args, **kwargs)

            with mock.patch.object(hub_module, "replay_to_store", paused_replay):
                thread = threading.Thread(target=hub.process_next_job)
                thread.start()
                self.assertTrue(started.wait(timeout=10))
                self.assertEqual(hub.get_job(job["id"])["status"], "running")
                self.assertEqual(hub.status()["jobs"]["running"], 1)
                self.assertEqual(hub.list_jobs()["total"], 1)
                release.set()
                thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(hub.get_job(job["id"])["status"], "succeeded")

    def test_close_waits_for_an_active_worker_before_releasing_lock(self) -> None:
        wav = active_wav()
        hub = Hub(self.root)
        job = hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
        started = threading.Event()
        release = threading.Event()
        real_replay = hub_module.replay_to_store

        def paused_replay(*args, **kwargs):
            started.set()
            if not release.wait(timeout=10):
                raise RuntimeError("test worker release timed out")
            return real_replay(*args, **kwargs)

        with mock.patch.object(hub_module, "replay_to_store", paused_replay):
            worker = threading.Thread(target=hub.process_next_job)
            worker.start()
            self.assertTrue(started.wait(timeout=10))
            closer = threading.Thread(target=hub.close)
            closer.start()
            closer.join(timeout=0.05)
            self.assertTrue(closer.is_alive())
            release.set()
            worker.join(timeout=10)
            closer.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        with Hub(self.root) as reopened:
            self.assertEqual(reopened.get_job(job["id"])["status"], "succeeded")

    def test_concurrent_review_writers_get_one_conflict(self) -> None:
        wav = active_wav()
        with Hub(self.root) as hub:
            hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
            hub.process_next_job()
            event_id = hub.list_events()["items"][0]["event_id"]
            barrier = threading.Barrier(3)
            revisions: list[int] = []
            errors: list[HubError] = []

            def reviewer(name: str) -> None:
                barrier.wait()
                try:
                    review = hub.save_review(
                        event_id, "uncertain", f"review by {name}", name, 0
                    )
                    revisions.append(review["revision"])
                except HubError as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=reviewer, args=("A",)),
                threading.Thread(target=reviewer, args=("B",)),
            ]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=10)
            self.assertEqual(revisions, [1])
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].code, "review_conflict")
            self.assertEqual(hub.get_event(event_id)["event"]["review"]["revision"], 1)

    def test_completed_evidence_is_retried_if_catalog_finalize_fails(self) -> None:
        wav = active_wav()
        with Hub(self.root) as hub:
            job = hub.submit_recording(io.BytesIO(wav), manifest_bytes(wav))
            with mock.patch.object(
                hub,
                "_finish_job",
                side_effect=HubError("workspace_unavailable", "temporary catalog error", 500),
            ):
                self.assertTrue(hub.process_next_job())
            self.assertEqual(hub.get_job(job["id"])["status"], "queued")
            self.assertEqual(hub.list_recordings()["total"], 0)
            with hub._workspace.evidence_connection(read_only=True) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1
                )
            self.assertTrue(hub.process_next_job())
            self.assertEqual(hub.get_job(job["id"])["status"], "succeeded")
            self.assertEqual(hub.list_recordings()["total"], 1)
            self.assertEqual(hub.list_events()["total"], 1)

    def test_unknown_and_unrelated_workspace_files_are_never_deleted(self) -> None:
        self.root.mkdir()
        unknown = self.root / "keep-me.bin"
        unknown.write_bytes(b"owned by someone else")
        with self.assertRaises(HubError) as raised:
            Hub(self.root)
        self.assertEqual(raised.exception.code, "incompatible_workspace")
        self.assertEqual(unknown.read_bytes(), b"owned by someone else")

        other_root = Path(self.temporary.name) / "other"
        other_root.mkdir()
        unrelated = other_root / "hub.sqlite3"
        connection = sqlite3.connect(unrelated)
        try:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
            connection.commit()
        finally:
            connection.close()
        before = unrelated.read_bytes()
        with self.assertRaises(HubError):
            Hub(other_root)
        self.assertEqual(unrelated.read_bytes(), before)

    def test_unrelated_evidence_database_and_staging_file_are_preserved(self) -> None:
        with Hub(self.root):
            pass
        evidence = self.root / "evidence.sqlite3"
        evidence.unlink()
        connection = sqlite3.connect(evidence)
        try:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
            connection.commit()
        finally:
            connection.close()
        before = evidence.read_bytes()
        with self.assertRaises(HubError) as raised:
            Hub(self.root)
        self.assertEqual(raised.exception.code, "incompatible_evidence_store")
        self.assertEqual(evidence.read_bytes(), before)

        evidence.unlink()
        from poseidon_acoustic.store import _create_database

        replacement = _create_database(evidence)
        replacement.close()
        unfinished = self.root / ".staging" / "unknown.part"
        unfinished.write_bytes(b"do not delete")
        with self.assertRaises(HubError) as raised:
            Hub(self.root)
        self.assertEqual(raised.exception.code, "incompatible_workspace")
        self.assertEqual(unfinished.read_bytes(), b"do not delete")

    def test_symlink_and_nonregular_workspace_targets_are_rejected(self) -> None:
        real = Path(self.temporary.name) / "real"
        real.mkdir()
        linked = Path(self.temporary.name) / "linked"
        linked.symlink_to(real, target_is_directory=True)
        with self.assertRaises(HubError) as raised:
            Hub(linked)
        self.assertEqual(raised.exception.code, "invalid_data_dir")

        with Hub(self.root):
            pass
        token = self.root / "access.token"
        token.unlink()
        token.symlink_to(Path(self.temporary.name) / "missing-token")
        with self.assertRaises(HubError) as raised:
            Hub(self.root)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertTrue(token.is_symlink())

    def test_broad_token_permissions_are_rejected_without_replacement(self) -> None:
        with Hub(self.root) as hub:
            token = hub.access_token()
        path = self.root / "access.token"
        path.chmod(0o644)
        with self.assertRaises(HubError) as raised:
            Hub(self.root)
        self.assertEqual(raised.exception.code, "unsafe_workspace")
        self.assertEqual(path.read_text(encoding="ascii").strip(), token)


if __name__ == "__main__":
    unittest.main()
