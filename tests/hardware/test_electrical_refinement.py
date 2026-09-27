"""Synthetic arithmetic tests for a non-adopted comparison, not hardware tests."""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "hardware/electronics/refine_power.py"
SPEC = importlib.util.spec_from_file_location("poseidon_power_refinement", SCRIPT)
assert SPEC and SPEC.loader
refine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refine)


class ElectricalRefinementTests(unittest.TestCase):
    def setUp(self):
        self.inputs, self.evidence, self.controller, self.hashes = refine.load_frozen()
        self.result = refine.build_refinement()
        self.arrays = {a["scenario"]: a for a in self.result["arrays"]}

    def test_frozen_failed_baseline_hash_and_all_files_preserved(self):
        self.assertEqual(self.result["baseline_evidence_sha256"],
                         "dfc71d2a6bfffc8a99b12e83af9e5daf9ad33ead8da6337c50cdfb7f1b17e40f")
        self.assertEqual(refine.baseline_hashes(), self.hashes)
        self.assertEqual(self.result["baseline_file_sha256"], self.hashes)
        self.assertFalse(self.evidence["thermal"]["shade_screen_passes"])
        self.assertFalse(self.evidence["solar"]["hot_voc_start_screen_passes"])

    def test_same_load_weather_derates_efficiencies_and_battery(self):
        self.assertEqual(self.result["unchanged_reef_daily_load_wh"], 27.5247475)
        self.assertEqual(self.result["unchanged_usable_load_side_battery_wh"], 294.912)
        self.assertEqual(self.result["frozen_battery_rail_v"], [11.2, 14.4])
        self.assertEqual(self.result["frozen_solar_inputs"], self.inputs["solar"])
        self.assertEqual(self.result["frozen_battery_inputs"], self.inputs["battery"])
        self.assertEqual(self.result["frozen_solar_inputs"]["peak_sun_hours"], 1)

    def test_one_panel_reproduces_failed_case(self):
        original = self.arrays["1S1P"]
        self.assertEqual(original["array_stc_power_w"], 40)
        self.assertAlmostEqual(original["cold_voc_v"], 25.200125)
        self.assertAlmostEqual(original["hot_voc_v"], 18.914125)
        self.assertAlmostEqual(original["array_design_isc_a"], 3)
        self.assertAlmostEqual(original["energy"]["harvest_wh_per_day"], 21.06)
        self.assertAlmostEqual(original["energy"]["net_wh_per_day"], -6.4647475)
        self.assertFalse(original["screens"]["hot_voc_above_start_requirement"])
        self.assertFalse(original["screens"]["load_side_daily_energy_covers_reef"])

    def test_two_series_fix_array_screens_not_qualification(self):
        series = self.arrays["2S1P"]
        self.assertEqual(series["panel_count"], 2)
        self.assertEqual(series["array_stc_power_w"], 80)
        self.assertAlmostEqual(series["cold_voc_v"], 50.40025)
        self.assertAlmostEqual(series["hot_voc_v"], 37.82825)
        self.assertAlmostEqual(series["array_design_isc_a"], 3)
        self.assertAlmostEqual(series["ideal_stc_charge_a_at_min_battery"], 80 / 11.2)
        self.assertTrue(series["all_array_calculation_screens_pass"])
        self.assertFalse(series["all_reference_hardware_qualified"])
        self.assertFalse(series["adopted_configuration"])
        self.assertFalse(series["energization_allowed"])

    def test_two_parallel_preserve_hot_start_failure(self):
        parallel = self.arrays["1S2P"]
        self.assertEqual(parallel["array_stc_power_w"], 80)
        self.assertAlmostEqual(parallel["cold_voc_v"], 25.200125)
        self.assertAlmostEqual(parallel["hot_voc_v"], 18.914125)
        self.assertAlmostEqual(parallel["array_design_isc_a"], 6)
        self.assertTrue(parallel["screens"]["load_side_daily_energy_covers_reef"])
        self.assertFalse(parallel["screens"]["hot_voc_above_start_requirement"])
        self.assertFalse(parallel["all_array_calculation_screens_pass"])

    def test_energy_boundary_matches_charge_and_discharge_losses(self):
        for scenario in ("2S1P", "1S2P"):
            with self.subTest(scenario=scenario):
                energy = self.arrays[scenario]["energy"]
                self.assertAlmostEqual(energy["harvest_stored_wh_per_day"], 80 * 1 * 0.65 * 0.9)
                self.assertAlmostEqual(energy["harvest_wh_per_day"], 42.12)
                self.assertAlmostEqual(energy["net_wh_per_day"], 14.5952525)
                self.assertAlmostEqual(energy["break_even_peak_sun_hours"], 27.5247475 / 42.12)

    def test_controller_limits_are_executable_not_assumed_pass(self):
        self.assertEqual(self.result["controller_nominal_pv_power_limit_w_at_12v"], 145)
        excessive = refine.array_comparison(4, 5, self.inputs, self.evidence, self.controller)
        self.assertAlmostEqual(excessive["array_stc_power_w"], 800)
        self.assertAlmostEqual(excessive["array_design_isc_a"], 15)
        for key in ("cold_voc_below_controller_max", "design_isc_below_controller_max",
                    "ideal_stc_charge_within_controller_limit", "stc_power_within_nominal_12v_pv_limit"):
            self.assertFalse(excessive["screens"][key], key)
        self.assertFalse(excessive["all_reference_hardware_qualified"])

    def test_invalid_series_and_parallel_counts_fail(self):
        for bad in (0, -1, 1.0, 1.5, True, False, "2", None, math.nan, math.inf):
            for side in ("series", "parallel"):
                args = (bad, 1) if side == "series" else (1, bad)
                with self.subTest(side=side, bad=bad), self.assertRaises(ValueError):
                    refine.array_comparison(*args, self.inputs, self.evidence, self.controller)

    def test_comparison_does_not_mutate_loaded_baseline_objects(self):
        before = copy.deepcopy((self.inputs, self.evidence, self.controller))
        refine.array_comparison(2, 1, self.inputs, self.evidence, self.controller)
        refine.thermal_requirements(self.inputs, self.evidence)
        self.assertEqual((self.inputs, self.evidence, self.controller), before)

    def test_required_thermal_resistance_not_convenient_replacement(self):
        thermal = self.result["thermal"]
        heat = 21.857142857
        self.assertAlmostEqual(thermal["required_shade_rtheta_max_k_per_w"], 15 / heat)
        self.assertAlmostEqual(thermal["required_sun_rtheta_max_k_per_w"], 15 / (heat + 48))
        self.assertAlmostEqual(thermal["required_shade_rtheta_max_k_per_w"], 0.68627451, places=8)
        self.assertAlmostEqual(thermal["required_sun_rtheta_max_k_per_w"], 0.214723926, places=8)
        self.assertAlmostEqual(thermal["shade_temperature_at_existing_assumption_c"], 67.7857142855)
        self.assertAlmostEqual(thermal["sun_temperature_at_existing_assumption_c"], 139.7857142855)
        self.assertIsNone(thermal["replacement_rtheta_selected"])
        self.assertIsNone(thermal["measured_rtheta_k_per_w"])

    def test_existing_heat_path_output_cap_below_record_and_peak(self):
        thermal = self.result["thermal"]
        self.assertAlmostEqual(thermal["shade_enclosed_heat_cap_w_at_existing_rtheta"], 10)
        self.assertAlmostEqual(thermal["shade_pi_and_usb_output_cap_w_at_existing_rtheta"], 7)
        self.assertAlmostEqual(thermal["shade_pi_and_usb_output_cap_a_at_5v1"], 7 / 5.1)
        loads = {s["state"]: s for s in thermal["workload_comparison"]}
        self.assertAlmostEqual(loads["record"]["pi_and_usb_output_w"], 9.18)
        self.assertAlmostEqual(loads["peak"]["pi_and_usb_output_w"], 15.3)
        self.assertTrue(loads["record"]["exceeds_shade_output_cap"])
        self.assertTrue(loads["peak"]["exceeds_shade_output_cap"])
        self.assertFalse(thermal["workload_reduction_justified"])
        self.assertTrue(thermal["sun_heat_alone_exceeds_headroom_at_existing_rtheta"])

    def test_uncertainty_aware_acceptance_arithmetic_and_invalid_inputs(self):
        self.assertTrue(refine.uncertainty_temperature_screen(48, 2)["inequality_passes"])
        self.assertFalse(refine.uncertainty_temperature_screen(48.1, 2)["inequality_passes"])
        self.assertFalse(refine.uncertainty_temperature_screen(48, 2)["qualification"])
        for air, uncertainty in ((48, -1), (math.nan, 1), (48, math.inf), (True, 1)):
            with self.subTest(values=(air, uncertainty)), self.assertRaises(ValueError):
                refine.uncertainty_temperature_screen(air, uncertainty)

    def test_every_scenario_remains_blocked_and_not_adopted(self):
        for record in [self.result, *self.result["arrays"]]:
            self.assertEqual(record["disposition"], "BLOCKED_ON_THERMAL_POWER_PATH_AND_PART_SELECTION")
            self.assertFalse(record["all_reference_hardware_qualified"])
            self.assertFalse(record["adopted_configuration"])
            self.assertFalse(record["energization_allowed"])
        self.assertFalse(self.result["thermal"]["thermal_qualified"])
        self.assertFalse(self.result["thermal"]["uncertainty_acceptance"]["live_tests_authorized"])
        self.assertTrue(self.result["remaining_physical_blockers"])

    def test_cli_deterministic_and_cannot_overwrite_frozen_evidence(self):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, str(SCRIPT)]
        first = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env, check=True)
        second = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env, check=True)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, "")
        self.assertEqual(first.stdout, refine.base.deterministic_json(self.result))
        self.assertEqual(first.stdout, (ROOT / "hardware/electronics/refinement-evidence.json").read_text())
        forbidden = subprocess.run(command + ["--output", str(ROOT / "hardware/electronics/reference-evidence.json")],
                                   capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(forbidden.returncode, 2)
        self.assertEqual(forbidden.stdout, "")
        self.assertEqual(refine.baseline_hashes(), self.hashes)


if __name__ == "__main__":
    unittest.main()
