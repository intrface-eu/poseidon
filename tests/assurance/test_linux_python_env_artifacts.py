"""Synthetic Stage2 pin, artifact, wheel-provenance and offline-check tests.

Every byte here is built in an owned temporary directory. No download, no
extraction of a real distribution, no uv, no VM and no network call happens:
the one download test drives an in-memory response object.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.assurance.linux_python_env import artifacts, locked_checks, locked_env

# Published digests frozen in the parent tool plan; a silent pin edit must fail.
OFFICIAL_PINS = {
    "uv0.12.3_linux_aarch64": "bb66cb52e7b1823aed1183630d8d8e5c958840d584a4c55ec10a4cfc168dcca2",
    "cpython3.11.15_linux_aarch64_20260807": "2290f3a9115ee2cd0928a7fc1f3f918142705fba3efa04dc64ffe6e5bae3245f",
    "cpython3.12.13_linux_aarch64_20260807": "11e713ae1f969385907a76533cc554f6b2e3f1a84896009f91c3fc871034a170",
}


def urlsafe(raw: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")


def build_wheel(path: Path, payload: dict[str, bytes], *, dist_info: str, record_rows=None, extra_members=None) -> Path:
    rows = []
    with zipfile.ZipFile(path, "w") as wheel:
        for name, raw in payload.items():
            wheel.writestr(name, raw)
            rows.append((name, "sha256=" + urlsafe(raw), str(len(raw))))
        for name, raw in (extra_members or {}).items():
            wheel.writestr(name, raw)
        rows = record_rows if record_rows is not None else rows
        record = f"{dist_info}/RECORD"
        text = "".join(f"{name},{value},{size}\n" for name, value, size in [*rows, (record, "", "")])
        wheel.writestr(record, text)
    return path


class NoNetworkMixin(unittest.TestCase):
    """Every artifact test refuses to open a socket or spawn a process."""

    def setUp(self):
        for module, name in ((urllib.request, "urlopen"), (subprocess, "run"), (subprocess, "Popen")):
            patcher = patch.object(module, name, side_effect=AssertionError("synthetic test must not use the network"))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="poseidon-synthetic-stage2-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()


class PinAndUrlTests(NoNetworkMixin):
    def test_official_pins_match_the_frozen_tool_plan(self):
        self.assertEqual(artifacts.UV_PIN["sha256"], OFFICIAL_PINS["uv0.12.3_linux_aarch64"])
        self.assertEqual(artifacts.UV_VERSION, "0.12.3")
        self.assertEqual(artifacts.PYTHON_PINS["3.11.15"]["sha256"], OFFICIAL_PINS["cpython3.11.15_linux_aarch64_20260807"])
        self.assertEqual(artifacts.PYTHON_PINS["3.12.13"]["sha256"], OFFICIAL_PINS["cpython3.12.13_linux_aarch64_20260807"])
        for pin in (artifacts.UV_PIN, *artifacts.PYTHON_PINS.values()):
            self.assertTrue(pin["url"].startswith("https://github.com/astral-sh/"))
            self.assertIn("aarch64", pin["url"])

    def test_only_explicit_public_https_artifact_hosts_are_accepted(self):
        for url in (artifacts.UV_PIN["url"], "https://files.pythonhosted.org/packages/x/y-1.0-py3-none-any.whl"):
            self.assertEqual(artifacts.public_url(url), url)
        for url in ("http://github.com/a.tar.gz", "https://example.invalid/a.tar.gz",
                    "https://user:pw@github.com/a.tar.gz", "https://github.com:8443/a.tar.gz",
                    "file:///etc/passwd", "https://github.com/a.tar.gz#fragment",
                    "https://pypi.org/simple/x-1.0-py3-none-any.whl"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                artifacts.public_url(url)

    def test_redirects_to_unlisted_hosts_are_refused(self):
        handler = artifacts.PublicRedirect()
        with self.assertRaises(ValueError):
            handler.redirect_request(urllib.request.Request(artifacts.UV_PIN["url"]), None, 302, "Found", {}, "https://example.invalid/uv.tar.gz")

    def test_download_refuses_unpinned_targets_before_any_request(self):
        target = self.base / "artifact.bin"
        with patch.object(artifacts.urllib.request, "build_opener", side_effect=AssertionError("no request may be built")):
            for pin, name in ((({"url": "https://example.invalid/x", "sha256": "a" * 64}), "host"),
                              (({"url": artifacts.UV_PIN["url"], "sha256": "not-a-digest"}), "digest")):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    artifacts.download(pin, target)
            existing = self.base / "already"
            existing.write_bytes(b"SYNTHETIC retained artifact")
            with self.assertRaises(ValueError):
                artifacts.download({"url": artifacts.UV_PIN["url"], "sha256": "a" * 64}, existing)
            self.assertEqual(existing.read_bytes(), b"SYNTHETIC retained artifact")
            for deadline in (0, 601):
                with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                    artifacts.download({"url": artifacts.UV_PIN["url"], "sha256": "a" * 64}, target, deadline=deadline)
        self.assertFalse(target.exists())

    def test_download_verifies_hash_and_size_without_retry(self):
        raw = b"SYNTHETIC pinned artifact payload"
        pin = {"url": artifacts.UV_PIN["url"], "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
        opened = []

        class Response(io.BytesIO):
            status = 200

            def geturl(self):
                return pin["url"]

        def opener(*handlers):
            class Opener:
                def open(self, request, timeout=None):
                    opened.append(request.full_url)
                    return Response(raw)
            return Opener()

        with patch.object(artifacts.urllib.request, "build_opener", opener):
            record = artifacts.download(pin, self.base / "good.bin")
            self.assertEqual(record["sha256"], pin["sha256"])
            self.assertEqual(record["size"], len(raw))
            self.assertEqual((self.base / "good.bin").read_bytes(), raw)
            self.assertEqual(opened, [pin["url"]])
            with self.assertRaises(ValueError):
                artifacts.download(pin | {"sha256": "b" * 64}, self.base / "wrong-hash.bin")
            with self.assertRaises(ValueError):
                artifacts.download(pin | {"size": 4}, self.base / "oversized.bin")
        self.assertEqual(len(opened), 3)


class ArchiveTests(NoNetworkMixin):
    def archive(self, path: Path, members) -> str:
        with tarfile.open(path, "w:gz") as bundle:
            for member, raw in members:
                bundle.addfile(member, io.BytesIO(raw) if member.isfile() else None)
        return artifacts.sha256(path)

    def member(self, name, raw=b"SYNTHETIC tool byte", **fields):
        info = tarfile.TarInfo(name)
        info.size = len(raw)
        for key, value in fields.items():
            setattr(info, key, value)
        if not info.isfile():
            info.size = 0
            raw = b""
        return info, raw

    def test_pinned_distribution_extracts_only_inside_its_prefix(self):
        path = self.base / "tool.tar.gz"
        digest = self.archive(path, [self.member("uv-dist/uv"), self.member("uv-dist/lib/x.so")])
        record = artifacts.extract(path, digest, self.base / "extracted", prefix="uv-dist")
        self.assertEqual(record["members"], 2)
        self.assertEqual(Path(record["root"]), self.base / "extracted/uv-dist")
        self.assertTrue((self.base / "extracted/uv-dist/uv").is_file())

    def test_extraction_refuses_before_hash_verification(self):
        path = self.base / "tool.tar.gz"
        self.archive(path, [self.member("uv-dist/uv")])
        with self.assertRaisesRegex(ValueError, "hash verification"):
            artifacts.extract(path, "a" * 64, self.base / "never", prefix="uv-dist")
        self.assertFalse((self.base / "never").exists())

    def test_unexpected_prefix_links_devices_and_setuid_members_refuse(self):
        cases = {
            "prefix": [self.member("other/uv")],
            "escape": [self.member("uv-dist/uv"), self.member("uv-dist/link", type=tarfile.SYMTYPE, linkname="../../etc/passwd")],
            "absolute-link": [self.member("uv-dist/link", type=tarfile.SYMTYPE, linkname="/etc/passwd")],
            "device": [self.member("uv-dist/dev", type=tarfile.CHRTYPE)],
            "setuid": [self.member("uv-dist/uv", mode=0o4755)],
            "duplicate": [self.member("uv-dist/uv"), self.member("uv-dist/uv")],
            "through-link": [self.member("uv-dist/lib", type=tarfile.SYMTYPE, linkname="sub"), self.member("uv-dist/lib/x.so")],
            "traversal": [self.member("uv-dist/../escape")],
        }
        for name, members in cases.items():
            path = self.base / (name + ".tar.gz")
            digest = self.archive(path, members)
            with self.subTest(name=name), self.assertRaises(ValueError):
                artifacts.extract(path, digest, self.base / (name + "-out"), prefix="uv-dist")


class LockWheelProvenanceTests(NoNetworkMixin):
    def setUp(self):
        super().setUp()
        self.locks = {lane: tomllib.loads((ROOT / project / "uv.lock").read_text())
                      for lane, (project, _) in locked_env.LANES.items()}

    def registry_packages(self, lane: str):
        return [p for p in self.locks[lane]["package"] if "registry" in p.get("source", {}) and p.get("wheels")]

    def test_real_lock_wheel_tags_select_exactly_one_artifact(self):
        checked = 0
        for lane in self.locks:
            for package in self.registry_packages(lane):
                for wheel in package["wheels"]:
                    name = PurePosixPath(wheel["url"]).name
                    if "aarch64" not in name and not name.endswith("-none-any.whl"):
                        continue
                    installed = {"name": package["name"], "version": package["version"], "tags": sorted(artifacts.filename_tags(name))}
                    selected = artifacts.lock_wheel(self.locks[lane], installed)
                    self.assertEqual(selected["filename"], name)
                    self.assertTrue(selected["hash"].startswith("sha256:"))
                    self.assertEqual(artifacts.public_url(selected["url"]), wheel["url"])
                    checked += 1
                    break
        self.assertGreater(checked, 10, "the real locks must supply Linux aarch64 and pure-python wheels")

    def test_normalized_distribution_names_and_versions_must_agree(self):
        lock = self.locks["api"]
        package = next(p for p in self.registry_packages("api") if "_" in PurePosixPath(p["wheels"][0]["url"]).name.split("-")[0] or "-" in p["name"])
        name = PurePosixPath(package["wheels"][0]["url"]).name
        tags = sorted(artifacts.filename_tags(name))
        installed = {"name": package["name"].replace("-", "_").upper(), "version": package["version"], "tags": tags}
        self.assertEqual(artifacts.lock_wheel(lock, installed)["filename"], name)
        with self.assertRaises(ValueError):
            artifacts.lock_wheel(lock, installed | {"version": "0.0.0-SYNTHETIC"})
        with self.assertRaises(ValueError):
            artifacts.lock_wheel(lock, installed | {"name": "synthetic-absent-distribution"})

    def test_ambiguous_missing_source_and_unpinned_entries_refuse(self):
        lock = copy.deepcopy(self.locks["api"])
        package = next(p for p in lock["package"] if "registry" in p.get("source", {}) and p.get("wheels"))
        name = PurePosixPath(package["wheels"][0]["url"]).name
        installed = {"name": package["name"], "version": package["version"], "tags": sorted(artifacts.filename_tags(name))}
        duplicate = copy.deepcopy(package["wheels"][0])
        duplicate["url"] = duplicate["url"].replace(name, "renamed_" + name.split("-", 1)[1])
        ambiguous = copy.deepcopy(lock)
        target = next(p for p in ambiguous["package"] if p["name"] == package["name"])
        target["wheels"] = [package["wheels"][0], duplicate]
        with self.assertRaisesRegex(ValueError, "one exact locked wheel"):
            artifacts.lock_wheel(ambiguous, installed)
        source_only = copy.deepcopy(lock)
        target = next(p for p in source_only["package"] if p["name"] == package["name"])
        target["wheels"] = []
        with self.assertRaises(ValueError):
            artifacts.lock_wheel(source_only, installed)
        virtual = copy.deepcopy(lock)
        target = next(p for p in virtual["package"] if p["name"] == package["name"])
        target["source"] = {"virtual": "."}
        with self.assertRaisesRegex(ValueError, "registry"):
            artifacts.lock_wheel(virtual, installed)
        unpinned = copy.deepcopy(lock)
        target = next(p for p in unpinned["package"] if p["name"] == package["name"])
        target["wheels"] = [copy.deepcopy(package["wheels"][0])]
        target["wheels"][0]["hash"] = "md5:" + "a" * 32
        with self.assertRaisesRegex(ValueError, "SHA256"):
            artifacts.lock_wheel(unpinned, installed)
        duplicated_package = copy.deepcopy(lock)
        duplicated_package["package"].append(copy.deepcopy(package))
        with self.assertRaises(ValueError):
            artifacts.lock_wheel(duplicated_package, installed)

    def test_source_distributions_are_never_accepted_as_wheels(self):
        for name in ("cryptography-46.0.3.tar.gz", "pytest-9.1.1.zip", "package-1.0"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "source distribution"):
                artifacts.filename_tags(name)
        self.assertEqual(artifacts.filename_tags("anyio-4.15.1-py3-none-any.whl"), {"py3-none-any"})
        self.assertEqual(artifacts.filename_tags("x-1.0-cp311-abi3-manylinux_2_28_aarch64.manylinux_2_34_aarch64.whl"),
                         {"cp311-abi3-manylinux_2_28_aarch64", "cp311-abi3-manylinux_2_34_aarch64"})


class WheelPayloadTests(NoNetworkMixin):
    def setUp(self):
        super().setUp()
        self.site = (self.base / "site-packages").resolve()
        self.site.mkdir()
        self.payload = {"synthetic_pkg/__init__.py": b"SYNTHETIC = True\n",
                        "synthetic_pkg-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n",
                        "synthetic_pkg-1.0.dist-info/METADATA": b"Name: synthetic-pkg\nVersion: 1.0\n"}
        for name, raw in self.payload.items():
            target = self.site / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        self.installed = {"name": "synthetic-pkg", "version": "1.0", "tags": ["py3-none-any"], "site_packages": str(self.site)}

    def wheel(self, name="good.whl", **changes) -> Path:
        return build_wheel(self.base / name, self.payload, dist_info="synthetic_pkg-1.0.dist-info", **changes)

    def test_installed_bytes_match_every_declared_record_entry(self):
        record = artifacts.wheel_payload(self.wheel(), self.installed)
        self.assertEqual(record["checked_payload_files"], len(self.payload))
        self.assertEqual(record["installer_generated_records"], ["synthetic_pkg-1.0.dist-info/RECORD"])
        self.assertTrue(record["payload_sha256_verified"])

    def test_record_hash_size_and_membership_mismatches_refuse(self):
        rows = [(name, "sha256=" + urlsafe(raw), str(len(raw))) for name, raw in self.payload.items()]
        cases = {
            "hash": [(rows[0][0], "sha256=" + urlsafe(b"other"), rows[0][2]), *rows[1:]],
            "size": [(rows[0][0], rows[0][1], "999999"), *rows[1:]],
            "algorithm": [(rows[0][0], "md5=" + urlsafe(b"x"), rows[0][2]), *rows[1:]],
            "missing-entry": rows[1:],
            "duplicate": [rows[0], *rows],
            "absent-member": [*rows, ("synthetic_pkg/absent.py", "sha256=" + urlsafe(b""), "0")],
        }
        for name, record_rows in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                artifacts.wheel_payload(self.wheel(name + ".whl", record_rows=record_rows), self.installed)

    def test_undeclared_payload_and_missing_record_refuse(self):
        extra = self.wheel("extra.whl", extra_members={"synthetic_pkg/hidden.py": b"SYNTHETIC undeclared\n"})
        with self.assertRaisesRegex(ValueError, "undeclared"):
            artifacts.wheel_payload(extra, self.installed)
        without = self.base / "no-record.whl"
        with zipfile.ZipFile(without, "w") as wheel:
            for name, raw in self.payload.items():
                wheel.writestr(name, raw)
        with self.assertRaisesRegex(ValueError, "RECORD"):
            artifacts.wheel_payload(without, self.installed)

    def test_installed_file_drift_is_detected(self):
        wheel = self.wheel("drift.whl")
        (self.site / "synthetic_pkg/__init__.py").write_bytes(b"SYNTHETIC = False\n")
        with self.assertRaisesRegex(ValueError, "differs from retained wheel"):
            artifacts.wheel_payload(wheel, self.installed)
        (self.site / "synthetic_pkg/__init__.py").unlink()
        with self.assertRaises(ValueError):
            artifacts.wheel_payload(wheel, self.installed)

    def test_data_layouts_are_remapped_only_for_reviewed_schemes(self):
        payload = dict(self.payload)
        payload["synthetic_pkg-1.0.data/purelib/synthetic_extra.py"] = b"SYNTHETIC extra module\n"
        (self.site / "synthetic_extra.py").write_bytes(payload["synthetic_pkg-1.0.data/purelib/synthetic_extra.py"])
        good = build_wheel(self.base / "data-good.whl", payload, dist_info="synthetic_pkg-1.0.dist-info")
        self.assertTrue(artifacts.wheel_payload(good, self.installed)["payload_sha256_verified"])
        scripts = dict(self.payload)
        scripts["synthetic_pkg-1.0.data/scripts/synthetic-entry"] = b"#!/usr/bin/env python3\n"
        bad = build_wheel(self.base / "data-scripts.whl", scripts, dist_info="synthetic_pkg-1.0.dist-info")
        with self.assertRaisesRegex(ValueError, "explicit review"):
            artifacts.wheel_payload(bad, self.installed)

    def test_relative_installed_root_is_refused(self):
        with self.assertRaises(ValueError):
            artifacts.wheel_payload(self.wheel("relative.whl"), self.installed | {"site_packages": "site-packages"})


class LockedToolPlanTests(NoNetworkMixin):
    def plan(self) -> dict:
        return {"schema_version": "poseidon.linux-python-locked-tools.v1", "uv": copy.deepcopy(artifacts.UV_PIN),
                "python": copy.deepcopy(artifacts.PYTHON_PINS),
                "locks": {lane: {"project": project, "python": version, "lock_sha256": "a" * 64, "pyproject_sha256": "b" * 64}
                          for lane, (project, version) in locked_env.LANES.items()}}

    def test_plan_must_carry_the_exact_official_pins_and_all_lanes(self):
        self.assertEqual(locked_env.validate_plan(self.plan()), self.plan())
        broken = self.plan()
        broken["uv"]["sha256"] = "c" * 64
        with self.assertRaises(ValueError):
            locked_env.validate_plan(broken)
        for change in ({"schema_version": "poseidon.linux-python-locked-tools.v2"},
                       {"python": {"3.11.15": artifacts.PYTHON_PINS["3.11.15"]}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                locked_env.validate_plan(self.plan() | change)
        missing = self.plan()
        del missing["locks"]["firmware"]
        with self.assertRaises(ValueError):
            locked_env.validate_plan(missing)
        wrong = self.plan()
        wrong["locks"]["api"]["python"] = "3.12.13"
        with self.assertRaises(ValueError):
            locked_env.validate_plan(wrong)
        unpinned = self.plan()
        unpinned["locks"]["nereid"]["lock_sha256"] = "not-a-digest"
        with self.assertRaises(ValueError):
            locked_env.validate_plan(unpinned)

    def test_lane_environment_is_offline_capable_and_never_builds_from_source(self):
        environment = locked_env.environment(self.base / "workspace")
        self.assertEqual(environment["UV_PYTHON_DOWNLOADS"], "never")
        self.assertEqual(environment["UV_NO_BUILD"], "1")
        self.assertEqual(environment["UV_HTTP_RETRIES"], "0")
        self.assertEqual(environment["PATH"], "/usr/bin:/bin")
        self.assertNotIn("SSH_AUTH_SOCK", environment)
        self.assertTrue(environment["HOME"].startswith(str(self.base)))

    def test_lane_lock_identity_must_match_the_frozen_source(self):
        plan = self.plan()
        root = self.base / "source"
        for lane, item in plan["locks"].items():
            path = root / item["project"]
            path.mkdir(parents=True)
            (path / "uv.lock").write_text(f"# SYNTHETIC {lane} lock\n")
            (path / "pyproject.toml").write_text(f"# SYNTHETIC {lane} project\n")
            item["lock_sha256"] = hashlib.sha256((path / "uv.lock").read_bytes()).hexdigest()
            item["pyproject_sha256"] = hashlib.sha256((path / "pyproject.toml").read_bytes()).hexdigest()
        locked_env.check_lock_files(root, plan)
        (root / plan["locks"]["api"]["project"] / "uv.lock").write_text("# SYNTHETIC changed lock\n")
        with self.assertRaisesRegex(ValueError, "changed from frozen source"):
            locked_env.check_lock_files(root, plan)

    def test_stage2_provisioning_refuses_off_guest(self):
        manifest = self.base / "tools.json"
        manifest.write_text("{}")
        args = argparse.Namespace(run_id="lp3-synthetic", source=self.base, plan=manifest, plan_sha256="a" * 64,
                                  workspace=self.base / "work", records=self.base / "records")
        with self.assertRaises(ValueError) as refusal:
            locked_env.prepare(args)
        # Off the guest the platform check refuses; inside a real Debian aarch64 guest the
        # shared guard refuses on the marker or privilege check instead. Both are refusals
        # raised before any path is created, which is what this test protects.
        self.assertRegex(str(refusal.exception), r"Linux aarch64 guest|Debian VERSION_ID|root preparation required|must run unprivileged|guest marker")
        self.assertFalse((self.base / "work").exists())
        self.assertFalse((self.base / "records").exists())


class Stage2CheckSetTests(NoNetworkMixin):
    def valid(self) -> dict:
        return {"schema_version": "poseidon.linux-python-locked-checkset.v1", "source_manifest_sha256": "a" * 64,
                "tool_plan_sha256": "b" * 64,
                "omissions": [{"paths": ["tests/acoustic/linux_backend_abi"], "reason": "separate accepted Task18 native gate"}],
                "commands": [{"id": "api-unittest", "lane": "api", "argv": ["{python}", "scripts/assurance/run_unittest.py", "-s", "tests/api", "-p", "test_routes.py"],
                              "timeout_seconds": 600, "environment": {}, "coverage": ["tests/api/test_routes.py"]}]}

    def test_frozen_stage2_schema_accepts_only_reviewed_forms(self):
        self.assertEqual(locked_checks.validate_checkset(self.valid()), self.valid())
        for argv in (["uv", "run", "pytest"], ["{python}", "-m", "pip", "install", "x"],
                     ["/usr/bin/python3", "scripts/assurance/run_unittest.py"], ["bash", "-c", "true"],
                     ["{python}", "scripts/assurance/run_unittest.py\x00"], ["{python}", "-m", "compileall"]):
            checkset = self.valid()
            checkset["commands"][0]["argv"] = argv
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                locked_checks.validate_checkset(checkset)
        for update in ({"lane": "unknown"}, {"timeout_seconds": 0}, {"timeout_seconds": 901},
                       {"environment": {"UV_OFFLINE": "0"}}, {"coverage": []}, {"coverage": ["../escape"]}):
            checkset = self.valid()
            checkset["commands"][0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                locked_checks.validate_checkset(checkset)
        duplicate = self.valid()
        duplicate["commands"].append(copy.deepcopy(duplicate["commands"][0]))
        with self.assertRaises(ValueError):
            locked_checks.validate_checkset(duplicate)
        for field in ("source_manifest_sha256", "tool_plan_sha256"):
            checkset = self.valid()
            checkset[field] = "not-a-digest"
            with self.subTest(field=field), self.assertRaises(ValueError):
                locked_checks.validate_checkset(checkset)
        stale = self.valid()
        stale["commands"][0]["evidence_label"] = "SYNTHETIC proposal field"
        with self.assertRaises(ValueError):
            locked_checks.validate_checkset(stale)

    def test_zero_skip_guard_summaries_are_required(self):
        unittest_argv = ["/env/bin/python", "scripts/assurance/run_unittest.py"]
        text = "Assurance PASS: tests_run=17, failures=0, errors=0, skipped=0, expected_failures=0, unexpected_successes=0, required_minimum=1."
        self.assertEqual(locked_checks.guard_summary(unittest_argv, text)["tests_run"], 17)
        for bad in ("Assurance PASS: tests_run=0, failures=0, errors=0, skipped=0, expected_failures=0, unexpected_successes=0, required_minimum=1.",
                    "Assurance PASS: tests_run=2, failures=0, errors=0, skipped=1, expected_failures=0, unexpected_successes=0, required_minimum=1.",
                    "Assurance FAILED: tests_run=17, failures=1", "", text + "\n" + text):
            with self.subTest(bad=bad[:40]), self.assertRaises(ValueError):
                locked_checks.guard_summary(unittest_argv, bad)
        pytest_argv = ["/env/bin/python", "scripts/assurance/run_pytest.py"]
        self.assertEqual(locked_checks.guard_summary(pytest_argv, "Assurance PASS: collected=9, call_reports=9, pytest_exit=0.")["collected"], 9)
        # Subtests add call reports beyond the collected count (run lp3-stage2-003 shape).
        with_subtests = locked_checks.guard_summary(pytest_argv, "Assurance PASS: collected=466, call_reports=662, pytest_exit=0.")
        self.assertEqual((with_subtests["collected"], with_subtests["tests_run"]), (466, 662))
        for bad in ("Assurance PASS: collected=9, call_reports=8, pytest_exit=0.",
                    "Assurance PASS: collected=466, call_reports=465, pytest_exit=0.",
                    "Assurance PASS: collected=0, call_reports=0, pytest_exit=0.",
                    "Assurance PASS: collected=9, call_reports=9, pytest_exit=0.\nAssurance PASS: collected=9, call_reports=9, pytest_exit=0.",
                    "Assurance FAILED: collected=466, call_reports=662, pytest_exit=1.",
                    "Assurance PASS: collected=9, call_reports=9, pytest_exit=1.", "no summary"):
            with self.subTest(bad=bad[:40]), self.assertRaises(ValueError):
                locked_checks.guard_summary(pytest_argv, bad)
        self.assertIsNone(locked_checks.guard_summary(["/usr/bin/make", "check-hardware-reference"], "done"))


class LaneIdentityTests(NoNetworkMixin):
    def setUp(self):
        super().setUp()
        self.source = self.base / "source"
        (self.source / "apps/aeolus-api").mkdir(parents=True)
        self.lock = self.source / "apps/aeolus-api/uv.lock"
        self.lock.write_text("# SYNTHETIC api lock\n")
        self.interpreter = self.base / "python3.11"
        self.interpreter.write_bytes(b"SYNTHETIC interpreter binary\n")
        self.site = (self.base / "envs/api/lib/site-packages").resolve()
        self.site.mkdir(parents=True)
        payload = {"synthetic_pkg/__init__.py": b"SYNTHETIC = True\n",
                   "synthetic_pkg-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n"}
        for name, raw in payload.items():
            target = self.site / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        self.wheel = build_wheel(self.base / "synthetic_pkg-1.0-py3-none-any.whl", payload, dist_info="synthetic_pkg-1.0.dist-info")
        installed = {"name": "synthetic-pkg", "version": "1.0", "tags": ["py3-none-any"], "site_packages": str(self.site)}
        self.environments = {
            "interpreters": {"3.11.15": {"binary_sha256": hashlib.sha256(self.interpreter.read_bytes()).hexdigest()}},
            "lanes": {"api": {"state": "ready-offline", "python": str(self.interpreter), "python_version": "3.11.15",
                              "lock_sha256": hashlib.sha256(self.lock.read_bytes()).hexdigest(),
                              "installed": {"distributions": [installed]},
                              "wheels": [{"name": "synthetic-pkg", "version": "1.0", "filename": self.wheel.name,
                                          "artifact": {"file": str(self.wheel), "sha256": hashlib.sha256(self.wheel.read_bytes()).hexdigest()}}]}},
        }

    def test_lane_identities_are_preserved_before_and_after_tests(self):
        locked_checks.verify_lane(self.source, self.environments, "api")

    def test_changed_lock_interpreter_or_wheel_identity_refuses(self):
        cases = {}
        omitted = copy.deepcopy(self.environments)
        omitted["lanes"]["api"]["state"] = "omitted-provisioning-failed"
        cases["omitted"] = omitted
        changed_lock = copy.deepcopy(self.environments)
        changed_lock["lanes"]["api"]["lock_sha256"] = "a" * 64
        cases["lock"] = changed_lock
        interpreter = copy.deepcopy(self.environments)
        interpreter["interpreters"]["3.11.15"]["binary_sha256"] = "b" * 64
        cases["interpreter"] = interpreter
        wheel = copy.deepcopy(self.environments)
        wheel["lanes"]["api"]["wheels"][0]["artifact"]["sha256"] = "c" * 64
        cases["wheel"] = wheel
        counts = copy.deepcopy(self.environments)
        counts["lanes"]["api"]["wheels"] = []
        cases["counts"] = counts
        version = copy.deepcopy(self.environments)
        version["lanes"]["api"]["python_version"] = "3.12.13"
        cases["python-version"] = version
        absent_interpreter = copy.deepcopy(self.environments)
        absent_interpreter["interpreters"] = {}
        cases["absent-interpreter"] = absent_interpreter
        absent_lane = copy.deepcopy(self.environments)
        absent_lane["lanes"] = {}
        cases["absent-lane"] = absent_lane
        renamed = copy.deepcopy(self.environments)
        renamed["lanes"]["api"]["wheels"][0]["name"] = "other-synthetic-pkg"
        cases["unmatched-wheel"] = renamed
        reversioned = copy.deepcopy(self.environments)
        reversioned["lanes"]["api"]["wheels"][0]["version"] = "2.0"
        cases["wheel-version"] = reversioned
        for name, environments in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                locked_checks.verify_lane(self.source, environments, "api")

    def test_stage2_checks_refuse_off_guest(self):
        args = argparse.Namespace(run_id="lp3-synthetic", source=self.source, source_manifest=self.lock,
                                  source_manifest_sha256="a" * 64, checkset=self.lock, checkset_sha256="a" * 64,
                                  environments=self.lock, environments_sha256="a" * 64,
                                  output=Path("/home/builder/python-checks-lp3-synthetic"))
        with self.assertRaises(ValueError) as refusal:
            locked_checks.run(args)
        # Off the guest the platform check refuses; inside a real Debian aarch64 guest the
        # shared guard refuses on the marker or privilege check instead. Both are refusals
        # raised before any path is created, which is what this test protects.
        self.assertRegex(str(refusal.exception), r"Linux aarch64 guest|Debian VERSION_ID|root preparation required|must run unprivileged|guest marker")
        self.assertEqual(os.getuid(), os.geteuid())


if __name__ == "__main__":
    unittest.main()
