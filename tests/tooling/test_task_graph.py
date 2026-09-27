from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "task_graph.py"
SPEC = importlib.util.spec_from_file_location("task_graph", SCRIPT)
assert SPEC and SPEC.loader
TASK_GRAPH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TASK_GRAPH
SPEC.loader.exec_module(TASK_GRAPH)


class TaskGraphTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / ".taskmaster" / "tasks"
        self.root.mkdir(parents=True)
        self.database = self.root / "tasks.json"

    @staticmethod
    def task(task_id: object, dependencies: object = None, **fields: object) -> dict[str, object]:
        task = {
            "id": task_id,
            "title": f"Task {task_id}",
            "description": "Description",
            "details": "Implementation details",
            "testStrategy": "Run tests",
            "status": "pending",
            "priority": "medium",
            "dependencies": [] if dependencies is None else dependencies,
            "subtasks": [],
        }
        task.update(fields)
        return task

    def write_tasks(self, tasks: object, tag: str = "production-v1") -> None:
        self.database.write_text(json.dumps({tag: {"tasks": tasks}}), encoding="utf-8")

    def run_cli(
        self, *arguments: str, database: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments, "--file", str(database or self.database)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_corrupt_json_schema_and_utf8_fail_with_diagnostics(self) -> None:
        self.database.write_text("{broken", encoding="utf-8")
        corrupt = self.run_cli("validate")
        self.assertEqual(corrupt.returncode, 1)
        self.assertIn("invalid JSON", corrupt.stderr)

        self.database.write_text(json.dumps({"production-v1": {"tasks": {}}}), encoding="utf-8")
        schema = self.run_cli("validate")
        self.assertEqual(schema.returncode, 1)
        self.assertIn("field 'tasks' must be a list", schema.stderr)

        self.database.write_bytes(b"\xff")
        invalid_utf8 = self.run_cli("validate")
        self.assertEqual(invalid_utf8.returncode, 1)
        self.assertIn("invalid UTF-8 in task database", invalid_utf8.stderr)

    def test_json_numeric_and_nesting_limits_fail_without_tracebacks(self) -> None:
        documents = (
            (
                '{"production-v1":{"tasks":[{"id":' + "9" * 5000 + "}]}}",
                ("exceeds supported limits",),
            ),
            (
                "[" * 2000 + "0" + "]" * 2000,
                ("exceeds supported limits", "root must be an object"),
            ),
        )
        for document, diagnostics in documents:
            with self.subTest(length=len(document)):
                self.database.write_text(document, encoding="utf-8")
                result = self.run_cli("validate")
                self.assertEqual(result.returncode, 1)
                self.assertTrue(any(message in result.stderr for message in diagnostics), result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_missing_and_invalid_essentials_fail(self) -> None:
        missing = self.task(1)
        del missing["title"]
        self.write_tasks([missing])
        missing_result = self.run_cli("validate")
        self.assertEqual(missing_result.returncode, 1)
        self.assertIn("field 'title' must be a non-empty string", missing_result.stderr)

        self.write_tasks(
            [
                self.task(
                    1,
                    description="",
                    details=3,
                    testStrategy="",
                    status="unknown",
                    priority="urgent",
                    dependencies={},
                    subtasks={},
                )
            ]
        )
        invalid_result = self.run_cli("validate")
        self.assertEqual(invalid_result.returncode, 1)
        self.assertIn("field 'description' must be a non-empty string", invalid_result.stderr)
        self.assertIn("invalid status", invalid_result.stderr)
        self.assertIn("invalid priority", invalid_result.stderr)
        self.assertIn("field 'dependencies' must be a list", invalid_result.stderr)
        self.assertIn("field 'subtasks' must be a list", invalid_result.stderr)

    def test_valid_dag_passes(self) -> None:
        self.write_tasks([self.task(1), self.task(2, [1]), self.task(10, [2])])
        result = self.run_cli("validate")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_string_boolean_zero_negative_and_duplicate_ids_fail(self) -> None:
        cases = (("1", "'1'"), (True, "True"), (0, "0"), (-1, "-1"))
        for task_id, label in cases:
            with self.subTest(task_id=task_id):
                self.write_tasks([self.task(task_id)])
                result = self.run_cli("validate")
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"invalid positive integer id {label}", result.stderr)

        self.write_tasks([self.task(1), self.task(1)])
        duplicate = self.run_cli("validate")
        self.assertEqual(duplicate.returncode, 1)
        self.assertIn("duplicate id 1", duplicate.stderr)

    def test_invalid_missing_self_and_cycle_dependencies_fail(self) -> None:
        for dependency, label in (("1", "'1'"), (True, "True"), (0, "0")):
            with self.subTest(dependency=dependency):
                self.write_tasks([self.task(1, [dependency])])
                result = self.run_cli("validate")
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"invalid positive integer dependency id {label}", result.stderr)

        self.write_tasks([self.task(1, [9])])
        missing = self.run_cli("validate")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("missing or out-of-scope id 9", missing.stderr)

        self.write_tasks([self.task(1, [1])])
        self_dependency = self.run_cli("validate")
        self.assertEqual(self_dependency.returncode, 1)
        self.assertIn("depends on itself", self_dependency.stderr)

        self.write_tasks([self.task(1, [2]), self.task(2, [1])])
        cycle = self.run_cli("validate")
        self.assertEqual(cycle.returncode, 1)
        self.assertIn("dependency cycle", cycle.stderr)

    def test_subtask_dependencies_stay_with_parent(self) -> None:
        self.write_tasks(
            [
                self.task(1, subtasks=[self.task(11, [])]),
                self.task(2, subtasks=[self.task(12, [11])]),
            ]
        )
        result = self.run_cli("validate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing or out-of-scope id 11", result.stderr)

    def test_generator_check_detects_missing_stale_and_invalid_utf8_files(self) -> None:
        self.write_tasks([self.task(1), self.task(2, [1])])
        missing = self.run_cli("generate", "--check")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("missing generated file", missing.stderr)
        self.assertFalse((self.root / "production-v1").exists())

        generated = self.run_cli("generate")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        target = self.root / "production-v1"
        self.assertEqual(self.run_cli("generate", "--check").returncode, 0)

        task_file = target / "task_001.txt"
        task_file.write_text("stale\n", encoding="utf-8")
        stale = self.run_cli("generate", "--check")
        self.assertEqual(stale.returncode, 1)
        self.assertIn("stale generated file", stale.stderr)
        self.assertEqual(task_file.read_text(encoding="utf-8"), "stale\n")

        task_file.write_bytes(b"\xff")
        invalid_utf8 = self.run_cli("generate", "--check")
        self.assertEqual(invalid_utf8.returncode, 1)
        self.assertIn("invalid UTF-8 in existing target file", invalid_utf8.stderr)

    def test_generator_scope_isolation_and_unexpected_files_are_preserved(self) -> None:
        self.write_tasks([self.task(1)])
        target = self.root / "production-v1"
        other_tag = self.root / "other-tag"
        target.mkdir()
        (target / "notes.txt").write_text("keep", encoding="utf-8")
        other_tag.mkdir()
        (other_tag / "task_001.txt").write_text("other", encoding="utf-8")

        generated = self.run_cli("generate")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual((target / "notes.txt").read_text(encoding="utf-8"), "keep")
        self.assertEqual((other_tag / "task_001.txt").read_text(encoding="utf-8"), "other")

        unexpected = target / "task_999.txt"
        unexpected.write_text("old", encoding="utf-8")
        check = self.run_cli("generate", "--check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("unexpected generated file", check.stderr)
        write = self.run_cli("generate")
        self.assertEqual(write.returncode, 1)
        self.assertIn("unexpected generated file", write.stderr)
        self.assertEqual(unexpected.read_text(encoding="utf-8"), "old")

    def test_generator_rejects_unsafe_namespace_and_output_symlinks(self) -> None:
        self.write_tasks([self.task(1)], tag="../outside")
        unsafe = self.run_cli("generate", "--tag", "../outside")
        self.assertEqual(unsafe.returncode, 1)
        self.assertIn("unsafe tag name", unsafe.stderr)

        self.write_tasks([self.task(1)])
        outside = Path(self.temporary_directory.name) / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_text("outside", encoding="utf-8")
        namespace = self.root / "production-v1"
        namespace.symlink_to(outside, target_is_directory=True)
        symlinked_namespace = self.run_cli("generate")
        self.assertEqual(symlinked_namespace.returncode, 1)
        self.assertIn("refusing symlinked generation namespace", symlinked_namespace.stderr)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside")

        namespace.unlink()
        namespace.mkdir()
        output = namespace / "task_001.txt"
        output.symlink_to(sentinel)
        symlinked_output = self.run_cli("generate")
        self.assertEqual(symlinked_output.returncode, 1)
        self.assertIn("refusing symlink", symlinked_output.stderr)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside")

    def test_generate_rejects_unscoped_file_option(self) -> None:
        unscoped = Path(self.temporary_directory.name) / "tasks.json"
        unscoped.write_text(json.dumps({"production-v1": {"tasks": [self.task(1)]}}), encoding="utf-8")
        result = self.run_cli("generate", database=unscoped)
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing generation outside a .taskmaster/tasks/tasks.json database", result.stderr)


if __name__ == "__main__":
    unittest.main()
