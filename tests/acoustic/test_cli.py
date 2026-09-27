from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = os.pathsep.join(
    (
        str(ROOT / "libs/proto-py/src"),
        str(ROOT / "apps/acoustic/src"),
    )
)


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    inherited = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = SOURCE_PATH if not inherited else SOURCE_PATH + os.pathsep + inherited
    return subprocess.run(
        [sys.executable, "-m", "poseidon_acoustic", *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CliTests(unittest.TestCase):
    def test_replay_missing_required_input_is_friendly(self) -> None:
        completed = run_cli("replay")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("required", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_replay_nonexistent_manifest_is_friendly_and_creates_no_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "evidence.sqlite3"
            completed = run_cli(
                "replay",
                "--wav",
                str(root / "missing.wav"),
                "--manifest",
                str(root / "missing.json"),
                "--database",
                str(database),
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("error:", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertFalse(database.exists())

    def test_oversized_manifest_integer_is_friendly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            manifest.write_text('{"schema_version":' + "9" * 5_000 + "}", encoding="utf-8")
            database = root / "evidence.sqlite3"
            completed = run_cli(
                "replay",
                "--wav",
                str(root / "missing.wav"),
                "--manifest",
                str(manifest),
                "--database",
                str(database),
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("exceeds supported limits", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertFalse(database.exists())

    def test_events_missing_database_errors_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "missing.sqlite3"
            completed = run_cli("events", "--database", str(database))
            self.assertEqual(completed.returncode, 2)
            self.assertIn("does not exist", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertFalse(database.exists())

    def test_demo_refuses_nonempty_directory_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "demo"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            completed = run_cli("demo", "--output-dir", str(output))
            self.assertEqual(completed.returncode, 2)
            self.assertIn("not empty", completed.stderr)
            self.assertNotIn("Traceback", completed.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertEqual(tuple(path.name for path in output.iterdir()), ("keep.txt",))

    def test_demo_creates_two_marked_candidates_and_refuses_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "demo"
            completed = run_cli("demo", "--output-dir", str(output))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            lines = completed.stdout.splitlines()
            self.assertEqual(len(lines), 2)
            events = [json.loads(line) for line in lines]
            self.assertTrue(all(event["provenance"] == "synthetic" for event in events))
            self.assertTrue(all(event["emission_enabled"] is False for event in events))
            artifacts = {
                name: output / name
                for name in (
                    "synthetic.wav",
                    "recording-manifest.json",
                    "evidence.sqlite3",
                    "events.ndjson",
                )
            }
            self.assertTrue(all(path.is_file() for path in artifacts.values()))
            before = {name: digest(path) for name, path in artifacts.items()}

            repeated = run_cli("demo", "--output-dir", str(output))
            self.assertEqual(repeated.returncode, 2)
            self.assertIn("not empty", repeated.stderr)
            self.assertEqual(before, {name: digest(path) for name, path in artifacts.items()})

            exported = run_cli("events", "--database", str(artifacts["evidence.sqlite3"]))
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertEqual(exported.stdout.splitlines(), lines)


if __name__ == "__main__":
    unittest.main()
