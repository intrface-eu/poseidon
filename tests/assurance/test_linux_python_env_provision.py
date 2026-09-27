"""Synthetic Stage1 APT preparation tests.

Nothing here reaches APT, a package archive, a VM or the network: only plan
validation, option/argument construction and index verification run, plus the
host-side refusals that keep provisioning inside a new marked Linux guest.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.assurance.linux_capture_env import guest_prepare as shared
from scripts.assurance.linux_python_env import provision

INDEX_NAMES = ("snapshot.debian.org_archive_debian_20260901T000000Z_dists_trixie_main_binary-arm64_Packages",
               "snapshot.debian.org_archive_debian_20260901T000000Z_dists_trixie-updates_main_binary-arm64_Packages",
               "snapshot.debian.org_archive_debian-security_20260901T000000Z_dists_trixie-security_main_binary-arm64_Packages")


def plan(**changes) -> dict:
    value = {"schema_version": "poseidon.linux-python-packages.v1", "snapshot": shared.SNAPSHOT,
             "roots": {"make": "4.4.1-2", "g++": "4:14.2.0-1", "python3-dev": "3.13.5-1"},
             "indexes": {name: format(index, "064x") for index, name in enumerate(INDEX_NAMES, start=1)}}
    value.update(changes)
    return value


class NoNetworkOrSubprocessMixin(unittest.TestCase):
    def setUp(self):
        for module, name in ((subprocess, "run"), (subprocess, "Popen")):
            patcher = patch.object(module, name, side_effect=AssertionError("synthetic test must not run a process"))
            patcher.start()
            self.addCleanup(patcher.stop)


class PackagePlanTests(NoNetworkOrSubprocessMixin):
    def test_exact_snapshot_pins_are_required(self):
        self.assertEqual(provision.validate_plan(plan()), plan())
        for change in ({"snapshot": "20260101T000000Z"}, {"schema_version": "poseidon.linux-python-packages.v2"},
                       {"roots": {}}, {"roots": {"make": "4.4.1-2", "python3-dev": "latest "}},
                       {"roots": {"Make": "4.4.1-2"}}, {"roots": {"make": ""}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                provision.validate_plan(plan(**change))
        broken = plan()
        del broken["indexes"]
        with self.assertRaises(ValueError):
            provision.validate_plan(broken)

    def test_kernel_module_and_container_roots_refuse(self):
        for name in ("linux-image-arm64", "linux-headers-6.12", "linux-modules-extra", "dkms", "docker.io", "podman"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                provision.validate_plan(plan(roots={name: "1.0"}))

    def test_three_authenticated_arm64_index_digests_are_required(self):
        for indexes in ({}, {INDEX_NAMES[0]: "a" * 64},
                        {name: "a" * 64 for name in INDEX_NAMES} | {"extra": "b" * 64},
                        {INDEX_NAMES[0]: "a" * 63, INDEX_NAMES[1]: "b" * 64, INDEX_NAMES[2]: "c" * 64},
                        {"snapshot.debian.org_archive_debian_20260901T000000Z_dists_trixie_main_binary-amd64_Packages": "a" * 64,
                         INDEX_NAMES[1]: "b" * 64, INDEX_NAMES[2]: "c" * 64},
                        {"snapshot.debian.org_archive_debian_20250101T000000Z_dists_trixie_main_binary-arm64_Packages": "a" * 64,
                         INDEX_NAMES[1]: "b" * 64, INDEX_NAMES[2]: "c" * 64}):
            with self.subTest(indexes=sorted(indexes)), self.assertRaises(ValueError):
                provision.validate_plan(plan(indexes=indexes))


class AptBehaviourTests(NoNetworkOrSubprocessMixin):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="poseidon-synthetic-apt-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name).resolve()

    def options(self) -> dict[str, str]:
        values = provision.apt_options(self.work)
        self.assertEqual(values[::2], ["-o"] * (len(values) // 2))
        return dict(value.split("=", 1) for value in values[1::2])

    def test_retries_are_disabled_and_never_duplicated(self):
        options = self.options()
        self.assertEqual(options["Acquire::Retries"], "0")
        self.assertEqual(provision.apt_options(self.work).count("Acquire::Retries=0"), 1)
        with patch.object(shared, "apt_options", return_value=["-o", "Acquire::Retries=2", "-o", "Acquire::Retries=5"]), self.assertRaises(ValueError):
            provision.apt_options(self.work)
        with patch.object(shared, "apt_options", return_value=["-o", "Dir::Etc::sourceparts=-"]), self.assertRaises(ValueError):
            provision.apt_options(self.work)

    def test_metadata_stays_authenticated_and_the_environment_stays_clean(self):
        options = self.options()
        for key, expected in (("Acquire::AllowInsecureRepositories", "false"),
                              ("Acquire::AllowDowngradeToInsecureRepositories", "false"),
                              ("APT::Get::AllowUnauthenticated", "false"),
                              ("APT::Get::Allow-Downgrades", "false"),
                              ("APT::Get::Allow-Change-Held-Packages", "false"),
                              ("APT::Install-Recommends", "false"),
                              ("APT::Install-Suggests", "false"),
                              ("Acquire::Languages", "none"),
                              ("Dir::Etc::sourceparts", "-")):
            self.assertEqual(options[key], expected, key)
        for key in ("Dir::Etc::sourcelist", "Dir::Etc::main", "Dir::State::lists", "Dir::Cache::archives"):
            self.assertTrue(options[key].startswith(str(self.work)), key)
        self.assertEqual(shared.ENV["PATH"], "/usr/sbin:/usr/bin:/sbin:/bin")
        self.assertFalse({"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "SSH_AUTH_SOCK", "HOME"} & set(shared.ENV))
        self.assertIn(f"snapshot.debian.org/archive/debian/{shared.SNAPSHOT}/ trixie main", shared.snapshot_sources())
        self.assertIn(f"signed-by={shared.KEYRING}", shared.snapshot_sources())

    def test_install_is_pinned_bounded_and_never_upgrades(self):
        arguments = provision.install_arguments(plan()["roots"])
        self.assertEqual(arguments[:5], ["--yes", "--no-remove", "--no-upgrade", "--no-install-recommends", "install"])
        self.assertEqual(arguments[5:], ["g++=4:14.2.0-1", "make=4.4.1-2", "python3-dev=3.13.5-1"])
        self.assertFalse({"--force-yes", "--allow-downgrades", "-f", "--fix-broken", "upgrade", "dist-upgrade"} & set(arguments))
        with self.assertRaises(ValueError):
            provision.install_arguments({})

    def test_index_hashes_and_authenticated_release_files_are_verified(self):
        lists = self.work / "apt/lists"
        lists.mkdir(parents=True)
        expected = {}
        for index, name in enumerate(INDEX_NAMES, start=1):
            raw = f"SYNTHETIC Packages index {index}\n".encode()
            (lists / name).write_bytes(raw)
            expected[name] = hashlib.sha256(raw).hexdigest()
        for suite in ("trixie", "trixie-updates", "trixie-security"):
            (lists / f"snapshot.debian.org_archive_debian_{shared.SNAPSHOT}_dists_{suite}_InRelease").write_text("SYNTHETIC signed release\n")
        self.assertEqual(provision.verified_indexes(self.work, expected), expected)
        with self.assertRaisesRegex(ValueError, "differ"):
            provision.verified_indexes(self.work, expected | {INDEX_NAMES[0]: "a" * 64})
        (lists / (INDEX_NAMES[0] + "_extra_Packages")).write_bytes(b"SYNTHETIC unplanned index\n")
        with self.assertRaises(ValueError):
            provision.verified_indexes(self.work, expected)
        (lists / (INDEX_NAMES[0] + "_extra_Packages")).unlink()
        (lists / f"snapshot.debian.org_archive_debian_{shared.SNAPSHOT}_dists_trixie-security_InRelease").unlink()
        with self.assertRaisesRegex(ValueError, "InRelease"):
            provision.verified_indexes(self.work, expected)


class GuestBoundaryTests(NoNetworkOrSubprocessMixin):
    def test_preparation_refuses_off_guest_before_touching_any_path(self):
        with tempfile.TemporaryDirectory(prefix="poseidon-synthetic-apt-guard-") as temporary:
            work = Path(temporary)
            manifest = work / "packages.json"
            manifest.write_text("{}")
            output = work / "never-created"
            args = argparse.Namespace(run_id="lp3-synthetic", plan=manifest, plan_sha256="a" * 64, output=output)
            with self.assertRaises(ValueError) as refusal:
                provision.prepare(args)
            # Off the guest the platform check refuses; inside a real Debian aarch64 guest the
            # shared guard refuses on the marker or privilege check instead. Both are refusals
            # raised before any path is created, which is what this test protects.
            self.assertRegex(str(refusal.exception), r"Linux aarch64 guest|Debian VERSION_ID|root preparation required|must run unprivileged|guest marker")
            self.assertFalse(output.exists())

    def test_marker_and_root_identity_are_required_for_a_new_guest(self):
        temporary = tempfile.TemporaryDirectory(prefix="poseidon-synthetic-marker-")
        self.addCleanup(temporary.cleanup)
        temporary = temporary.name
        with patch.object(shared.sys, "platform", "linux"), patch.object(shared.platform, "machine", return_value="aarch64"):
            with self.assertRaises(ValueError):
                shared.guard_guest("not a valid run id", root=True)
            with patch.object(shared.os, "getuid", return_value=1000), patch.object(shared.os, "geteuid", return_value=1000), \
                 self.assertRaisesRegex(ValueError, "root preparation required"):
                shared.guard_guest("lp3-synthetic", root=True)
            with patch.object(shared.os, "getuid", return_value=0), patch.object(shared.os, "geteuid", return_value=0), \
                 patch.object(shared.platform, "freedesktop_os_release", return_value={"ID": "ubuntu", "VERSION_ID": "24.04"}), \
                 self.assertRaisesRegex(ValueError, "Debian"):
                shared.guard_guest("lp3-synthetic", root=True)
            with patch.object(shared.os, "getuid", return_value=0), patch.object(shared.os, "geteuid", return_value=0), \
                 patch.object(shared.platform, "freedesktop_os_release", return_value={"ID": "debian", "VERSION_ID": "13"}), \
                 patch.object(shared, "MARKER", Path(temporary) / "absent-guest-marker"), \
                 self.assertRaises(FileNotFoundError):
                shared.guard_guest("lp3-synthetic", root=True)
            marker = Path(temporary) / "guest-marker"
            marker.write_text("lp3-other-run\n")
            with patch.object(shared.os, "getuid", return_value=0), patch.object(shared.os, "geteuid", return_value=0), \
                 patch.object(shared.platform, "freedesktop_os_release", return_value={"ID": "debian", "VERSION_ID": "13"}), \
                 patch.object(shared, "MARKER", marker), self.assertRaises(ValueError) as refusal:
                shared.guard_guest("lp3-synthetic", root=True)
            self.assertIn("marker", str(refusal.exception))

    def test_new_output_directory_must_be_absolute_and_unused(self):
        with tempfile.TemporaryDirectory(prefix="poseidon-synthetic-apt-out-") as temporary:
            existing = Path(temporary) / "already-there"
            existing.mkdir()
            for path in (Path("relative/path"), existing, Path(temporary) / ".." / "escape"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    shared.new_directory(path, root=False)


if __name__ == "__main__":
    unittest.main()
