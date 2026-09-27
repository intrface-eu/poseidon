#!/usr/bin/env python3
"""Provision only a marked, owned Debian 13 ARM64 guest; never upgrade it.

This program is not a host bootstrap. All subprocesses have explicit argv,
clean environments, deadlines, and retained stdout/stderr. A failed run keeps
its new work directory and cannot be resumed over existing evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import time

MARKER = Path("/etc/poseidon-no-device-verification")
SNAPSHOT = "20260901T000000Z"
KEYRING = Path("/usr/share/keyrings/debian-archive-keyring.gpg")
PROFILE_SCHEMA = "poseidon.linux-capture-native-profile.v1"
BASE_PINS = {
    "libc6": "2.41-12+deb13u3",
    "gcc-14-base": "14.2.0-19",
    "python3": "3.13.5-1",
    "python3.13": "3.13.5-2+deb13u4",
}
INSTALL_PINS = {
    **BASE_PINS,
    "gcc-14": "14.2.0-19",
    "gcc-14-aarch64-linux-gnu": "14.2.0-19",
    "libc6-dev": "2.41-12+deb13u3",
    "linux-libc-dev": "6.12.107-1",
    "libasound2t64": "1.2.14-1",
    "libasound2-dev": "1.2.14-1",
}
REQUIRED_PACKAGES = {
    "gcc", "libc6", "libc6-dev", "linux-libc-dev", "libasound2t64",
    "libasound2-dev", "python3",
}
KERNEL_VERSION = "6.12.107-1"
ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C",
    "DEBIAN_FRONTEND": "noninteractive", "TZ": "UTC",
}
PACKAGE_RE = re.compile(r"[a-z0-9][a-z0-9+.-]*\Z")
VERSION_RE = re.compile(r"[0-9][A-Za-z0-9.+:~\-]*\Z")


def fail(message: str):
    raise ValueError(message)


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path: Path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def load_json(path: Path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda value: fail(f"nonfinite JSON: {value}"))


def validate_image(reference: str, digest: str):
    if not reference.strip() or any(ord(c) < 32 for c in reference):
        fail("a parent-verified image reference is required")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        fail("a parent-verified raw-image sha256: digest is required")


def guard_guest(run_id: str, *, root: bool):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
        fail("invalid run-id")
    if sys.platform != "linux" or platform.machine() != "aarch64":
        fail("refusing: this program requires a Linux aarch64 guest")
    if (os.getuid() == 0) != root or (os.geteuid() == 0) != root:
        fail("root preparation required" if root else "verification must run unprivileged")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "debian" or release.get("VERSION_ID") != "13":
        fail("refusing: Debian VERSION_ID=13 required")
    info = MARKER.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        fail("parent guest marker must be a root-owned, non-writable regular file")
    if info.st_size > 65 or MARKER.read_bytes() not in (run_id.encode(), (run_id + "\n").encode()):
        fail("run-id does not match the parent-created guest marker")
    return release


def new_directory(path: Path, *, root: bool):
    if not path.is_absolute() or ".." in path.parts or path.exists() or path.is_symlink():
        fail("an absolute, new output directory without '..' is required")
    parent = path.parent
    if not parent.is_dir():
        fail("output parent must already exist")
    for part in (parent, *parent.parents):
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode):
            fail(f"symlink/non-directory output ancestor: {part}")
        if root and (info.st_uid != 0 or info.st_mode & 0o022):
            fail(f"root work parent must be root-owned and not group/world writable: {part}")
    path.mkdir(mode=0o755 if root else 0o700)


class Runner:
    def __init__(self, output: Path):
        self.logs = output / "logs"
        self.logs.mkdir(mode=0o755)
        self.counter = 0
        self.env = dict(ENV)

    def run(self, argv, *, timeout=60, cwd: Path | None = None, allowed=(0,)) -> str:
        argv = [str(value) for value in argv]
        self.counter += 1
        stem = self.logs / f"{self.counter:04d}"
        started = time.time()
        record = {"argv": argv, "cwd": str(cwd) if cwd else None,
                  "timeout_seconds": timeout, "started_unix": started,
                  "environment": dict(self.env), "returncode": None}
        with stem.with_suffix(".stdout").open("xb") as stdout, stem.with_suffix(".stderr").open("xb") as stderr:
            process = None
            completed = False
            try:
                process = subprocess.Popen(argv, cwd=cwd, env=self.env, stdin=subprocess.PIPE,
                                           stdout=stdout, stderr=stderr, start_new_session=True)
                process.stdin.close()
                record["returncode"] = process.wait(timeout=timeout)
                completed = True
            except (OSError, subprocess.SubprocessError) as exc:
                record["error"] = str(exc)
                raise
            finally:
                try:
                    if process is not None and not completed:
                        # Kill only our new process group, never by process name.
                        # Reap apt/dpkg descendants on a deadline or interrupt.
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        record["cleanup_returncode"] = process.wait(timeout=10)
                except (OSError, subprocess.SubprocessError) as exc:
                    record["cleanup_error"] = str(exc)
                    raise
                finally:
                    record["elapsed_seconds"] = time.time() - started
                    write_json(stem.with_suffix(".json"), record)
        if record["returncode"] not in allowed:
            fail(f"command failed ({record['returncode']}); inspect {stem}.stderr: {argv!r}")
        return stem.with_suffix(".stdout").read_text(encoding="utf-8")


def parse_control(text: str) -> list[dict[str, str]]:
    """Parse Debian binary control paragraphs, preserving continuation lines."""
    records = []
    current: dict[str, str] = {}
    key = None
    for line in text.splitlines() + [""]:
        if not line:
            if current:
                records.append(current)
                current = {}
            key = None
        elif line[0].isspace():
            if key is None:
                fail("control continuation without a field")
            current[key] += "\n" + line[1:]
        else:
            key, sep, value = line.partition(":")
            if not sep or not key or key in current:
                fail("malformed/duplicate Debian control field")
            current[key] = value.lstrip()
    return records


def installed_packages(run: Runner) -> dict[str, dict[str, str]]:
    fields = ["Package", "Version", "Architecture", "db:Status-Status", "Depends", "Pre-Depends", "Provides"]
    text = run.run(["/usr/bin/dpkg-query", "-W", "-f=" + "\t".join("${" + f + "}" for f in fields) + "\n"])
    records = {}
    for line in text.splitlines():
        values = line.split("\t")
        if len(values) != len(fields):
            fail("unexpected dpkg-query inventory format")
        item = dict(zip(fields, values))
        if item["db:Status-Status"] != "installed":
            continue
        name = item["Package"]
        if not PACKAGE_RE.fullmatch(name) or not VERSION_RE.fullmatch(item["Version"]):
            fail("invalid installed package identity")
        if item["Architecture"] not in ("all", "arm64") or name in records:
            fail("foreign/duplicate package architecture is outside this guest profile")
        records[name] = item
    return records


def check_base(packages):
    for name, version in BASE_PINS.items():
        if packages.get(name, {}).get("Version") != version:
            fail(f"base image pin mismatch: {name} must be {version}; no repair/upgrade")
    kernel = "linux-image-" + platform.release()
    if packages.get(kernel, {}).get("Version") != KERNEL_VERSION:
        fail(f"running kernel package {kernel} must be {KERNEL_VERSION}; no kernel changes")
    for name, version in INSTALL_PINS.items():
        if name in packages and packages[name]["Version"] != version:
            fail(f"installed {name} differs from required pin; no upgrade/downgrade permitted")
    return kernel


def snapshot_sources() -> str:
    options = f"arch=arm64 signed-by={KEYRING} check-valid-until=no"
    return "\n".join([
        f"deb [{options}] https://snapshot.debian.org/archive/debian/{SNAPSHOT}/ trixie main",
        f"deb [{options}] https://snapshot.debian.org/archive/debian/{SNAPSHOT}/ trixie-updates main",
        f"deb [{options}] https://snapshot.debian.org/archive/debian-security/{SNAPSHOT}/ trixie-security main",
        "",
    ])


def apt_options(work: Path) -> list[str]:
    options = {
        "Dir::Etc::sourcelist": str(work / "apt/sources.list"),
        "Dir::Etc::sourceparts": "-",
        "Dir::Etc::main": str(work / "apt/apt.conf"),
        "Dir::Etc::parts": str(work / "apt/conf.d"),
        "Dir::State::lists": str(work / "apt/lists"),
        "Dir::Cache::archives": str(work / "apt/archives"),
        "Dir::Cache::pkgcache": "", "Dir::Cache::srcpkgcache": "",
        "Acquire::Languages": "none", "Acquire::Retries": "2",
        "Acquire::http::Timeout": "30", "Acquire::https::Timeout": "30",
        "Acquire::AllowInsecureRepositories": "false",
        "Acquire::AllowDowngradeToInsecureRepositories": "false",
        "APT::Get::AllowUnauthenticated": "false",
        "APT::Get::Allow-Downgrades": "false",
        "APT::Get::Allow-Change-Held-Packages": "false",
        "APT::Get::List-Cleanup": "false", "APT::Update::Error-Mode": "any",
        "APT::Install-Recommends": "false", "APT::Install-Suggests": "false",
        "Dpkg::Use-Pty": "0", "DPkg::Lock::Timeout": "30",
    }
    return [part for key, value in options.items() for part in ("-o", f"{key}={value}")]


def freeze_automation(run: Runner):
    units = ("apt-daily.timer", "apt-daily-upgrade.timer", "apt-daily.service",
             "apt-daily-upgrade.service", "unattended-upgrades.service")
    before = {}
    for unit in units:
        before[unit] = run.run(["/usr/bin/systemctl", "show", unit, "--property=LoadState,ActiveState,UnitFileState"], allowed=(0, 1))
    run.run(["/usr/bin/systemctl", "mask", *units], timeout=60)
    # Stop only known loaded units; a base image may omit unattended-upgrades.
    for unit in units:
        if "LoadState=not-found" not in before[unit]:
            run.run(["/usr/bin/systemctl", "stop", unit], timeout=120)
    after = {}
    for unit in units:
        state = run.run(["/usr/bin/systemctl", "show", unit, "--property=LoadState,ActiveState,UnitFileState"])
        fields = dict(line.split("=", 1) for line in state.splitlines() if "=" in line)
        if fields.get("LoadState") != "masked" or fields.get("ActiveState") != "inactive":
            fail(f"automatic APT unit is not masked and inactive: {unit}")
        after[unit] = fields
    return {"before": before, "after": after}


def preserve_sources(work: Path):
    destination = work / "originals"
    destination.mkdir()
    for path in (Path("/etc/apt/sources.list"), *sorted(Path("/etc/apt/sources.list.d").glob("*"))):
        if not path.exists():
            continue
        if not path.is_file():
            fail(f"unexpected APT source entry: {path}")
        target = destination / path.relative_to("/etc/apt")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(path.read_bytes())
    shutil.copyfile(KEYRING, destination / KEYRING.name)


def parse_install_plan(text: str, installed) -> dict[str, str]:
    selected = {}
    for line in text.splitlines():
        if line.startswith(("Remv ", "Purg ")):
            fail("APT plan removes packages")
        if not line.startswith("Inst "):
            continue
        match = re.match(r"Inst ([a-z0-9][a-z0-9+.-]*)(?::arm64)?(?: \[[^\]]+\])? \(([^\s()]+)\s", line)
        if not match or not VERSION_RE.fullmatch(match[2]):
            fail(f"unrecognized APT install plan: {line}")
        name, version = match[1], match[2]
        if name.startswith(("linux-image", "linux-headers", "linux-modules")) or name == "dkms":
            fail(f"kernel/module package outside scope: {name}")
        if name in installed and installed[name]["Version"] != version:
            fail(f"APT plan would change installed {name}; no upgrade/downgrade")
        if name in selected and selected[name] != version:
            fail("conflicting APT plan versions")
        selected[name] = version
    return selected


def parse_relation(text: str):
    match = re.fullmatch(r"\s*([a-z0-9][a-z0-9+.-]*)(?::(any|native|arm64))?\s*(?:\((<<|<=|=|>=|>>)\s*([^\s()]+)\))?\s*", text)
    if not match or (match[4] and not VERSION_RE.fullmatch(match[4])):
        fail(f"unsupported binary dependency relation: {text!r}")
    return match[1], match[3], match[4]


def dependency_closure(roots, installed, compare) -> tuple[list[str], dict[str, list[str]]]:
    """Resolve Depends/Pre-Depends against actual installed packages/providers.

    Binary package relationships have no source architecture/profile conditions.
    Unsupported syntax fails instead of silently losing a closure edge.
    """
    providers = {}
    for name, item in installed.items():
        for relation in filter(None, item.get("Provides", "").split(",")):
            virtual, operator, version = parse_relation(relation)
            if operator not in (None, "="):
                fail("unexpected versioned Provides operator")
            providers.setdefault(virtual, []).append((name, version))
    pending = list(roots)
    selected = set()
    edges = {}
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        if name not in installed:
            fail(f"closure package is not installed: {name}")
        selected.add(name)
        dependencies = []
        item = installed[name]
        for group in filter(None, (item.get("Pre-Depends", "") + "," + item.get("Depends", "")).split(",")):
            chosen = None
            for alternative in group.split("|"):
                dependency, operator, version = parse_relation(alternative)
                candidates = []
                if dependency in installed:
                    candidates.append((dependency, installed[dependency]["Version"]))
                candidates.extend(sorted(providers.get(dependency, [])))
                for candidate, actual in candidates:
                    if operator is None or (actual is not None and compare(actual, operator, version)):
                        chosen = candidate
                        break
                if chosen:
                    break
            if chosen is None:
                fail(f"no installed dependency satisfies {name}: {group}")
            dependencies.append(chosen)
            pending.append(chosen)
        edges[name] = sorted(set(dependencies))
    return sorted(selected), edges


def package_record(text: str, name: str, version: str, architecture: str):
    matches = []
    required = {"Package", "Version", "Architecture", "Filename", "Size", "SHA256"}
    for item in parse_control(text):
        if not required <= item.keys():
            continue
        if (item["Package"], item["Version"], item["Architecture"]) == (name, version, architecture):
            if not re.fullmatch(r"[0-9a-f]{64}", item["SHA256"]) or not item["Size"].isdigit() or int(item["Size"]) <= 0:
                fail("invalid signed package artifact identity")
            filename = Path(item["Filename"])
            if filename.is_absolute() or ".." in filename.parts or not item["Filename"].startswith("pool/"):
                fail("invalid package archive Filename")
            matches.append(item)
    if not matches:
        fail(f"no signed snapshot metadata for {name}={version}/{architecture}")
    identities = {tuple(item[field] for field in sorted(required)) for item in matches}
    if len(identities) != 1:
        fail(f"ambiguous signed package metadata for {name}")
    return matches[0]


def artifact_manifest(work: Path):
    files = {}
    for directory, dirs, names in os.walk(work, followlinks=False):
        current = Path(directory)
        if not stat.S_ISDIR(current.lstat().st_mode):
            fail(f"non-directory evidence path: {current}")
        if os.geteuid() == 0:
            os.chown(current, 0, 0)
            current.chmod(0o755)
        dirs[:] = sorted(d for d in dirs if d not in ("partial", "auxfiles"))
        for name in dirs:
            if not stat.S_ISDIR((current / name).lstat().st_mode):
                fail(f"symlink/non-directory evidence artifact: {current / name}")
        for name in sorted(names):
            path = Path(directory) / name
            if name == "lock" or path == work / "artifact-manifest.json":
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                fail(f"unexpected non-regular evidence artifact: {path}")
            if os.geteuid() == 0:
                # APT download helpers can leave _apt ownership; final evidence
                # belongs to root and is readable by the verification account.
                os.chown(path, 0, 0)
                path.chmod(0o644)
            files[str(path.relative_to(work))] = {"sha256": sha256(path), "size": info.st_size}
    value = {"schema": "poseidon.linux-capture-environment-artifacts.v1", "files": files}
    write_json(work / "artifact-manifest.json", value)
    return value


def prepare(args):
    release = guard_guest(args.run_id, root=True)
    validate_image(args.image_reference, args.image_digest)
    os.umask(0o022)
    new_directory(args.work_dir, root=True)
    work = args.work_dir
    try:
        run = Runner(work)
        installed_before = installed_packages(run)
        kernel_package = check_base(installed_before)
        automation = freeze_automation(run)
        preserve_sources(work)
        for directory in ("apt", "apt/conf.d", "apt/lists", "apt/archives", "package-metadata"):
            (work / directory).mkdir()
        (work / "apt/sources.list").write_text(snapshot_sources(), encoding="utf-8")
        (work / "apt/apt.conf").write_text(
            "// Read through APT_CONFIG before APT's global configuration phase.\n"
            + "Dir::Etc::main " + json.dumps(str(work / "apt/apt.conf")) + ";\n"
            + "Dir::Etc::parts " + json.dumps(str(work / "apt/conf.d")) + ";\n",
            encoding="utf-8")
        run.env["APT_CONFIG"] = str(work / "apt/apt.conf")
        options = apt_options(work)
        apt = ["/usr/bin/apt-get", *options]
        cache = ["/usr/bin/apt-cache", *options]
        run.run([*apt, "update"], timeout=900)
        retained = [p.name for p in (work / "apt/lists").iterdir() if p.is_file()]
        for suite in ("trixie", "trixie-updates", "trixie-security"):
            if not any(name.endswith(f"_dists_{suite}_InRelease") for name in retained):
                fail(f"missing authenticated InRelease for {suite}")
        if not any("_binary-arm64_Packages" in name for name in retained):
            fail("missing ARM64 package indices")
        policy = run.run([*cache, "policy", "gcc"])
        candidates = re.findall(r"^\s*Candidate:\s*(\S+)\s*$", policy, flags=re.MULTILINE)
        if len(candidates) != 1 or not VERSION_RE.fullmatch(candidates[0]):
            fail("gcc exact meta-package version not resolved from pinned APT metadata")
        pins = {**INSTALL_PINS, "gcc": candidates[0]}
        if "gcc" in installed_before and installed_before["gcc"]["Version"] != pins["gcc"]:
            fail("installed gcc meta-package differs from snapshot; no upgrade/downgrade")
        for name, version in pins.items():
            architecture = "all" if name == "linux-libc-dev" else "arm64"
            package_record(run.run([*cache, "show", f"{name}={version}"]), name, version, architecture)
        requested = [f"{name}={version}" for name, version in sorted(pins.items())]
        install = ["--yes", "--no-remove", "--no-upgrade", "--no-install-recommends", "install", *requested]
        plan = parse_install_plan(run.run([*apt, "--simulate", *install], timeout=120), installed_before)
        run.run([*apt, "--download-only", *install], timeout=1200)
        # Recheck the plan after downloads and prohibit network acquisition during
        # installation. The dedicated lists/config remain unchanged throughout.
        if parse_install_plan(run.run([*apt, "--simulate", *install], timeout=120), installed_before) != plan:
            fail("APT install plan changed after download")
        run.run([*apt, "--no-download", *install], timeout=900)
        installed_after = installed_packages(run)
        for name, item in installed_before.items():
            if installed_after.get(name, {}).get("Version") != item["Version"]:
                fail(f"installer changed/removed pre-existing {name}")
        for name, version in {**pins, **plan}.items():
            if installed_after.get(name, {}).get("Version") != version:
                fail(f"installed version mismatch: {name}")
        unexpected = set(installed_after) - set(installed_before) - set(plan)
        if unexpected:
            fail(f"unplanned package installation: {sorted(unexpected)}")
        check_base(installed_after)

        comparisons = {}
        def compare(actual, operator, wanted):
            key = (actual, operator, wanted)
            if key not in comparisons:
                run.run(["/usr/bin/dpkg", "--compare-versions", actual, operator, wanted], allowed=(0, 1), timeout=10)
                record = load_json(run.logs / f"{run.counter:04d}.json")
                comparisons[key] = record["returncode"] == 0
            return comparisons[key]
        closure, edges = dependency_closure(set(pins) | set(plan), installed_after, compare)
        inputs = {}
        archives = work / "apt/archives"
        archive_hashes = {sha256(p): p for p in archives.glob("*.deb")}
        for name in closure:
            item = installed_after[name]
            raw = run.run([*cache, "show", f"{name}={item['Version']}"])
            metadata = package_record(raw, name, item["Version"], item["Architecture"])
            (work / "package-metadata" / f"{name}.control").write_text(raw, encoding="utf-8")
            expected = metadata["SHA256"]
            if expected not in archive_hashes:
                run.run([*apt, "download", f"{name}={item['Version']}"], cwd=archives, timeout=300)
                archive_hashes = {sha256(p): p for p in archives.glob("*.deb")}
            artifact = archive_hashes.get(expected)
            if artifact is None or artifact.stat().st_size != int(metadata["Size"]):
                fail(f"download hash/size mismatch: {name}")
            deb = parse_control(run.run(["/usr/bin/dpkg-deb", "--field", artifact, "Package", "Version", "Architecture"]))
            if len(deb) != 1 or any(deb[0].get(field) != metadata[field] for field in ("Package", "Version", "Architecture")):
                fail(f"downloaded .deb identity mismatch: {name}")
            inputs[name] = {field: metadata[field] for field in ("Package", "Version", "Architecture", "Filename", "SHA256")}
            inputs[name].update({"Size": int(metadata["Size"]), "artifact": str(artifact.relative_to(work)),
                                 "metadata": f"package-metadata/{name}.control", "dependencies": edges[name]})
        known = {item["SHA256"] for item in inputs.values()}
        if set(archive_hashes) - known:
            fail("unidentified downloaded package input")
        compiler_target = run.run(["/usr/bin/gcc", "-dumpmachine"], timeout=10).strip()
        if compiler_target != "aarch64-linux-gnu":
            fail("compiler target must be aarch64-linux-gnu")
        package_inputs = {"schema": "poseidon.linux-capture-package-inputs.v1",
                          "snapshot": SNAPSHOT, "roots": pins, "install_plan": plan,
                          "packages": inputs, "dependency_kinds": ["Depends", "Pre-Depends"],
                          "recommendations_installed": False}
        write_json(work / "package-inputs.json", package_inputs)
        result = {"schema": "poseidon.linux-capture-preparation.v1", "run_id": args.run_id,
                  "image_reference": args.image_reference, "image_digest": args.image_digest,
                  "image_digest_provenance": "parent-provided digest of verified raw image; not recomputed in guest",
                  "snapshot": SNAPSHOT, "os_release": release, "uname": platform.uname()._asdict(),
                  "python_version": platform.python_version(), "kernel_package": kernel_package,
                  "compiler_target": compiler_target, "installed_before": installed_before,
                  "installed_after": installed_after, "automation": automation,
                  "apt_sources_scope": "isolated sources; originals preserved and system sources unchanged",
                  "signatures_required": True, "check_valid_until_disabled_only_for_frozen_snapshots": True,
                  "keyring_sha256": sha256(KEYRING), "script_sha256": sha256(Path(__file__).resolve()),
                  "device_access_occurred": False, "hardware_qualified": False}
        write_json(work / "preparation.json", result)
        artifact_manifest(work)
        print(json.dumps({"prepared": str(work), "preparation": str(work / "preparation.json"),
                          "artifact_manifest": str(work / "artifact-manifest.json")}, sort_keys=True))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        write_json(work / "failure.json", {"error": str(exc), "run_id": args.run_id})
        raise


def main(argv=None):
    # Let an aggregate guest deadline unwind Runner's exact child-group cleanup
    # and retain failure.json instead of abandoning a separately-sessioned APT.
    def interrupted(signum, _frame):
        raise InterruptedError(f"guest preparation interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--image-reference", required=True)
    parser.add_argument("--image-digest", required=True)
    args = parser.parse_args(argv)
    try:
        prepare(args)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"guest preparation refused/failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
