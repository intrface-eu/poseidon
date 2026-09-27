"""Stdlib compiler/runner for the portable C++17 REEF proposal reference.

No global build tools, target I/O, network access, or Python packages required.
Artifacts live in one owned TemporaryDirectory, removed even on test failure.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROTO = ROOT / "libs/proto-cpp"
REEF = ROOT / "firmware/reef"
FIXTURE_PATH = PROTO / "fixtures/reef-telemetry-v1.json"
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
_SPEC = importlib.util.spec_from_file_location("reef_synthetic_vectors", PROTO / "tools/generate_vectors.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load deterministic fixture builder")
VECTORS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(VECTORS)

CPP_CASES = (
    "codec_output_atomicity",
    "codec_bounded_mutations",
    "journal_blank_and_restart",
    "journal_every_write_interruption",
    "journal_every_provision_interruption",
    "journal_sync_and_read_failures",
    "journal_corruption_fail_closed",
    "journal_exhaustion_and_ambiguity",
    "sequence_no_wrap",
    "runtime_samples_and_quality",
    "runtime_sleep_and_battery_hysteresis",
    "runtime_queue_and_config",
    "runtime_restart_and_session_rollover",
    "runtime_clock_faults_and_extremes",
    "runtime_identity_fail_closed",
    "runtime_invalid_configs",
)


class ReefHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = os.environ.get("CXX", "c++")
        if shutil.which(compiler) is None:
            raise RuntimeError(f"C++17 compiler unavailable: {compiler}; no install attempted")
        cls.workspace = tempfile.TemporaryDirectory(prefix="poseidon-reef-host-", dir=os.environ.get("REEF_TEST_TMPDIR"))
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.cli = Path(cls.workspace.name) / "codec_cli"
        cls.runner = Path(cls.workspace.name) / "runtime_cases"
        flags = [compiler, "-std=c++17", "-O2", "-DNDEBUG", "-Wall", "-Wextra", "-Werror", "-pedantic", "-I", str(PROTO / "include"), "-I", str(REEF / "include")]
        if os.environ.get("REEF_SANITIZE") == "1":
            flags += ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        commands = [
            flags + [str(PROTO / "src/telemetry.cpp"), str(PROTO / "tools/codec_cli.cpp"), "-o", str(cls.cli)],
            flags + [str(PROTO / "src/telemetry.cpp"), str(REEF / "src/reef.cpp"), str(ROOT / "tests/firmware/runtime_cases.cpp"), "-o", str(cls.runner)],
        ]
        for command in commands:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
            if result.returncode:
                raise RuntimeError(f"host compile failed ({result.returncode})\n{result.stdout}\n{result.stderr}")

    def cli_run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(self.cli), *args], capture_output=True, text=True, timeout=10, check=False)

    def check_valid(self, vector: dict) -> None:
        decoded = self.cli_run("decode", vector["hex"])
        self.assertEqual(decoded.returncode, 0, decoded.stderr)
        self.assertEqual(json.loads(decoded.stdout), vector["fields"])
        self.assertIsInstance(json.loads(decoded.stdout)[1], str)
        encoded = self.cli_run("encode", *("null" if value is None else str(value) for value in vector["fields"]))
        self.assertEqual(encoded.returncode, 0, encoded.stderr)
        self.assertEqual(encoded.stdout.strip(), vector["hex"])
        self.assertLessEqual(len(bytes.fromhex(vector["hex"])), 64)

    def test_fixture_reproduction(self) -> None:
        self.assertEqual(FIXTURES, VECTORS.fixture_document())
        self.assertTrue(FIXTURES["synthetic"])

    def test_every_truncated_prefix(self) -> None:
        for vector in FIXTURES["valid"]:
            payload = bytes.fromhex(vector["hex"])
            for length in range(len(payload)):
                with self.subTest(vector=vector["name"], length=length):
                    result = self.cli_run("decode", payload[:length].hex())
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")

    def test_maximum_size_and_parser_bound(self) -> None:
        longest = max(FIXTURES["valid"], key=lambda vector: len(vector["hex"]))
        self.assertEqual(len(bytes.fromhex(longest["hex"])), 44)
        for size in (64, 65, 128):
            payload = bytes.fromhex(longest["hex"]).ljust(size, b"\x00")
            result = self.cli_run("decode", payload.hex())
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr.strip(), "trailing" if size == 64 else "size")

    def test_cli_numeric_and_syntax_rejection(self) -> None:
        fields = list(FIXTURES["valid"][0]["fields"])
        for index, value in ((1, "18446744073709551616"), (1, "-1"), (1, "+1"), (1, "01"), (1, "1junk"), (2, "4294967296"), (3, "4294967296"), (6, "65536"), (8, "256"), (10, "2147483648"), (10, "-2147483649"), (10, "1.0"), (12, "65536")):
            args = ["null" if item is None else str(item) for item in fields]
            args[index] = value
            with self.subTest(index=index, value=value):
                result = self.cli_run("encode", *args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
        for text in ("g0", "8", " 8d", "0x8d", "8d\n"):
            self.assertEqual(self.cli_run("decode", text).returncode, 2)
        self.assertEqual(self.cli_run("encode").returncode, 2)
        self.assertEqual(self.cli_run("unknown").returncode, 2)

    def test_nonminimal_encoding_each_integer_position(self) -> None:
        fields = [1, "1", 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
        tokens = [VECTORS.scalar(int(value)) for value in fields]
        for index in range(13):
            bad = b"\x8d" + b"".join(b"\x18\x01" if position == index else token for position, token in enumerate(tokens))
            with self.subTest(index=index):
                result = self.cli_run("decode", bad.hex())
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr.strip(), "nonminimal")

    def test_deterministic_random_valid_frames(self) -> None:
        rng = random.Random(0x52454546)
        for case in range(100):
            quality = rng.randrange(3)
            kind = rng.randrange(4)
            sensor_quality = 2 if kind == 0 else rng.randrange(3)
            fields = [1, str(rng.randrange(1, 2**64)), rng.randrange(2**32), rng.randrange(2**32), quality,
                      None if quality == 0 else rng.randrange(2**32),
                      rng.choice([None, rng.randrange(65536)]), rng.choice([None, rng.randrange(65536)]),
                      rng.randrange(3), kind, None if sensor_quality == 2 else rng.randrange(-(2**31), 2**31),
                      sensor_quality, rng.randrange(1, 65536) if sensor_quality == 1 else None]
            with self.subTest(case=case):
                self.check_valid({"fields": fields, "hex": VECTORS.wire(fields).hex()})

    def test_platform_candidate_vectors(self) -> None:
        # Parity is evidence only; it does not freeze or publish the contract.
        candidate = json.loads((ROOT / "contracts/v1/fixtures/reef-cbor-vectors.json").read_text(encoding="utf-8"))
        for vector in candidate["valid"]:
            with self.subTest(name=vector["name"]):
                self.check_valid({"hex": vector["hex"], "fields": [vector["fields"][name] for name in FIXTURES["field_names"]]})
        for vector in candidate["invalid"]:
            with self.subTest(name=vector["name"]):
                self.assertEqual(self.cli_run("decode", vector["hex"]).returncode, 2)

    def test_reference_ab_partition_layout(self) -> None:
        path = ROOT / "firmware/reference/partitions-reference.csv"
        rows = list(csv.reader(line for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")))
        entries = [{"name": row[0].strip(), "type": row[1].strip(), "subtype": row[2].strip(), "offset": int(row[3].strip(), 0), "size": int(row[4].strip(), 0)} for row in rows]
        self.assertEqual([entry["name"] for entry in entries], ["nvs", "otadata", "phy_init", "ota_0", "ota_1"])
        previous_end = 0x9000
        for entry in entries:
            self.assertGreaterEqual(entry["offset"], previous_end)
            self.assertGreater(entry["size"], 0)
            self.assertEqual(entry["offset"] % (0x10000 if entry["type"] == "app" else 0x1000), 0)
            self.assertEqual(entry["size"] % 0x1000, 0)
            previous_end = entry["offset"] + entry["size"]
            self.assertLessEqual(previous_end, 0x400000)
        self.assertEqual(entries[1]["size"], 0x2000)
        self.assertEqual([entry["subtype"] for entry in entries if entry["type"] == "app"], ["ota_0", "ota_1"])
        self.assertEqual(entries[-1]["size"], entries[-2]["size"])
        self.assertEqual(entries[-1]["size"], 0x1F0000)

    def test_reference_ota_bindings_not_invoked(self) -> None:
        reference = ROOT / "firmware/reference"
        source = (reference / "src/ota_compile_reference.cpp").read_text(encoding="utf-8")
        main = (reference / "src/main.cpp").read_text(encoding="utf-8")
        for name in ("esp_ota_get_running_partition", "esp_ota_get_state_partition", "esp_ota_mark_app_valid_cancel_rollback", "esp_ota_mark_app_invalid_rollback_and_reboot"):
            self.assertIn("&" + name, source)
            self.assertNotRegex(source, name + r"\s*\(")
            self.assertNotIn(name, main)
        self.assertNotIn("ota_api_compile_bindings", main)
        defaults = (reference / "sdkconfig.defaults").read_text(encoding="utf-8")
        for value in ("CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y", "CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK=n", "CONFIG_SECURE_BOOT=n", "CONFIG_SECURE_FLASH_ENC_ENABLED=n"):
            self.assertIn(value, defaults)
        self.assertIn("board_build.partitions = partitions-reference.csv", (reference / "platformio.ini").read_text(encoding="utf-8"))

    def test_reference_config_matches_hardware_revision(self) -> None:
        reference = json.loads((ROOT / "hardware/interfaces/reference-v1.json").read_text(encoding="utf-8"))
        config = (ROOT / "firmware/reference/src/reference_config.hpp").read_text(encoding="utf-8")
        self.assertIn(reference["revision"], config)
        board = next(board for board in reference["boards"] if board["id"] == "MCU-01")
        self.assertEqual(board["model"], "ESP32-DevKitC-32E")
        reserved = board["reserved_logical_interfaces"]
        for constant, number in (("provisional_radio_uart_tx_gpio", reserved["radio_uart"]["tx_gpio"]),
                                 ("provisional_radio_uart_rx_gpio", reserved["radio_uart"]["rx_gpio"]),
                                 ("provisional_probe_i2c_sda_gpio", reserved["probe_i2c"]["sda_gpio"]),
                                 ("provisional_probe_i2c_scl_gpio", reserved["probe_i2c"]["scl_gpio"])):
            self.assertIn(f"{constant} = {number};", config)
        self.assertIn("hardware_io_authorized = false", config)


def _valid_test(vector: dict):
    def run(self: ReefHostTests) -> None:
        self.check_valid(vector)
    return run


def _invalid_test(vector: dict):
    def run(self: ReefHostTests) -> None:
        result = self.cli_run("decode", vector["hex"])
        self.assertEqual(result.returncode, 2, f"accepted malformed vector {vector['name']}")
        self.assertEqual(result.stdout, "")
        self.assertNotEqual(result.stderr, "")
    return run


def _runtime_test(name: str):
    def run(self: ReefHostTests) -> None:
        result = subprocess.run([str(self.runner), name], capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), f"PASS {name}")
    return run


for _vector in FIXTURES["valid"]:
    setattr(ReefHostTests, f"test_golden_{_vector['name']}", _valid_test(_vector))
for _vector in FIXTURES["invalid"]:
    setattr(ReefHostTests, f"test_reject_{_vector['name']}", _invalid_test(_vector))
for _case in CPP_CASES:
    setattr(ReefHostTests, f"test_cpp_{_case}", _runtime_test(_case))

if __name__ == "__main__":
    unittest.main()
