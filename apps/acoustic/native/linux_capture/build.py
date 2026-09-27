#!/usr/bin/env python3
"""Explicit pinned Linux build, without package installation or device probes.

The separately provisioned profile is data, not a generated dependency lock.
Missing/mismatched pins fail before compilation. Output must not already exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

SCHEMA = "poseidon.linux-capture-native-profile.v1"
SOURCE_NAMES = ("capture_abi.h", "capture_internal.h", "capture_common.c", "alsa_capture.c", "v4l2_capture.c", "build.py")
REQUIRED_PACKAGES = {"libasound2t64", "libasound2-dev", "linux-libc-dev", "libc6", "libc6-dev", "gcc", "python3"}
REQUIRED_FIELDS = {"schema", "image_reference", "image_digest", "architecture", "os_id", "os_version", "kernel_release", "compiler_path", "compiler_version", "python_version", "packages", "files", "alsa_library", "libc_library", "uapi_header", "alsa_header"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def fail(message):
    raise ValueError(message)


def load_profile(path: Path):
    if not path.is_absolute() or not path.is_file():
        fail("an existing absolute native profile is required; no repair/install is permitted")
    raw = path.read_bytes()
    if not 0 < len(raw) <= 1024 * 1024:
        fail("profile size bound")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("duplicate native profile key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: fail("nonfinite profile"))
    if type(value) is not dict or set(value) != REQUIRED_FIELDS or value["schema"] != SCHEMA:
        fail("native profile schema/fields mismatch")
    for key in REQUIRED_FIELDS - {"files", "packages"}:
        if type(value[key]) is not str or not value[key].strip():
            fail(f"explicit profile {key} required")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value["image_digest"]):
        fail("real immutable provisioned image digest required")
    if value["os_id"] != "debian" or value["os_version"] != "13" or value["architecture"] != "aarch64":
        fail("only the selected Debian 13 ARM64 development profile is admitted")
    if value["alsa_header"] != "/usr/include/alsa/asoundlib.h" or value["uapi_header"] != "/usr/include/linux/videodev2.h":
        fail("profile must pin the actual default ALSA/Linux include paths used by this build")
    if sys.platform != "linux" or platform.machine() != value["architecture"] or sys.byteorder != "little":
        fail("Linux ARM64 little-endian environment required; host fakes are a separate test")
    if platform.release() != value["kernel_release"] or platform.python_version() != value["python_version"]:
        fail("kernel/Python identity mismatch")
    os_release = platform.freedesktop_os_release()
    if os_release.get("ID") != value["os_id"] or os_release.get("VERSION_ID") != value["os_version"]:
        fail("OS identity mismatch")
    packages = value["packages"]
    if type(packages) is not dict or not REQUIRED_PACKAGES <= set(packages):
        fail("explicit runtime/development/compiler/Python package versions required")
    for name, version in packages.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?", name) or type(version) is not str or not version:
            fail("package identity invalid")
        result = subprocess.run(["/usr/bin/dpkg-query", "-W", "-f=${Version}", name], check=True, text=True, capture_output=True, timeout=10)
        if result.stdout != version:
            fail(f"package pin mismatch: {name}")
    files = value["files"]
    if type(files) is not dict or not 4 <= len(files) <= 10000:
        fail("explicit dependency artifact hashes required")
    for key in ("compiler_path", "alsa_library", "libc_library", "uapi_header", "alsa_header"):
        if value[key] not in files:
            fail(f"missing artifact hash for {key}")
    for name, expected in files.items():
        file = Path(name)
        if not file.is_absolute() or ".." in file.parts or type(expected) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected):
            fail("invalid absolute dependency artifact/hash")
        if not file.is_file() or digest(file.read_bytes()) != expected:
            fail(f"dependency artifact pin mismatch: {name}")
    compiler = subprocess.run([value["compiler_path"], "--version"], check=True, capture_output=True, text=True, timeout=10)
    if compiler.stdout != value["compiler_version"]:
        fail("compiler version pin mismatch")
    return value, digest(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        profile, profile_hash = load_profile(args.native_profile)
        if not args.output.is_absolute() or args.output.exists():
            fail("new absolute owned output directory required")
        source_dir = Path(__file__).resolve().parent
        sources = {name: digest((source_dir / name).read_bytes()) for name in SOURCE_NAMES}
        flags = ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared", "-D_FILE_OFFSET_BITS=64", "-Wl,-z,defs", "-Wl,-z,relro,-z,now", "-Wl,-soname,libposeidon_linux_capture.so"]
        build_hash = digest(canonical({"profile_sha256": profile_hash, "sources": sources, "flags": flags}))
        args.output.mkdir(parents=False, exist_ok=False)
        artifact = args.output / "libposeidon_linux_capture.so"
        command = [profile["compiler_path"], *flags, f'-DPT_BUILD_SHA256="{build_hash}"', f'-DPT_PROFILE_SHA256="{profile_hash}"', "-o", str(artifact), *(str(source_dir / name) for name in ("capture_common.c", "alsa_capture.c", "v4l2_capture.c")), profile["alsa_library"]]
        # Fixed flags, clean loader/compiler environment; never consult user CFLAGS or LD_PRELOAD.
        env = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
        subprocess.run(command, check=True, timeout=120, env=env)
        result = {"schema": "poseidon.linux-capture-build.v1", "artifact": str(artifact),
                  "artifact_sha256": digest(artifact.read_bytes()), "build_sha256": build_hash,
                  "profile_sha256": profile_hash, "sources": sources, "command": command,
                  "artifact_kind": "production-linux", "device_access_occurred": False,
                  "linux_compile_link_completed": True, "linux_abi_verified": False,
                  "hardware_qualified": False}
        (args.output / "build.json").write_bytes(canonical(result))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"native build refused/failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
