"""Check an existing paired monitor build; never build, flash or run firmware.

Evidence is verbose app_main compiler flags, ELF metadata and linked text symbols.
It is NOT an initializer/data-flow proof, build-provenance attestation or target
execution. The caller must build both profiles successfully in fresh, distinct
build/sdkconfig roots before invoking this checker. compile_commands.json is not
read: CMake omits the PlatformIO-injected persistence define there.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import stat
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
APP_SOURCE = ROOT / "firmware/monitor-target/src/main.cpp"
MACRO = "POSEIDON_MONITOR_PERSISTED"
TOOLCHAIN = "toolchain-xtensa-esp-elf"
TOOLCHAIN_VERSION = "13.2.0+20240530"
MAX_ELF_BYTES = 32 * 1024 * 1024
MAX_BIN_BYTES = 4 * 1024 * 1024
MAX_CONFIG_BYTES = 1024 * 1024
MAX_LOG_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 128 * 1024
MAX_TOOL_BYTES = 64 * 1024 * 1024
MAX_TOOL_OUTPUT = 4 * 1024 * 1024
MAX_DISASSEMBLY_BYTES = 64 * 1024
TOOL_TIMEOUT = 15.0
MANUAL_DISASSEMBLY_SYMBOLS = {
    "initializer": "_Z41__static_initialization_and_destruction_0v",
    "app_main": "app_main",
}
REQUIRED_TEXT_SYMBOLS = (
    "app_main",
    "poseidon::reef::MonitorTask::start(poseidon::reef::Config)",
    "poseidon::reef::NvsBootIdentity::allocate_boot(unsigned long long&)",
    "poseidon::reef::NvsBootIdentity::open_existing(poseidon::reef::PartitionSpec const&)",
    "poseidon::reef::(anonymous namespace)::worker_entry(void*)",
    "nvs_set_blob",
    "nvs_commit",
    "esp_timer_start_once",
)
LIMITATIONS = [
    "Compiler-log flags and linked text symbols only; initializer/member semantics and app_main call flow are not automatically verified.",
    "Manual initializer review must be tied to the current ELF and source/layout; old addresses or registers are not proof for a new build.",
    "Freshness, successful compiler execution and log/artifact provenance are caller obligations, not established by hashes or timestamps.",
    "No target execution, NVS persistence/power-cut, scheduling, sensor, radio, safety or field qualification evidence.",
]


class CheckError(ValueError):
    """Evidence is missing, unsupported, contradictory or outside bounds."""


class InspectionInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"vendor inspection interrupted by signal {signum}")


INSPECTION_SIGNALS = (signal.SIGINT, signal.SIGTERM)


def restore_handlers(previous: dict) -> None:
    # A restored caller handler may raise. Deliver queued signals only after
    # BOTH handlers have been restored, never halfway through restoration.
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, INSPECTION_SIGNALS)
    try:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)


def strict_manifest(data: bytes) -> dict:
    def unique_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise CheckError(f"duplicate toolchain manifest field: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise CheckError(f"nonfinite toolchain manifest number: {value}")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise CheckError("nonfinite toolchain manifest number")
        return number

    try:
        result = json.loads(decode_text(data), object_pairs_hook=unique_object, parse_constant=reject_constant, parse_float=finite_float)
    except (ValueError, RecursionError) as exc:
        raise CheckError(f"invalid toolchain manifest: {exc}") from exc
    if not isinstance(result, dict):
        raise CheckError("toolchain manifest must be an object")
    return result


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_regular(path: Path, limit: int) -> bytes:
    """Reject symlinks and special files before reading; reject concurrent changes."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise CheckError(f"not a regular non-symlink file: {path}")
    if not 0 < before.st_size <= limit:
        raise CheckError(f"empty or exceeds size limit ({limit} bytes): {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        if _identity(before) != _identity(opened) or not stat.S_ISREG(opened.st_mode):
            raise CheckError(f"file changed while opening: {path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) != before.st_size or _identity(before) != _identity(os.fstat(fd)):
            raise CheckError(f"file changed while reading: {path}")
        if _identity(before) != _identity(path.lstat()):
            raise CheckError(f"file replaced while reading: {path}")
        return data
    finally:
        os.close(fd)


def directory(path: Path) -> Path:
    # /tmp is an OS alias on macOS; reject the supplied directory itself and
    # every child we traverse, but do not prohibit that ancestor alias.
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise CheckError(f"not a non-symlink directory: {path}")
    return path.resolve(strict=True)


def digest(path: Path, data: bytes) -> dict:
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def decode_text(data: bytes) -> str:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise CheckError("unsupported non-UTF-8 record") from exc
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise CheckError("unsupported control character in record")
    if any(len(line.encode("utf-8")) > MAX_LINE_BYTES for line in text.splitlines()):
        raise CheckError("record exceeds line size limit")
    return text


def check_elf_header(data: bytes) -> dict:
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise CheckError("expected ELF32 little-endian version-1 header")
    fields = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
    kind, machine, version, entry, phoff, shoff, flags, size, phsize, phnum, shsize, shnum, shstr = fields
    if (kind, machine, version, size) != (2, 94, 1, 52):
        raise CheckError("expected Xtensa ET_EXEC ELF metadata")
    if not entry or phsize != 32 or shsize != 40 or not phnum or not shnum or not 0 < shstr < shnum:
        raise CheckError("unsupported ELF table metadata")
    if phoff < 52 or shoff < 52 or phoff + phsize * phnum > len(data) or shoff + shsize * shnum > len(data):
        raise CheckError("ELF tables outside artifact bounds")
    return {"class": "ELF32", "byte_order": "little", "machine": "Xtensa", "type": "ET_EXEC", "entry": f"0x{entry:08x}", "flags": f"0x{flags:08x}"}


def check_objdump(text: str, elf: Path, entry: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 4 or not re.fullmatch(re.escape(str(elf)) + r":\s+file format elf32-xtensa-le", lines[0]):
        raise CheckError("unsupported objdump file format record")
    if lines[1] != "architecture: xtensa, flags 0x00000112:":
        raise CheckError("expected objdump Xtensa architecture and EXEC_P/HAS_SYMS/D_PAGED flags")
    if lines[2] != "EXEC_P, HAS_SYMS, D_PAGED" or lines[3] != f"start address {entry}":
        raise CheckError("unsupported objdump flags or inconsistent entry address")
    return {"format": "elf32-xtensa-le", "architecture": "xtensa", "flags": ["EXEC_P", "HAS_SYMS", "D_PAGED"], "entry": entry}


def check_nm(text: str) -> dict:
    found: dict[str, dict] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"(?:([0-9a-fA-F]{8})| {8}) ([aAbBcCdDgGiInNpPrRsStTuUvVwW]) (\S.*)", line)
        if not match:
            raise CheckError("unsupported nm symbol record")
        address, kind, name = match.groups()
        if name in REQUIRED_TEXT_SYMBOLS:
            if name in found or kind not in ("T", "t") or not address or int(address, 16) == 0:
                raise CheckError(f"required symbol is duplicate, undefined or not text: {name}")
            found[name] = {"address": f"0x{address.lower()}", "type": kind}
    missing = sorted(set(REQUIRED_TEXT_SYMBOLS) - found.keys())
    if missing:
        raise CheckError("missing required text symbols: " + ", ".join(missing))
    return found


def _compile_tokens(line: str) -> list[str]:
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError as exc:
        raise CheckError("unsupported compiler command quoting") from exc
    if not tokens or Path(tokens[0]).name != "xtensa-esp32-elf-g++":
        raise CheckError("unsupported app_main compiler command (wrappers/metadata are not evidence)")
    if any(any(char in token for char in ";&|<>`$\n\r") or token.startswith("@") for token in tokens):
        raise CheckError("unsupported shell/response-file compiler record")
    return tokens


def check_log(data: bytes, profile: str, build: Path, compiler: Path) -> dict:
    text = decode_text(data)
    lines = text.splitlines()
    compiles = []
    diagnostics = []
    diagnostic_count = 0
    successes = 0
    profile_successes = 0
    diagnostic_pattern = re.compile(r"(?:^|\s)(?:warning:|error:|fatal:)|CMake (?:Warning|Error)|LEGACY_INCLUDE_COMMON_HEADERS|git rev-parse returned|Could not use 'git describe'", re.I)
    for number, line in enumerate(lines, 1):
        if diagnostic_pattern.search(line):
            diagnostic_count += 1
            if len(diagnostics) < 100:
                # Keep the CMake warning body as well as the line-count evidence.
                context = "\n".join(lines[number - 1:number + 5]) if line == "CMake Warning:" else line
                diagnostics.append({"line": number, "text": context[:4096], "text_truncated": len(context) > 4096})
        known_git_fatal = bool(re.match(r"(?:-- git rev-parse returned ')?fatal: not a git repository(?:\s|:|$)", line))
        unknown_fatal = bool(re.search(r"(?:^|\s)fatal:", line)) and not known_git_fatal
        if unknown_fatal or re.search(r"\[FAILED\]|\bFAILED\s+\d|CMake Error|(?:^|\s)(?:fatal error:|error:)", line):
            raise CheckError(f"build failure diagnostic at log line {number}")
        if re.fullmatch(r"=+ \[SUCCESS\] Took [0-9]+(?:\.[0-9]+)? seconds =+", line):
            successes += 1
        if re.fullmatch(re.escape(profile) + r"\s+SUCCESS\s+\d+:\d{2}:\d{2}(?:\.\d+)?", line):
            profile_successes += 1
        # A bare main.cpp operand identifies this source. Also catch attempts to
        # hide it behind a response file or an unsupported compile record.
        source_mentioned = re.search(r"(?:^|[/\s\"'])main\.cpp(?=$|[\s\"'])", line)
        object_compile = "main.cpp.o" in line and (re.search(r"(?:^|\s)-c(?:\s|$)", line) or "@" in line)
        if not (source_mentioned or object_compile):
            continue
        tokens = _compile_tokens(line)
        if tokens[0] != compiler.name and Path(tokens[0]) != compiler:
            # PIO can print an absolute path through the macOS /tmp alias.
            if not Path(tokens[0]).is_absolute() or Path(tokens[0]).resolve() != compiler:
                raise CheckError("app_main command names a different compiler")
        if tokens.count("-c") != 1 or tokens.count("-o") != 1:
            raise CheckError("app_main needs one direct compilation and object output")
        output_index = tokens.index("-o") + 1
        if output_index >= len(tokens):
            raise CheckError("missing app_main object path")
        output = Path(tokens[output_index])
        expected_object = build / profile / "src/main.cpp.o"
        if not output.is_absolute() or output.resolve() != expected_object:
            raise CheckError("app_main object does not belong to the supplied build/profile")
        sources = [token for token in tokens[1:] if not token.startswith("-") and token.endswith(".cpp")]
        if len(sources) != 1 or sources[0] not in ("src/main.cpp", str(APP_SOURCE)):
            raise CheckError("unsupported app_main source operand")
        gate_tokens = [token for token in tokens if MACRO in token]
        if gate_tokens != [f"-D{MACRO}={int(profile == 'monitor_persisted')}"]:
            raise CheckError("missing, wrong, duplicate, unset or contradictory monitor gate flag")
        # Fail closed on preprocessor indirection and unreviewed argument forms.
        # Do not read response files or execute anything from the log.
        operands = {output_index, tokens.index(sources[0])}
        for index, token in enumerate(tokens[1:], 1):
            if index in operands or token in ("-c", "-o"):
                continue
            if token.startswith(("-D", "-I")) and len(token) > 2:
                continue
            if token.startswith(("-W", "-f", "-g", "-m", "-O", "-std=")) and not token.startswith(("-Wp,", "-Wl,", "-Wa,", "-fplugin", "-fpreprocessed", "-fdirectives-only")):
                continue
            raise CheckError(f"unsupported compiler argument: {token[:120]}")
        compiles.append({"line": number, "source": str(APP_SOURCE), "object": str(expected_object), "gate_flag": gate_tokens[0], "command_sha256": hashlib.sha256(line.encode()).hexdigest()})
    if len(compiles) != 1:
        raise CheckError("expected exactly one verbose app_main compilation in a fresh-build log")
    if successes != 1 or profile_successes != 1:
        raise CheckError("missing or ambiguous successful build/profile summary")
    return {"app_main_compilation": compiles[0], "success_markers": successes, "profile_success_markers": profile_successes, "diagnostics_count": diagnostic_count, "diagnostics": diagnostics, "diagnostics_truncated": diagnostic_count > len(diagnostics), "compile_commands_used": False}


def run_tool(command: list[str]) -> str:
    """Run only caller-constructed nm/objdump argv, with time and output bounds."""
    if os.name != "posix":
        raise CheckError("bounded vendor inspection requires POSIX")
    process = None
    pending: int | None = None
    output = bytearray()
    deadline = time.monotonic() + TOOL_TIMEOUT

    def interrupt(signum: int, _frame: object) -> None:
        nonlocal pending
        if pending is None:
            pending = signum
        # Never raise asynchronously: Popen may have created a group without
        # returning its handle, or Python may be entering a cleanup finally.
        # Raise only at owned checkpoints below, polling at most every 0.1s.
        # Signals stay unblocked during spawn, so no blocked mask reaches tools.

    previous = {sig: signal.getsignal(sig) for sig in INSPECTION_SIGNALS}
    try:
        for sig in INSPECTION_SIGNALS:
            signal.signal(sig, interrupt)
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, env={**os.environ, "LC_ALL": "C"})
        if pending is not None:
            raise InspectionInterrupted(pending)
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if pending is not None:
                    raise InspectionInterrupted(pending)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CheckError("vendor tool timeout")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > MAX_TOOL_OUTPUT:
                            raise CheckError("vendor tool output exceeds size limit")
        while True:
            if pending is not None:
                raise InspectionInterrupted(pending)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CheckError("vendor tool timeout")
            try:
                code = process.wait(timeout=min(remaining, 0.1))
                break
            except subprocess.TimeoutExpired:
                continue
        if code:
            raise CheckError(f"vendor tool exited {code}: {bytes(output[-2048:]).decode('utf-8', errors='replace')}")
        return decode_text(bytes(output))
    finally:
        try:
            # Block only during cleanup, after ownership is known. Unblocking
            # with our deferred handler still installed records any cancellation
            # delivered during kill/reap without interrupting cleanup itself.
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, INSPECTION_SIGNALS)
            try:
                if process is not None:
                    try:
                        # Only our group is touched, including pipe-holding children.
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    finally:
                        if process.stdout is not None:
                            process.stdout.close()
                        process.wait(timeout=5)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        finally:
            restore_handlers(previous)
        if pending is not None:
            raise InspectionInterrupted(pending)


