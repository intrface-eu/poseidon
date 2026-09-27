import copy
import importlib.util
import json
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("hardware_mechanical", ROOT / "hardware/analysis/mechanical.py")
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)


class MechanicalCalculationTests(unittest.TestCase):
    def setUp(self):
        self.scenario = json.loads((ROOT / "hardware/analysis/scenario.json").read_text())

    def test_transverse_tether_force_at_half_meter_per_second(self):
        self.assertAlmostEqual(MODEL.drag_n(1025, 1.2, 0.08, 0.5), 12.3, places=10)

    def test_zero_flow_has_zero_drag(self):
        self.assertEqual(MODEL.drag_n(1025, 1.2, 0.08, 0), 0)

    def test_doubled_speed_quadruples_force(self):
        report = MODEL.calculate(self.scenario)
        drag = report["submerged_drag_sensitivity"]
        self.assertAlmostEqual(drag[2]["sum_of_modeled_transverse_drag_n"] / drag[1]["sum_of_modeled_transverse_drag_n"], 4)
        wind = report["panel_wind_sensitivity"]
        self.assertAlmostEqual(wind[1]["panel_normal_force_n"] / wind[0]["panel_normal_force_n"], 4)

    def test_millimeters_convert_to_cubic_meters(self):
        expected = math.pi * 0.055**2 * 0.25
        self.assertAlmostEqual(MODEL.cylinder_volume_m3(110, 250), expected, places=12)
        self.assertAlmostEqual(expected * 1000, 2.3758294443, places=8)

    def test_hydrostatic_pressure_is_gauge_not_a_rating(self):
        report = MODEL.calculate(self.scenario)
        self.assertAlmostEqual(report["illustrative_pressure"]["gauge_pressure_pa"], 100518.1625, places=5)
        self.assertFalse(report["operating_envelope_frozen"])
        self.assertEqual(report["physical_tests_performed"], 0)

    def test_projected_panel_area_uses_vendor_axis_mapping(self):
        report = MODEL.calculate(self.scenario)
        self.assertAlmostEqual(report["projected_areas_m2"]["panel"], 0.2839, places=8)
        interface = json.loads((ROOT / "hardware/interfaces/reference-v1.json").read_text())
        reef = next(item for item in interface["mechanical_envelopes"] if item["assembly"] == "REEF")
        self.assertEqual(reef["solar_envelope_mm"][:2], [self.scenario["inputs"]["panel_width_mm"], self.scenario["inputs"]["panel_height_mm"]])

    def test_net_force_sign_and_buoyancy_equation(self):
        report = MODEL.calculate(self.scenario)
        result = report["illustrative_buoyancy"]
        self.assertAlmostEqual(result["gross_camera_cylinder_buoyancy_n"], 1025 * 9.80665 * result["gross_camera_cylinder_volume_m3"])
        self.assertGreater(result["weight_minus_gross_camera_buoyancy_n"], 0)
        self.assertLess(result["weight_minus_gross_camera_buoyancy_n"], 6)

    def test_invalid_inputs_fail(self):
        for value in (-1, float("nan"), float("inf"), True, "1"):
            with self.subTest(value=value):
                scenario = copy.deepcopy(self.scenario)
                scenario["inputs"]["current_speeds_m_s"] = [value]
                with self.assertRaises(ValueError):
                    MODEL.calculate(scenario)

    def test_cannot_promote_example_to_operating_envelope(self):
        self.scenario["operating_envelope_frozen"] = True
        with self.assertRaisesRegex(ValueError, "cannot release"):
            MODEL.calculate(self.scenario)

    def test_stored_calculation_reproduces_exactly(self):
        generated = json.loads((ROOT / "hardware/analysis/calculated-reference.json").read_text())
        self.assertEqual(MODEL.calculate(self.scenario), generated)


if __name__ == "__main__":
    unittest.main()
