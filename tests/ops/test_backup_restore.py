"""Private, synthetic workspace recovery drills; no user workspace is touched."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from poseidon_trident import Hub, HubError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("poseidon_backup", ROOT / "scripts/platform/backup_restore.py")
backup_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup_module)


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="poseidon-backup-test-")
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        with Hub(self.source) as hub:
            job = hub.submit_demo()
            while hub.process_next_job():
                pass
            self.recording = hub.get_job(job["id"])["recording_id"]
            self.before = hub.status()
        self.backup = self.root / "private-backup"

    def tearDown(self):
        self.temp.cleanup()

    def test_backup_restore_preserves_real_synthetic_evidence(self):
        result = backup_module.backup(self.source, self.backup)
        self.assertGreater(result["files"], 3)
        backup_module.verify(self.backup)
        restored = self.root / "restored"
        result = backup_module.restore(self.backup, restored)
        self.assertEqual(result["recordings"], self.before["recordings"])
        self.assertEqual(result["events"], self.before["events"])
        with Hub(restored) as hub:
            self.assertEqual(hub.get_recording(self.recording)["provenance"], "synthetic")
        self.assertEqual(self.backup.stat().st_mode & 0o077, 0)
        self.assertEqual((restored / "access.token").stat().st_mode & 0o077, 0)

    def test_backup_preserves_observations_registry_and_scoped_credentials(self):
        with Hub(self.source) as hub:
            hub.create_device({"id": "synthetic-restore-device", "site_id": "synthetic-site", "label": "Synthetic restore fixture", "kind": "reef", "hardware_revision": "simulation-v1", "source_kind": "synthetic"})
            issued = hub.create_principal({"subject": "synthetic-restore-reader", "role": "viewer", "site_ids": ["synthetic-site"], "device_id": None})
            observation = hub.create_observation(self.recording, {"id": "synthetic-restored-observation", "start_s": 0, "end_s": 0.1, "label": "uncertain", "notes": "Synthetic backup evidence", "observer": "Synthetic observer", "expected_revision": 0})
        backup_module.backup(self.source, self.backup)
        restored = self.root / "restored-platform"
        backup_module.restore(self.backup, restored)
        with Hub(restored) as hub:
            self.assertEqual(hub.get_device("synthetic-restore-device")["source_kind"], "synthetic")
            self.assertEqual(hub.authenticate(issued["token"])["subject"], "synthetic-restore-reader")
            self.assertEqual(hub.list_observations(self.recording)["items"][0], observation)

    def test_locked_workspace_is_not_backed_up(self):
        with Hub(self.source):
            with self.assertRaises(HubError):
                backup_module.backup(self.source, self.backup)
        self.assertFalse(self.backup.exists())

    def test_corrupt_backup_fails_before_creating_restore_target(self):
        backup_module.backup(self.source, self.backup)
        with (self.backup / "hub.sqlite3").open("ab") as stream:
            stream.write(b"synthetic corruption")
        restored = self.root / "restored"
        with self.assertRaises(ValueError):
            backup_module.restore(self.backup, restored)
        self.assertFalse(restored.exists())

    def test_existing_destination_is_never_overwritten(self):
        backup_module.backup(self.source, self.backup)
        marker = self.backup / "operator-owned.txt"
        marker.write_text("preserve")
        with self.assertRaises(ValueError):
            backup_module.backup(self.source, self.backup)
        self.assertEqual(marker.read_text(), "preserve")

    def test_symlinks_unknown_paths_and_nonprivate_backup_rejected(self):
        backup_module.backup(self.source, self.backup)
        os.chmod(self.backup, 0o755)
        with self.assertRaises(ValueError):
            backup_module.verify(self.backup)
        os.chmod(self.backup, 0o700)
        (self.backup / "unknown").symlink_to(self.source / "hub.sqlite3")
        with self.assertRaises(ValueError):
            backup_module.verify(self.backup)

    def test_manifest_traversal_and_duplicate_entry_rejected(self):
        backup_module.backup(self.source, self.backup)
        path = self.backup / backup_module.MANIFEST
        manifest = json.loads(path.read_text())
        manifest["files"][0]["path"] = "../source/access.token"
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            backup_module.verify(self.backup)


if __name__ == "__main__":
    unittest.main()