def capture_manual_disassembly(objdump: Path, elf: Path, elf_sha256: str) -> dict:
    """Retain bounded raw output, not an instruction/member-semantics decoder."""
    evidence = {}
    for name, symbol in MANUAL_DISASSEMBLY_SYMBOLS.items():
        command = [str(objdump), "-d", f"--disassemble={symbol}", str(elf)]
        output = run_tool(command)
        raw = output.encode("utf-8")
        if not 0 < len(raw) <= MAX_DISASSEMBLY_BYTES:
            raise CheckError("manual disassembly is empty or exceeds size limit")
        # Check only that objdump returned the requested artifact/function frame.
        # No opcode, address, register, offset or enabled-member meaning is inferred.
        header = re.escape(str(elf)) + r":\s+file format elf32-xtensa-le"
        label = r"[0-9a-fA-F]{8} <" + re.escape(symbol) + r">:"
        if len(re.findall("^" + header + "$", output, re.M)) != 1 or len(re.findall("^" + label + "$", output, re.M)) != 1:
            raise CheckError(f"missing or unsupported manual disassembly frame: {symbol}")
        command_json = json.dumps(command, ensure_ascii=True, separators=(",", ":"))
        evidence[name] = {
            "symbol": symbol,
            "elf_sha256": elf_sha256,
            "command": command,
            "command_sha256": hashlib.sha256(command_json.encode("utf-8")).hexdigest(),
            "command_hash_encoding": "UTF-8 JSON argv; ensure_ascii=true; compact separators",
            "output": output,
            "output_bytes": len(raw),
            "output_sha256": hashlib.sha256(raw).hexdigest(),
            "output_stream": "stdout and stderr merged, unmodified UTF-8 text",
            "semantics_verified": False,
        }
    return evidence


