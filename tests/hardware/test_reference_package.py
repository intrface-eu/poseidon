import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "hardware_reference_check", ROOT / "hardware/validation/check_reference.py"
)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class ReferencePackageTests(unittest.TestCase):
    def setUp(self):
        self.interface, self.plan, self.traveler = copy.deepcopy(CHECK.load_records(ROOT))

    def verify(self):
        return CHECK.check_reference(self.interface, self.plan, self.traveler)

    def test_issued_reference_has_ten_consistency_checks(self):
        self.assertEqual(len(self.verify()), 10)

    def test_verified_uart_pin_cross_connection(self):
        boards = {board["id"]: board for board in self.interface["boards"]}
        uart = boards["MCU-01"]["reserved_logical_interfaces"]["radio_uart"]
        self.assertEqual((uart["tx_gpio"], uart["tx_board_pin"]), (17, "J3.11"))
        self.assertEqual((uart["rx_gpio"], uart["rx_board_pin"]), (16, "J3.12"))
        self.assertEqual(boards["RADIO-01"]["board_pins"], {
            "UART2_TX": "J4.7", "UART2_RX": "J4.8", "3V3": "J5.9", "GND": "J5.7"
        })
        self.assertNotIn("J4.9", boards["RADIO-01"]["board_pins"].values())

    def test_reef_vendor_envelope_axis_mapping(self):
        reef = next(item for item in self.interface["mechanical_envelopes"] if item["assembly"] == "REEF")
        self.assertEqual(reef["battery_envelope_mm"], [188, 147, 199])
        self.assertEqual(reef["solar_envelope_mm"], [668, 425, 25])
        self.assertGreaterEqual(reef["battery_terminal_service_allowance_mm"], 40)

    def test_revision_mismatch_fails(self):
        self.plan["revision"] = "HW-REF-OTHER"
        with self.assertRaisesRegex(ValueError, "wrong revision"):
            self.verify()

    def test_ambiguous_units_fail(self):
        self.interface["units"]["length"] = "inch"
        with self.assertRaisesRegex(ValueError, "units"):
            self.verify()

    def test_active_hardware_in_passive_variant_fails(self):
        self.interface["variants"]["passive_monitor"]["acoustic_output_hardware_populated"] = True
        with self.assertRaisesRegex(ValueError, "must be absent"):
            self.verify()

    def test_invented_acoustic_limit_fails(self):
        self.interface["physical_safety"]["acoustic_limit"] = 1.0
        with self.assertRaisesRegex(ValueError, "acoustic limit"):
            self.verify()

    def test_invented_depth_limit_fails(self):
        self.interface["physical_safety"]["depth_limit_m"] = 10
        with self.assertRaisesRegex(ValueError, "qualified depth"):
            self.verify()

    def test_insufficient_cpu_supply_allocation_fails(self):
        rail = next(rail for rail in self.interface["power_rails"] if rail["id"] == "V5_HUB")
        rail["source_current_budget_a"] = 2.9
        with self.assertRaisesRegex(ValueError, "vendor minimum"):
            self.verify()

    def test_invalid_dimensions_fail(self):
        for value in (0, -1, float("nan"), float("inf"), True, "400"):
            with self.subTest(value=value):
                original = self.interface["mechanical_envelopes"][0]["envelope_mm"][0]
                self.interface["mechanical_envelopes"][0]["envelope_mm"][0] = value
                with self.assertRaisesRegex(ValueError, "invalid"):
                    self.verify()
                self.interface["mechanical_envelopes"][0]["envelope_mm"][0] = original

    def test_impossible_interior_fails(self):
        self.interface["mechanical_envelopes"][0]["usable_interior_mm"][0] = 401
        with self.assertRaisesRegex(ValueError, "smaller than exterior"):
            self.verify()

    def test_duplicate_harness_fails(self):
        self.interface["harness_allocations"].append(copy.deepcopy(self.interface["harness_allocations"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate harness"):
            self.verify()

    def test_fabricated_physical_result_fails(self):
        self.plan["tests"][0]["result"] = "pass"
        with self.assertRaisesRegex(ValueError, "fabricated result"):
            self.verify()

    def test_missing_physical_coverage_fails(self):
        for test in self.plan["tests"]:
            test["assemblies"] = [name for name in test["assemblies"] if name != "ARRAY"]
        with self.assertRaisesRegex(ValueError, "all reference assemblies"):
            self.verify()

    def test_template_cannot_claim_measured_mass(self):
        self.traveler["measured_mass_kg"] = 10.0
        with self.assertRaisesRegex(ValueError, "unsupported measured_mass"):
            self.verify()

    def test_purchases_are_not_authorized(self):
        self.interface["purchase_authorized"] = True
        with self.assertRaisesRegex(ValueError, "purchases"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
