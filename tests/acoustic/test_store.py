from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from poseidon_acoustic.detector import DetectorConfig, detect_wav
from poseidon_acoustic.errors import InputError, StoreError
from poseidon_acoustic.replay import replay_to_store
from poseidon_acoustic.store import list_event_json, save_replay

from _support import manifest_for, mono_windows, write_manifest, write_pcm16_wav


class EvidenceStoreTests(unittest.TestCase):
    def _fixture(self, root: Path, *, recording_id: str = "recording-1") -> tuple[Path, Path]:
        wav = root / f"{recording_id}.wav"
        write_pcm16_wav(wav, mono_windows(0, 20_000, 20_000, 0, 20_000, 0))
        manifest_path = root / f"{recording_id}.json"
        write_manifest(manifest_path, manifest_for(wav, recording_id=recording_id))
        return wav, manifest_path

    def test_idempotent_rerun_and_new_config_create_expected_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav, manifest = self._fixture(root)
            database = root / "evidence.sqlite3"
            first_result, first_save = replay_to_store(wav, manifest, database, DetectorConfig())
            second_result, second_save = replay_to_store(wav, manifest, database, DetectorConfig())
            third_result, third_save = replay_to_store(
                wav, manifest, database, DetectorConfig(threshold=0.7)
            )
            self.assertEqual(first_result, second_result)
            self.assertFalse(first_save.already_present)
            self.assertTrue(second_save.already_present)
            self.assertNotEqual(first_save.run_id, third_save.run_id)
            self.assertFalse(third_save.already_present)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 2)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                    len(first_result.events) + len(third_result.events),
                )

    def test_conflicting_recording_context_is_rejected_without_new_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav, manifest_path = self._fixture(root)
            database = root / "evidence.sqlite3"
            replay_to_store(wav, manifest_path, database, DetectorConfig())
            conflicting = manifest_for(wav, recording_id="recording-1", site_id="different-site")
            conflicting_path = root / "conflicting.json"
            write_manifest(conflicting_path, conflicting)
            with self.assertRaisesRegex(StoreError, "conflicting"):
                replay_to_store(wav, conflicting_path, database, DetectorConfig())
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_truncated_second_recording_does_not_partially_mutate_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav, manifest_path = self._fixture(root)
            database = root / "evidence.sqlite3"
            replay_to_store(wav, manifest_path, database, DetectorConfig())

            truncated = root / "truncated.wav"
            write_pcm16_wav(truncated, mono_windows(20_000, 20_000))
            truncated.write_bytes(truncated.read_bytes()[:-1])
            truncated_manifest_path = root / "truncated.json"
            write_manifest(
                truncated_manifest_path,
                manifest_for(truncated, recording_id="recording-2"),
            )
            with self.assertRaises(InputError):
                replay_to_store(truncated, truncated_manifest_path, database, DetectorConfig())
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_export_is_deterministic_and_marks_synthetic_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav, manifest_path = self._fixture(root)
            database = root / "evidence.sqlite3"
            replay_to_store(wav, manifest_path, database, DetectorConfig())
            first = list_event_json(database)
            second = list_event_json(database)
            self.assertEqual(first, second)
            self.assertGreater(len(first), 0)
            for line in first:
                event = json.loads(line)
                self.assertEqual(event["provenance"], "synthetic")
                self.assertEqual(event["calibration_status"], "uncalibrated")
                self.assertEqual(event["amplitude_units"], "normalized_pcm16_full_scale")
                self.assertFalse(event["emission_enabled"])

    def test_missing_and_unrelated_databases_are_not_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = root / "missing.sqlite3"
            with self.assertRaisesRegex(StoreError, "does not exist"):
                list_event_json(missing)
            self.assertFalse(missing.exists())

            unrelated = root / "unrelated.sqlite3"
            with closing(sqlite3.connect(unrelated)) as connection:
                connection.execute("CREATE TABLE other (value TEXT)")
            with self.assertRaisesRegex(StoreError, "schema mismatch"):
                list_event_json(unrelated)
            with closing(sqlite3.connect(unrelated)) as connection:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            self.assertEqual(tables, [("other",)])

    def test_inconsistent_public_result_is_rejected_before_database_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav, _ = self._fixture(root)
            manifest = manifest_for(wav)
            result = detect_wav(wav, manifest, DetectorConfig())
            altered_event = replace(result.events[0], site_id="other-site")
            altered_result = replace(result, events=(altered_event,) + result.events[1:])
            database = root / "evidence.sqlite3"
            with self.assertRaisesRegex(StoreError, "context"):
                save_replay(database, manifest, altered_result)
            self.assertFalse(database.exists())

    def test_failed_database_initialization_closes_and_removes_created_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wav, _ = self._fixture(root)
            manifest = manifest_for(wav)
            result = detect_wav(wav, manifest, DetectorConfig())
            database = root / "evidence.sqlite3"
            with mock.patch(
                "poseidon_acoustic.store._validate_schema",
                side_effect=StoreError("forced schema check failure"),
            ):
                with self.assertRaisesRegex(StoreError, "forced"):
                    save_replay(database, manifest, result)
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
