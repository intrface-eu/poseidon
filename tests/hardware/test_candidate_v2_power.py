"""Offline HW-CAND-2.0 source/arithmetic checks; no electrical measurements."""
from __future__ import annotations

import copy
import csv
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "hardware/candidates/passive-v2/power"
SPEC = importlib.util.spec_from_file_location("candidate_v2_power", HERE / "calculate.py")
assert SPEC and SPEC.loader
power = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(power)


class CandidateV2PowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = power.load_context()

    def setUp(self):
        self.context = copy.deepcopy(self.frozen)
        self.result = power.calculate(self.context)

    def test_historical_baseline_and_failed_evidence_unchanged(self):
        check = power.baseline_check()
        self.assertTrue(check["all_unchanged"])
        self.assertEqual(check["evidence_sha256"], "dfc71d2a6bfffc8a99b12e83af9e5daf9ad33ead8da6337c50cdfb7f1b17e40f")
        self.assertFalse(self.context["baseline_evidence"]["thermal"]["shade_screen_passes"])
        self.assertFalse(self.context["baseline_evidence"]["solar"]["hot_voc_start_screen_passes"])

    def test_two_real_panel_quantities_geometry_and_cad_key(self):
        geometry = self.result["geometry_contract"]
        self.assertEqual(geometry["cad_bom_id"], "REEF-PV-2S")
        self.assertEqual(geometry["panel_quantity"], 2)
        self.assertEqual(geometry["panel_xyz_mm"], [668, 425, 25])
        self.assertEqual(geometry["combined_panel_footprint_mm"], [668, 900])
        self.assertAlmostEqual(237.5 - (-237.5) - 425, geometry["gap_mm"])
        self.assertFalse(geometry["fit_qualified_here"])

    def test_candidate_requires_two_series_not_unmatched_one_panel_cad(self):
        for change in ("one_panel", "parallel", "bom_quantity", "gap"):
            context = copy.deepcopy(self.context)
            if change == "one_panel":
                context["candidate"]["array"]["series"] = 1
            elif change == "parallel":
                context["candidate"]["array"].update(series=1, parallel=2)
            elif change == "bom_quantity":
                context["bom"]["parts"][0]["quantity"] = 1
            else:
                context["candidate"]["array"]["panel_gap_mm"] = 0
            with self.subTest(change=change), self.assertRaises(ValueError):
                power.calculate(context)

    def test_series_power_voltage_and_controller_screens(self):
        array = self.result["array"]
        self.assertEqual(array["array_stc_w"], 80)
        self.assertAlmostEqual(array["stc_voc_v"], 44.9)
        self.assertAlmostEqual(array["cold_voc_v"], 50.40025)
        self.assertAlmostEqual(array["hot_voc_v"], 37.82825)
        self.assertAlmostEqual(array["design_isc_a"], 3)
        self.assertAlmostEqual(array["ideal_charge_a_at_min_battery"], 80 / 11.2)
        self.assertAlmostEqual(array["required_start_v"], 19.4)
        self.assertTrue(array["all_catalog_array_screens_pass"])
        self.assertFalse(array["tolerance_cable_and_loaded_start_qualified"])

    def test_invalid_counts_and_excessive_controller_loads_fail(self):
        original = self.context["baseline_inputs"]
        for bad in (0, -1, True, 1.0, "2", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                power.array_screen(bad, 1, original["solar"], original["rails"], 145)
        excessive = power.array_screen(4, 5, original["solar"], original["rails"], 145)
        self.assertFalse(excessive["all_catalog_array_screens_pass"])
        self.assertFalse(excessive["screens"]["cold_voc_below75v"])
        self.assertFalse(excessive["screens"]["design_isc_below13a"])
        self.assertFalse(excessive["screens"]["charge_current_within10a"])
        self.assertFalse(excessive["screens"]["stc_power_within_nominal145w"])

    def test_unchanged_load_weather_heat_and_charge_discharge_boundary(self):
        preserved = self.result["preserved_comparison"]
        self.assertEqual(preserved["ambient_c"], 35)
        self.assertAlmostEqual(preserved["hub_peak_enclosed_heat_w"], 21.857142857)
        self.assertEqual(preserved["absorbed_sun_w"], 48)
        self.assertEqual(preserved["peak_sun_hours"], 1)
        self.assertEqual(preserved["reef_daily_wh"], 27.5247475)
        energy = self.result["baseline_only_energy_comparison"]
        self.assertAlmostEqual(energy["harvest_stored_wh_per_day"], 46.8)
        self.assertAlmostEqual(energy["harvest_wh_per_day"], 42.12)
        self.assertAlmostEqual(energy["net_wh_per_day"], 14.5952525)

    def test_no_convenient_load_ambient_or_zero_sun_change(self):
        for key, value in (("ambient_c", 25), ("hub_peak_enclosed_heat_w", 10),
                           ("peak_sun_hours", 2), ("reef_baseline_daily_wh", 20),
                           ("load_reduction_allowed", True), ("zero_sun_shade_substitution_allowed", True)):
            context = copy.deepcopy(self.context)
            context["candidate"]["fixed_comparison"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                power.calculate(context)

    def test_all_selected_nominal_quiescent_power_added_without_subtraction(self):
        overlay = self.result["selected_nominal_ancillary_overlay"]
        self.assertEqual(len(overlay), 4)
        self.assertAlmostEqual(sum(r["catalog_current_a"] for r in overlay), 0.0096)
        self.assertAlmostEqual(sum(r["added_nominal_w"] for r in overlay), 0.12288)
        account = self.result["ancillary_accounting"]
        self.assertAlmostEqual(account["nominal_added_wh_per_day"], 2.94912)
        self.assertAlmostEqual(account["retained_baseline_load_wh_per_day"], 27.5247475)
        self.assertAlmostEqual(account["cases"][0]["candidate_load_wh_per_day_under_assumption"], 30.4738675)
        self.assertTrue(all(not r["guaranteed_maximum"] for r in overlay))

    def test_unknown_losses_can_flip_energy_result_but_no_autonomy_claim(self):
        account = self.result["ancillary_accounting"]
        cases = {c["assumed_unknown_extra_w"]: c for c in account["cases"]}
        self.assertAlmostEqual(account["remaining_unknown_power_allowance_before_energy_deficit_w"], 0.4852555208333333)
        self.assertTrue(cases[0]["energy_screen_passes_under_assumption"])
        self.assertFalse(cases[0.5]["energy_screen_passes_under_assumption"])
        self.assertAlmostEqual(cases[0.5]["net_load_side_wh_per_day_under_assumption"], -0.3538675)
        self.assertIsNone(account["actual_total_candidate_load_wh_per_day"])
        self.assertIsNone(account["actual_autonomy_days"])
        self.assertTrue(all(not c["autonomy_qualified"] for c in cases.values()))

    def test_selected_unknown_power_cannot_be_omitted_or_invented(self):
        for change in ("omit_part", "empty_unknowns", "invent_total"):
            context = copy.deepcopy(self.context)
            a = context["candidate"]["ancillary_accounting"]
            if change == "omit_part":
                a["selected_quiescent_parts"].pop()
            elif change == "empty_unknowns":
                a["unknown_selected_overheads"] = []
            else:
                a["measured_or_guaranteed_total_ancillary_w"] = 0
            with self.subTest(change=change), self.assertRaises(ValueError):
                power.calculate(context)
        with self.assertRaises(ValueError):
            power.ancillary_sensitivity(27, 42, 0.1, [-0.5], 294)

    def test_radio_tolerance_pass_does_not_claim_fault_protection(self):
        radio = self.result["reef_voltage_screens"]
        self.assertAlmostEqual(radio["radio_output_tolerance_range_v"][0], 3.168)
        self.assertAlmostEqual(radio["radio_output_tolerance_range_v"][1], 3.432)
        self.assertTrue(radio["radio_nominal_tolerance_within2_to3v6"])
        self.assertAlmostEqual(radio["radio_pg_high_status_v"], 3.96)
        self.assertTrue(radio["pg_is_not_ovp"])
        self.assertFalse(radio["fault_voltage_guaranteed_below3v6"])
        self.assertFalse(radio["current_limit_ovp_and_burst_qualified"])

    def test_smart_battery_bms_charge_path_supported_but_settings_unverified(self):
        charge = self.result["charge_control"]
        self.assertIn("NOT NG-only", charge["bms_battery_family"])
        self.assertAlmostEqual(charge["bms_high_signal_range_v"][0], 10.6)
        self.assertAlmostEqual(charge["bms_high_signal_range_v"][1], 13.8)
        self.assertTrue(charge["manufacturer_topology_supported"])
        self.assertTrue(charge["cable_static_enable_screen_passes"])
        self.assertFalse(charge["actual_rx_remote_setting_verified"])
        self.assertFalse(charge["ve_direct_telemetry_available_simultaneously"])
        self.assertIsNone(charge["cable_output_load_current_a"])
        self.assertTrue(self.result["load_control"]["mppt_bat_branch_bypasses_load_switch"])
        self.assertTrue(self.result["load_control"]["pv_must_not_pass_through35v_batteryprotect"])

    def test_control_wire_and_configuration_faults_block_fixture_permissions(self):
        healthy = dict(bms_powered=True, remote_enabled=True, cells_allow_load=True,
                       cells_allow_charge=True, load_wire_connected=True, charge_wire_connected=True,
                       bp_mode_c_verified=True, mppt_rx_remote_setting_verified=True)
        model = power.control_logic(**healthy)
        self.assertTrue(model["load_permission_model"])
        self.assertTrue(model["charge_permission_model"])
        self.assertFalse(model["physical_operation"])
        for fault, result_key in (("load_wire_connected", "load_permission_model"),
                                  ("charge_wire_connected", "charge_permission_model"),
                                  ("bp_mode_c_verified", "load_permission_model"),
                                  ("mppt_rx_remote_setting_verified", "charge_permission_model"),
                                  ("cells_allow_charge", "charge_permission_model")):
            with self.subTest(fault=fault):
                self.assertFalse(power.control_logic(**{**healthy, fault: False})[result_key])
        model = power.control_logic(**{**healthy, "bms_powered": False})
        self.assertFalse(model["load_permission_model"])
        self.assertFalse(model["charge_permission_model"])
        with self.assertRaises(ValueError):
            power.control_logic(**{**healthy, "bms_powered": "true"})

    def test_blocked_fuse_sources_and_bench_supply_never_close_field_path(self):
        hub = self.result["hub_power"]
        self.assertFalse(hub["qualified_12v_usbc_source_selected"])
        self.assertFalse(hub["bench_alternative_resolves_field_dc"])
        self.assertIn("SC0444", hub["bench_alternative"])
        self.assertFalse(hub["bench_operations_authorized"])
        self.assertIsNone(self.result["protection"]["selected_verified_main_fuse"])
        self.assertFalse(self.result["protection"]["fuse_interrupt_and_wire_coordination_qualified"])
        parts = {p["id"]: p for p in self.context["bom"]["parts"]}
        self.assertIsNone(parts["V2-FLOAD-CAND"]["rated_values"]["dc_voltage_v"])
        self.assertIsNone(parts["V2-FLOAD-CAND"]["rated_values"]["interrupt_a"])
        self.assertIsNone(parts["V2-FHOLD-CAND"]["rated_values"]["current_a"])
        self.assertTrue(all(len(b["families_screened"]) <= 3 for b in self.result["bounded_source_blocks"]))

    def test_captured_sources_and_editable_wiring_are_traceable(self):
        captures = self.result["source_captures"]
        self.assertEqual(len(captures), 13)
        self.assertEqual(len({c["file"] for c in captures}), 13)
        registered = {c["file"]: c for s in self.context["sources"]["sources"] for c in s["captures"]}
        for capture in captures:
            self.assertEqual(capture["sha256"], registered[capture["file"]]["sha256"])
            self.assertEqual(capture["retrieved_date"], "2026-09-08")
            self.assertTrue(capture["url"].startswith("https://"))
            self.assertFalse((HERE / capture["file"]).exists())
        with (HERE / "wiring.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(rows)
        self.assertTrue(all(None not in row and all(v is not None for v in row.values()) for row in rows))
        by_id = {r["net_id"]: r for r in rows}
        self.assertIn("J5.9", by_id["W2-RAK3"]["to_terminal"])
        self.assertIn("RemoteH", by_id["W2-LOADCTRL"]["to_terminal"])
        self.assertIn("Remote on/off", by_id["W2-CHGRX"]["to_terminal"])
        self.assertIn("Positive", by_id["W2-PVSERIES"]["from_terminal"])
        self.assertIn("Negative", by_id["W2-PVSERIES"]["to_terminal"])

    def test_no_product_release_or_physical_actuation_claim(self):
        self.assertEqual(self.result["status"], "NON_ADOPTED_NOT_BUILD_AUTHORIZED")
        self.assertFalse(self.result["all_hardware_qualified"])
        self.assertFalse(self.result["energization_allowed"])
        self.assertFalse(self.result["thermal"]["heat_path_qualified_here"])
        self.assertFalse(self.context["bom"]["purchase_authorized"])
        self.assertFalse(self.context["bom"]["quote_available"])
        self.context["candidate"]["output_boundary"]["amplifier_installed"] = True
        with self.assertRaises(ValueError):
            power.calculate(self.context)

    def test_cli_stored_evidence_is_deterministic_and_baseline_output_denied(self):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, str(HERE / "calculate.py")]
        first = subprocess.run(command, capture_output=True, text=True, timeout=60, env=env, check=True)
        second = subprocess.run(command, capture_output=True, text=True, timeout=60, env=env, check=True)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, "")
        self.assertEqual(first.stdout, power.base.deterministic_json(self.result))
        self.assertEqual(first.stdout, (HERE / "evidence.json").read_text())
        denied = subprocess.run(command + ["--output", str(ROOT / "hardware/electronics/reference-evidence.json")],
                                capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(denied.returncode, 2)
        self.assertEqual(denied.stdout, "")
        self.assertEqual(power.baseline_check(), self.context["baseline_check"])


if __name__ == "__main__":
    unittest.main()
