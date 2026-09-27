"""Actual MonitorTask/NvsBootIdentity/Runtime against deterministic host ABI.

No target builds, SDK execution, physical IO, or package installation. Each case
runs in a bounded subprocess so the one-start process-lifetime context resets
only by a real new process, never a hidden product reset hook.
"""
from __future__ import annotations

import configparser
import csv
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ABI = ROOT / "tests/firmware/abi_monitor"
CASES = (
    "disabled_zero_sdk", "target_disabled_zero_sdk", "target_persisted_runs_actual_worker",
    "enabled_invalid_config_zero_sdk", "stop_before_start_zero_sdk", "task_create_failure",
    "stop_races_task_create", "second_facade_cannot_stop_owner", "restart_rejected_after_stop",
    "timer_create_failure_no_nvs", "missing_partition_no_fallback", "missing_record_no_baseline",
    "erased_partition_no_init", "negative_clock_no_identity", "microsecond_regression_fault",
    "clock_output_atomicity", "delay_overflow_atomicity", "long_interval_checked",
    "timer_absolute_overflow_fault", "delayed_wake_coalesces", "queue_full_no_delivery_nulls",
    "timer_start_failure", "timer_stop_failure_retains", "timer_delete_failure_retains",
    "nvs_commit_failure_preserves_error", "nvs_cleanup_failure_retains",
    "inflight_callback_retains_worker", "selected_late_callback_no_notify", "handle_destruction_safe",
    "notification_failure_cleanup", "stop_races_timer_arming",
)


class MonitorTaskHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX", "c++")
        if shutil.which(compiler) is None:
            raise RuntimeError("C++17 compiler unavailable; no installation attempted")
        cls.owned = tempfile.TemporaryDirectory(prefix="poseidon-monitor-abi-", dir=os.environ.get("REEF_TEST_TMPDIR"))
        cls.addClassCleanup(cls.owned.cleanup)
        cls.runners = {}
        includes = (ABI, ROOT / "firmware/esp-idf/include", ROOT / "firmware/reef/include", ROOT / "libs/proto-cpp/include")
        sources = (ROOT / "firmware/esp-idf/src/monitor_task.cpp",
                   ROOT / "firmware/esp-idf/src/nvs_boot_identity.cpp",
                   ROOT / "firmware/reef/src/reef.cpp", ROOT / "libs/proto-cpp/src/telemetry.cpp",
                   ROOT / "firmware/monitor-target/src/main.cpp", ABI / "fake_monitor.cpp",
                   ROOT / "tests/firmware/monitor_task_cases.cpp")
        flags = [compiler, "-std=c++17", "-pthread", "-O1", "-DNDEBUG", "-Wall", "-Wextra", "-Werror", "-pedantic"]
        if os.environ.get("MONITOR_SANITIZE") == "1":
            flags += ["-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        for include in includes:
            flags += ["-I", str(include)]
        for enabled in (0, 1):
            output = Path(cls.owned.name) / f"actual_monitor_gate_{enabled}"
            command = flags + [f"-DPOSEIDON_MONITOR_PERSISTED={enabled}", *map(str, sources), "-o", str(output)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=90)
            if result.returncode:
                raise RuntimeError(f"actual monitor host compile failed\n{result.stdout}\n{result.stderr}")
            cls.runners[enabled] = output

    def run_case(self, name):
        enabled = int(name == "target_persisted_runs_actual_worker")
        result = subprocess.run([str(self.runners[enabled]), name], capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("passed (host fake ABI, no hardware)", result.stdout)


def _case(name):
    def test(self):
        self.run_case(name)
    return test


for _name in CASES:
    setattr(MonitorTaskHostTests, "test_" + _name, _case(_name))


class MonitorTargetConfigurationTests(unittest.TestCase):
    def test_default_gate_and_exact_pinned_toolchain(self):
        target = configparser.ConfigParser(interpolation=None)
        target.read(ROOT / "firmware/monitor-target/platformio.ini")
        original = configparser.ConfigParser(interpolation=None)
        original.read(ROOT / "firmware/reference/platformio.ini")
        self.assertEqual(target["platformio"]["default_envs"], "monitor_disabled")
        self.assertEqual(target["platformio"]["build_dir"], "${sysenv.PLATFORMIO_BUILD_DIR}")
        for key in ("platform", "board", "framework", "platform_packages"):
            self.assertEqual(target["env"][key], original["env:reef_reference"][key])
        self.assertIn("POSEIDON_MONITOR_PERSISTED=0", target["env:monitor_disabled"]["build_flags"])
        self.assertIn("POSEIDON_MONITOR_PERSISTED=1", target["env:monitor_persisted"]["build_flags"])
        self.assertNotEqual(target["env:monitor_disabled"]["board_build.esp-idf.sdkconfig_path"],
                            target["env:monitor_persisted"]["board_build.esp-idf.sdkconfig_path"])

    def test_new_target_partition_is_fixed_nonoverlapping_development_region(self):
        path = ROOT / "firmware/monitor-target/partitions-monitor.csv"
        with path.open() as source:
            rows = list(csv.reader(line for line in source if line.strip() and not line.startswith("#")))
        rows = [[cell.strip() for cell in row] for row in rows]
        region = next(row for row in rows if row[0] == "reef_state")
        self.assertEqual(region[1:5], ["data", "nvs", "0x3f0000", "0x10000"])
        intervals = sorted((int(row[3], 0), int(row[3], 0) + int(row[4], 0)) for row in rows)
        self.assertEqual(intervals[-1][1], 0x400000)
        self.assertTrue(all(left[1] <= right[0] for left, right in zip(intervals, intervals[1:])))
        self.assertEqual(sum(row[0] == "reef_state" for row in rows), 1)


if __name__ == "__main__":
    unittest.main()
