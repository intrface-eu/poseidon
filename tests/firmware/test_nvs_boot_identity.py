"""Host ABI tests link the actual ESP adapter; no NVS/device execution.

Each named case gets a fresh process. This deliberately preserves and tests the
production process-wide uncertainty latch without adding a reset backdoor.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests/firmware"
OPEN_CASES = (
    "spec_label", "spec_null", "spec_address", "spec_size", "spec_type", "spec_subtype", "spec_namespace", "spec_key",
    "task_null", "partition_missing", "partition_address", "partition_size", "partition_label", "partition_type",
    "partition_subtype", "partition_encrypted", "partition_readonly", "erased", "preflight_error", "preflight_last_error",
    "externally_initialized", "stats_error", "init_error", "init_partial", "init_new_version", "namespace_missing",
    "ro_open_error", "rw_open_error", "key_missing", "wrong_type", "short_body", "changed_on_rw",
    "length_0", "length_31", "length_33", "length_65535",
    "semantic_magic", "semantic_version", "semantic_marker", "semantic_reserved", "semantic_complement",
    *(f"record_byte_{byte}" for byte in range(32)),
    *(f"open_read_{read}" for read in range(1, 5)),
)
ALLOCATION_CASES = (
    "set_error", "set_early_error", "commit_error", "commit_early_error", "readback_length", "readback_body",
    "readback_corrupt", "readback_old", "prewrite_length", "prewrite_body", "external_floor", "max",
)
CASES = (
    "disabled", "success", "owner", "reentrant", "concurrent", "boundaries", "cleanup_failure", "open_cleanup_failure",
    "wrong_owner_destruction", "stats_partition_not_registered", "runtime_compatibility",
    *("open_" + name for name in OPEN_CASES), *("allocate_" + name for name in ALLOCATION_CASES),
)


class NvsBootIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = os.environ.get("CXX", "c++")
        if shutil.which(compiler) is None:
            raise RuntimeError(f"C++17 compiler unavailable: {compiler}; no install attempted")
        cls.workspace = tempfile.TemporaryDirectory(prefix="poseidon-nvs-abi-", dir=os.environ.get("REEF_TEST_TMPDIR"))
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.runner = Path(cls.workspace.name) / "nvs_identity_cases"
        flags = [compiler, "-std=c++17", "-O2", "-DNDEBUG", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread"]
        if os.environ.get("REEF_SANITIZE") == "1":
            flags += ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        command = flags + [
            "-I", str(TESTS / "abi_nvs"),
            "-I", str(ROOT / "firmware/esp-idf/include"),
            "-I", str(ROOT / "firmware/reef/include"),
            "-I", str(ROOT / "libs/proto-cpp/include"),
            str(ROOT / "firmware/esp-idf/src/nvs_boot_identity.cpp"),
            str(ROOT / "firmware/reef/src/reef.cpp"),
            str(ROOT / "libs/proto-cpp/src/telemetry.cpp"),
            str(TESTS / "nvs_identity_cases.cpp"), "-o", str(cls.runner),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        if result.returncode:
            raise RuntimeError(f"NVS ABI compile failed ({result.returncode})\n{result.stdout}\n{result.stderr}")


def _case(name: str):
    def run(self: NvsBootIdentityTests) -> None:
        result = subprocess.run([str(self.runner), name], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS " + name)
    return run


for _name in CASES:
    setattr(NvsBootIdentityTests, "test_" + _name, _case(_name))

if __name__ == "__main__":
    unittest.main()
