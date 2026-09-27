"""Real offline backup/restore of synthetic companion imports and corruption."""
from __future__ import annotations

from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from poseidon_proto.companion import DOCUMENT_ROLES
from poseidon_trident import Hub, HubError

ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = load_module("companion_backup_tool", ROOT / "scripts/platform/backup_restore.py")
fixtures = load_module("companion_backup_fixtures", ROOT / "tests/trident/_companion_support.py")


class CompanionBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-companion-backup-")
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.first, self.later = fixtures.make_exports(self.root / "fixtures", final_encoding="utf-16")
        self.source = self.root / "source"
        with Hub(self.source) as hub:
            fixtures.context(hub)
            self.jobs = [fixtures.submit(hub, bundle) for bundle in (self.first, self.later)]
            while hub.process_next_job():
                pass
            self.projections = [hub.get_acquisition_companion(job["recording_id"]) for job in self.jobs]

    def test_exact_seven_role_bytes_projection_and_snapshot_survive_backup_restore(self):
        archive, restored = self.root / "backup", self.root / "restored"
        backup.backup(self.source, archive)
        backup.verify(archive)
        result = backup.restore(archive, restored)
        self.assertEqual(result["recordings"], 2)
        self.assertEqual(result["events"], 1)
        with Hub(restored) as hub:
            for index, bundle in enumerate((self.first, self.later)):
                recording_id = self.jobs[index]["recording_id"]
                self.assertEqual(hub.get_acquisition_companion(recording_id), self.projections[index])
                directory = restored / "recordings" / recording_id
                self.assertEqual((directory / "source.wav").read_bytes(), bundle["bytes"]["wav"])
                self.assertEqual((directory / "manifest.json").read_bytes(), bundle["bytes"]["manifest"])
                for role in DOCUMENT_ROLES:
                    self.assertEqual(hub.get_companion_document(recording_id, role)["bytes"], bundle["bytes"][role])
            with hub._workspace.connect(read_only=True) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM acquisition_source_bindings").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM recording_companion_documents").fetchone()[0], 10)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_corrupt_companion_source_is_rejected_before_backup_destination(self):
        with closing(sqlite3.connect(self.source / "hub.sqlite3")) as connection, connection:
            connection.execute("UPDATE recording_companion_documents SET sha256 = ? WHERE role = 'source_final'", ("0" * 64,))
        destination = self.root / "rejected-backup"
        with self.assertRaises(HubError) as caught:
            backup.backup(self.source, destination)
        self.assertEqual(caught.exception.code, "companion_store_error")
        self.assertFalse(destination.exists())

    def test_rehashed_outer_backup_manifest_cannot_hide_corrupt_projection_on_restore(self):
        archive, restored = self.root / "backup", self.root / "rejected-restore"
        backup.backup(self.source, archive)
        with closing(sqlite3.connect(archive / "hub.sqlite3")) as connection, connection:
            connection.execute("UPDATE recording_companion_imports SET projection_bytes = ?, projection_sha256 = ?", (b"{}", hashlib.sha256(b"{}").hexdigest()))
        manifest_path = archive / backup.MANIFEST
        manifest = json.loads(manifest_path.read_bytes())
        for entry in manifest["files"]:
            if entry["path"] == "hub.sqlite3":
                raw = (archive / "hub.sqlite3").read_bytes()
                entry["size_bytes"], entry["sha256"] = len(raw), hashlib.sha256(raw).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        # Existing verify checks file hashes, not source semantics. Restore opens
        # the real Hub, whose acquisition-reader integrity checks must reject it.
        backup.verify(archive)
        with self.assertRaises(HubError) as caught:
            backup.restore(archive, restored)
        self.assertEqual(caught.exception.code, "companion_store_error")
        self.assertEqual((restored / "hub.sqlite3").read_bytes(), (archive / "hub.sqlite3").read_bytes())


if __name__ == "__main__":
    unittest.main()
