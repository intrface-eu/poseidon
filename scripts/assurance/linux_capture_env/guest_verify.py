#!/usr/bin/env python3
"""Unprivileged, no-device Linux ABI smoke and exact native-profile collection.

Transfer this file beside guest_prepare.py and abi_smoke.c. This does not build
or test Acquisition's production shim; its build.py and tests remain a separate
gate. The image identity is supplied by the parent that verified the raw image.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import os
import platform
import re
import stat
import struct
import subprocess
import sys

# Importing the helper must not emit a cache beside transferred source inputs.
sys.dont_write_bytecode = True
from guest_prepare import (  # noqa: E402
    KEYRING, PROFILE_SCHEMA, REQUIRED_PACKAGES, SNAPSHOT, Runner, artifact_manifest,
    check_base, fail, guard_guest, installed_packages, load_json, new_directory,
    sha256, validate_image, write_json,
)

NATIVE_FIELDS = {
    "schema", "image_reference", "image_digest", "architecture", "os_id",
    "os_version", "kernel_release", "compiler_path", "compiler_version",
    "python_version", "packages", "files", "alsa_library", "libc_library",
    "uapi_header", "alsa_header",
}


def trusted_file(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        fail(f"preparation artifact must be root-owned and not writable: {path}")
    return info


def checked_relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        fail("invalid relative artifact path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        fail("invalid relative artifact path")
    return path


def verify_preparation(work: Path, run_id: str, image_reference: str, image_digest: str):
    if not work.is_absolute() or ".." in work.parts:
        fail("prepared directory must be absolute and without '..'")
    for path in (work, *work.parents):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            fail(f"prepared directory ancestry is not root-owned/non-writable: {path}")
    manifest_path = work / "artifact-manifest.json"
    trusted_file(manifest_path)
    manifest = load_json(manifest_path)
    if manifest.get("schema") != "poseidon.linux-capture-environment-artifacts.v1" or not isinstance(manifest.get("files"), dict):
        fail("preparation artifact manifest schema mismatch")
    for name, expected in manifest["files"].items():
        path = work / checked_relative(name)
        # Check every interior directory rather than following a substituted link.
        parent = path.parent
        while parent != work:
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                fail(f"untrusted artifact directory: {parent}")
            parent = parent.parent
        info = trusted_file(path)
        if not isinstance(expected, dict) or set(expected) != {"sha256", "size"}:
            fail("artifact hash/size record required")
        if type(expected["size"]) is not int or expected["size"] < 0 or not isinstance(expected["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]):
            fail("invalid artifact hash/size")
        if info.st_size != expected["size"] or sha256(path) != expected["sha256"]:
            fail(f"preparation artifact hash/size mismatch: {name}")
    for required in ("preparation.json", "package-inputs.json", "apt/sources.list", "originals/" + KEYRING.name):
        if required not in manifest["files"]:
            fail(f"missing preparation artifact: {required}")
    prepared = load_json(work / "preparation.json")
    if prepared.get("schema") != "poseidon.linux-capture-preparation.v1" or prepared.get("run_id") != run_id:
        fail("preparation schema/run-id mismatch")
    if prepared.get("image_reference") != image_reference or prepared.get("image_digest") != image_digest:
        fail("image identity differs from the root preparation record")
    if prepared.get("snapshot") != SNAPSHOT or prepared.get("signatures_required") is not True:
        fail("signed frozen snapshot preparation required")
    if prepared.get("keyring_sha256") != sha256(KEYRING):
        fail("APT signing keyring changed after preparation")
    package_inputs = load_json(work / "package-inputs.json")
    if package_inputs.get("schema") != "poseidon.linux-capture-package-inputs.v1" or package_inputs.get("snapshot") != SNAPSHOT:
        fail("package-input schema/snapshot mismatch")
    packages = package_inputs.get("packages")
    if not isinstance(packages, dict) or not REQUIRED_PACKAGES <= packages.keys():
        fail("required reproducible package inputs missing")
    for name, item in packages.items():
        if not isinstance(item, dict) or item.get("Package") != name:
            fail("invalid package input record")
        artifact = str(checked_relative(item.get("artifact")))
        metadata = str(checked_relative(item.get("metadata")))
        expected = manifest["files"].get(artifact)
        if expected != {"sha256": item.get("SHA256"), "size": item.get("Size")} or metadata not in manifest["files"]:
            fail(f"package archive/metadata not bound by preparation manifest: {name}")
    return prepared, package_inputs, manifest


def parse_dependencies(text: str) -> list[str]:
    """Read GCC -MD's one Make rule, including escaped spaces and continuations."""
    text = text.replace("\\\n", "")
    escaped = False
    separator = None
    for index, character in enumerate(text):
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            separator = index
            break
    if separator is None:
        fail("missing dependency rule separator")
    words = []
    word = []
    escaped = False
    for character in text[separator + 1:]:
        if escaped:
            word.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character.isspace():
            if word:
                words.append("".join(word).replace("$$", "$"))
                word = []
        else:
            word.append(character)
    if escaped:
        fail("truncated dependency escape")
    if word:
        words.append("".join(word).replace("$$", "$"))
    if not words:
        fail("empty compiler dependency rule")
    return words


