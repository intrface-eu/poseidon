"""Synthetic source-transfer/check-set tests only; no VM or package download."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.assurance.linux_python_env import guest_checks, source


class FullSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="poseidon-synthetic-python-source-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "source"
        self.root.mkdir()
        self.files = {"apps/acoustic/src/synthetic/__init__.py": b"SYNTHETIC = True\n",
                      "tests/assurance/test_synthetic.py": b"# SYNTHETIC fixture only\n"}
        self.manifest = {"schema_version": "poseidon.linux-python-sources.v1", "files": {},
                         "required_files": list(self.files), "coverage_roots": ["apps/acoustic/src", "tests/assurance"]}
        for name, raw in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.manifest["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}

    def test_normal_full_import_closure_roundtrip_and_deterministic_tar(self):
        archive = self.base / "first.tar"
        first = source.freeze(self.root, self.manifest, self.base / "stage", archive)
        source.unpack(archive, self.base / "guest", self.manifest)
        second = source.freeze(self.root, self.manifest, self.base / "stage2", self.base / "second.tar")
        self.assertEqual(first, second)
        self.assertEqual(first["files"], 2)
        source.verify(self.base / "guest", self.manifest)
        self.assertEqual((self.base / "guest/apps/acoustic/src/synthetic/__init__.py").read_bytes(), self.files["apps/acoustic/src/synthetic/__init__.py"])

    def test_path_policy_rejects_caches_keys_traversal_and_private_state(self):
        for name in ("../escape", "/etc/passwd", "apps//x.py", "apps/./x.py", "apps/../x.py", "apps\\x.py", "apps/.venv/key", "apps/.env", "apps/key.pem", ".taskmaster/config.json", ".git/config", ".local/evidence.json", "home/private"):
            with self.subTest(name=name), self.assertRaises(source.SourceError):
                source.safe_name(name)

    def test_missing_required_package_init_fails(self):
        broken = copy.deepcopy(self.manifest)
        del broken["files"]["apps/acoustic/src/synthetic/__init__.py"]
        with self.assertRaisesRegex(source.SourceError, "required"):
            source.validate_manifest(broken)

    def test_duplicate_and_nonfinite_manifest_json_fail(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]'):
            with self.assertRaises(ValueError):
                source.strict_json(raw)

    def test_hash_size_and_nonregular_files_fail(self):
        path = self.root / "tests/assurance/test_synthetic.py"
        path.write_bytes(b"CHANGED synthetic source")
        with self.assertRaises(source.SourceError):
            source.verify(self.root, self.manifest)
        path.unlink()
        path.symlink_to(self.root / "apps/acoustic/src/synthetic/__init__.py")
        with self.assertRaises(source.SourceError):
            source.verify(self.root, self.manifest)

    def test_source_mutation_during_copy_fails_and_preserves_partial_evidence(self):
        real = source.read_file
        calls = 0

        def changed(root, name, expected):
            nonlocal calls
            calls += 1
            data = real(root, name, expected)
            if calls == 3:
                (self.root / "tests/assurance/test_synthetic.py").write_bytes(b"changed")
            return data

        with patch.object(source, "read_file", side_effect=changed), self.assertRaises(source.SourceError):
            source.freeze(self.root, self.manifest, self.base / "stage", self.base / "partial.tar")
        self.assertTrue((self.base / "partial.tar").exists())

    def test_staged_extra_source_file_is_not_accepted(self):
        (self.root / "tests/assurance/test_unlisted.py").write_text("# new unlisted source\n")
        with self.assertRaisesRegex(source.SourceError, "membership changed"):
            source.verify(self.root, self.manifest)
        # Transfer never adds the unlisted file as an implicit import dependency.
        source.freeze(self.root, self.manifest, self.base / "stage", self.base / "selected.tar")
        self.assertFalse((self.base / "stage/tests/assurance/test_unlisted.py").exists())

    def test_existing_output_is_preserved(self):
        output = self.base / "already-owned-by-another-run"
        output.mkdir()
        (output / "unknown").write_text("retain")
        with self.assertRaises(source.SourceError):
            source.freeze(self.root, self.manifest, output, self.base / "new.tar")
        self.assertEqual((output / "unknown").read_text(), "retain")

    def test_tar_extra_duplicate_link_and_device_members_refuse(self):
        for kind in ("extra", "duplicate", "link", "device"):
            archive = self.base / (kind + ".tar")
            with tarfile.open(archive, "w") as bundle:
                name = "tests/assurance/test_synthetic.py"
                raw = self.files[name]
                member = tarfile.TarInfo("tests/assurance/extra.py" if kind == "extra" else name)
                member.size = len(raw)
                if kind == "link":
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/SYNTHETIC-not-an-actual-device"
                if kind == "device":
                    member.type = tarfile.CHRTYPE
                bundle.addfile(member, io.BytesIO(raw) if member.isfile() else None)
                if kind == "duplicate":
                    bundle.addfile(member, io.BytesIO(raw))
            with self.subTest(kind=kind), self.assertRaises(source.SourceError):
                source.unpack(archive, self.base / (kind + "-guest"), self.manifest)

    def test_tar_missing_and_tampered_members_refuse(self):
        for name, content in (("missing", b""), ("tampered", b"# SYNTHETIC fixture only!")):
            archive = self.base / (name + ".tar")
            with tarfile.open(archive, "w") as bundle:
                if name == "tampered":
                    member = tarfile.TarInfo("tests/assurance/test_synthetic.py")
                    member.size = len(content)
                    bundle.addfile(member, io.BytesIO(content))
            with self.assertRaises(source.SourceError):
                source.unpack(archive, self.base / (name + "-guest"), self.manifest)


class GuestChecksetTests(unittest.TestCase):
    def valid(self):
        return {"schema_version": "poseidon.linux-python-checkset.v1", "python_version": "3.13.5",
                "source_manifest_sha256": "a" * 64,
                "omissions": [{"paths": ["tests/api", "tests/nereid"], "reason": "SYNTHETIC lock unavailable; cryptography46 lanes stay Stage2"}],
                "package_pins": {"python3": "3.13.5-1"}, "commands": [{"id": "synthetic-unittest", "argv": ["/usr/bin/python3", "-m", "scripts.assurance.linux_python_env.suite", "--root", "tests/assurance", "--pattern", "test_linux_python_env.py", "--minimum", "1"], "timeout_seconds": 30, "environment": {}, "coverage": ["tests/assurance/test_linux_python_env.py"]}]}

    def test_suite_selector_needs_exact_root_pattern_and_positive_minimum(self):
        base = ["/usr/bin/python3", "-m", "scripts.assurance.linux_python_env.suite"]
        good = base + ["--root", "tests/assurance", "--pattern", "test_hil_gate.py", "--minimum", "13", "--class-name", "HilSyntheticSignatureTests"]
        self.assertEqual(guest_checks.stage1_command_paths(good),
                         {"tests/assurance/test_hil_gate.py", "scripts/assurance/linux_python_env/suite.py"})
        for tail in (["--root", "tests/assurance", "--pattern", "test_hil_gate.py"],
                     ["--root", "tests/assurance", "--pattern", "test_hil_gate.py", "--minimum", "0"],
                     ["--root", "tests/assurance", "--pattern", "test_hil_gate.py", "--minimum", "-1"],
                     ["--root", "tests/assurance", "--pattern", "*.py", "--minimum", "1"],
                     ["--root", "../escape", "--pattern", "test_hil_gate.py", "--minimum", "1"],
                     ["--root", "tests/assurance", "--pattern", "test_hil_gate.py", "--minimum", "1", "--class-name", "not a class"],
                     ["--root", "tests/assurance", "--pattern", "test_hil_gate.py", "--minimum", "1", "--verbose", "1"]):
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                guest_checks.stage1_command_paths(base + tail)

    def test_hil_command_needs_the_exact_limited_label(self):
        checkset = self.valid()
        command = checkset["commands"][0]
        command["argv"][6] = "test_hil_gate.py"
        command["coverage"] = ["tests/assurance/test_hil_gate.py"]
        with self.assertRaisesRegex(ValueError, "HIL"):
            guest_checks.validate_checkset(copy.deepcopy(checkset))
        command["evidence_label"] = guest_checks.HIL_LABEL
        self.assertEqual(guest_checks.validate_checkset(copy.deepcopy(checkset))["commands"][0]["evidence_label"], guest_checks.HIL_LABEL)
        command["evidence_label"] = "SYNTHETIC cryptography 46 qualified"
        with self.assertRaises(ValueError):
            guest_checks.validate_checkset(copy.deepcopy(checkset))

    def test_non_hil_command_may_not_carry_an_evidence_label(self):
        checkset = self.valid()
        checkset["commands"][0]["evidence_label"] = guest_checks.HIL_LABEL
        with self.assertRaises(ValueError):
            guest_checks.validate_checkset(checkset)

    def test_locked_crypto46_lanes_cannot_be_selected_or_left_unstated(self):
        for coverage, pattern, root in ((["tests/api/test_routes.py"], "test_routes.py", "tests/api"),
                                        (["tests/nereid/test_codec.py"], "test_codec.py", "tests/nereid"),
                                        (["tests/firmware/test_update.py"], "test_update.py", "tests/firmware"),
                                        (["tests/trident/test_lifecycle.py"], "test_lifecycle.py", "tests/trident"),
                                        (["tests/acoustic/linux_backend_abi/test_abi.py"], "test_abi.py", "tests/acoustic/linux_backend_abi")):
            checkset = self.valid()
            command = checkset["commands"][0]
            command["argv"][4], command["argv"][6] = root, pattern
            command["coverage"] = coverage
            with self.subTest(coverage=coverage), self.assertRaises(ValueError):
                guest_checks.validate_checkset(checkset)
        for omissions in ([{"paths": ["tests/api"], "reason": "SYNTHETIC"}],
                          [{"paths": ["tests/api", "tests/nereid"], "reason": "   "}],
                          [{"paths": [], "reason": "SYNTHETIC"}],
                          ["tests/api and tests/nereid"]):
            checkset = self.valid()
            checkset["omissions"] = omissions
            with self.subTest(omissions=omissions), self.assertRaises(ValueError):
                guest_checks.validate_checkset(checkset)

    def test_valid_frozen_checkset_has_explicit_omissions(self):
        self.assertEqual(guest_checks.validate_checkset(self.valid()), self.valid())

    def test_pending_proposal_unknown_command_installs_and_devices_refuse(self):
        for argv in (["uv", "sync"], ["sudo", "apt-get", "install"], ["/usr/bin/python3", "apps/acoustic/live_capture_cli.py"], ["/usr/bin/make", "verify-cad"], ["bash", "-c", "true"]):
            checkset = self.valid()
            checkset["commands"][0]["argv"] = argv
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                guest_checks.validate_checkset(checkset)
        checkset = self.valid()
        checkset["commands"][0]["pending_root_decision"] = "not approved"
        with self.assertRaises(ValueError):
            guest_checks.validate_checkset(checkset)

    def test_unbounded_timeout_duplicate_ids_and_injected_environment_refuse(self):
        for update in ({"timeout_seconds": 0}, {"timeout_seconds": 901}, {"timeout_seconds": True}, {"environment": {"HTTPS_PROXY": "SYNTHETIC-invalid"}}):
            checkset = self.valid()
            checkset["commands"][0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                guest_checks.validate_checkset(checkset)
        checkset = self.valid()
        checkset["commands"].append(copy.deepcopy(checkset["commands"][0]))
        with self.assertRaises(ValueError):
            guest_checks.validate_checkset(checkset)

    def test_environment_does_not_inherit_credentials_or_proxy(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "synthetic-never-forward", "SSH_AUTH_SOCK": "/synthetic-agent"}):
            env = guest_checks.command_environment(Path("/owned/source"), Path("/owned/results"))
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertIn("/owned/source/libs/proto-py/src", env["PYTHONPATH"])
        self.assertIn("/owned/source/firmware/update/src", env["PYTHONPATH"])

    def test_machine_result_rejects_zero_skip_expected_failure_and_duplicate_record(self):
        good = {"accepted": True, "tests_run": 1, "required_minimum": 1, "selected_ids": ["synthetic.test"], "failures": 0, "errors": 0, "skipped": 0, "expected_failures": 0, "unexpected_successes": 0}
        line = lambda value: "POSEIDON_SUITE_RESULT=" + json.dumps(value)
        self.assertEqual(guest_checks.suite_record(line(good)), good)
        for update in ({"tests_run": 0}, {"skipped": 1}, {"expected_failures": 1}, {"errors": 1}, {"selected_ids": []}, {"accepted": False}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                guest_checks.suite_record(line(good | update))
        with self.assertRaises(ValueError):
            guest_checks.suite_record(line(good) + "\n" + line(good))


class ExplicitSuiteTests(unittest.TestCase):
    def run_fixture(self, body, *arguments):
        with tempfile.TemporaryDirectory(prefix="poseidon-synthetic-python-selector-") as temporary:
            root = Path(temporary)
            (root / "test_synthetic.py").write_text(body)
            return subprocess.run([sys.executable, str(ROOT / "scripts/assurance/linux_python_env/suite.py"), "--root", str(root), "--pattern", "test_synthetic.py", *arguments], env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=10)

    def test_exact_class_selection_records_not_hides_deselection(self):
        body = "import unittest\nclass Included(unittest.TestCase):\n def test_ok(self): pass\nclass Excluded(unittest.TestCase):\n def test_not_run(self): self.fail('excluded by explicit scope')\n"
        result = self.run_fixture(body, "--class-name", "Included")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = guest_checks.suite_record(result.stdout)
        self.assertEqual(len(record["deselected_ids"]), 1)
        self.assertEqual(record["tests_run"], 1)

    def test_skip_missing_class_zero_and_failures_are_not_success(self):
        for body, args in (("import unittest\nclass Case(unittest.TestCase):\n @unittest.skip('SYNTHETIC skip')\n def test_no(self): pass\n", []), ("# no tests\n", []), ("import unittest\nclass Case(unittest.TestCase):\n def test_no(self): self.fail()\n", []), ("import unittest\nclass Case(unittest.TestCase):\n def test_ok(self): pass\n", ["--class-name", "Absent"])):
            with self.subTest(body=body, args=args):
                self.assertNotEqual(self.run_fixture(body, *args).returncode, 0)


if __name__ == "__main__":
    unittest.main()
