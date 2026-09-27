"""Offline numerical/reference checks, not electrical or acoustic measurements."""
from __future__ import annotations

import copy
import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
ELECTRONICS = ROOT / "hardware" / "electronics"
SPEC = importlib.util.spec_from_file_location("poseidon_electrical_calculate", ELECTRONICS / "calculate.py")
assert SPEC and SPEC.loader
calc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calc)


class ElectricalEquationTests(unittest.TestCase):
    def test_battery_capacity_and_all_derating_factors(self):
        value = calc.battery_usable_wh(12.8, 50, 0.8, 0.8, 0.8, 0.9)
        self.assertAlmostEqual(value, 294.912, places=8)
        self.assertAlmostEqual(calc.battery_usable_wh(12.8, 50, 1, 1, 1, 1), 640)

    def test_battery_capacity_sensitivity(self):
        baseline = calc.battery_usable_wh(12.8, 50, 0.8, 0.8, 0.8, 0.9)
        self.assertAlmostEqual(calc.battery_usable_wh(12.8, 25, 0.8, 0.8, 0.8, 0.9), baseline / 2)
        self.assertAlmostEqual(calc.battery_usable_wh(12.8, 50, 0.8, 0.8, 0.4, 0.9), baseline / 2)

    def test_invalid_fractions_are_not_silently_clamped(self):
        for bad in (0, -1, 1.01, math.nan, math.inf, True, "0.8"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                calc.battery_usable_wh(12.8, 50, bad, 0.8, 0.8, 0.9)

    def test_loop_counts_both_conductors_and_contacts(self):
        self.assertAlmostEqual(calc.loop_resistance(25, 0.75, 20, 0.05), 1.2166666666666668)
        self.assertAlmostEqual(calc.loop_resistance(25, 0.75, 40, 0.05), 1.3083666666666667)

    def test_loop_length_area_temperature_sensitivity(self):
        base = calc.loop_resistance(10, 1, 20, 0)
        self.assertAlmostEqual(calc.loop_resistance(20, 1, 20, 0), 2 * base)
        self.assertAlmostEqual(calc.loop_resistance(10, 2, 20, 0), base / 2)
        self.assertGreater(calc.loop_resistance(10, 1, 60, 0), base)

    def test_invalid_tether_inputs(self):
        for length, area, temp, contact in ((-1, 1, 20, 0), (1, 0, 20, 0),
                                             (1, 1, 500, 0), (1, 1, 20, -0.1)):
            with self.subTest(values=(length, area, temp, contact)), self.assertRaises(ValueError):
                calc.loop_resistance(length, area, temp, contact)

    def test_constant_power_tether_conserves_power(self):
        result = calc.constant_power_tether(12, 12, 1)
        expected_v = (12 + math.sqrt(96)) / 2
        self.assertAlmostEqual(result["load_v"], expected_v)
        self.assertAlmostEqual(result["load_v"] * result["current_a"], 12)
        self.assertAlmostEqual(12 * result["current_a"], result["source_w"])
        self.assertAlmostEqual(result["cable_loss_w"], result["current_a"] ** 2)
        self.assertAlmostEqual(result["collapse_power_w"], 36)

    def test_constant_power_rejects_collapse_and_threshold(self):
        for power in (36, 40):
            with self.subTest(power=power), self.assertRaises(ValueError):
                calc.constant_power_tether(12, power, 1)

    def test_zero_loss_and_unloaded_tether(self):
        zero_r = calc.constant_power_tether(12, 6, 0)
        self.assertEqual(zero_r["load_v"], 12)
        self.assertEqual(zero_r["current_a"], 0.5)
        self.assertEqual(zero_r["cable_loss_w"], 0)
        self.assertIsNone(zero_r["collapse_power_w"])
        self.assertEqual(calc.constant_power_tether(12, 0, 2)["load_v"], 12)

    def test_capacitor_ramp_current_energy_and_i2t(self):
        result = calc.capacitor_startup(0.0047, 14.4, 0.01, 2)
        self.assertAlmostEqual(result["assumed_linear_ramp_capacitor_current_a"], 6.768)
        self.assertAlmostEqual(result["coincident_assumed_current_a"], 8.768)
        self.assertAlmostEqual(result["stored_energy_j"], 0.487296)
        self.assertAlmostEqual(result["rectangular_coincident_i2t_a2s"], 8.768 ** 2 * 0.01)

    def test_inrush_ramp_sensitivity_and_invalid_ramp(self):
        a = calc.capacitor_startup(0.0047, 14.4, 0.01, 0)
        b = calc.capacitor_startup(0.0047, 14.4, 0.02, 0)
        self.assertAlmostEqual(a["assumed_linear_ramp_capacitor_current_a"], 2 * b["assumed_linear_ramp_capacitor_current_a"])
        self.assertEqual(a["stored_energy_j"], b["stored_energy_j"])
        with self.assertRaises(ValueError):
            calc.capacitor_startup(0.0047, 14.4, 0, 1)

    def test_thermal_heat_and_solar_add(self):
        self.assertAlmostEqual(calc.enclosure_temperature(35, 20, 1.5), 65)
        self.assertAlmostEqual(calc.enclosure_temperature(35, 20, 1.5, 48), 137)
        self.assertAlmostEqual(calc.enclosure_temperature(35, 20, 0.75), 50)

    def test_thermal_rejects_bad_inputs(self):
        for heat, theta in ((-1, 1), (1, 0), (1, -1), (math.nan, 1)):
            with self.subTest(heat=heat, theta=theta), self.assertRaises(ValueError):
                calc.enclosure_temperature(35, heat, theta)

    def test_solar_deficit_break_even_and_no_sun(self):
        result = calc.solar_energy(40, 1, 0.65, 0.9, 30)
        self.assertAlmostEqual(result["harvest_wh_per_day"], 23.4)
        self.assertAlmostEqual(result["net_wh_per_day"], -6.6)
        self.assertAlmostEqual(result["break_even_peak_sun_hours"], 30 / 23.4)
        self.assertFalse(result["sustainable_under_assumptions"])
        self.assertEqual(calc.solar_energy(40, 0, 0.65, 0.9, 30)["harvest_wh_per_day"], 0)

    def test_solar_harvest_and_load_share_discharge_energy_boundary(self):
        result = calc.solar_energy(40, 1, 0.65, 0.9, 30, 0.9)
        self.assertAlmostEqual(result["harvest_stored_wh_per_day"], 23.4)
        self.assertAlmostEqual(result["harvest_wh_per_day"], 21.06)
        self.assertAlmostEqual(result["net_wh_per_day"], -8.94)
        self.assertAlmostEqual(result["break_even_peak_sun_hours"], 30 / 21.06)
        with self.assertRaises(ValueError):
            calc.solar_energy(40, 1, 0.65, 0.9, 30, 0)

    def test_solar_temperature_voltage(self):
        self.assertAlmostEqual(calc.pv_voc_at_temperature(22.45, -0.0035, -10), 25.200125)
        self.assertAlmostEqual(calc.pv_voc_at_temperature(22.45, -0.0035, 70), 18.914125)
        self.assertEqual(calc.pv_voc_at_temperature(22.45, -0.0035, 25), 22.45)

    def test_solar_rejects_nonphysical_values(self):
        for args in ((0, 1, 0.65, 0.9, 30), (40, 25, 0.65, 0.9, 30),
                     (40, 1, 1.1, 0.9, 30), (40, 1, 0.65, 0.9, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                calc.solar_energy(*args)
        with self.assertRaises(ValueError):
            calc.pv_voc_at_temperature(22.45, 0.5, -10)

    def test_fuse_ampacity_screen_is_never_certification(self):
        okay = calc.fuse_coordination_screen(3, 4, 5, 5)
        self.assertTrue(okay["inequality_passes"])
        self.assertFalse(okay["certified"])
        self.assertFalse(calc.fuse_coordination_screen(3, 6, 5, 10)["inequality_passes"])
        self.assertFalse(calc.fuse_coordination_screen(5, 4, 6, 6)["inequality_passes"])
        self.assertFalse(calc.fuse_coordination_screen(3, 4, 5, 3.5)["inequality_passes"])


class ElectricalReferenceTests(unittest.TestCase):
    def setUp(self):
        self.inputs = calc.load_inputs(ELECTRONICS / "reference-inputs.json")
        self.result = calc.build_evidence(self.inputs)

    def test_hub_full_usb_supply_and_conversion_loss(self):
        hub = self.result["hub"]
        self.assertEqual(hub["required_source_a"], 3)
        self.assertAlmostEqual(hub["required_source_w"], 15.3)
        self.assertAlmostEqual(hub["peak"]["converter_loss_w"], 15.3 / 0.7 - 15.3)
        self.assertAlmostEqual(hub["peak"]["bus_w"], 15.3 / 0.7 + self.result["tether"]["at_min_battery"]["source_w"])
        self.assertFalse(hub["usb_c_path_qualified"])

    def test_hub_daily_energy_includes_cable_loss_without_double_counting(self):
        hub = self.result["hub"]
        expected_5v_and_camera_without_cable = 5.1 + 20 * (9.18 / 0.7 + 4) + 3 * (11.73 / 0.7 + 4)
        cable = sum(s["camera_cable_loss_w"] * s["hours"] for s in hub["states"])
        self.assertGreater(cable, 0)
        self.assertAlmostEqual(hub["daily_wh"], expected_5v_and_camera_without_cable + cable)
        self.assertAlmostEqual(hub["daily_wh"], sum(s["wh"] for s in hub["states"]))
        self.assertEqual(sum(s["hours"] for s in hub["states"]), 24)

    def test_reef_board_radio_and_controller_overhead(self):
        reef = self.result["reef"]
        self.assertAlmostEqual(reef["daily_wh"], 27.5247475)
        self.assertAlmostEqual(reef["peak"]["bus_w"], 4.948)
        self.assertAlmostEqual(reef["peak"]["controller_bms_bus_w"], 0.328)
        self.assertAlmostEqual(reef["radio_current_headroom_over_operating_point_a"], 0.033)
        self.assertIsNone(reef["devkit_3v3_spare_a"])
        self.assertFalse(reef["radio_supply_capacity_qualified"])

    def test_reference_exposes_failed_thermal_and_solar_screens(self):
        self.assertAlmostEqual(self.result["thermal"]["estimated_shade_internal_air_c"], 67.7857142857)
        self.assertFalse(self.result["thermal"]["shade_screen_passes"])
        self.assertFalse(self.result["thermal"]["sun_screen_passes"])
        self.assertAlmostEqual(self.result["solar"]["net_wh_per_day"], -6.4647475)
        self.assertFalse(self.result["solar"]["sustainable_under_assumptions"])
        self.assertFalse(self.result["solar"]["hot_voc_start_screen_passes"])
        self.assertAlmostEqual(self.result["solar"]["required_start_v_at_max_battery"], 19.4)
        self.assertFalse(self.result["energization_allowed"])

    def test_static_battery_input_range_and_tether_numbers(self):
        rail = self.result["battery_rail_screen"]
        self.assertEqual((rail["minimum_v"], rail["maximum_v"]), (11.2, 14.4))
        self.assertTrue(rail["converter_static_range_passes"])
        self.assertAlmostEqual(self.result["tether"]["at_min_battery"]["load_v"], 10.170893421, places=8)
        self.assertFalse(rail["transients_drop_and_regulators_qualified"])
        self.assertFalse(self.result["tether"]["camera_range_vendor_verified"])

    def test_valid_but_incompatible_rails_fail_screen_not_silently_pass(self):
        self.inputs["rails"]["battery_min_v"] = 9.0
        self.assertFalse(calc.build_evidence(self.inputs)["battery_rail_screen"]["converter_static_range_passes"])
        self.inputs["rails"]["radio_supply_v"] = 5.0
        result = calc.build_evidence(self.inputs)
        self.assertFalse(result["battery_rail_screen"]["radio_static_regulated_range_passes"])
        self.assertFalse(result["energization_allowed"])

    def test_sensitivity_efficiency_changes_loss_not_useful_power(self):
        baseline = self.result
        self.inputs["converter"]["efficiency"] = 0.9
        result = calc.build_evidence(self.inputs)
        self.assertLess(result["hub"]["daily_wh"], baseline["hub"]["daily_wh"])
        self.assertEqual(result["hub"]["peak"]["output_5v_w"], baseline["hub"]["peak"]["output_5v_w"])
        self.assertLess(result["thermal"]["estimated_shade_internal_air_c"], baseline["thermal"]["estimated_shade_internal_air_c"])

    def test_sensitivity_doubled_panel_does_not_close_bms_or_start_gate(self):
        self.inputs["solar"]["panel_stc_w"] = 80
        result = calc.build_evidence(self.inputs)
        self.assertAlmostEqual(result["solar"]["harvest_wh_per_day"], 42.12)
        self.assertTrue(result["solar"]["sustainable_under_assumptions"])
        self.assertFalse(result["solar"]["hot_voc_start_screen_passes"])
        self.assertFalse(result["battery"]["bms_power_path_qualified"])
        self.assertFalse(result["energization_allowed"])

    def test_sensitivity_smaller_battery_and_missing_solar(self):
        self.inputs["battery"]["capacity_ah"] = 5
        self.inputs["solar"]["peak_sun_hours"] = 0
        result = calc.build_evidence(self.inputs)
        self.assertAlmostEqual(result["battery"]["usable_load_side_wh"], 29.4912)
        self.assertFalse(result["battery"]["reef_reserve_screen_passes"])
        self.assertAlmostEqual(result["solar"]["days_until_usable_reserve_exhaustion_at_deficit"], result["battery"]["reef_zero_solar_days"])

    def test_rejects_bad_duty_totals_and_duplicate_states(self):
        self.inputs["hub_states"][0]["hours"] = 2
        with self.assertRaises(ValueError):
            calc.build_evidence(self.inputs)
        self.inputs["hub_states"][0]["hours"] = 1
        self.inputs["hub_states"][0]["name"] = "record"
        with self.assertRaises(ValueError):
            calc.build_evidence(self.inputs)

    def test_rejects_understated_peaks_and_usb_overallocation(self):
        self.inputs["hub_peak"] = {"pi_a": 0.1, "usb_a": 0, "camera_load_w": 0}
        with self.assertRaises(ValueError):
            calc.build_evidence(self.inputs)
        self.inputs = calc.load_inputs(ELECTRONICS / "reference-inputs.json")
        self.inputs["hub_states"][1]["usb_a"] = 1.21
        with self.assertRaises(ValueError):
            calc.build_evidence(self.inputs)

    def test_rejects_active_population_even_if_software_claims_disabled(self):
        for field in ("amplifier_installed", "projector_connected", "wiper_installed"):
            values = copy.deepcopy(self.inputs)
            values["default_population"][field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                calc.build_evidence(values)
        self.inputs["default_population"]["output_actuation_gpio"] = [25]
        with self.assertRaises(ValueError):
            calc.build_evidence(self.inputs)

    def test_cli_and_stored_evidence_are_deterministic(self):
        command = [sys.executable, str(ELECTRONICS / "calculate.py")]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        first = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env, check=True)
        second = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env, check=True)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, "")
        self.assertEqual(first.stdout, calc.deterministic_json(self.result))
        self.assertEqual(first.stdout, (ELECTRONICS / "reference-evidence.json").read_text())

    def test_cli_fails_invalid_json_without_nan_evidence(self):
        with tempfile.TemporaryDirectory(prefix="electrical-test-") as directory:
            path = Path(directory) / "invalid.json"
            for content in ('{"x": NaN}', '{"x": 1, "x": 2}', '[]', '{'):
                path.write_text(content)
                result = subprocess.run([sys.executable, str(ELECTRONICS / "calculate.py"), "--inputs", str(path)],
                                        capture_output=True, text=True, timeout=30,
                                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("invalid electrical calculation", result.stderr)


class ElectricalPhysicalInhibitTests(unittest.TestCase):
    def setUp(self):
        self.model = calc.ManualInhibitModel()
        self.healthy = {"installed": True, "control_power": True, "physical_key": True,
                        "stop_a_nc_closed": True, "stop_b_nc_closed": True,
                        "independent_watchdog_ok": True, "feedback_ok": True,
                        "manual_rearm": False, "software_request": False}

    def test_software_request_cannot_energize(self):
        for _ in range(3):
            self.assertFalse(self.model.step(**{**self.healthy, "software_request": True}))

    def test_manual_release_then_press_arms_without_software(self):
        self.assertFalse(self.model.step(**self.healthy))
        self.assertTrue(self.model.step(**{**self.healthy, "manual_rearm": True}))
        self.assertTrue(self.model.step(**self.healthy))

    def test_held_reset_on_start_never_arms(self):
        for _ in range(3):
            self.assertFalse(self.model.step(**{**self.healthy, "manual_rearm": True, "software_request": True}))

    def test_every_required_interlock_fault_drops_and_blocks_auto_rearm(self):
        for fault in ("installed", "control_power", "physical_key", "stop_a_nc_closed",
                      "stop_b_nc_closed", "independent_watchdog_ok", "feedback_ok"):
            with self.subTest(fault=fault):
                model = calc.ManualInhibitModel()
                model.step(**self.healthy)
                self.assertTrue(model.step(**{**self.healthy, "manual_rearm": True}))
                self.assertFalse(model.step(**{**self.healthy, fault: False}))
                self.assertFalse(model.step(**{**self.healthy, "manual_rearm": True, "software_request": True}))
                self.assertFalse(model.step(**self.healthy))
                self.assertTrue(model.step(**{**self.healthy, "manual_rearm": True}))

    def test_default_absent_module_cannot_be_armed(self):
        for manual in (False, True, False, True):
            self.assertFalse(self.model.step(**{**self.healthy, "installed": False, "manual_rearm": manual, "software_request": True}))

    def test_non_boolean_interlocks_rejected(self):
        with self.assertRaises(ValueError):
            self.model.step(**{**self.healthy, "stop_a_nc_closed": "false"})


class ElectricalPackageTraceabilityTests(unittest.TestCase):
    def test_exact_vendor_converter_values_and_correction_are_retained(self):
        registry = json.loads((ROOT / "hardware/bom/sources.json").read_text())
        sources = {s["id"]: s for s in registry["sources"]}
        values = sources["SRC-SD50"]["verified_facts"]
        self.assertEqual(values["input_v"], [9.2, 18.0])
        self.assertEqual(values["dimensions_lwh_mm"], [159, 97, 38])
        self.assertEqual(values["efficiency_typical"], 0.70)
        self.assertEqual(values["input_output_withstand_vac"], 1500)
        self.assertIn("incorrectly", " ".join(sources["SRC-SD50"]["caveats"]))
        self.assertEqual(registry["reference"], "HW-REF-1.1")
        self.assertEqual(registry["retrieved_date"], "2026-09-08")
        self.assertTrue(all(s["url"].startswith("https://") for s in sources.values()))

    def test_bom_sources_quantities_and_missing_quotes(self):
        bom = json.loads((ROOT / "hardware/bom/reference-v1.json").read_text())
        registry = json.loads((ROOT / "hardware/bom/sources.json").read_text())
        source_ids = {s["id"] for s in registry["sources"]}
        ids = [p["id"] for p in bom["parts"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(bom["purchase_authorized"])
        self.assertFalse(bom["quotes_available"])
        self.assertIsNone(bom["quote_defaults"]["unit_price"])
        for part in bom["parts"]:
            self.assertTrue(set(part["sources"]) <= source_ids)
            if part["reference_qty"] is not None:
                self.assertGreaterEqual(part["reference_qty"], 0)
            self.assertGreaterEqual(part["populated_default_qty"], 0)
            if part["assembly"] in ("PROJECTOR", "WIPER", "ARRAY"):
                self.assertEqual(part["populated_default_qty"], 0)
            if part["mpn"] is None:
                self.assertTrue(part["gates"])

    def test_wiring_has_verified_uart_crossconnect_and_safe_power_pin(self):
        with (ROOT / "hardware/wiring/harnesses.csv").open(newline="") as handle:
            harness = {r["harness_id"]: r for r in csv.DictReader(handle)}
        self.assertEqual(harness["H-REEF-08"]["from_pin"], "J3.11 GPIO17 TX")
        self.assertEqual(harness["H-REEF-08"]["to_pin"], "J4.8 UART2_RX")
        self.assertEqual(harness["H-REEF-09"]["to_pin"], "J3.12 GPIO16 RX")
        self.assertEqual(harness["H-REEF-06"]["to_pin"], "J5.9")
        self.assertFalse(any(r["to_pin"] == "J4.9" for r in harness.values()))
        self.assertTrue(all(r["installed_default"] == "false" for r in harness.values()))
        with (ROOT / "hardware/wiring/connectors.csv").open(newline="") as handle:
            connectors = list(csv.DictReader(handle))
        self.assertTrue(all(None not in r for r in connectors))
        self.assertTrue(all(r["mating_orientation"] and r["locking_or_retention"] for r in connectors))

    def test_optional_hardware_and_fuse_ratings_stay_open(self):
        design = json.loads((ROOT / "hardware/wiring/design.json").read_text())
        physical = design["default_physical_population"]
        self.assertFalse(physical["amplifier_installed"])
        self.assertFalse(physical["projector_connected"])
        self.assertFalse(physical["output_harness_installed"])
        self.assertEqual(physical["output_actuation_gpio"], [])
        self.assertEqual(design["optional_output_safety"]["normally_open_disconnects"], ["K1", "K2"])
        self.assertTrue(design["optional_output_safety"]["independent_of_software"])
        self.assertTrue(design["optional_output_safety"]["qualification_open"])
        self.assertTrue(all(f["rating_a"] is None and f["interrupt_rating_a"] is None for f in design["fuse_schedule"]))
        self.assertFalse(design["custom_pcb"]["required"])


if __name__ == "__main__":
    unittest.main()
