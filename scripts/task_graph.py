#!/usr/bin/env python3
"""Validate and generate namespaced Taskmaster task files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TAG = "production-v1"
VALID_STATUSES = frozenset({"pending", "in-progress", "done", "blocked", "deferred", "cancelled"})
VALID_PRIORITIES = frozenset({"low", "medium", "high"})
SAFE_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
GENERATED_FILE = re.compile(r"task_\d{3,}\.txt\Z")


class ValidationError(Exception):
    """The selected Taskmaster graph cannot be safely consumed."""


@dataclass(frozen=True)
class LoadedTag:
    database: Path
    tasks: list[dict[str, Any]]
    task_directory: Path


@dataclass(frozen=True)
class GenerationPlan:
    target: Path
    expected: dict[str, str]
    existing: dict[str, tuple[Path, str]]


def default_database_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".taskmaster" / "tasks" / "tasks.json"


def valid_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def format_id(value: Any) -> str:
    return repr(value)


def stable_task_key(task: dict[str, Any]) -> int:
    return task["id"]


def load_selected_tag(database: Path, tag: str) -> LoadedTag:
    try:
        raw = database.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(f"invalid UTF-8 in task database {database}: {error}") from error
    except OSError as error:
        raise ValidationError(f"cannot read task database {database}: {error}") from error

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValidationError(
            f"invalid JSON in {database}: {error.msg} (line {error.lineno}, column {error.colno})"
        ) from error
    except (ValueError, RecursionError) as error:
        raise ValidationError(
            f"JSON numeric value or nesting exceeds supported limits in {database}"
        ) from error

    if not isinstance(document, dict):
        raise ValidationError("task database root must be an object")
    selected = document.get(tag)
    if selected is None:
        raise ValidationError(f"selected tag {tag!r} is missing")
    if not isinstance(selected, dict):
        raise ValidationError(f"selected tag {tag!r} must be an object")
    tasks = selected.get("tasks")
    if not isinstance(tasks, list):
        raise ValidationError(f"selected tag {tag!r} field 'tasks' must be a list")
    return LoadedTag(database=database, tasks=tasks, task_directory=database.parent)


def validate_scope(items: list[Any], scope: str) -> list[dict[str, Any]]:
    errors: list[str] = []
    parsed: list[dict[str, Any]] = []
    by_id: dict[int, dict[str, Any]] = {}

    for position, item in enumerate(items, start=1):
        location = f"{scope} item {position}"
        if not isinstance(item, dict):
            errors.append(f"{location} must be an object")
            continue

        task_id = item.get("id")
        if "id" not in item:
            errors.append(f"{location} is missing id")
        elif not valid_id(task_id):
            errors.append(f"{location} has invalid positive integer id {format_id(task_id)}")
        elif task_id in by_id:
            errors.append(f"{scope} has duplicate id {format_id(task_id)}")
        else:
            by_id[task_id] = item
            parsed.append(item)

        for field in ("title", "description", "details", "testStrategy"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{location} field {field!r} must be a non-empty string")

        status = item.get("status")
        if not isinstance(status, str) or status not in VALID_STATUSES:
            errors.append(f"{location} has invalid status {format_id(status)}")

        priority = item.get("priority")
        if not isinstance(priority, str) or priority not in VALID_PRIORITIES:
            allowed = ", ".join(sorted(VALID_PRIORITIES))
            errors.append(f"{location} has invalid priority {format_id(priority)} (expected one of: {allowed})")

        for field in ("dependencies", "subtasks"):
            if not isinstance(item.get(field), list):
                errors.append(f"{location} field {field!r} must be a list")

    if errors:
        raise ValidationError("\n".join(errors))

    edges: dict[int, list[int]] = {}
    for item in parsed:
        task_id = item["id"]
        resolved: list[int] = []
        for dependency in item["dependencies"]:
            if not valid_id(dependency):
                errors.append(
                    f"{scope} id {task_id} has invalid positive integer dependency id {format_id(dependency)}"
                )
            elif dependency == task_id:
                errors.append(f"{scope} id {task_id} depends on itself")
            elif dependency not in by_id:
                errors.append(f"{scope} id {task_id} depends on missing or out-of-scope id {dependency}")
            else:
                resolved.append(dependency)
        edges[task_id] = resolved

    if errors:
        raise ValidationError("\n".join(errors))

    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node: int, trail: list[int]) -> None:
        if node in visiting:
            cycle = trail[trail.index(node):] + [node]
            raise ValidationError(
                f"{scope} has dependency cycle: " + " -> ".join(str(value) for value in cycle)
            )
        if node in visited:
            return
        visiting.add(node)
        for dependency in edges[node]:
            visit(dependency, trail + [node])
        visiting.remove(node)
        visited.add(node)

    for node in edges:
        visit(node, [])
    return parsed


def validate(database: Path, tag: str) -> LoadedTag:
    loaded = load_selected_tag(database, tag)
    tasks = validate_scope(loaded.tasks, f"tag {tag!r}")
    for task in tasks:
        validate_scope(task["subtasks"], f"subtasks of task {task['id']} in tag {tag!r}")
    return LoadedTag(database=loaded.database, tasks=tasks, task_directory=loaded.task_directory)


def generated_filename(task: dict[str, Any]) -> str:
    return f"task_{task['id']:03d}.txt"


def generated_contents(task: dict[str, Any]) -> str:
    return json.dumps(task, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def safe_target(loaded: LoadedTag, tag: str) -> Path:
    if not SAFE_TAG.fullmatch(tag):
        raise ValidationError(f"unsafe tag name {tag!r}")

    task_directory = loaded.task_directory
    if (
        loaded.database.name != "tasks.json"
        or task_directory.name != "tasks"
        or task_directory.parent.name != ".taskmaster"
    ):
        raise ValidationError(
            f"refusing generation outside a .taskmaster/tasks/tasks.json database: {loaded.database}"
        )
    if task_directory.is_symlink() or task_directory.parent.is_symlink():
        raise ValidationError("refusing generation through a symlinked Taskmaster namespace")

    target = task_directory / tag
    if target.is_symlink():
        raise ValidationError(f"refusing symlinked generation namespace {target}")
    try:
        target.relative_to(task_directory)
    except ValueError as error:
        raise ValidationError(f"refusing to write outside task directory for tag {tag!r}") from error
    return target


def read_target_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(f"invalid UTF-8 in existing target file {path}: {error}") from error
    except OSError as error:
        raise ValidationError(f"cannot read existing target file {path}: {error}") from error


def generation_plan(loaded: LoadedTag, tag: str) -> GenerationPlan:
    target = safe_target(loaded, tag)
    expected = {
        generated_filename(task): generated_contents(task)
        for task in sorted(loaded.tasks, key=stable_task_key)
    }
    if len(expected) != len(loaded.tasks):
        raise ValidationError("generated task filenames would collide")

    existing: dict[str, tuple[Path, str]] = {}
    if not target.exists():
        return GenerationPlan(target=target, expected=expected, existing=existing)
    if not target.is_dir():
        raise ValidationError(f"generation target {target} is not a directory")

    try:
        children = list(target.iterdir())
    except OSError as error:
        raise ValidationError(f"cannot read generation target {target}: {error}") from error

    for child in children:
        if child.is_symlink():
            raise ValidationError(f"refusing symlink in generation namespace {child}")
        if child.is_file():
            contents = read_target_file(child)
            if GENERATED_FILE.fullmatch(child.name):
                existing[child.name] = (child, contents)
        elif child.name in expected or GENERATED_FILE.fullmatch(child.name):
            raise ValidationError(f"refusing non-regular generated output path {child}")

    for name in expected:
        path = target / name
        if path.is_symlink():
            raise ValidationError(f"refusing symlinked generated output path {path}")
        if path.exists() and not path.is_file():
            raise ValidationError(f"refusing non-regular generated output path {path}")
    return GenerationPlan(target=target, expected=expected, existing=existing)


def check_generation(loaded: LoadedTag, tag: str) -> list[str]:
    plan = generation_plan(loaded, tag)
    problems: list[str] = []
    for name, contents in plan.expected.items():
        current = plan.existing.get(name)
        if current is None:
            problems.append(f"missing generated file {plan.target / name}")
        elif current[1] != contents:
            problems.append(f"stale generated file {current[0]}")
    for name in sorted(set(plan.existing) - set(plan.expected)):
        problems.append(f"unexpected generated file {plan.existing[name][0]}")
    return problems


def generate(loaded: LoadedTag, tag: str, check: bool) -> None:
    plan = generation_plan(loaded, tag)
    problems = check_generation(loaded, tag)
    if check:
        if problems:
            raise ValidationError("\n".join(problems))
        return
    unexpected = [problem for problem in problems if problem.startswith("unexpected generated file")]
    if unexpected:
        raise ValidationError("\n".join(unexpected))

    try:
        if plan.target.is_symlink():
            raise ValidationError(f"refusing symlinked generation namespace {plan.target}")
        plan.target.mkdir(parents=True, exist_ok=True)
        if plan.target.is_symlink():
            raise ValidationError(f"refusing symlinked generation namespace {plan.target}")
        for name, contents in plan.expected.items():
            current = plan.existing.get(name)
            if current is None or current[1] != contents:
                path = plan.target / name
                if path.is_symlink() or (path.exists() and not path.is_file()):
                    raise ValidationError(f"refusing unsafe generated output path {path}")
                path.write_text(contents, encoding="utf-8")
    except OSError as error:
        raise ValidationError(f"cannot generate task files in {plan.target}: {error}") from error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "generate"))
    parser.add_argument("--tag", default=DEFAULT_TAG, help=f"Taskmaster tag (default: {DEFAULT_TAG})")
    parser.add_argument("--file", type=Path, default=default_database_path(), help="Task database JSON path")
    parser.add_argument("--check", action="store_true", help="Verify generated files without writing")
    arguments = parser.parse_args(argv)
    if arguments.check and arguments.command != "generate":
        parser.error("--check requires the generate command")
    return arguments


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        loaded = validate(arguments.file, arguments.tag)
        if arguments.command == "generate":
            generate(loaded, arguments.tag, arguments.check)
    except ValidationError as error:
        print(f"task_graph: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