def parse_ldd(text: str) -> dict[str, str]:
    libraries = {}
    for line in text.splitlines():
        if "not found" in line:
            fail("linked runtime dependency not found")
        match = re.fullmatch(r"\s*(\S+)\s+=>\s+(/\S+)\s+\(0x[0-9a-fA-F]+\)\s*", line)
        if match:
            if match[1] in libraries and libraries[match[1]] != match[2]:
                fail("duplicate runtime library identity")
            libraries[match[1]] = match[2]
            continue
        loader = re.fullmatch(r"\s*(/\S+)\s+\(0x[0-9a-fA-F]+\)\s*", line)
        if loader:
            libraries[Path(loader[1]).name] = loader[1]
            continue
        if re.fullmatch(r"\s*linux-vdso\.so\.\d+\s+\(0x[0-9a-fA-F]+\)\s*", line):
            continue
        if line.strip():
            fail(f"unrecognized linked library record: {line}")
    if not {"libasound.so.2", "libc.so.6"} <= libraries.keys():
        fail("smoke must link the actual ALSA and libc shared libraries")
    return libraries


def add_file(files: dict[str, str], paths: dict[str, str], path: Path):
    if not path.is_absolute() or not path.is_file():
        fail(f"missing absolute dependency artifact: {path}")
    # Normalize '..' returned by GCC; preserve the requested symlink identity as
    # well when it is already a normalized path acceptable to build.py.
    absolute = Path(os.path.abspath(path))
    resolved = absolute.resolve(strict=True)
    if not resolved.is_file():
        fail(f"dependency target is not a regular file: {resolved}")
    files[str(absolute)] = sha256(absolute)
    files[str(resolved)] = sha256(resolved)
    paths[str(absolute)] = str(resolved)
    return str(absolute)


def system_header(path: Path) -> bool:
    # These five dependencies were observed in GCC's real headers.d and bound
    # to the retained signed Debian13 linux-libc-dev:all package file list.
    arm64_uapi = {
        "/usr/lib/linux/uapi/arm64/asm/errno.h",
        "/usr/lib/linux/uapi/arm64/asm/ioctl.h",
        "/usr/lib/linux/uapi/arm64/asm/types.h",
        "/usr/lib/linux/uapi/arm64/asm/bitsperlong.h",
        "/usr/lib/linux/uapi/arm64/asm/posix_types.h",
    }
    return path.is_absolute() and ".." not in path.parts and (
        str(path) in arm64_uapi or str(path).startswith((
            "/usr/include/", "/usr/lib/gcc/", "/usr/aarch64-linux-gnu/include/",
        ))
    )


def compiler_file(run: Runner, compiler: str, option: str) -> Path:
    value = run.run([compiler, option], timeout=10).strip()
    path = Path(value)
    if not path.is_absolute():
        # GCC often reports 'as'/'ld'; resolve only inside the fixed system PATH.
        if path.name != value or not value:
            fail(f"compiler reported an unresolved artifact: {option}: {value!r}")
        for directory in ("/usr/bin", "/bin"):
            candidate = Path(directory) / value
            if candidate.is_file():
                path = candidate
                break
    if not path.is_absolute() or not path.is_file():
        fail(f"compiler dependency not found: {option}: {value!r}")
    return path


