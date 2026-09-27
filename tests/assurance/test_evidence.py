"""Synthetic negative fixtures for evidence validation, not certification records."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/assurance"))
import evidence as ev
from run_system_checks import run
from snapshot import snapshot


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="poseidon-assurance-negative-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in (ev.POLICY, "docs/requirements/production-requirements.md", "docs/production-roadmap.md"):
            self.put(relative, (ROOT / relative).read_text())
        self.rules = ev.policy(self.root)
        for directory in ev.SOURCE_DIRS:
            self.put(f"{directory}/synthetic.py", "# Synthetic validator fixture, not product source.\n")
        for dependency in ev.DEPENDENCY_FILES:
            self.put(dependency, "# Synthetic dependency fixture, not a product lock.\n")
        self.put("tests/system/fixture.wav", "SYNTHETIC NONCODE FIXTURE BYTES")
        self.report_path = next(gate["artifact"] for gate in self.rules["gates"] if gate["id"] == "G-LOCAL")
        self.log_path = str(Path(self.report_path).with_suffix(".log"))
        test_id = "test_synthetic (synthetic_fixture.SyntheticTests.test_synthetic)"
        self.put(self.log_path, f"{test_id} ... ok\n\nRan 1 test in 0.001s\n\nOK\n")
        self.report = {
            "schema_version": 1, "configuration": self.rules["configuration"], "evidence_level": "simulated",
            "provenance": "synthetic", "created_at": datetime.now(timezone.utc).isoformat(),
            "command": ev.TEST_COMMAND, "exit_code": 0, "tests_run": 1, "failures": 0, "errors": 0,
            "skipped": 0, "input_hashes": ev.source_hashes(self.root), "test_ids": [test_id],
            "log": self.log_path, "log_sha256": ev.digest(self.root / self.log_path), "release_authorized": False,
        }
        self.put(self.report_path, json.dumps(self.report))
        paths = {}
        for gate in self.rules["gates"]:
            if gate["artifact"] != self.report_path:
                paths.setdefault(gate["artifact"], []).append(gate["id"])
        plan = "# SYNTHETIC VALIDATOR FIXTURE ONLY\nStatus: blocked; not performed.\n" + (
            "This is an unperformed procedure fixture, not field data, approval, measured pressure or legal assessment. " * 3)
        for path in paths:
            self.put(path, plan)
        self.put("docs/qualification/evidence-guide.md", plan)
        self.manifest = {
            "schema_version": 1, "policy_id": self.rules["policy_id"], "configuration": self.rules["configuration"],
            "created_at": datetime.now(timezone.utc).isoformat(), "release_authorized": False,
            "claims": {g["id"]: "software-checks-passed" if g["id"] == "G-LOCAL" else "blocked" for g in self.rules["gates"]},
            "artifacts": [self.artifact(path, "plan", "documented-plan", gates) for path, gates in paths.items()]
                         + [self.artifact(self.report_path, "test-report", "simulated", ["G-LOCAL"])],
        }
        self.manifest_path = self.root / "manifest.json"
        self.save()

    def put(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def artifact(self, path: str, kind: str, level: str, gates: list[str]) -> dict:
        return {"path": path, "sha256": ev.digest(self.root / path), "bytes": (self.root / path).stat().st_size,
                "kind": kind, "level": level, "gates": gates, "configuration": self.rules["configuration"]}

    def save(self) -> None:
        self.manifest_path.write_text(json.dumps(self.manifest))

    def update_report(self) -> None:
        self.put(self.report_path, json.dumps(self.report))
        self.manifest["artifacts"][-1] = self.artifact(self.report_path, "test-report", "simulated", ["G-LOCAL"])
        self.save()

    def rejected(self) -> None:
        with self.assertRaises(ev.EvidenceError):
            ev.evaluate(self.root, self.manifest_path)

    def test_valid_integrity_never_authorizes_release(self) -> None:
        result = ev.evaluate(self.root, self.manifest_path)
        self.assertIs(result["release_authorized"], False)
        self.assertEqual(sum(g["status"] == "software-checks-passed" for g in result["gates"]), 1)
        self.assertEqual(sum(g["status"] == "blocked" for g in result["gates"]), 14)

    def test_missing_artifact_fails(self) -> None:
        (self.root / self.manifest["artifacts"][0]["path"]).unlink()
        self.rejected()

    def test_changed_bytes_fail(self) -> None:
        path = self.root / self.manifest["artifacts"][0]["path"]
        path.write_text(path.read_text() + "changed")
        self.rejected()

    def test_duplicate_json_keys_and_nonfinite_fail(self) -> None:
        for content in ('{"schema_version":1,"schema_version":1}', '{"value":NaN}', '{"value":Infinity}'):
            with self.subTest(content=content):
                self.manifest_path.write_text(content)
                self.rejected()

    def test_bad_shapes_fail(self) -> None:
        original = copy.deepcopy(self.manifest)
        for key, value in (("schema_version", True), ("artifacts", []), ("claims", {}),
                           ("configuration", "different-hardware"), ("created_at", "2999-01-01T00:00:00Z")):
            with self.subTest(key=key):
                self.manifest = original | {key: value}
                self.save()
                self.rejected()

    def test_false_physical_and_release_claims_fail(self) -> None:
        for gate in ("G-SAFETY", "G-MECHANICAL", "G-EFFICACY", "G-CONFORMITY", "G-MANUFACTURE"):
            with self.subTest(gate=gate):
                self.manifest["claims"][gate] = "software-checks-passed"
                self.save()
                self.rejected()
                self.manifest["claims"][gate] = "blocked"
        self.manifest["release_authorized"] = True
        self.save()
        self.rejected()

    def test_synthetic_report_cannot_be_physical_proof(self) -> None:
        self.manifest["artifacts"][-1]["level"] = "physically-tested"
        self.save()
        self.rejected()

    def test_document_cannot_be_promoted_by_label(self) -> None:
        self.manifest["artifacts"][0]["level"] = "independently-reviewed"
        self.save()
        self.rejected()

    def test_empty_or_placeholder_plan_fails_even_with_matching_hash(self) -> None:
        item = self.manifest["artifacts"][0]
        self.put(item["path"], "# TODO\n")
        self.manifest["artifacts"][0] = self.artifact(item["path"], "plan", "documented-plan", item["gates"])
        self.save()
        self.rejected()

    def test_json_inventories_are_hashed_data_not_plans(self) -> None:
        inventory = "docs/compliance/software-supply-chain/sbom.cdx.json"
        template = "docs/manufacturing/templates/unperformed-records.json"
        self.put(inventory, json.dumps({"bomFormat": "CycloneDX", "components": []}))
        self.put(template, json.dumps({"is_template": True, "status": "not performed; blocked pending physical work " * 8}))
        output = self.root / "inventory-snapshot.json"
        snapshot(self.root, output)
        kinds = {a["path"]: (a["kind"], a["level"]) for a in json.loads(output.read_text())["artifacts"]}
        self.assertEqual(kinds[inventory], ("inventory", "software-complete"))
        self.assertEqual(kinds[template], ("plan", "documented-plan"))
        self.assertIs(ev.evaluate(self.root, output)["integrity_valid"], True)
        self.manifest["artifacts"].append(self.artifact(inventory, "inventory", "independently-reviewed", ["G-CONFORMITY"]))
        self.save()
        self.rejected()
        self.put(inventory, "{}")
        self.manifest["artifacts"][-1] = self.artifact(inventory, "inventory", "software-complete", ["G-CONFORMITY"])
        self.save()
        self.rejected()

    def test_unknown_fields_and_duplicate_artifacts_fail(self) -> None:
        self.manifest["artifacts"][0]["approved"] = True
        self.save()
        self.rejected()
        del self.manifest["artifacts"][0]["approved"]
        self.manifest["artifacts"].append(copy.deepcopy(self.manifest["artifacts"][0]))
        self.save()
        self.rejected()

    def test_path_traversal_absolute_and_symlink_fail(self) -> None:
        original = self.manifest["artifacts"][0]["path"]
        for path in ("../outside", str(self.root / original), "docs/../other", "./manifest.json", "docs\\other"):
            with self.subTest(path=path):
                self.manifest["artifacts"][0]["path"] = path
                self.save()
                self.rejected()
        link = self.root / "linked-evidence.md"
        link.symlink_to(self.root / original)
        self.manifest["artifacts"][0]["path"] = "linked-evidence.md"
        self.save()
        self.rejected()

    def test_stale_added_and_removed_sources_fail(self) -> None:
        path = self.root / ev.SOURCE_DIRS[0] / "synthetic.py"
        before = path.read_text()
        path.write_text("changed source")
        self.rejected()
        path.write_text(before)
        added = path.parent / "new.py"
        added.write_text("new source")
        self.rejected()
        added.unlink()
        path.unlink()
        self.rejected()

    def test_false_test_results_fail(self) -> None:
        original = copy.deepcopy(self.report)
        for key, value in (("exit_code", 1), ("tests_run", 0), ("tests_run", True), ("failures", 1),
                           ("errors", 1), ("skipped", 1), ("provenance", "field"), ("release_authorized", True),
                           ("command", ["echo", "OK"]), ("test_ids", ["test_fake (fake.case.test_fake)"])):
            with self.subTest(key=key):
                self.report = original | {key: value}
                self.update_report()
                self.rejected()

    def test_false_test_log_fails_even_with_updated_hash(self) -> None:
        self.put(self.log_path, "Ran 1 test in 0.001s\n\nOK\n")
        self.report["log_sha256"] = ev.digest(self.root / self.log_path)
        self.update_report()
        self.rejected()

    def test_contradictory_or_extra_test_log_results_fail(self) -> None:
        original = (self.root / self.log_path).read_text()
        for prefix in (
            "test_bad (fake.Case.test_bad) ... FAIL\nFAILED (failures=1)\nRan 2 tests in 0.1s\n",
            "test_extra (fake.Case.test_extra) ... ok\n",
            "test_skipped (fake.Case.test_skipped) ... skipped 'not performed'\n",
            "Ran 1 test in 0.2s\n",
        ):
            with self.subTest(prefix=prefix):
                self.put(self.log_path, prefix + original)
                self.report["log_sha256"] = ev.digest(self.root / self.log_path)
                self.update_report()
                self.rejected()

    def test_noncode_fixture_and_dependency_changes_invalidate_report(self) -> None:
        for relative in ("tests/system/fixture.wav", *ev.DEPENDENCY_FILES):
            with self.subTest(relative=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.write_bytes(original + b" changed")
                self.rejected()
                path.write_bytes(original)

    def test_malformed_policy_metadata_fails(self) -> None:
        original = copy.deepcopy(self.rules)
        for key, value in (("policy_id", []), ("configuration", {}), ("configuration", "../escape"),
                           ("date", "invalid"), ("date", "2999-01-01"),
                           ("evidence_levels", {level: True for level in ev.LEVELS}),
                           ("evidence_levels", original["evidence_levels"] + ["simulated"])):
            with self.subTest(key=key):
                self.put(ev.POLICY, json.dumps(original | {key: value}))
                self.rejected()

    def test_manifest_cannot_omit_gate_artifact(self) -> None:
        self.manifest["artifacts"].pop(0)
        self.save()
        self.rejected()

    def test_policy_missing_requirements_or_verification_gates_fails(self) -> None:
        self.rules["gates"][0]["requirements"] = ["REQ-SW-001"]
        self.put(ev.POLICY, json.dumps(self.rules))
        self.rejected()

    def test_policy_cannot_automate_external_gate(self) -> None:
        self.rules["gates"][1]["automated"] = True
        self.put(ev.POLICY, json.dumps(self.rules))
        self.rejected()

    def test_policy_rejects_unknown_and_cyclic_dependency(self) -> None:
        for dependency in ("G-MISSING", "G-SCOPE"):
            with self.subTest(dependency=dependency):
                self.rules["gates"][1]["dependencies"] = [dependency]
                self.put(ev.POLICY, json.dumps(self.rules))
                self.rejected()

    def test_external_template_or_missing_raw_proof_fails(self) -> None:
        external = {"schema_version": 1, "is_template": True, "configuration": self.rules["configuration"],
                    "evidence_level": "physically-tested", "performed_at": datetime.now(timezone.utc).isoformat(),
                    "author": "SYNTHETIC FIXTURE", "method": "SYNTHETIC METHOD", "criterion_revision": "fixture-v1",
                    "result": "SYNTHETIC NOT ACTUAL PASS", "raw_files": {}, "limitations": "Not actual evidence"}
        path = "external-fixture.json"
        for template in (True, False):
            with self.subTest(template=template):
                external["is_template"] = template
                self.put(path, json.dumps(external))
                item = self.artifact(path, "external-candidate", "physically-tested", ["G-MECHANICAL"])
                self.manifest["artifacts"].append(item)
                self.save()
                self.rejected()
                self.manifest["artifacts"].pop()

    def test_external_self_attestation_never_closes_gate(self) -> None:
        self.put("synthetic-raw.txt", "SYNTHETIC SELF-ASSERTED NOT PHYSICAL DATA")
        external = {"schema_version": 1, "is_template": False, "configuration": self.rules["configuration"],
                    "evidence_level": "physically-tested", "performed_at": datetime.now(timezone.utc).isoformat(),
                    "author": "SYNTHETIC CLAIMANT", "method": "SYNTHETIC", "criterion_revision": "fixture-v1",
                    "result": "claims-pass", "raw_files": {"synthetic-raw.txt": ev.digest(self.root / "synthetic-raw.txt")},
                    "limitations": "This tests rejection of untrusted self-assertions as approval"}
        self.put("external-fixture.json", json.dumps(external))
        self.manifest["artifacts"].append(self.artifact("external-fixture.json", "external-candidate", "physically-tested", ["G-MECHANICAL"]))
        self.save()
        result = ev.evaluate(self.root, self.manifest_path)
        self.assertEqual(next(g for g in result["gates"] if g["id"] == "G-MECHANICAL")["status"], "blocked")
        self.assertIs(result["release_authorized"], False)

    def test_exclusive_report_output_preserves_unknown_files(self) -> None:
        target = self.root / "user.json"
        target.write_text("USER CONTENT")
        with self.assertRaises(FileExistsError):
            ev.write_new(target, {"overwritten": True})
        self.assertEqual(target.read_text(), "USER CONTENT")
        with self.assertRaises(ev.EvidenceError):
            run(self.root, self.root)
        self.assertEqual(target.read_text(), "USER CONTENT")

    def test_snapshot_is_valid_and_refuses_existing_output(self) -> None:
        output = self.root / "snapshot.json"
        snapshot(self.root, output)
        self.assertIs(ev.evaluate(self.root, output)["release_authorized"], False)
        before = output.read_bytes()
        with self.assertRaises(FileExistsError):
            snapshot(self.root, output)
        self.assertEqual(output.read_bytes(), before)
        original_policy = (self.root / ev.POLICY).read_bytes()
        revised_policy = "docs/qualification/gate-policy-next.json"
        revised_report = "docs/qualification/evidence-next/system-checks-v1.json"
        self.put(revised_report, json.dumps(self.report))
        for gate in self.rules["gates"]:
            if gate["artifact"] == self.report_path:
                gate["artifact"] = revised_report
        self.rules["policy_id"] += ".next"
        self.put(revised_policy, json.dumps(self.rules))
        revised_manifest = self.root / "snapshot-next.json"
        snapshot(self.root, revised_manifest, revised_policy)
        self.assertIs(ev.evaluate(self.root, revised_manifest, revised_policy)["integrity_valid"], True)
        self.assertIs(ev.evaluate(self.root, output)["integrity_valid"], True)
        self.assertEqual((self.root / ev.POLICY).read_bytes(), original_policy)
        self.assertEqual(output.read_bytes(), before)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/assurance/evidence.py"), "evaluate",
                                 "--root", str(self.root), "--manifest", revised_manifest.name,
                                 "--policy", revised_policy], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIs(json.loads(result.stdout)["release_authorized"], False)

    def test_writers_reject_traversal_and_symlink_parents(self) -> None:
        paths = [self.root / ".." / "outside-assurance-output"]
        link = self.root / "linked-parent"
        link.symlink_to(self.root, target_is_directory=True)
        paths.append(link / "output")
        for path in paths:
            with self.subTest(path=path):
                with self.assertRaises(ev.EvidenceError):
                    run(self.root, path)
                with self.assertRaises(ev.EvidenceError):
                    snapshot(self.root, path)

    def test_cli_distinguishes_integrity_and_blocked_release(self) -> None:
        for action, expected in (("validate", 0), ("evaluate", 2)):
            result = subprocess.run([sys.executable, str(ROOT / "scripts/assurance/evidence.py"), action,
                                     "--root", str(self.root), "--manifest", "manifest.json"],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
            self.assertIs(json.loads(result.stdout)["release_authorized"], False)
        self.manifest_path.write_text("{broken")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/assurance/evidence.py"), "validate",
                                 "--root", str(self.root), "--manifest", "manifest.json"],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertIs(json.loads(result.stdout)["integrity_valid"], False)

    def test_runner_refuses_source_change_during_test(self) -> None:
        def changed(*args, **kwargs):
            self.put(f"{ev.SOURCE_DIRS[0]}/changed.py", "changed during run")
            return subprocess.CompletedProcess(ev.TEST_COMMAND, 0, "", "Ran 1 test in 0.01s\nOK\n")
        output = self.root / "new-report"
        with patch("run_system_checks.subprocess.run", side_effect=changed):
            with self.assertRaises(ev.EvidenceError):
                run(self.root, output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
