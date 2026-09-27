"""Synthetic cross-language JSON inputs; no field or cryptographic evidence."""
import copy
import json
from pathlib import Path
import unittest

from poseidon_proto.models import ModelValidationError
from poseidon_proto.platform import CONTRACTS, SCHEMA_DIR, canonical_json, validate_contract


class PlatformContractTests(unittest.TestCase):
    def fixture(self, name):
        return json.loads((SCHEMA_DIR / "fixtures" / f"{name}.valid.json").read_text())

    def test_all_golden_shapes_are_valid(self):
        for name in CONTRACTS:
            with self.subTest(contract=name):
                fixture = self.fixture(name)
                self.assertEqual(validate_contract(name, fixture), fixture)

    def test_published_negative_cases(self):
        cases = json.loads((SCHEMA_DIR / "fixtures" / "negative-cases.json").read_text())
        for case in cases:
            with self.subTest(reason=case["reason"]):
                fixture = self.fixture(case["contract"])
                path = case["mutation"].split(".")
                target = fixture
                for part in path[:-1]:
                    target = target[int(part)] if isinstance(target, list) else target[part]
                target[path[-1]] = case["value"]
                with self.assertRaises(ModelValidationError):
                    validate_contract(case["contract"], fixture)

    def test_nonfinite_numbers_and_wrong_python_types(self):
        for value in [float("nan"), float("inf"), True, "0", 10**1000]:
            with self.subTest(value=type(value).__name__):
                fixture = self.fixture("independent-observation")
                fixture["start_s"] = value
                with self.assertRaises(ModelValidationError):
                    validate_contract("independent-observation", fixture)

    def test_operator_offset_is_not_verified_sync(self):
        fixture = self.fixture("clock-quality")
        fixture.update(status="synchronized", method="operator_offset", offset_ms=120,
                       uncertainty_ms=2, reference="operator entered")
        with self.assertRaises(ModelValidationError):
            validate_contract("clock-quality", fixture)
        fixture["status"] = "operator_declared"
        self.assertEqual(validate_contract("clock-quality", fixture), fixture)

    def test_unknown_clock_cannot_invent_utc(self):
        fixture = self.fixture("telemetry-envelope")
        fixture["observed_at"] = "2026-09-08T00:00:00Z"
        with self.assertRaises(ModelValidationError):
            validate_contract("telemetry-envelope", fixture)

    def test_calibration_reference_and_invalid_measurement(self):
        fixture = self.fixture("telemetry-envelope")
        measurement = fixture["measurements"][0]
        measurement["quality"] = "calibrated"
        with self.assertRaises(ModelValidationError):
            validate_contract("telemetry-envelope", fixture)
        measurement.update(quality="invalid", value=None)
        validate_contract("telemetry-envelope", fixture)
        measurement["value"] = 0
        with self.assertRaises(ModelValidationError):
            validate_contract("telemetry-envelope", fixture)

    def test_duplicates_and_unknown_fields(self):
        fixture = self.fixture("telemetry-envelope")
        fixture["measurements"].append(copy.deepcopy(fixture["measurements"][0]))
        with self.assertRaises(ModelValidationError):
            validate_contract("telemetry-envelope", fixture)
        for name in CONTRACTS:
            fixture = self.fixture(name)
            fixture["new_field"] = 1
            with self.assertRaises(ModelValidationError):
                validate_contract(name, fixture)

    def test_observation_positive_interval_notes_and_blank_observer(self):
        for update in [dict(start_s=0.2), dict(label="feeding_observed", notes=" "), dict(observer=" "), dict(id="unsafe\n")]:
            fixture = self.fixture("independent-observation")
            fixture.update(update)
            with self.assertRaises(ModelValidationError):
                validate_contract("independent-observation", fixture)

    def test_real_dates_and_session_order(self):
        fixture = self.fixture("acquisition-session")
        fixture.update(started_at="2026-02-30T00:00:00Z")
        with self.assertRaises(ModelValidationError):
            validate_contract("acquisition-session", fixture)
        fixture.update(started_at="2026-09-08T00:00:00Z", ended_at="2026-09-07T00:00:00Z")
        with self.assertRaises(ModelValidationError):
            validate_contract("acquisition-session", fixture)

    def test_canonicalization_and_detached_validation(self):
        self.assertEqual(canonical_json({"z": True, "a": "é"}), b'{"a":"\\u00e9","z":true}')
        fixture = self.fixture("telemetry-envelope")
        validated = validate_contract("telemetry-envelope", fixture)
        validated["measurements"][0]["value"] = 0
        self.assertNotEqual(validated, fixture)

    def test_unknown_contract(self):
        with self.assertRaises(ModelValidationError):
            validate_contract("../secrets", {})


if __name__ == "__main__":
    unittest.main()
