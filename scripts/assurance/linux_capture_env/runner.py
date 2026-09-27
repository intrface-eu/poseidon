"""Project-local Lima/VZ Linux ARM64 no-device verification.

No host sudo, global installation/configuration, security bypass, device sharing,
container service, or capture operation is supported. Every run owns a new VM.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
LIMA_VERSION = "2.2.0"
LIMA_SHA256 = "bbdef91774885a0d05f7b048c4eb89ae2bcf3a0c252ae7ca7934e63df76d93c3"
LIMA_ARCHIVE = "lima-2.2.0-Darwin-arm64.tar.gz"
IMAGE_NAME = "debian-13-genericcloud-arm64-20260831-2587.raw"
IMAGE_URL = "https://cloud.debian.org/images/cloud/trixie/20260831-2587/" + IMAGE_NAME
IMAGE_BYTES = 3221225472
IMAGE_SHA512 = "d1217c88cd84a659686490fb206463138ca04dedcd4c061a6dae68eee1d3b288ad2bb2d096238b99e740d2557988cd24ce84df4c3a96a236d0d0a55c7297ecc1"
OWNER = "poseidon-linux-no-device-task18"
MIN_FREE = 12 * 1024**3
VM_NAME = "abi"
GUEST_HOME = "/home/builder"


class EnvironmentError(RuntimeError):
    pass


class Cancelled(EnvironmentError):
    def __init__(self, signum: int):
        self.signum = signum
        super().__init__(f"cancelled by signal {signum}")


def digest(path: Path, algorithm: str = "sha256") -> str:
    value = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def owned_local_path(root: Path, path: Path) -> Path:
    root = root.resolve()
    absolute = path.absolute()
    if ".." in absolute.parts or not absolute.is_relative_to(root):
        raise EnvironmentError("workspace must remain inside this project")
    parts = absolute.relative_to(root).parts
    if len(parts) < 2 or parts[0] != ".local":
        raise EnvironmentError("workspace must be a named project-local .local directory")
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise EnvironmentError("workspace must not traverse symlinks")
    return absolute


def host_preflight(root: Path) -> dict:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise EnvironmentError("this pinned VZ route requires Darwin arm64")
    if shutil.disk_usage(root).free < MIN_FREE:
        raise EnvironmentError("at least12GiB free disk space is required")
    version = subprocess.run(["/usr/bin/sw_vers", "-productVersion"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if int(version.split(".")[0]) < 13:
        raise EnvironmentError("VZ route requires macOS13 or later")
    values = {}
    for name in ("kern.hv_support", "hw.ncpu", "hw.memsize"):
        values[name] = int(subprocess.run(["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True, check=True, timeout=10).stdout.strip())
    if values["kern.hv_support"] != 1 or values["hw.ncpu"] < 2 or values["hw.memsize"] < 2 * 1024**3:
        raise EnvironmentError("required virtualization/CPU/memory resources unavailable")
    return {"architecture": "arm64", "macOS": version, "resources": values, "free_disk_bytes": shutil.disk_usage(root).free}


def isolated_environment(cache: Path, runtime: Path) -> dict[str, str]:
    return {"PATH": str(cache / "tools/bin") + ":/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(runtime / "home"), "LIMA_HOME": str(runtime / "lima"),
            "TMPDIR": str(runtime / "tmp"), "LANG": "C", "LC_ALL": "C", "TERM": "dumb"}


def verify_cache(cache: Path) -> dict:
    """Independently rehash the published archive, extracted tree and raw image."""
    archive = cache / "downloads" / LIMA_ARCHIVE
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size != 37586365 or digest(archive) != LIMA_SHA256:
        raise EnvironmentError("Lima archive does not match the official pin")
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise EnvironmentError("unsafe archive member")
            path = cache / "tools" / member.name
            if member.isfile():
                stream = bundle.extractfile(member)
                if stream is None or path.is_symlink() or not path.is_file():
                    raise EnvironmentError(f"missing/changed extracted artifact: {member.name}")
                with stream:
                    expected = hashlib.sha256(stream.read()).hexdigest()
                if digest(path) != expected:
                    raise EnvironmentError(f"extracted artifact hash mismatch: {member.name}")
            elif member.issym():
                if not path.is_symlink() or os.readlink(path) != member.linkname:
                    raise EnvironmentError(f"extracted symlink mismatch: {member.name}")
            elif not member.isdir():
                raise EnvironmentError("unsupported archive member type")
    image = cache / "downloads" / IMAGE_NAME
    if image.is_symlink() or not image.is_file() or image.stat().st_size != IMAGE_BYTES or digest(image, "sha512") != IMAGE_SHA512:
        raise EnvironmentError("Debian raw image does not match the official SHA512 pin")
    return {"lima_archive_sha256": LIMA_SHA256, "image_reference": IMAGE_URL,
            "image_published_sha512": IMAGE_SHA512, "image_digest": "sha256:" + digest(image),
            "image_sha256_origin": "locally calculated after published SHA512 verification"}


def configuration(image: Path, run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
        raise EnvironmentError("invalid run identity")
    return f'''minimumLimaVersion: "2.2.0"
vmType: vz
os: Linux
arch: aarch64
images:
  - location: {json.dumps(str(image))}
    arch: aarch64
    digest: sha512:{IMAGE_SHA512}
cpus: 2
memory: 2GiB
disk: 8GiB
additionalDisks: []
plain: true
mounts: []
mountType: virtiofs
mountInotify: false
ssh:
  localPort: 0
  loadDotSSHPubKeys: false
  forwardAgent: false
  forwardX11: false
  forwardX11Trusted: false
  overVsock: false
networks: []
portForwards:
  - guestIP: "0.0.0.0"
    guestPortRange: [1, 65535]
    proto: any
    ignore: true
containerd:
  system: false
  user: false
vmOpts:
  vz:
    diskImageFormat: raw
    rosetta:
      enabled: false
      binfmt: false
audio:
  device: none
video:
  display: none
nestedVirtualization: false
tpm: false
upgradePackages: false
propagateProxyEnv: false
env: {{}}
hostResolver:
  enabled: false
caCerts:
  files: []
  certs: []
user:
  name: builder
  comment: Linux ABI verification
  uid: 1000
  home: /home/builder
  shell: /bin/bash
  passwordlessSudo: true
provision:
  - mode: boot
    script: |
      set -eu
      test "$(uname -s)" = Linux
      test "$(uname -m)" = aarch64
      test "$(id -u)" = 0
      timeout 30s systemctl mask --now apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service unattended-upgrades.service
      printf '%s\\n' 'APT::Periodic::Enable "0";' 'APT::Periodic::Update-Package-Lists "0";' 'APT::Periodic::Unattended-Upgrade "0";' > /etc/apt/apt.conf.d/99-poseidon-no-periodic
      if test -e /etc/poseidon-no-device-verification; then
        test "$(cat /etc/poseidon-no-device-verification)" = {run_id}
      else
        (set -C; umask 022; printf '%s\\n' '{run_id}' > /etc/poseidon-no-device-verification)
      fi
      test "$(cat /etc/poseidon-no-device-verification)" = {run_id}
'''


def selected_inputs(manifest: Path, destination: Path) -> dict:
    """Freeze exactly the explicit handoff; never copy an implicit import closure."""
    raw = manifest.read_bytes()
    handoff = json.loads(raw)
    files = handoff.get("files")
    if not isinstance(files, dict) or not files or len(files) > 100:
        raise EnvironmentError("selected source handoff needs1..100 exact file hashes")
    destination.mkdir(mode=0o700, exist_ok=False)
    for name, expected in files.items():
        relative = PurePosixPath(name)
        if (not isinstance(name, str) or relative.is_absolute() or ".." in relative.parts
                or str(relative) != name or not name.startswith(("apps/acoustic/", "apps/nereid/", "tests/acoustic/", "tests/nereid/", "libs/proto-py/src/poseidon_proto/"))
                or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
            raise EnvironmentError("invalid selected source path/hash")
        if relative.name in {"live_journal.py", "live_supervisor.py", "live_capture_cli.py"}:
            raise EnvironmentError("changing live-capture orchestration source is outside this selected gate")
        source = ROOT / name
        if source.resolve() != source or not source.is_file() or source.stat().st_size > 2 * 1024**2:
            raise EnvironmentError("selected source is not a bounded regular project file")
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise EnvironmentError(f"selected source hash differs from Acquisition handoff: {name}")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
    return {"manifest": str(manifest), "manifest_sha256": hashlib.sha256(raw).hexdigest(), "files": files}


def check_selected(record: dict, root: Path) -> None:
    for name, expected in record["files"].items():
        path = root / name
        if path.resolve() != path or not path.is_file() or digest(path) != expected:
            raise EnvironmentError(f"selected source changed: {path}")


class Session:
    def __init__(self, cache: Path, output: Path):
        self.cache = owned_local_path(ROOT, cache)
        self.output = owned_local_path(ROOT, output)
        if self.output.exists():
            raise EnvironmentError("output must be a new directory; existing evidence is preserved")
        self.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.runtime = Path(tempfile.mkdtemp(prefix="pc18-", dir="/tmp")).resolve()
        for part in ("home", "lima", "tmp"):
            (self.runtime / part).mkdir(mode=0o700)
        self.run_id = "lc18-" + uuid.uuid4().hex[:16]
        self.env = isolated_environment(self.cache, self.runtime)
        self.limactl = self.cache / "tools/bin/limactl"
        self.records: list[dict] = []
        self.pending: int | None = None
        self.deferred = 0
        self.may_exist = False
        self.cleanup_ok = False
        self.identity = {"owner": OWNER, "run_id": self.run_id, "runtime": str(self.runtime),
                         "cache": str(self.cache), "output": str(self.output), "instance": VM_NAME}
        write_new(self.runtime / "owner.json", self.identity)
        write_new(self.output / "session.json", self.identity)

    def interrupt(self, signum: int, _frame: object) -> None:
        if self.pending is None:
            self.pending = signum
        if not self.deferred:
            raise Cancelled(self.pending)

    @contextmanager
    def defer(self):
        self.deferred += 1
        try:
            yield
        finally:
            self.deferred -= 1
            if not self.deferred and self.pending is not None:
                raise Cancelled(self.pending)

    def call(self, args: list[str], timeout: float = 60, *, allow_failure: bool = False) -> subprocess.CompletedProcess:
        number = len(self.records) + 1
        stdout_path = self.output / f"command-{number:03}.stdout.log"
        stderr_path = self.output / f"command-{number:03}.stderr.log"
        command = [str(self.limactl), *args]
        process = None
        started = time.monotonic()
        status = None
        try:
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                try:
                    with self.defer():
                        process = subprocess.Popen(command, env=self.env, cwd=ROOT, stdin=subprocess.DEVNULL,
                                                   stdout=stdout, stderr=stderr, start_new_session=True)
                    while True:
                        if stdout_path.stat().st_size + stderr_path.stat().st_size > 16 * 1024**2:
                            raise EnvironmentError("control command output limit exceeded")
                        remaining = timeout - (time.monotonic() - started)
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(command, timeout)
                        try:
                            status = process.wait(timeout=min(remaining, 0.25))
                            break
                        except subprocess.TimeoutExpired:
                            continue
                except BaseException:
                    if process is not None:
                        with self.defer():
                            try:
                                os.killpg(process.pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                pass
                            finally:
                                try:
                                    os.killpg(process.pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                                process.wait(timeout=5)
                    raise
        finally:
            self.records.append({"command": command, "timeout_seconds": timeout, "exit": status,
                                 "elapsed_seconds": time.monotonic() - started,
                                 "stdout": str(stdout_path), "stderr": str(stderr_path)})
        result = subprocess.CompletedProcess(command, status, stdout_path.read_text(errors="replace"), stderr_path.read_text(errors="replace"))
        if status and not allow_failure:
            raise EnvironmentError(f"command exited{status}: {' '.join(args)}; see {stderr_path}")
        return result

    def guest(self, args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
        # sudo, when needed, is an argument of the guest shell operation only.
        return self.call(["shell", "--tty=false", VM_NAME, *args], timeout)

    def listing(self) -> list[dict]:
        result = self.call(["list", "--json"], 30)
        values = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        if len(values) == 1 and isinstance(values[0], list):
            values = values[0]
        if any(value.get("name") != VM_NAME for value in values):
            raise EnvironmentError("unexpected instance in newly owned Lima home")
        return values

    def check_running(self, state: list[dict]) -> dict:
        if len(state) != 1 or state[0].get("status", "").lower() != "running":
            raise EnvironmentError("Lima did not report one owned running VM")
        item = state[0]
        for key, expected in (("cpus", 2), ("memory", 2 * 1024**3), ("disk", 8 * 1024**3)):
            if type(item.get(key)) is not int or item[key] != expected:
                raise EnvironmentError(f"VM resource bound mismatch: {key}")
        if item.get("vmType") != "vz" or item.get("arch") != "aarch64":
            raise EnvironmentError("unexpected VM backend/architecture")
        if Path(item.get("dir", "")).resolve() != (self.runtime / "lima" / VM_NAME).resolve():
            raise EnvironmentError("instance directory does not belong to this session")
        host_pid, driver_pid, ssh_port = item.get("hostAgentPID"), item.get("driverPID"), item.get("sshLocalPort")
        if type(host_pid) is not int or host_pid <= 1 or type(driver_pid) is not int or driver_pid < 0:
            raise EnvironmentError("invalid owned VM process identities")
        if type(ssh_port) is not int or not 1 <= ssh_port <= 65535:
            raise EnvironmentError("invalid owned loopback SSH port")
        pids = sorted({host_pid} | ({driver_pid} if driver_pid > 1 else set()))
        ps = subprocess.run(["/bin/ps", "-p", ",".join(map(str, pids)), "-o", "pid=,command="], env=self.env,
                            capture_output=True, text=True, check=True, timeout=10)
        commands = {int(line.strip().split(None, 1)[0]): line for line in ps.stdout.splitlines() if line.strip()}
        if set(commands) != set(pids) or any(str(self.runtime) not in line for line in commands.values()):
            raise EnvironmentError("reported control PIDs are not bound to this owned runtime")
        network = subprocess.run(["/usr/sbin/lsof", "-nP", "-a", "-p", ",".join(map(str, pids)),
                                  "-iTCP", "-sTCP:LISTEN", "-Fpn"], env=self.env, capture_output=True,
                                 text=True, timeout=10)
        if network.returncode != 0 or network.stderr.strip():
            raise EnvironmentError("owned endpoint inspection failed or reported diagnostics")
        endpoints = [line[1:] for line in network.stdout.splitlines() if line.startswith("n")]
        if f"127.0.0.1:{ssh_port}" not in endpoints:
            raise EnvironmentError("expected loopback SSH listener was not observed")
        if any(not value.startswith(("127.0.0.1:", "[::1]:")) for value in endpoints):
            raise EnvironmentError("owned control endpoint is not loopback-only")
        return {"owned_control_pids": pids, "tcp_listeners": endpoints, "resource_bounds_checked": True}

    def stop(self) -> None:
        with self.defer():
            if not self.may_exist:
                # Never execute a possibly unverified tool merely to clean up a
                # preflight failure before this session could create an instance.
                self.cleanup_ok = True
                return
            try:
                result = self.call(["stop", "--tty=false", VM_NAME], 60, allow_failure=True)
                force_needed = result.returncode != 0
            except (EnvironmentError, OSError, subprocess.SubprocessError):
                force_needed = True
            if force_needed:
                self.call(["stop", "--force", "--tty=false", VM_NAME], 30, allow_failure=True)
            values = self.listing()
            if any(value.get("status", "").lower() not in {"stopped", "broken"} for value in values):
                raise EnvironmentError("owned VM did not reach stopped state")
            # A broken instance is not successful cleanup without process proof.
            if any(value.get("status", "").lower() == "broken" for value in values):
                raise EnvironmentError("owned VM is broken; cleanup needs review")
            control = self.runtime / "lima" / VM_NAME / "ssh.sock"
            if control.exists() and stat.S_ISSOCK(control.lstat().st_mode):
                command = ["/usr/bin/ssh", "-F", "/dev/null", "-S", str(control), "-O", "exit", "lima-" + VM_NAME]
                result = subprocess.run(command, env=self.env, stdin=subprocess.DEVNULL, capture_output=True,
                                        text=True, timeout=10)
                self.records.append({"command": command, "exit": result.returncode,
                                     "scope": "exit only the owned SSH control socket", "stderr": result.stderr})
            ps = subprocess.run(["/bin/ps", "-axo", "pid=,command="], env=self.env, capture_output=True,
                                text=True, check=True, timeout=10)
            remaining = [line for line in ps.stdout.splitlines()
                         if str(self.runtime) in line and (str(control) in line or any(name in line for name in ("limactl", "/ssh ", "ssh:", "lima-vz")))]
            write_new(self.output / "cleanup-process-proof.json", {
                "runtime": str(self.runtime), "instances": values, "remaining_owned_processes": remaining,
                "ps_command": ["/bin/ps", "-axo", "pid=,command="], "ps_exit": ps.returncode,
                "observed_at": datetime.now(timezone.utc).isoformat()})
            if remaining:
                raise EnvironmentError("owned VM/control processes remain after stop: " + "; ".join(remaining))
            self.cleanup_ok = True

    def collect_guest_tree(self, guest_path: str, label: str) -> None:
        """Keep only this run's explicit evidence, including failed guest logs."""
        exists = self.guest(["python3", "-c", "from pathlib import Path;import sys;print(Path(sys.argv[1]).is_dir())", guest_path], 20)
        if exists.stdout.strip() != "True":
            return
        archive = GUEST_HOME + "/" + label + "-" + self.run_id + ".tar"
        self.guest(["tar", "-C", guest_path, "--exclude=./apt/lists/partial", "--exclude=./apt/lists/auxfiles",
                    "--exclude=./apt/archives/partial", "--exclude=./apt/lists/lock", "--exclude=./apt/archives/lock",
                    "-cf", archive, "."], 120)
        local_archive = self.output / (label + ".tar")
        self.call(["copy", "--tty=false", "--backend=scp", VM_NAME + ":" + archive, str(local_archive)], 300)
        target = self.output / label
        target.mkdir(mode=0o700)
        with tarfile.open(local_archive) as bundle:
            for member in bundle.getmembers():
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts or not (member.isfile() or member.isdir()):
                    raise EnvironmentError("non-regular or escaping guest evidence archive member")
                path = target / relative
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    stream = bundle.extractfile(member)
                    if stream is None:
                        raise EnvironmentError("unreadable guest evidence archive member")
                    with stream, path.open("xb") as output:
                        shutil.copyfileobj(stream, output)
        manifest = target / "artifact-manifest.json"
        if manifest.is_file():
            for name, expected in json.loads(manifest.read_text())["files"].items():
                relative = PurePosixPath(name)
                path = target / relative
                if relative.is_absolute() or ".." in relative.parts or not path.is_file():
                    raise EnvironmentError("guest evidence manifest path is invalid/missing")
                if path.stat().st_size != expected["size"] or digest(path) != expected["sha256"]:
                    raise EnvironmentError(f"transferred guest evidence hash mismatch: {name}")

    def check_guest_sources(self, root: str, files: dict) -> None:
        code = ("import hashlib,json,pathlib,sys;root=pathlib.Path(sys.argv[1]);files=json.loads(sys.argv[2]);"
                "actual={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files};"
                "print(json.dumps(actual,sort_keys=True));"
                "sys.exit(0 if actual==files else 2)")
        self.guest(["python3", "-c", code, root, json.dumps(files, sort_keys=True)], 30)

    def native_gate(self, selected: dict, profile: str, native_output: str) -> dict:
        guest_repo = GUEST_HOME + "/selected-repo-" + self.run_id
        self.call(["copy", "--tty=false", "--backend=scp", "-r", str(self.output / "selected-repo"), VM_NAME + ":" + guest_repo], 120)
        self.check_guest_sources(guest_repo, selected["files"])
        clean = ["env", "-i", "PATH=/usr/bin:/bin", "LANG=C", "LC_ALL=C", "HOME=" + GUEST_HOME,
                 "PYTHONDONTWRITEBYTECODE=1", "PYTHONPATH=" + guest_repo + "/apps/acoustic/src:" + guest_repo + "/apps/nereid/src:" + guest_repo + "/libs/proto-py/src"]
        try:
            self.guest([*clean, "python3", guest_repo + "/apps/acoustic/native/linux_capture/build.py",
                        "--native-profile", profile, "--output", native_output], 600)
            gate = self.guest([*clean, "PT_NATIVE_PROFILE=" + profile, "PT_NATIVE_BUILD=" + native_output + "/build.json",
                               "python3", "-m", "unittest", "discover", "-s", guest_repo + "/tests/acoustic/linux_backend_abi", "-v"], 600)
            text = gate.stdout + gate.stderr
            if not re.search(r"\bRan 4 tests in ", text) or not re.search(r"^OK$", text, re.MULTILINE) or re.search(r"skip", text, re.IGNORECASE):
                raise EnvironmentError("native ABI gate must execute exactly4 tests with zero skips")
            return {"build_exit": 0, "gate_exit": 0, "tests_run": 4, "skipped": 0,
                    "artifact_kind": "production-linux", "numeric_kind_asserted_by_gate": 1,
                    "guest_uid": 1000, "device_access_occurred": False}
        finally:
            self.check_guest_sources(guest_repo, selected["files"])

    def verify(self, *, provision: bool = True, native_inputs: Path | None = None) -> dict:
        previous = {sig: signal.signal(sig, self.interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
        outcome = {"owner": OWNER, "run_id": self.run_id, "started_at": datetime.now(timezone.utc).isoformat(),
                   "release_authorized": False, "physical_capture_performed": False,
                   "verification_scope": "unprivileged compile/link/no-device ABI" if provision else "boot/identity/stop only; no ABI claim"}
        error = None
        selected = None
        collect = []
        selected_helpers = []
        try:
            if native_inputs is not None:
                if not provision:
                    raise EnvironmentError("native gate requires guest provisioning")
                selected = selected_inputs(native_inputs, self.output / "selected-repo")
                handoff = native_inputs.read_bytes()
                if hashlib.sha256(handoff).hexdigest() != selected["manifest_sha256"]:
                    raise EnvironmentError("Acquisition handoff changed during source selection")
                with (self.output / "native-input-handoff.json").open("xb") as stream:
                    stream.write(handoff)
                outcome["selected_native_inputs"] = selected
                write_new(self.output / "selected-inputs.json", selected)
            outcome["host"] = host_preflight(ROOT)
            outcome["pins"] = verify_cache(self.cache)
            selected_helpers = [HERE / name for name in ("runner.py", "bootstrap.py", "guest_prepare.py", "guest_verify.py", "abi_smoke.c")]
            outcome["helper_source_hashes"] = {str(path.relative_to(ROOT)): digest(path) for path in selected_helpers}
            for target in (self.cache / "downloads" / LIMA_ARCHIVE, self.limactl):
                attrs = subprocess.run(["/usr/bin/xattr", str(target)], env=self.env, capture_output=True, text=True, check=True, timeout=10).stdout.splitlines()
                if "com.apple.quarantine" in attrs:
                    raise EnvironmentError("quarantine attribute present; no bypass/removal allowed")
            subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(self.limactl)], env=self.env, check=True, timeout=20)
            version = self.call(["--version"], 20)
            if "2.2.0" not in version.stdout:
                raise EnvironmentError("wrong Lima version")
            if self.listing():
                raise EnvironmentError("new Lima home unexpectedly contains a VM")
            config = self.output / "lima.yaml"
            with config.open("x") as stream:
                stream.write(configuration(self.cache / "downloads" / IMAGE_NAME, self.run_id))
            self.call(["validate", str(config)], 30)
            self.may_exist = True
            self.call(["create", "--tty=false", "--mount-none", "--name=" + VM_NAME, str(config)], 120)
            self.call(["start", "--tty=false", "--timeout=180s", VM_NAME], 210)
            state = self.listing()
            write_new(self.output / "running-instance.json", {"instances": state})
            outcome["host_isolation_audit"] = self.check_running(state)
            identity = self.guest(["python3", "-c", "import json,os,platform,sys;print(json.dumps({'system':platform.system(),'machine':platform.machine(),'kernel':platform.release(),'python':platform.python_version(),'uid':os.getuid(),'byteorder':sys.byteorder}))"])
            info = json.loads(identity.stdout)
            if info["system"] != "Linux" or info["machine"] != "aarch64" or info["uid"] == 0 or info["byteorder"] != "little":
                raise EnvironmentError("guest is not unprivileged Linux aarch64 little-endian")
            outcome["guest"] = info
            self.guest(["test", "-f", "/etc/poseidon-no-device-verification"])
            marker = self.guest(["python3", "-c", "from pathlib import Path;print(Path('/etc/poseidon-no-device-verification').read_text().strip())"])
            if marker.stdout.strip() != self.run_id:
                raise EnvironmentError("guest boot ownership marker mismatch")
            if provision:
                for name in ("guest_prepare.py", "guest_verify.py", "abi_smoke.c"):
                    self.call(["copy", "--tty=false", "--backend=scp", str(HERE / name), VM_NAME + ":" + GUEST_HOME + "/" + name], 60)
                helper_files = {name: outcome["helper_source_hashes"][str((HERE / name).relative_to(ROOT))]
                                for name in ("guest_prepare.py", "guest_verify.py", "abi_smoke.c")}
                self.check_guest_sources(GUEST_HOME, helper_files)
                work = "/var/lib/poseidon-no-device-" + self.run_id
                collect.append((work, "guest-package-inputs"))
                image_args = ["--image-reference", IMAGE_URL, "--image-digest", outcome["pins"]["image_digest"]]
                # A single aggregate deadline encloses the separately bounded APT
                # stages (900/1200/900s and exact closure downloads). Host allows
                # guest cancellation/child reaping before its own hard deadline.
                self.guest(["sudo", "-n", "timeout", "--signal=TERM", "--kill-after=15s", "5400s",
                            "python3", GUEST_HOME + "/guest_prepare.py", "--run-id", self.run_id,
                            "--work-dir", work, *image_args], 5460)
                result_dir = GUEST_HOME + "/verification-" + self.run_id
                collect.append((result_dir, "guest-verification"))
                self.guest(["python3", GUEST_HOME + "/guest_verify.py", "--run-id", self.run_id,
                            "--prepared", work, "--output", result_dir, *image_args], 300)
                outcome["no_device_compile_link_abi"] = "performed; inspect copied guest records"
                if selected is not None:
                    native_output = GUEST_HOME + "/native-build-" + self.run_id
                    collect.append((native_output, "native-build"))
                    outcome["native_gate"] = self.native_gate(selected, result_dir + "/native-profile.json", native_output)
                self.check_guest_sources(GUEST_HOME, helper_files)
            if outcome["helper_source_hashes"] != {str(path.relative_to(ROOT)): digest(path) for path in selected_helpers}:
                raise EnvironmentError("selected helper source changed during verification")
            outcome["state"] = "verification-complete-cleanup-pending"
        except BaseException as exc:
            error = exc
            outcome["state"] = "failed"
            outcome["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if self.pending is None:
                for guest_path, label in collect:
                    try:
                        self.collect_guest_tree(guest_path, label)
                    except BaseException as collection_error:
                        outcome.setdefault("evidence_collection_errors", []).append(f"{label}: {type(collection_error).__name__}: {collection_error}")
                        error = error or collection_error
                        outcome["state"] = "failed"
            elif collect:
                outcome["guest_evidence_retained_in_stopped_disk"] = str(self.runtime / "lima" / VM_NAME / "disk")
            try:
                if selected is not None:
                    check_selected(selected, ROOT)
                    check_selected(selected, self.output / "selected-repo")
                    outcome["selected_source_hashes_preserved"] = True
                if selected_helpers:
                    if outcome["helper_source_hashes"] != {str(path.relative_to(ROOT)): digest(path) for path in selected_helpers}:
                        raise EnvironmentError("selected helper source changed during verification")
                    outcome["helper_source_hashes_preserved"] = True
            except BaseException as source_error:
                outcome["source_preservation_error"] = f"{type(source_error).__name__}: {source_error}"
                error = error or source_error
                outcome["state"] = "failed"
            try:
                self.stop()
            except BaseException as cleanup:
                # A prior cancellation may be re-raised only after real cleanup.
                if not isinstance(cleanup, Cancelled) or not self.cleanup_ok:
                    outcome["cleanup_error"] = f"{type(cleanup).__name__}: {cleanup}"
                    outcome["state"] = "failed"
                    error = error or cleanup
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            outcome["cleanup_ok"] = self.cleanup_ok
            outcome["commands"] = self.records
            outcome["finished_at"] = datetime.now(timezone.utc).isoformat()
            if error is None and self.cleanup_ok:
                outcome["state"] = "passed-development-no-device-ABI" if provision else "passed-boot-stop-only"
            write_new(self.output / "result.json", outcome)
        if error is not None or not self.cleanup_ok:
            raise EnvironmentError(outcome.get("error", outcome.get("cleanup_error", "cleanup failed")))
        return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--boot-only", action="store_true", help="Only prove owned Linux boot/stop; no ABI claim")
    parser.add_argument("--native-inputs", type=Path, help="Exact stable Acquisition file/hash handoff; runs real4-test gate")
    args = parser.parse_args()
    try:
        session = Session(args.cache, args.output)
        result = session.verify(provision=not args.boot_only, native_inputs=args.native_inputs)
        print(json.dumps({"state": result["state"], "result": str(session.output / "result.json"),
                          "guest": result.get("guest"), "cleanup_ok": result["cleanup_ok"], "release_authorized": False}, indent=2))
        return 0
    except (EnvironmentError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Linux verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