def verify(args):
    release = guard_guest(args.run_id, root=False)
    validate_image(args.image_reference, args.image_digest)
    if sys.byteorder != "little":
        fail("selected native build requires little-endian ARM64")
    prepared, package_inputs, preparation_manifest = verify_preparation(
        args.prepared, args.run_id, args.image_reference, args.image_digest)
    os.umask(0o077)
    new_directory(args.output, root=False)
    output = args.output
    try:
        run = Runner(output)
        installed = installed_packages(run)
        kernel_package = check_base(installed)
        if installed != prepared.get("installed_after"):
            fail("installed package inventory changed since preparation")
        if platform.release() != prepared.get("uname", {}).get("release") or platform.python_version() != prepared.get("python_version"):
            fail("runtime kernel/Python changed since preparation")
        packages = {}
        for name, item in package_inputs["packages"].items():
            if (installed.get(name, {}).get("Version"), installed.get(name, {}).get("Architecture")) != (item.get("Version"), item.get("Architecture")):
                fail(f"current package differs from retained archive: {name}")
            packages[name] = item["Version"]
        compiler = "/usr/bin/gcc"
        target = run.run([compiler, "-dumpmachine"], timeout=10).strip()
        if target != "aarch64-linux-gnu":
            fail("compiler target must be aarch64-linux-gnu")
        compiler_version = run.run([compiler, "--version"], timeout=10)
        compiler_full_version = run.run([compiler, "-dumpfullversion"], timeout=10).strip()
        source = Path(__file__).resolve().with_name("abi_smoke.c")
        if not source.is_file():
            fail("abi_smoke.c must be transferred beside guest_verify.py")
        source_digest = sha256(source)
        binary = output / "abi-smoke"
        dependencies = output / "headers.d"
        flags = ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-D_FILE_OFFSET_BITS=64",
                 "-D_POSIX_C_SOURCE=200809L", "-MD", "-MF", str(dependencies),
                 "-Wl,-z,defs", "-Wl,-z,relro,-z,now"]
        command = [compiler, *flags, "-o", str(binary), str(source), "-lasound"]
        run.run(command, cwd=output, timeout=120)
        if sha256(source) != source_digest:
            fail("ABI source changed during compilation")
        smoke_text = run.run([str(binary)], cwd=output, timeout=10)
        # Keep exact runtime stdout separately from the command log.
        with (output / "abi-smoke.json").open("x", encoding="utf-8") as stream:
            stream.write(smoke_text)
        smoke = load_json(output / "abi-smoke.json")
        if smoke.get("schema") != "poseidon.linux-capture-abi-smoke.v1":
            fail("ABI smoke JSON schema mismatch")
        if smoke.get("pointer_size") != struct.calcsize("P") or smoke.get("endianness") != sys.byteorder:
            fail("compiled pointer/byte-order observation disagrees with Python runtime")
        if smoke.get("device_access_occurred") is not False or smoke.get("hardware_qualified") is not False:
            fail("unexpected device/qualification claims in smoke")
        if not isinstance(smoke.get("alsa_runtime_version"), str) or not smoke["alsa_runtime_version"]:
            fail("actual ALSA runtime version missing")
        libraries = parse_ldd(run.run(["/usr/bin/ldd", binary], timeout=10))
        files: dict[str, str] = {}
        paths: dict[str, str] = {}
        add_file(files, paths, Path(compiler))
        for path in libraries.values():
            add_file(files, paths, Path(path))
        compiler_artifacts = {}
        for key, option in (
            ("cc1", "-print-prog-name=cc1"), ("collect2", "-print-prog-name=collect2"),
            ("assembler", "-print-prog-name=as"), ("linker", "-print-prog-name=ld"),
            ("libgcc", "-print-libgcc-file-name"), ("alsa_link_input", "-print-file-name=libasound.so"),
            ("libc_link_input", "-print-file-name=libc.so"),
            ("crt1", "-print-file-name=Scrt1.o"), ("crti", "-print-file-name=crti.o"),
            ("crtbegin", "-print-file-name=crtbeginS.o"), ("crtend", "-print-file-name=crtendS.o"),
            ("crtn", "-print-file-name=crtn.o"),
        ):
            compiler_artifacts[key] = add_file(files, paths, compiler_file(run, compiler, option))
        headers = []
        for name in parse_dependencies(dependencies.read_text(encoding="utf-8")):
            path = Path(name)
            if not path.is_absolute():
                path = output / path
            path = Path(os.path.abspath(path))
            if path == source:
                continue
            if not system_header(path):
                fail(f"unexpected non-system header dependency: {path}")
            headers.append(add_file(files, paths, path))
        alsa_header = "/usr/include/alsa/asoundlib.h"
        uapi_header = "/usr/include/linux/videodev2.h"
        if not {alsa_header, uapi_header} <= set(headers):
            fail("compiler did not use the required actual ALSA/V4L2 default headers")
        add_file(files, paths, Path(sys.executable))
        add_file(files, paths, KEYRING)
        profile = {
            "schema": PROFILE_SCHEMA, "image_reference": args.image_reference,
            "image_digest": args.image_digest, "architecture": platform.machine(),
            "os_id": release["ID"], "os_version": release["VERSION_ID"],
            "kernel_release": platform.release(), "compiler_path": compiler,
            "compiler_version": compiler_version, "python_version": platform.python_version(),
            "packages": dict(sorted(packages.items())), "files": dict(sorted(files.items())),
            "alsa_library": libraries["libasound.so.2"], "libc_library": libraries["libc.so.6"],
            "uapi_header": uapi_header, "alsa_header": alsa_header,
        }
        if set(profile) != NATIVE_FIELDS:
            fail("internal native-profile field mismatch")
        for path, expected in files.items():
            if sha256(Path(path)) != expected:
                fail(f"dependency changed while collecting profile: {path}")
        write_json(output / "native-profile.json", profile)
        if (output / "native-profile.json").stat().st_size > 1024 * 1024:
            fail("native-profile exceeds Acquisition build.py size bound")
        environment = {
            "schema": "poseidon.linux-capture-environment.v1", "run_id": args.run_id,
            "image_reference": args.image_reference, "image_digest": args.image_digest,
            "image_digest_provenance": prepared["image_digest_provenance"],
            "snapshot": SNAPSHOT, "uid": os.getuid(), "euid": os.geteuid(),
            "os_release": release, "uname": platform.uname()._asdict(),
            "kernel_package": kernel_package, "kernel_package_version": installed[kernel_package]["Version"],
            "python_executable": sys.executable, "python_version": sys.version,
            "compiler_target": target, "compiler_version": compiler_version,
            "compiler_full_version": compiler_full_version,
            "compiler_artifacts": compiler_artifacts, "resolved_files": paths,
            "glibc_runtime_version": run.run(["/usr/bin/getconf", "GNU_LIBC_VERSION"], timeout=10).strip(),
            "ldd_version": run.run(["/usr/bin/ldd", "--version"], timeout=10),
            "runtime_libraries": libraries, "system_headers": sorted(set(headers)),
            "installed_packages": installed, "abi": smoke, "compile_command": command,
            "sources": {name: sha256(Path(__file__).resolve().with_name(name)) for name in ("guest_prepare.py", "guest_verify.py", "abi_smoke.c")},
            "prepared_directory": str(args.prepared),
            "preparation_manifest_sha256": sha256(args.prepared / "artifact-manifest.json"),
            "verified_preparation_artifact_count": len(preparation_manifest["files"]),
            "native_profile_sha256": sha256(output / "native-profile.json"),
            "abi_smoke_sha256": sha256(binary), "linux_compile_link_completed": True,
            "linux_no_device_abi_smoke_executed": True, "production_shim_built": False,
            "production_shim_tests_executed": False, "device_access_occurred": False,
            "hardware_qualified": False,
        }
        write_json(output / "environment.json", environment)
        artifact_manifest(output)
        print(str(output / "native-profile.json"))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        write_json(output / "failure.json", {"error": str(exc), "run_id": args.run_id})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-reference", required=True)
    parser.add_argument("--image-digest", required=True)
    args = parser.parse_args(argv)
    try:
        verify(args)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"guest verification refused/failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