def check_pair(disabled_build: Path, persisted_build: Path, disabled_log: Path, persisted_log: Path, packages: Path) -> dict:
    builds = [directory(disabled_build), directory(persisted_build)]
    if builds[0] == builds[1] or builds[0] in builds[1].parents or builds[1] in builds[0].parents:
        raise CheckError("build roots must be distinct and non-nested")
    package_root = directory(packages)
    toolchain = directory(package_root / TOOLCHAIN)
    bin_dir = directory(toolchain / "bin")
    manifest_path = toolchain / "package.json"
    manifest_data = read_regular(manifest_path, 65536)
    manifest = strict_manifest(manifest_data)
    if not isinstance(manifest, dict) or manifest.get("name") != TOOLCHAIN or manifest.get("version") != TOOLCHAIN_VERSION:
        raise CheckError("unexpected pinned toolchain package metadata")
    tools = {name: bin_dir / f"xtensa-esp32-elf-{name}" for name in ("nm", "objdump")}
    tool_hashes = {name: digest(path, read_regular(path, MAX_TOOL_BYTES)) for name, path in tools.items()}
    report = {"kind": "monitor_compile_artifact_check", "passed": True, "release_authorized": False, "scope": "compiler-log flags and linked ELF metadata/symbols, not target execution", "initializer_semantics_verified": False, "manual_initializer_review_required": True, "fresh_build_provenance_verified": False, "warning_free_claim": False, "limitations": LIMITATIONS, "toolchain": {"name": TOOLCHAIN, "version": TOOLCHAIN_VERSION, "manifest": digest(manifest_path, manifest_data), "tools": tool_hashes}, "profiles": []}
    for profile, build, log in zip(("monitor_disabled", "monitor_persisted"), builds, (disabled_log, persisted_log)):
        artifact_dir = directory(build / profile)
        artifacts = {}
        elf_data = b""
        for name, path, limit in (("elf", artifact_dir / "firmware.elf", MAX_ELF_BYTES), ("bin", artifact_dir / "firmware.bin", MAX_BIN_BYTES), ("sdkconfig", build / f"sdkconfig.{profile}", MAX_CONFIG_BYTES)):
            data = read_regular(path, limit)
            artifacts[name] = digest(path, data)
            if name == "elf":
                elf_data = data
        elf = artifact_dir / "firmware.elf"
        header = check_elf_header(elf_data)
        log_data = read_regular(log, MAX_LOG_BYTES)
        log_result = check_log(log_data, profile, build, bin_dir / "xtensa-esp32-elf-g++")
        metadata_output = run_tool([str(tools["objdump"]), "-f", str(elf)])
        metadata = check_objdump(metadata_output, elf, header["entry"])
        symbol_output = run_tool([str(tools["nm"]), "-C", str(elf)])
        symbols = check_nm(symbol_output)
        manual_disassembly = capture_manual_disassembly(tools["objdump"], elf, artifacts["elf"]["sha256"])
        # Recheck bytes after ALL reads, including retained manual-review output.
        # Detect artifact replacement during inspection; no copy/build mutation.
        for item in artifacts.values():
            if digest(Path(item["path"]), read_regular(Path(item["path"]), item["bytes"])) != item:
                raise CheckError("artifact changed during vendor inspection")
        report["profiles"].append({"profile": profile, "expected_gate": int(profile == "monitor_persisted"), "artifacts": artifacts, "log": {**digest(log, log_data), **log_result}, "elf_header": header, "objdump_metadata": metadata, "defined_text_symbols": symbols, "manual_disassembly": manual_disassembly, "tool_output_sha256": {"objdump": hashlib.sha256(metadata_output.encode()).hexdigest(), "nm": hashlib.sha256(symbol_output.encode()).hexdigest()}})
    profiles = report["profiles"]
    if profiles[0]["artifacts"]["bin"]["sha256"] == profiles[1]["artifacts"]["bin"]["sha256"]:
        raise CheckError("monitor firmware binaries are identical")
    if os.path.samefile(disabled_log, persisted_log):
        raise CheckError("profile logs must be distinct files")
    if os.path.samefile(builds[0] / "sdkconfig.monitor_disabled", builds[1] / "sdkconfig.monitor_persisted"):
        raise CheckError("profiles must not share one sdkconfig file")
    report["monitor_binaries_distinct"] = True
    report["diagnostics_count"] = sum(profile["log"]["diagnostics_count"] for profile in profiles)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("disabled-build", "persisted-build", "disabled-log", "persisted-log", "packages"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)

    def interrupt(signum: int, _frame: object) -> None:
        raise InspectionInterrupted(signum)

    previous = {sig: signal.getsignal(sig) for sig in INSPECTION_SIGNALS}
    try:
        for sig in INSPECTION_SIGNALS:
            signal.signal(sig, interrupt)
        result = check_pair(args.disabled_build, args.persisted_build, args.disabled_log, args.persisted_log, args.packages)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except InspectionInterrupted as exc:
        print(json.dumps({"kind": "monitor_compile_artifact_check", "passed": False, "release_authorized": False, "error": str(exc), "interrupted_signal": exc.signum, "initializer_semantics_verified": False}))
        return 128 + exc.signum
    except (CheckError, OSError, UnicodeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"kind": "monitor_compile_artifact_check", "passed": False, "release_authorized": False, "error": str(exc), "initializer_semantics_verified": False}))
        return 1
    finally:
        restore_handlers(previous)


if __name__ == "__main__":
    sys.exit(main())
