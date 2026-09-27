"""Independent synthetic probes of published additive contracts, not device evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs/proto-py/src"))
from poseidon_proto.models import ModelValidationError
from poseidon_proto.registry import CONTRACTS, SCHEMA_DIR, validate_contract


class ContractBoundaryTests(unittest.TestCase):
    def fixture(self, name: str) -> dict:
        return json.loads((SCHEMA_DIR / "fixtures" / f"{name}.valid.json").read_text())

    def test_published_fixtures_and_schema_versions_agree(self) -> None:
        self.assertEqual({p.name.removesuffix(".schema.json") for p in SCHEMA_DIR.glob("*.schema.json")}, CONTRACTS)
        for name in sorted(CONTRACTS):
            with self.subTest(contract=name):
                schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
                self.assertEqual(schema["$id"], f"https://poseidon.invalid/contracts/v1/{name}.schema.json")
                fixture = self.fixture(name)
                self.assertEqual(validate_contract(name, fixture), fixture)
                if "schema_version" in fixture:
                    changed = copy.deepcopy(fixture)
                    changed["schema_version"] = "poseidon.unknown.v99"
                    with self.assertRaises(ModelValidationError):
                        validate_contract(name, changed)

    def test_uint64_boot_identifier_has_exact_text_boundary(self) -> None:
        fixture = self.fixture("telemetry-envelope")
        for value in ("1", "9007199254740993", "18446744073709551615"):
            with self.subTest(valid=value):
                fixture["boot_id"] = value
                self.assertEqual(validate_contract("telemetry-envelope", fixture)["boot_id"], value)
        for value in ("0", "01", "-1", "18446744073709551616", "1.0", 9007199254740993, True):
            with self.subTest(invalid=value), self.assertRaises(ModelValidationError):
                fixture["boot_id"] = value
                validate_contract("telemetry-envelope", fixture)

    def test_time_claim_cannot_become_verified_clock(self) -> None:
        fixture = self.fixture("telemetry-envelope")
        fixture["observed_at"] = "2026-09-08T00:00:00Z"
        with self.assertRaises(ModelValidationError):
            validate_contract("telemetry-envelope", fixture)
        clock = self.fixture("clock-quality")
        clock.update(status="synchronized", method="operator_offset", uncertainty_ms=1,
                     offset_ms=0, reference="SYNTHETIC OPERATOR ASSERTION")
        with self.assertRaises(ModelValidationError):
            validate_contract("clock-quality", clock)

    def test_calibration_and_units_cannot_be_promoted(self) -> None:
        original = self.fixture("telemetry-envelope")
        for measurement in (
            {"name": "digital_rms", "value": 0.5, "unit": "dB re 1 uPa", "quality": "uncalibrated", "calibration_id": None},
            {"name": "temperature", "value": 23, "unit": "Cel", "quality": "calibrated", "calibration_id": None},
            {"name": "temperature_raw", "value": 23, "unit": "Cel", "quality": "uncalibrated", "calibration_id": None},
        ):
            with self.subTest(measurement=measurement), self.assertRaises(ModelValidationError):
                fixture = copy.deepcopy(original)
                fixture["measurements"] = [measurement]
                validate_contract("telemetry-envelope", fixture)


if __name__ == "__main__":
    unittest.main()
