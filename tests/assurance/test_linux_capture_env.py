"""Source-only safety tests; no VM, download, guest, device or Linux ABI claim."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import io
import json
import tarfile
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/assurance/linux_capture_env/runner.py"
spec = importlib.util.spec_from_file_location("linux_env_runner", SCRIPT)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
bootstrap_spec = importlib.util.spec_from_file_location("linux_env_bootstrap", SCRIPT.with_name("bootstrap.py"))
assert bootstrap_spec and bootstrap_spec.loader
bootstrap = importlib.util.module_from_spec(bootstrap_spec)
with patch.dict(sys.modules, {"runner": runner}):
    bootstrap_spec.loader.exec_module(bootstrap)
prepare_spec = importlib.util.spec_from_file_location("linux_guest_prepare", SCRIPT.with_name("guest_prepare.py"))
assert prepare_spec and prepare_spec.loader
prepare = importlib.util.module_from_spec(prepare_spec)
prepare_spec.loader.exec_module(prepare)
verify_spec = importlib.util.spec_from_file_location("linux_guest_verify", SCRIPT.with_name("guest_verify.py"))
assert verify_spec and verify_spec.loader
verify = importlib.util.module_from_spec(verify_spec)
with patch.dict(sys.modules, {"guest_prepare": prepare}):
    verify_spec.loader.exec_module(verify)


class LinuxEnvironmentSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="poseidon-linux-env-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def session(self):
        value = object.__new__(runner.Session)
        value.output = self.root / "output"
        value.output.mkdir()
        value.runtime = self.root / "runtime"
        value.runtime.mkdir()
        value.cache = self.root / "cache"
        value.limactl = Path(sys.executable)
        value.env = {"PATH": "/usr/bin:/bin", "HOME": str(self.root), "LANG": "C"}
        value.records = []
        value.pending = None
        value.deferred = 0
        value.may_exist = False
        value.cleanup_ok = False
        value.run_id = "synthetic-test-only"
        return value

    def test_environment_does_not_inherit_host_keys_proxies_or_tokens(self):
        with patch.dict(os.environ, {"SSH_AUTH_SOCK": "/personal/agent", "HTTPS_PROXY": "secret-proxy", "TOKEN": "not-for-guest"}):
            env = runner.isolated_environment(self.root / "cache", self.root / "short")
        self.assertEqual(set(env), {"PATH", "HOME", "LIMA_HOME", "TMPDIR", "LANG", "LC_ALL", "TERM"})
        self.assertTrue(env["HOME"].startswith(str(self.root)))
        self.assertNotIn("secret-proxy", str(env))
        self.assertNotIn("not-for-guest", str(env))

    def test_config_has_explicit_no_device_no_sharing_bounds(self):
        config = runner.configuration(self.root / "image.raw", "synthetic-run")
        for declaration in ("cpus: 2", "memory: 2GiB", "disk: 8GiB", "plain: true", "mounts: []", "additionalDisks: []",
                            "loadDotSSHPubKeys: false", "forwardAgent: false", "propagateProxyEnv: false",
                            "device: none", "display: none", "ignore: true", "upgradePackages: false", "mode: boot"):
            self.assertIn(declaration, config)
        self.assertNotIn("base:", config)
        self.assertNotIn("socket_vmnet", config)
        self.assertNotIn("vzNAT", config)
        self.assertIn("systemctl mask --now", config)
        self.assertIn("poseidon-no-device-verification", config)
        with self.assertRaises(runner.EnvironmentError):
            runner.configuration(self.root / "image.raw", "bad;command")

    def test_output_scope_rejects_traversal_home_and_symlinks(self):
        allowed = self.root / ".local" / "new-run"
        self.assertEqual(runner.owned_local_path(self.root, allowed), allowed)
        for path in (self.root, self.root / "source", self.root / ".local" / ".." / "escape", Path("/another-project/run")):
            with self.subTest(path=path), self.assertRaises(runner.EnvironmentError):
                runner.owned_local_path(self.root, path)
        (self.root / ".local").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(runner.EnvironmentError):
            runner.owned_local_path(self.root, allowed)

    def test_guest_sudo_is_only_a_guest_argument(self):
        session = self.session()
        session.call = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        session.guest(["sudo", "-n", "python3", "/guest/script.py"])
        args = session.call.call_args.args[0]
        self.assertEqual(args[:3], ["shell", "--tty=false", "abi"])
        self.assertEqual(args[3:5], ["sudo", "-n"])

    def test_real_control_fixture_pass_and_failure_are_recorded(self):
        session = self.session()
        result = session.call(["-c", "print('synthetic control only')"], 5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "synthetic control only")
        with self.assertRaises(runner.EnvironmentError):
            session.call(["-c", "raise SystemExit(7)"], 5)
        self.assertEqual([r["exit"] for r in session.records], [0, 7])
        self.assertTrue(all(Path(r["stdout"]).is_file() and Path(r["stderr"]).is_file() for r in session.records))

    def test_control_timeout_reaps_only_owned_group(self):
        session = self.session()
        with self.assertRaises(subprocess.TimeoutExpired):
            session.call(["-c", "import time;time.sleep(30)"], 0.1)
        self.assertEqual(len(session.records), 1)
        self.assertIsNone(session.records[0]["exit"])

    def test_spawn_cancellation_still_cleans_registered_control_process(self):
        session = self.session()
        process = Mock(pid=54321)
        process.wait.return_value = 0
        def spawn(*args, **kwargs):
            session.interrupt(signal.SIGTERM, None)
            return process
        with patch.object(runner.subprocess, "Popen", side_effect=spawn), patch.object(runner.os, "killpg") as kill:
            with self.assertRaises(runner.Cancelled):
                session.call(["synthetic-control"], 5)
        self.assertEqual({call.args[0] for call in kill.call_args_list}, {54321})
        self.assertEqual(process.wait.call_count, 2)

    def test_preflight_failure_does_not_execute_unverified_lima_to_stop(self):
        session = self.session()
        session.call = Mock(side_effect=AssertionError("must not run unverified tool"))
        session.stop()
        self.assertTrue(session.cleanup_ok)
        session.call.assert_not_called()

    def test_stop_timeout_uses_only_owned_force_fallback(self):
        session = self.session()
        session.may_exist = True
        session.call = Mock(side_effect=[subprocess.TimeoutExpired(["synthetic stop"], 60), subprocess.CompletedProcess([], 0, "", "")])
        session.listing = Mock(return_value=[{"name": "abi", "status": "Stopped"}])
        with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            session.stop()
        self.assertTrue(session.cleanup_ok)
        self.assertEqual(session.call.call_args_list[1].args[0], ["stop", "--force", "--tty=false", "abi"])

    def test_running_or_broken_vm_cannot_pass_cleanup(self):
        session = self.session()
        session.may_exist = True
        session.call = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        for status in ("Running", "Broken"):
            session.listing = Mock(return_value=[{"name": "abi", "status": status}])
            with self.subTest(status=status), self.assertRaises(runner.EnvironmentError):
                session.stop()
            self.assertFalse(session.cleanup_ok)

    def test_unknown_vm_in_owned_home_is_not_selected(self):
        session = self.session()
        session.call = Mock(return_value=subprocess.CompletedProcess([], 0, '{"name":"unowned","status":"Running"}\n', ""))
        with self.assertRaises(runner.EnvironmentError):
            session.listing()

    def test_resource_and_endpoint_mismatches_fail(self):
        session = self.session()
        valid = {"name": "abi", "status": "Running", "cpus": 2, "memory": 2*1024**3, "disk": 8*1024**3,
                 "vmType": "vz", "arch": "aarch64", "dir": str(session.runtime / "lima/abi"),
                 "hostAgentPID": 123, "driverPID": 0, "sshLocalPort": 60022}
        for key, value in (("cpus", 3), ("memory", 4*1024**3), ("disk", 9*1024**3), ("vmType", "qemu"), ("arch", "x86_64")):
            with self.subTest(key=key), self.assertRaises(runner.EnvironmentError):
                session.check_running([valid | {key: value}])
        ps = subprocess.CompletedProcess([], 0, f"123 /owned/limactl hostagent --socket {session.runtime}/lima/abi/ha.sock\n", "")
        bad = subprocess.CompletedProcess([], 0, "p123\nn*:60022\n", "")
        with patch.object(runner.subprocess, "run", side_effect=[ps, bad]), self.assertRaises(runner.EnvironmentError):
            session.check_running([valid])
        good = subprocess.CompletedProcess([], 0, "p123\nn127.0.0.1:60022\n", "")
        with patch.object(runner.subprocess, "run", side_effect=[ps, good]):
            self.assertTrue(session.check_running([valid])["resource_bounds_checked"])
        for empty in (subprocess.CompletedProcess([], 1, "", "lsof: inspection unavailable"),
                      subprocess.CompletedProcess([], 0, "", ""),
                      subprocess.CompletedProcess([], 0, "p123\nn127.0.0.1:60023\n", "")):
            with self.subTest(empty=empty), patch.object(runner.subprocess, "run", side_effect=[ps, empty]), self.assertRaises(runner.EnvironmentError):
                session.check_running([valid])

    def test_ssh_mux_title_is_not_mistaken_for_clean_shutdown(self):
        session = self.session()
        session.may_exist = True
        session.call = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        session.listing = Mock(return_value=[])
        ps = subprocess.CompletedProcess([], 0, f"123 ssh: {session.runtime}/lima/abi/ssh.sock [mux]\n", "")
        with patch.object(runner.subprocess, "run", return_value=ps), self.assertRaises(runner.EnvironmentError):
            session.stop()
        self.assertFalse(session.cleanup_ok)

    def test_selected_handoff_copies_only_listed_hash_bound_files(self):
        source = self.root / "apps/acoustic/native/linux_capture/build.py"
        source.parent.mkdir(parents=True)
        source.write_text("# synthetic source-only fixture\n")
        (source.parent / "unlisted.py").write_text("# must not transfer\n")
        relative = str(source.relative_to(self.root))
        handoff = self.root / "inputs.json"
        handoff.write_text(json.dumps({"files": {relative: runner.digest(source)}}))
        output = self.root / "selected"
        with patch.object(runner, "ROOT", self.root):
            record = runner.selected_inputs(handoff, output)
        runner.check_selected(record, output)
        self.assertEqual([p.name for p in output.rglob("*.py")], ["build.py"])
        (output / relative).write_text("# changed fixture\n")
        with self.assertRaises(runner.EnvironmentError):
            runner.check_selected(record, output)

    def test_selected_handoff_rejects_unapproved_paths_and_wrong_hashes(self):
        source = self.root / "apps/acoustic/source.py"
        source.parent.mkdir(parents=True)
        source.write_text("fixture")
        handoff = self.root / "inputs.json"
        for index, name in enumerate(("../escape", "/etc/passwd", "apps/acoustic/../escape", "other-lane/source.py", "apps/acoustic/source.py")):
            handoff.write_text(json.dumps({"files": {name: "0" * 64}}))
            with self.subTest(name=name), patch.object(runner, "ROOT", self.root), self.assertRaises(runner.EnvironmentError):
                runner.selected_inputs(handoff, self.root / f"selected-{index}")

    def test_selected_handoff_rejects_symlink_sources(self):
        source = self.root / "apps/acoustic/source.py"
        source.parent.mkdir(parents=True)
        actual = self.root / "actual.py"
        actual.write_text("fixture")
        source.symlink_to(actual)
        handoff = self.root / "inputs.json"
        handoff.write_text(json.dumps({"files": {"apps/acoustic/source.py": runner.digest(actual)}}))
        with patch.object(runner, "ROOT", self.root), self.assertRaises(runner.EnvironmentError):
            runner.selected_inputs(handoff, self.root / "selected")

    def test_native_gate_demands_four_executed_non_skipped_tests(self):
        session = self.session()
        session.call = Mock()
        session.check_guest_sources = Mock()
        selected = {"files": {"apps/acoustic/source.py": "0" * 64}}
        for output in ("Ran 0 tests in 0.1s\nOK\n", "Ran 4 tests in 0.1s\nOK (skipped=1)\n"):
            session.guest = Mock(side_effect=[subprocess.CompletedProcess([], 0, "", ""), subprocess.CompletedProcess([], 0, "", output)])
            with self.subTest(output=output), self.assertRaises(runner.EnvironmentError):
                session.native_gate(selected, "/guest/profile.json", "/guest/build")
        session.guest = Mock(side_effect=[subprocess.CompletedProcess([], 0, "", ""), subprocess.CompletedProcess([], 0, "", "Ran 4 tests in 0.1s\nOK\n")])
        self.assertEqual(session.native_gate(selected, "/guest/profile.json", "/guest/build")["tests_run"], 4)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", session.guest.call_args.args[0])
        self.assertIn("PT_NATIVE_BUILD=/guest/build/build.json", session.guest.call_args.args[0])
        self.assertNotIn("sudo", session.guest.call_args.args[0])

    def test_native_build_failure_still_checks_transferred_source_hashes(self):
        session = self.session()
        session.call = Mock()
        session.check_guest_sources = Mock()
        session.guest = Mock(side_effect=runner.EnvironmentError("synthetic compiler failure"))
        with self.assertRaisesRegex(runner.EnvironmentError, "compiler failure"):
            session.native_gate({"files": {}}, "/guest/profile.json", "/guest/build")
        self.assertEqual(session.check_guest_sources.call_count, 2)

    def test_bootstrap_refuses_existing_cache_before_network_or_host_checks(self):
        cache = self.root / ".local/existing"
        cache.mkdir(parents=True)
        with patch.object(bootstrap, "ROOT", self.root), patch.object(bootstrap, "host_preflight") as host, patch.object(bootstrap, "fetch") as fetch:
            with self.assertRaisesRegex(runner.EnvironmentError, "NEW absent"):
                bootstrap.bootstrap(cache)
        host.assert_not_called()
        fetch.assert_not_called()

    def test_bootstrap_download_is_single_bounded_https_and_keeps_failed_partial(self):
        cache = self.root / "cache"
        (cache / "downloads").mkdir(parents=True)
        (cache / "artifacts").mkdir()
        pin = ("https://example.invalid/synthetic", "fixture", 7, "sha256", "0" * 64, 5)
        def failed(command, **kwargs):
            self.assertEqual(command[:2], ["/usr/bin/curl", "--disable"])
            self.assertIn("=https", command)
            self.assertEqual(command[command.index("--retry") + 1], "0")
            self.assertEqual(kwargs["timeout"], 15)
            (cache / "downloads/fixture.partial").write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 28)
        with patch.object(bootstrap.shutil, "disk_usage", return_value=Mock(free=runner.MIN_FREE)), patch.object(bootstrap.subprocess, "run", side_effect=failed) as network:
            with self.assertRaisesRegex(runner.EnvironmentError, "exited28"):
                bootstrap.fetch(cache, {"HOME": "/owned/home"}, pin)
        self.assertEqual(network.call_count, 1)
        self.assertEqual((cache / "downloads/fixture.partial").read_bytes(), b"partial")
        self.assertFalse((cache / "downloads/fixture").exists())
        self.assertEqual(json.loads((cache / "artifacts/fixture.download.json").read_text())["exit"], 28)

    def test_bootstrap_checksum_mismatch_is_not_published_or_retried(self):
        cache = self.root / "cache"
        (cache / "downloads").mkdir(parents=True)
        (cache / "artifacts").mkdir()
        def changed(command, **kwargs):
            (cache / "downloads/fixture.partial").write_bytes(b"wrong")
            return subprocess.CompletedProcess(command, 0)
        with patch.object(bootstrap.shutil, "disk_usage", return_value=Mock(free=runner.MIN_FREE)), patch.object(bootstrap.subprocess, "run", side_effect=changed) as network:
            with self.assertRaisesRegex(runner.EnvironmentError, "checksum"):
                bootstrap.fetch(cache, {}, ("https://example.invalid/synthetic", "fixture", 5, "sha256", "0" * 64, 5))
        self.assertEqual(network.call_count, 1)
        self.assertTrue((cache / "downloads/fixture.partial").is_file())
        self.assertFalse((cache / "downloads/fixture").exists())

    def test_bootstrap_extraction_preserves_bytes_and_safe_symlink(self):
        archive = self.root / "fixture.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            member = tarfile.TarInfo("bin/tool")
            member.size, member.mode = 7, 0o755
            bundle.addfile(member, io.BytesIO(b"fixture"))
            link = tarfile.TarInfo("bin/link")
            link.type, link.linkname = tarfile.SYMTYPE, "tool"
            bundle.addfile(link)
        bootstrap.extract_checked(archive, self.root / "tools")
        self.assertEqual((self.root / "tools/bin/tool").read_bytes(), b"fixture")
        self.assertEqual(os.readlink(self.root / "tools/bin/link"), "tool")

    def test_bootstrap_extraction_rejects_escape_special_and_symlink_traversal(self):
        for index, kind in enumerate(("escape", "special", "link-escape", "link-parent")):
            archive = self.root / f"fixture-{index}.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                member = tarfile.TarInfo("../escape" if kind == "escape" else "link")
                if kind == "special":
                    member.type = tarfile.FIFOTYPE
                elif kind.startswith("link"):
                    member.type, member.linkname = tarfile.SYMTYPE, "../escape" if kind == "link-escape" else "target"
                bundle.addfile(member)
                if kind == "link-parent":
                    bundle.addfile(tarfile.TarInfo("link/child"))
            with self.subTest(kind=kind), self.assertRaises(runner.EnvironmentError):
                bootstrap.extract_checked(archive, self.root / f"tools-{index}")
        self.assertFalse((self.root / "escape").exists())

    def test_selected_proto_scope_is_narrow_and_live_orchestration_is_refused(self):
        for index, name in enumerate(("libs/proto-py/other/source.py", "libs/proto-ts/src/source.ts", "apps/acoustic/src/poseidon_acoustic/live_supervisor.py")):
            handoff = self.root / f"inputs-{index}.json"
            handoff.write_text(json.dumps({"files": {name: "0" * 64}}))
            with patch.object(runner, "ROOT", self.root), self.assertRaises(runner.EnvironmentError):
                runner.selected_inputs(handoff, self.root / f"selected-{index}")

    def test_debian13_arm64_uapi_header_directory_is_narrowly_admitted(self):
        for path in ("/usr/include/linux/videodev2.h", "/usr/include/alsa/asoundlib.h",
                     "/usr/lib/linux/uapi/arm64/asm/errno.h", "/usr/lib/linux/uapi/arm64/asm/ioctl.h",
                     "/usr/lib/linux/uapi/arm64/asm/types.h", "/usr/lib/linux/uapi/arm64/asm/bitsperlong.h",
                     "/usr/lib/linux/uapi/arm64/asm/posix_types.h"):
            self.assertTrue(verify.system_header(Path(path)), path)
        for path in ("/usr/lib/linux/uapi/x86/asm/errno.h", "/usr/lib/linux/uapi/arm64/other.h",
                     "/usr/lib/linux/uapi/arm64/asm/unlisted.h",
                     "/usr/lib/other.h", "/home/builder/errno.h", "usr/include/errno.h",
                     "/usr/lib/linux/uapi/arm64/asm/../../escape.h"):
            self.assertFalse(verify.system_header(Path(path)), path)

    def test_smoke_source_has_no_capture_function_calls(self):
        text = (ROOT / "scripts/assurance/linux_capture_env/abi_smoke.c").read_text()
        for function in ("snd_pcm_open(", "snd_pcm_readi(", "ioctl(", "open(", "mmap(", "VIDIOC_QUERYCAP("):
            self.assertNotIn(function, text)
        self.assertIn("snd_asoundlib_version()", text)
        self.assertIn("sizeof(type)", text)


if __name__ == "__main__":
    unittest.main()
