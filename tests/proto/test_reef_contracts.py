"""Canonical wire, wide-counter, unit and clock tests from synthetic vectors."""
import copy
import json
import unittest

from poseidon_proto.models import ModelValidationError
from poseidon_proto.platform import SCHEMA_DIR, map_clock, validate_contract
from poseidon_proto.reef import decode_frame, encode_frame, json_fields, validate_frame


class ReefContractTests(unittest.TestCase):
    def setUp(self):
        self.vectors = json.loads((SCHEMA_DIR / "fixtures/reef-cbor-vectors.json").read_text())

    def test_all_published_wire_vectors_round_trip(self):
        for vector in self.vectors["valid"]:
            with self.subTest(vector=vector["name"]):
                encoded = bytes.fromhex(vector["hex"])
                fields = decode_frame(encoded)
                self.assertEqual(encode_frame(fields), encoded)
                self.assertEqual(json_fields(fields), vector["fields"])
                self.assertLessEqual(len(encoded), 64)

    def test_all_published_bad_wire_vectors_fail(self):
        for vector in self.vectors["invalid"]:
            with self.subTest(vector=vector["name"]):
                with self.assertRaises(ModelValidationError):
                    decode_frame(bytes.fromhex(vector["hex"]))

    def test_every_truncation_fails(self):
        for vector in self.vectors["valid"]:
            encoded = bytes.fromhex(vector["hex"])
            for size in range(len(encoded)):
                with self.assertRaises(ModelValidationError):
                    decode_frame(encoded[:size])

    def test_counter_bounds_bool_and_absent_sensor_rules(self):
        fields = decode_frame(bytes.fromhex(self.vectors["valid"][0]["hex"]))
        for index, value in [(0, True), (1, 0), (1, 2**64), (2, 2**32), (10, 2**31), (9, 0)]:
            bad = list(fields)
            bad[index] = value
            with self.assertRaises(ModelValidationError):
                validate_frame(bad)
        fields[9:13] = [0, None, 2, None]
        self.assertEqual(decode_frame(encode_frame(fields)), fields)

    def test_raw_and_calibrated_semantics(self):
        fields = decode_frame(bytes.fromhex(self.vectors["valid"][0]["hex"]))
        for change in [(10, None), (12, 7), (11, 1)]:
            bad = list(fields)
            bad[change[0]] = change[1]
            with self.assertRaises(ModelValidationError):
                validate_frame(bad)
        fields[11:13] = [1, 7]
        self.assertEqual(decode_frame(encode_frame(fields)), fields)

    def test_uint64_json_boot_ids_never_use_js_numbers(self):
        fixture = json.loads((SCHEMA_DIR / "fixtures/telemetry-envelope.valid.json").read_text())
        fixture["boot_id"] = str(2**64 - 1)
        validate_contract("telemetry-envelope", fixture)
        for value in [str(2**64), "01", "0", 2**53, True, "1\n"]:
            fixture["boot_id"] = value
            with self.assertRaises(ModelValidationError):
                validate_contract("telemetry-envelope", fixture)

    def test_affine_clock_sign_domain_and_uncertainty(self):
        relation = json.loads((SCHEMA_DIR / "fixtures/clock-relation.valid.json").read_text())
        reference, uncertainty = map_clock(relation, 1000)
        self.assertAlmostEqual(reference, 1000.13)
        self.assertAlmostEqual(uncertainty, 0.025)
        self.assertAlmostEqual(map_clock(relation, -1000)[1], 0.025)
        for change in [dict(reference_domain=relation["source_domain"]), dict(drift_ppm=-1000000), dict(method="shared_clock"), dict(anchor_uncertainty_s=-1)]:
            bad = {**relation, **change}
            with self.assertRaises(ModelValidationError):
                map_clock(bad, 1)

    def test_raw_units_and_calibration_cannot_be_invented(self):
        fixture = json.loads((SCHEMA_DIR / "fixtures/telemetry-envelope.valid.json").read_text())
        item = fixture["measurements"][0]
        item.update(name="temperature_raw", unit="count", quality="uncalibrated", calibration_id=None)
        validate_contract("telemetry-envelope", fixture)
        for change in [dict(unit="Cel"), dict(quality="calibrated", calibration_id="made-up"), dict(calibration_id="made-up")]:
            bad = copy.deepcopy(fixture)
            bad["measurements"][0].update(change)
            with self.assertRaises(ModelValidationError):
                validate_contract("telemetry-envelope", bad)

    def test_bounded_strict_parser_rejects_non_bytes_and_maps(self):
        for invalid in [None, [1], b"", b"\xa0", b"\x8d" + b"\x00" * 64]:
            with self.assertRaises(ModelValidationError):
                decode_frame(invalid)


if __name__ == "__main__":
    unittest.main()
