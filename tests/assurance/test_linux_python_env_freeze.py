"""Synthetic host tests for the tranche3 freeze/translation tool.

Every test builds its own throwaway project, handoffs and proposal in a
temporary directory, generates artifacts from them and feeds those artifacts
through the pure validators (source.validate_manifest, guest_checks and
locked_checks validate_checkset, provision/locked_env validate_plan and
runner.validate_go). No Session is constructed, Lima is never invoked, no
socket is opened and no real repository path is written.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.assurance.linux_python_env import artifacts, freeze, guest_checks, locked_checks, locked_env, provision, runner as lifecycle, source

HIL = guest_checks.HIL_COVERAGE
LABEL = guest_checks.HIL_LABEL


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class Project:
    """A synthetic frozen project plus the five published lane inputs."""

    def __init__(self, base: Path):
        self.base = base
        self.root = base / "project"
        self.inputs = base / "inputs"
        self.inputs.mkdir(parents=True)
        self.files: dict[str, bytes] = {}
        for name in sorted(set(lifecycle.GUEST_HELPERS[1]) | set(lifecycle.GUEST_HELPERS[2])):
            self.write(name, f"# SYNTHETIC helper {name}\n".encode())
        for name in ("scripts/task_graph.py", "scripts/platform/check_ops.py", HIL,
                     "tests/tooling/test_tooling.py", "tests/nereid/test_codec.py", "tests/api/test_locked.py",
                     "tests/trident/test_lifecycle.py", "libs/dsp/src/dsp.py", "apps/acoustic/src/acoustic.py",
                     "hardware/validation/check_reference.py", "hardware/cad/generated/reference-v1/part.step",
                     "ops/compose/compose.json", "contracts/v1/schema.json", "research/literature/notes.json",
                     ".github/workflows/ci.yml", ".taskmaster/tasks/tasks.json",
                     ".taskmaster/tasks/production-v1/task_001.txt", "HARDWARE.md", "Makefile", "SECURITY.md", "pyproject.toml",
                     "docs/acquisition/synthetic.md"):
            self.write(name, f"# SYNTHETIC {name}\n".encode())
        for name in freeze.FIRMWARE_INPUTS:
            self.write(name, f"# SYNTHETIC firmware input {name}\n".encode())
        for project, _ in locked_env.LANES.values():
            for name in ("pyproject.toml", "uv.lock"):
                self.write(f"{project}/{name}", f"# SYNTHETIC {project} {name}\n".encode())
        self.paths = {"platform": self.publish("platform.json", {"lead": "platform", "sourceFiles": [
                          {"path": "apps/acoustic/src/acoustic.py", "bytes": len(self.files["apps/acoustic/src/acoustic.py"]),
                           "sha256": digest(self.files["apps/acoustic/src/acoustic.py"]), "lane": "backend"}]}),
                      "acquisition": self.publish("acquisition.json", {"lead": "acquisition",
                          "changedPathSha256": {"docs/acquisition/synthetic.md": digest(self.files["docs/acquisition/synthetic.md"])},
                          "selectedSourceAndTestSha256": {"libs/dsp/src/dsp.py": digest(self.files["libs/dsp/src/dsp.py"])}}),
                      "native": self.publish("native.json", {"lead": "acquisition",
                          "files": {"tests/tooling/test_tooling.py": digest(self.files["tests/tooling/test_tooling.py"])}}),
                      "helpers": self.publish("helpers.json", {"lead": "assurance", "files": {
                          name: {"bytes": len(self.files[name]), "sha256": digest(self.files[name])}
                          for name in lifecycle.GUEST_HELPERS[1]}}),
                      "proposal": self.publish("proposal.json", self.proposal()),
                      "tools": self.publish("tools.json", self.tools()),
                      "availability": self.publish("availability.json", self.availability())}

    def write(self, name: str, raw: bytes) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.files[name] = raw

    def publish(self, name: str, value: dict) -> Path:
        path = self.inputs / name
        path.write_bytes(freeze.canonical(value))
        return path

    def suite(self, identifier: str, root: str, pattern: str, minimum: int, *, klass: str | None = None, label: str | None = None) -> dict:
        argv = ["/usr/bin/python3", "-m", "scripts.assurance.linux_python_env.suite",
                "--root", root, "--pattern", pattern, "--minimum", str(minimum)]
        if klass:
            argv += ["--class-name", klass]
        command = {"id": identifier, "argv": argv, "timeout_seconds": 600, "environment": {},
                   "coverage": [f"{root}/{pattern}"], "expected_exit": 0}
        return command | ({"evidence_label": label} if label else {})

    def proposal(self) -> dict:
        stage1 = {"interpreter": {"path": "/usr/bin/python3", "version": "3.13.5"}, "hil_label": LABEL,
                  "apt_root_pins": {"make": "4.4.1-2", "python3.13": "3.13.5-2+deb13u4"},
                  "omissions": [{"paths": ["tests/api"], "make_targets": ["test-platform"], "reason": "SYNTHETIC locked API lane"},
                                {"paths": ["tests/nereid"], "reason": "SYNTHETIC locked codec lane"}],
                  "commands": [self.suite("tooling", "tests/tooling", "test_tooling.py", 1),
                               self.suite("hil-refusals", "tests/assurance", "test_hil_gate.py", 9, klass="HilRefusalTests"),
                               self.suite("hil-positive", "tests/assurance", "test_hil_gate.py", 13, klass="HilSyntheticSignatureTests", label=LABEL),
                               {"id": "compile-python", "argv": ["/usr/bin/python3", "-m", "compileall", "-q", "tests", "tests/api"],
                                "timeout_seconds": 180, "coverage": ["tests", "tests/api"], "expected_exit": 0},
                               {"id": "task-graph-validate", "argv": ["/usr/bin/python3", "scripts/task_graph.py", "validate", "--tag", "production-v1"],
                                "timeout_seconds": 120, "coverage": [".taskmaster/tasks/tasks.json"], "expected_exit": 0},
                               {"id": "ops-static", "argv": ["/usr/bin/python3", "scripts/platform/check_ops.py"],
                                "timeout_seconds": 60, "coverage": ["ops/compose"], "expected_exit": 0},
                               {"id": "check-hardware-reference", "timeout_seconds": 600, "expected_exit": 0,
                                "argv": ["/usr/bin/make", "check-hardware-reference", "PYTHON=/usr/bin/python3",
                                         "VERIFY_ROOT={source}/.local/python-tranche3-{run_id}"],
                                "coverage": ["hardware", "Makefile"]}]}
        stage2 = {"explicit_exclusions": ["SYNTHETIC device operations"], "label_limits": "SYNTHETIC software regression only",
                  "commands": [{"id": "tooling", "lane": "api", "timeout_seconds": 180, "coverage": ["tests/tooling"],
                                "argv": ["{workspace}/envs/api/bin/python", "scripts/assurance/run_unittest.py", "-s", "tests/tooling", "-p", "test*.py", "--min-tests", "1"],
                                "discovery": {"root": "tests/tooling"}, "evidence_label": "SYNTHETIC locked lane regression"},
                               {"id": "codec", "lane": "nereid", "timeout_seconds": 600, "coverage": ["tests/nereid"],
                                "argv": ["{workspace}/envs/nereid/bin/python", "scripts/assurance/run_unittest.py", "-s", "tests/nereid", "-p", "test_codec.py", "--min-tests", "31"]},
                               {"id": "platform", "lane": "firmware", "timeout_seconds": 600, "coverage": ["tests/api"], "environment": {"REEF_SANITIZE": "1"},
                                "argv": ["{workspace}/envs/firmware/bin/python", "scripts/assurance/run_pytest.py", "tests/api", "-q"]},
                               {"id": "check-hardware-reference", "lane": "api", "timeout_seconds": 600, "coverage": ["hardware"],
                                "argv": ["make", "check-hardware-reference", "PYTHON={workspace}/envs/api/bin/python",
                                         "VERIFY_ROOT={source}/.local/python-tranche3-{run_id}"]}]}
        return {"schema_version": "poseidon.synthetic-python-check-proposal.v4", "stage1": stage1, "stage2": stage2}

    def tools(self) -> dict:
        return {"schema_version": "poseidon.linux-python-locked-tools.v1", "uv": copy.deepcopy(artifacts.UV_PIN),
                "python": copy.deepcopy(artifacts.PYTHON_PINS),
                "locks": {lane: {"project": project, "python": version,
                                 "lock_sha256": digest(self.files[f"{project}/uv.lock"]),
                                 "pyproject_sha256": digest(self.files[f"{project}/pyproject.toml"])}
                          for lane, (project, version) in locked_env.LANES.items()}}

    def availability(self) -> dict:
        names = ("snapshot.debian.org_archive_debian_20260901T000000Z_dists_trixie_main_binary-arm64_Packages",
                 "snapshot.debian.org_archive_debian_20260901T000000Z_dists_trixie-updates_main_binary-arm64_Packages",
                 "snapshot.debian.org_archive_debian-security_20260901T000000Z_dists_trixie-security_main_binary-arm64_Packages")
        return {"schema_version": "poseidon.debian-python-availability.v1", "snapshot": "20260901T000000Z", "network_used": False,
                "indexes": [{"path": f"/synthetic/apt/lists/{name}", "sha256": format(index, "064x"), "accepted_manifest_match": True}
                            for index, name in enumerate(names, start=1)],
                "packages": {"make": [{"Version": "4.4.1-2"}], "python3.13": [{"Version": "3.13.5-2+deb13u4"}]}}

    def expectations(self) -> list[str]:
        return [value for name in freeze.ROOT_FROZEN for value in ("--expect", f"{name}={digest(self.files[name])}")]

    def repost(self, name: str, mutate) -> None:
        value = json.loads(self.paths[name].read_bytes())
        mutate(value)
        self.paths[name].write_bytes(freeze.canonical(value))


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="poseidon-synthetic-freeze-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.project = Project(self.base)
        for target in (subprocess.run, subprocess.Popen, urllib.request.urlopen):
            patcher = patch.object(sys.modules[target.__module__], target.__name__,
                                   side_effect=AssertionError("no process or network call is allowed"))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.counter = 0

    def generate(self, *extra: str, label: str = "final", expect: str | None = None) -> dict:
        self.counter += 1
        output = self.base / f"artifacts-{self.counter}"
        argv = ["generate", "--root", str(self.project.root), "--output", str(output), "--label", label, *self.project.expectations()]
        for name in ("platform", "acquisition", "native", "helpers", "proposal", "tools", "availability"):
            argv += ["--" + name, str(self.project.paths[name])]
        argv += list(extra)
        if expect is not None:
            with self.assertRaisesRegex(freeze.FreezeError, expect):
                freeze.generate(freeze.parse(argv))
            return {}
        result = freeze.generate(freeze.parse(argv))
        result["output"] = output
        result["values"] = {name: json.loads((output / name).read_bytes()) for name in freeze.ARTIFACTS}
        return result

    def go(self, result: dict, stage: int, *, expires: int | None = None, evidence: dict | None = None, expect: str | None = None) -> Path:
        path = self.base / f"go-{stage}-{self.counter}-{int(expires or 0)}.json"
        workspace = self.project.root / ".local/linux-python-env-tranche3-synthetic"
        argv = ["go", "--artifacts", str(result["output"]), "--output", str(path), "--stage", str(stage),
                "--run-id", f"lp3-synthetic-{stage}", "--workspace", str(workspace),
                "--expires-unix", str(expires if expires is not None else int(time.time()) + 3600), "--now", str(time.time())]
        if evidence is not None:
            argv += ["--stage1-result", evidence["path"], "--stage1-result-sha256", evidence["sha256"]]
        if expect is not None:
            with self.assertRaisesRegex(freeze.FreezeError, expect):
                freeze.go(freeze.parse(argv))
            return path
        freeze.go(freeze.parse(argv))
        return path

    def stage1_evidence(self) -> dict:
        directory = self.project.root / ".local/linux-python-env-tranche3-stage1"
        directory.mkdir(parents=True, exist_ok=True)
        runtime = str(self.base / "runtime-stage1")
        manifest = json.loads((self.base / "artifacts-1/source-manifest.json").read_bytes()) if (self.base / "artifacts-1").exists() else None
        result = {"owner": lifecycle.OWNER, "stage": 1, "run_id": "lp3-synthetic-stage1", "state": "passed-stage1-debian-python",
                  "cleanup_ok": True, "runtime": runtime, "output": str(directory),
                  "source_manifest_sha256": source.sha256(self.base / "artifacts-1/source-manifest.json") if manifest else "0" * 64}
        (directory / "result.json").write_text(json.dumps(result, sort_keys=True))
        (directory / "cleanup-process-proof.json").write_text(json.dumps(
            {"runtime": runtime, "remaining_owned_processes": [], "instances": [{"name": "synthetic", "status": "Stopped"}]}, sort_keys=True))
        return {"path": str(directory / "result.json"), "sha256": digest(json.dumps(result, sort_keys=True).encode())}

    def validate_go_args(self, result: dict, stage: int, go: Path) -> argparse.Namespace:
        output = result["output"]
        namespace = argparse.Namespace(stage=stage, output=self.project.root / ".local/linux-python-env-tranche3-synthetic",
                                       go=go, source_manifest=output / "source-manifest.json",
                                       checkset=output / f"stage{stage}-checkset.json", package_plan=output / "stage1-packages.json",
                                       handoffs=output / "handoffs.json", deadline_seconds=None,
                                       tool_plan=None if stage == 1 else output / "stage2-tools.json")
        for field in ("go", "source_manifest", "checkset", "package_plan", "handoffs"):
            setattr(namespace, field + "_sha256", source.sha256(getattr(namespace, field)))
        namespace.tool_plan_sha256 = None if stage == 1 else source.sha256(namespace.tool_plan)
        return namespace

    # --- generation, validators and determinism ---------------------------------

    def test_generated_artifacts_pass_every_pure_validator(self):
        result = self.generate()
        values = result["values"]
        source.validate_manifest(values["source-manifest.json"])
        guest_checks.validate_checkset(values["stage1-checkset.json"])
        locked_checks.validate_checkset(values["stage2-checkset.json"])
        provision.validate_plan(values["stage1-packages.json"])
        locked_env.validate_plan(values["stage2-tools.json"])
        self.assertEqual(values["stage1-checkset.json"]["source_manifest_sha256"], result["artifacts"]["source-manifest.json"]["sha256"])
        self.assertEqual(values["stage2-checkset.json"]["tool_plan_sha256"], result["artifacts"]["stage2-tools.json"]["sha256"])
        self.assertEqual(values["stage1-checkset.json"]["package_pins"], values["stage1-packages.json"]["roots"])
        self.assertEqual(values["handoffs.json"]["schema_version"], "poseidon.linux-python-handoffs.v1")
        self.assertLessEqual({"platform", "acquisition"}, set(values["handoffs.json"]["lanes"]))

    def test_validate_go_accepts_both_stages_without_constructing_a_session(self):
        result = self.generate()
        with patch.object(lifecycle, "ROOT", self.project.root), patch.object(lifecycle, "Session", side_effect=AssertionError("no VM session")):
            go, selected = lifecycle.validate_go(self.validate_go_args(result, 1, self.go(result, 1)))
            self.assertEqual(go["stage"], 1)
            self.assertEqual(len(selected["files"]), result["counts"]["files"])
            stage2 = self.validate_go_args(result, 2, self.go(result, 2, evidence=self.stage1_evidence()))
            lifecycle.validate_go(stage2)

    def test_every_executable_input_is_frozen_and_required(self):
        result = self.generate()
        manifest = result["values"]["source-manifest.json"]
        for stage, name in ((1, "stage1-checkset.json"), (2, "stage2-checkset.json")):
            required = lifecycle.required_sources(stage, result["values"][name])
            self.assertTrue(required)
            self.assertLessEqual(required, set(manifest["files"]))
            self.assertLessEqual(required, set(manifest["required_files"]))
        self.assertIn("Makefile", manifest["required_files"])
        self.assertIn("scripts/assurance/run_command.py", manifest["required_files"])

    def test_two_generations_of_one_tree_are_byte_identical(self):
        first, second = self.generate(), self.generate()
        for name in freeze.ARTIFACTS:
            with self.subTest(artifact=name):
                if name in ("index.json", "handoffs.json"):
                    # Both embed the artifacts directory: compare their content
                    # with the generated firmware manifest path normalized.
                    continue
                self.assertEqual(first["artifacts"][name]["sha256"], second["artifacts"][name]["sha256"])
        self.assertEqual(first["executed_command_list_sha256"], second["executed_command_list_sha256"])

        def normalized(result):
            lanes = copy.deepcopy(result["values"]["handoffs.json"]["lanes"])
            for entry in lanes.values():
                entry["manifest"] = Path(entry["manifest"]).name
            return lanes

        self.assertEqual(normalized(first), normalized(second))

    def test_executed_command_digest_follows_the_commands(self):
        result = self.generate()
        stage1, stage2 = result["values"]["stage1-checkset.json"], result["values"]["stage2-checkset.json"]
        self.assertEqual(freeze.executed_commands(stage1, stage2), result["executed_command_list_sha256"])
        moved = copy.deepcopy(stage1)
        moved["commands"][0]["argv"].append("--minimum")
        self.assertNotEqual(freeze.executed_commands(moved, stage2), result["executed_command_list_sha256"])

    # --- handoff integrity ------------------------------------------------------

    def test_tampered_handoff_digest_refuses_generation(self):
        self.project.repost("platform", lambda value: value["sourceFiles"][0].__setitem__("sha256", "b" * 64))
        self.generate(expect="do not match the working tree")

    def test_handoff_path_missing_from_the_tree_refuses(self):
        self.project.repost("native", lambda value: value["files"].__setitem__("tests/tooling/absent.py", "c" * 64))
        self.generate(expect="do not match the working tree")

    def test_rehearsal_accepts_only_the_named_mismatch(self):
        self.project.repost("platform", lambda value: value["sourceFiles"][0].__setitem__("sha256", "d" * 64))
        self.generate("--accept-mismatch", "apps/acoustic/src/acoustic.py", expect="only allowed in a labelled rehearsal")
        self.generate(expect="do not match the working tree")
        result = self.generate("--accept-mismatch", "apps/acoustic/src/acoustic.py", label="rehearsal")
        row = result["accepted_input_mismatches"][0]
        self.assertEqual((row["lane"], row["path"], row["declared_sha256"]), ("platform", "apps/acoustic/src/acoustic.py", "d" * 64))
        self.assertEqual(row["working_tree_sha256"], digest(self.project.files["apps/acoustic/src/acoustic.py"]))
        self.assertEqual(result["values"]["handoffs.json"]["lanes"]["platform"]["files"]["apps/acoustic/src/acoustic.py"], row["working_tree_sha256"])

    def test_unused_accepted_mismatch_refuses(self):
        self.generate("--accept-mismatch", "libs/dsp/src/dsp.py", label="rehearsal", expect="did not occur")

    def test_handoff_manifest_digests_bind_the_published_inputs(self):
        result = self.generate()
        for lane, entry in result["values"]["handoffs.json"]["lanes"].items():
            with self.subTest(lane=lane):
                self.assertEqual(source.sha256(Path(entry["manifest"])), entry["manifest_sha256"])
                for name, sha in entry["files"].items():
                    self.assertEqual(result["values"]["source-manifest.json"]["files"][name]["sha256"], sha)

    # --- Stage1 translation -----------------------------------------------------

    def test_exactly_one_labelled_hil_command_with_the_summed_minimum(self):
        stage1 = self.generate()["values"]["stage1-checkset.json"]
        labelled = [command for command in stage1["commands"] if command.get("evidence_label")]
        self.assertEqual(len(labelled), 1)
        self.assertEqual(labelled[0]["evidence_label"], LABEL)
        self.assertEqual(labelled[0]["argv"][-2:], ["--minimum", "22"])
        self.assertNotIn("--class-name", labelled[0]["argv"])
        self.assertEqual([command["id"] for command in stage1["commands"] if HIL in command["coverage"]], [labelled[0]["id"]])

    def test_a_second_hil_command_or_expected_exit_is_refused_by_the_validator(self):
        stage1 = self.generate()["values"]["stage1-checkset.json"]
        labelled = next(command for command in stage1["commands"] if command.get("evidence_label"))
        unlabelled = copy.deepcopy(labelled)
        unlabelled["id"] = "second-hil-command"
        del unlabelled["evidence_label"]
        two_commands = copy.deepcopy(stage1)
        two_commands["commands"].append(unlabelled)
        with self.assertRaisesRegex(ValueError, "exact limited HIL evidence label"):
            guest_checks.validate_checkset(two_commands)
        misplaced = copy.deepcopy(stage1)
        misplaced["commands"][0]["evidence_label"] = LABEL
        with self.assertRaisesRegex(ValueError, "only the labelled HIL guard check"):
            guest_checks.validate_checkset(misplaced)
        duplicate = copy.deepcopy(stage1)
        duplicate["commands"].append(copy.deepcopy(labelled))
        with self.assertRaisesRegex(ValueError, "duplicate command identity"):
            guest_checks.validate_checkset(duplicate)
        proposal_exit = copy.deepcopy(stage1)
        proposal_exit["commands"][0]["expected_exit"] = 0
        with self.assertRaisesRegex(ValueError, "invalid command fields"):
            guest_checks.validate_checkset(proposal_exit)
        self.assertTrue(all("expected_exit" not in command for command in stage1["commands"]))

    def test_nonzero_expected_exit_in_the_proposal_refuses(self):
        self.project.repost("proposal", lambda value: value["stage1"]["commands"][0].__setitem__("expected_exit", 1))
        self.generate(expect="zero-exit")

    def test_locked_lanes_never_become_stage1_coverage(self):
        stage1 = self.generate()["values"]["stage1-checkset.json"]
        compile_command = next(command for command in stage1["commands"] if command["id"] == "compile-python")
        self.assertIn("tests/tooling/test_tooling.py", compile_command["coverage"])
        self.assertNotIn("tests/api/test_locked.py", compile_command["coverage"])
        self.assertNotIn("tests/trident/test_lifecycle.py", compile_command["coverage"])
        self.assertNotIn(HIL, compile_command["coverage"])
        self.assertEqual(compile_command["argv"][-2:], ["tests", "tests/api"])
        omitted = {path for entry in stage1["omissions"] for path in entry["paths"]}
        self.assertLessEqual({"tests/api", "tests/nereid"}, omitted)

    def test_directory_coverage_expands_to_exact_frozen_files(self):
        stage1 = self.generate()["values"]["stage1-checkset.json"]
        hardware = next(command for command in stage1["commands"] if command["id"] == "check-hardware-reference")
        self.assertEqual(sorted(hardware["coverage"]),
                         ["Makefile", "hardware/cad/generated/reference-v1/part.step", "hardware/validation/check_reference.py"])
        ops = next(command for command in stage1["commands"] if command["id"] == "ops-static")
        self.assertEqual(ops["coverage"], ["ops/compose/compose.json"])

    def test_package_plan_versions_come_only_from_the_availability_proof(self):
        self.project.repost("proposal", lambda value: value["stage1"]["apt_root_pins"].__setitem__("make", "9.9.9-1"))
        self.generate(expect="not in the retained availability proof")

    def test_online_availability_record_is_refused(self):
        self.project.repost("availability", lambda value: value.__setitem__("network_used", True))
        self.generate(expect="accepted offline snapshot record")

    # --- Stage2 translation -----------------------------------------------------

    def test_stage2_argv_uses_placeholders_and_absolute_make(self):
        stage2 = self.generate()["values"]["stage2-checkset.json"]
        for command in stage2["commands"]:
            with self.subTest(command=command["id"]):
                self.assertEqual(set(command), {"id", "lane", "argv", "timeout_seconds", "environment", "coverage"})
                self.assertNotIn("{workspace}", json.dumps(command["argv"]))
        hardware = next(command for command in stage2["commands"] if command["id"] == "check-hardware-reference")
        self.assertEqual(hardware["argv"][:3], ["/usr/bin/make", "check-hardware-reference", "PYTHON={python}"])
        self.assertEqual(next(command for command in stage2["commands"] if command["id"] == "codec")["argv"][0], "{python}")
        self.assertEqual(next(command for command in stage2["commands"] if command["id"] == "platform")["environment"], {"REEF_SANITIZE": "1"})

    def test_stage2_interpreter_from_another_lane_refuses(self):
        self.project.repost("proposal", lambda value: value["stage2"]["commands"][0]["argv"].__setitem__(0, "{workspace}/envs/nereid/bin/python"))
        self.generate(expect="not its own lane")

    def test_stage2_keeps_the_proposal_scope_language_as_omissions(self):
        stage2 = self.generate()["values"]["stage2-checkset.json"]
        reasons = " ".join(entry["reason"] for entry in stage2["omissions"])
        self.assertIn("SYNTHETIC software regression only", reasons)
        self.assertIn("SYNTHETIC locked lane regression", reasons)
        self.assertIn("SYNTHETIC device operations", str(stage2["omissions"]))

    def test_tool_plan_takes_official_pins_and_frozen_lock_digests(self):
        result = self.generate()
        plan = result["values"]["stage2-tools.json"]
        self.assertEqual(plan["uv"], artifacts.UV_PIN)
        self.assertEqual(plan["python"], artifacts.PYTHON_PINS)
        for lane, (project, _) in locked_env.LANES.items():
            self.assertEqual(plan["locks"][lane]["lock_sha256"], digest(self.project.files[f"{project}/uv.lock"]))
        self.assertEqual(result["translation_notes"], sorted(set(result["translation_notes"])))

    def test_published_tool_plan_lock_drift_is_reported(self):
        self.project.repost("tools", lambda value: value["locks"]["api"].__setitem__("lock_sha256", "e" * 64))
        result = self.generate()
        self.assertTrue(any("differs from the published tool plan" in note for note in result["translation_notes"]))
        self.assertEqual(result["values"]["stage2-tools.json"]["locks"]["api"]["lock_sha256"],
                         digest(self.project.files["apps/aeolus-api/uv.lock"]))

    # --- closure and go record --------------------------------------------------

    def test_closure_skips_caches_credentials_and_symlinks(self):
        (self.project.root / "apps/aeolus-ui").mkdir(parents=True, exist_ok=True)
        (self.project.root / "apps/aeolus-ui/.env.example").write_bytes(b"SYNTHETIC=1\n")
        (self.project.root / "tests/tooling/__pycache__").mkdir(parents=True, exist_ok=True)
        (self.project.root / "tests/tooling/__pycache__/test_tooling.pyc").write_bytes(b"\x00")
        (self.project.root / "tests/tooling/private.pem").write_bytes(b"SYNTHETIC KEY\n")
        os.symlink(self.project.root / "Makefile", self.project.root / "tests/tooling/link.py")
        result = self.generate()
        files = result["values"]["source-manifest.json"]["files"]
        for name in ("apps/aeolus-ui/.env.example", "tests/tooling/__pycache__/test_tooling.pyc",
                     "tests/tooling/private.pem", "tests/tooling/link.py"):
            self.assertNotIn(name, files)
        excluded = {row["path"] for row in result["values"]["index.json"]["excluded_paths"]}
        self.assertIn("tests/tooling/private.pem", excluded)
        self.assertIn("apps/aeolus-ui/.env.example", excluded)

    def test_docs_tree_is_a_closure_root_for_document_reading_tests(self):
        # Run lp3-stage1-004: tests/assurance/test_dossier.py and test_evidence.py read
        # docs/manufacturing, docs/qualification, docs/requirements and the roadmap.
        for name in ("docs/manufacturing/templates/unperformed-records.json",
                     "docs/qualification/procedures/evt-dvt-pvt.md",
                     "docs/requirements/production-requirements.md", "docs/production-roadmap.md"):
            self.project.write(name, f"# SYNTHETIC document {name}\n".encode())
        result = self.generate()
        manifest = result["values"]["source-manifest.json"]
        self.assertIn("docs", freeze.CLOSURE_ROOTS)
        self.assertIn("docs", manifest["coverage_roots"])
        for name in ("docs/manufacturing/templates/unperformed-records.json",
                     "docs/qualification/procedures/evt-dvt-pvt.md",
                     "docs/requirements/production-requirements.md", "docs/production-roadmap.md",
                     "docs/acquisition/synthetic.md"):
            self.assertIn(name, manifest["files"])
            self.assertIn(name, manifest["required_files"])
        self.assertNotIn("docs/acquisition/synthetic.md", result["values"]["index.json"]["closure"]["declared_files_outside_roots"])
        self.assertIn("HARDWARE.md", freeze.CLOSURE_ROOT_FILES)
        self.assertIn("HARDWARE.md", manifest["files"])

    def test_root_frozen_files_are_enforced_and_required(self):
        result = self.generate()
        for name in freeze.ROOT_FROZEN:
            self.assertIn(name, result["values"]["source-manifest.json"]["required_files"])
            self.assertEqual(result["values"]["source-manifest.json"]["files"][name]["sha256"], digest(self.project.files[name]))
        (self.project.root / "Makefile").write_bytes(b"# SYNTHETIC Makefile edited after the freeze\n")
        self.generate(expect="root-frozen files do not match")

    def test_generation_never_writes_a_go_record(self):
        result = self.generate()
        self.assertEqual(sorted(path.name for path in result["output"].iterdir()), sorted(freeze.ARTIFACTS))
        self.assertEqual(result["values"]["index.json"]["state"], "artifacts-generated-no-go-record")
        self.assertIs(result["values"]["index.json"]["release_authorized"], False)

    def test_generation_refuses_to_reuse_an_existing_directory(self):
        result = self.generate()
        argv = ["generate", "--root", str(self.project.root), "--output", str(result["output"]), *self.project.expectations()]
        for name in ("platform", "acquisition", "native", "helpers", "proposal", "tools", "availability"):
            argv += ["--" + name, str(self.project.paths[name])]
        with self.assertRaisesRegex(freeze.FreezeError, "new directory"):
            freeze.generate(freeze.parse(argv))

    def test_go_binds_every_generated_digest_and_needs_a_live_expiry(self):
        result = self.generate()
        record = json.loads(self.go(result, 1).read_bytes())
        self.assertEqual(record["source_manifest_sha256"], result["artifacts"]["source-manifest.json"]["sha256"])
        self.assertEqual(record["checkset_sha256"], result["artifacts"]["stage1-checkset.json"]["sha256"])
        self.assertEqual(record["package_plan_sha256"], result["artifacts"]["stage1-packages.json"]["sha256"])
        self.assertEqual(record["handoffs_sha256"], result["artifacts"]["handoffs.json"]["sha256"])
        self.assertIsNone(record["tool_plan_sha256"])
        self.assertIs(record["release_authorized"], False)
        self.go(result, 1, expires=1, expect="expiry is already past")
        self.go(result, 2, expect="stopped Stage1 result")

    def test_expired_go_is_refused_by_validate_go(self):
        result = self.generate()
        go = self.go(result, 1, expires=int(time.time()) + 5)
        with patch.object(lifecycle, "ROOT", self.project.root):
            arguments = self.validate_go_args(result, 1, go)
            lifecycle.validate_go(arguments, now=time.time())
            with self.assertRaisesRegex(ValueError, "expired"):
                lifecycle.validate_go(arguments, now=time.time() + 600)


if __name__ == "__main__":
    unittest.main()
