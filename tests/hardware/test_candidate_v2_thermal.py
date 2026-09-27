import copy
import hashlib
import importlib.util
import json
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "hardware/candidates/passive-v2"
SPEC = importlib.util.spec_from_file_location("candidate_thermal_v2", CANDIDATE / "thermal/model.py")
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)


class CandidateThermalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs, cls.interface, cls.sources, cls.baseline_inputs = MODEL.load()
        cls.report = MODEL.build()

    def run_case(self, **overrides):
        params = dict(self.inputs["reference_sensitivity_case"], **overrides)
        return MODEL.case("test", params, self.inputs, self.interface, self.sources)

    def test_baseline_heat_environment_and_evidence_unchanged(self):
        source = ROOT / "hardware/electronics/reference-evidence.json"
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), MODEL.BASELINE_HASH)
        self.assertEqual(self.report["frozen_comparison"], {
            "ambient_c":35, "enclosed_peak_heat_w":21.857142857,
            "potential_absorbed_sun_w":48, "pi_vendor_ambient_limit_c":50})
        self.assertFalse(self.report["baseline_modified"])

    def test_vendor_dimensions_and_orientation(self):
        hub = self.interface["mechanical"]["hub"]
        self.assertEqual(hub["vendor_lwh_mm"], [275,175,66.6])
        self.assertEqual(hub["cad_xyz_mm"], [275,66.6,175])
        sink = self.interface["mechanical"]["heat_sink"]
        self.assertAlmostEqual(sink["profile_width_mm"], 10.78*25.4)
        self.assertAlmostEqual(sink["profile_depth_mm"], 3.77*25.4)
        self.assertAlmostEqual(sink["candidate_cut_length_mm"], 3*25.4)
        self.assertNotEqual(sink["stock_length_mm"], sink["candidate_cut_length_mm"])

    def test_contact_area_and_square_inch_conversion(self):
        result = self.run_case(contact_pressure_psi=50)
        self.assertAlmostEqual(result["effective_contact_area_m2"], .014)
        self.assertAlmostEqual(result["pad_interface_r_each_k_per_w"], .45*.0254**2/.014)
        # Quoted impedance already includes the pad/interface; no extra t/k term.
        self.assertAlmostEqual(result["common_wall_to_ambient_r_k_per_w"], .5 + .45*.0254**2/.014 + .0025/(70*.014))

    def test_pressure_force_is_exposed_not_an_approved_clamp(self):
        result = self.run_case(contact_pressure_psi=10)
        self.assertAlmostEqual(result["implied_total_clamp_force_per_interface_n"], 10*6894.757293168*.014)
        self.assertGreater(result["implied_total_clamp_force_per_interface_n"], 900)
        self.assertIn("NOT an allowed load", result["clamp_force_note"])
        self.assertIsNone(self.interface["mechanical"]["thermal_interfaces"]["clamping_pressure_psi"])

    def test_material_and_contact_area_sensitivity(self):
        first = self.run_case()
        higher_k = self.run_case(material_conductivity_w_mk=200)
        half_area = self.run_case(effective_contact_area_fraction=.5)
        self.assertLess(higher_k["base_through_thickness_r_k_per_w"], first["base_through_thickness_r_k_per_w"])
        self.assertAlmostEqual(half_area["pad_interface_r_each_k_per_w"], first["pad_interface_r_each_k_per_w"]*2)
        self.assertGreater(half_area["calculated_lumped_internal_air_c"], first["calculated_lumped_internal_air_c"])

    def test_contact_pressure_uses_vendor_points_without_interpolation(self):
        low = self.run_case(contact_pressure_psi=10)
        high = self.run_case(contact_pressure_psi=50)
        self.assertGreater(low["pad_interface_r_each_k_per_w"], high["pad_interface_r_each_k_per_w"])
        with self.assertRaisesRegex(ValueError, "tabulated"):
            self.run_case(contact_pressure_psi=42)

    def test_heat_is_conserved_at_common_path(self):
        result = self.run_case(residual_solar_fraction=.25)
        self.assertAlmostEqual(result["heat_leaving_common_path_w"], 21.857142857+12)
        self.assertAlmostEqual(result["calculated_common_wall_c"], 35+(21.857142857+12)*result["common_wall_to_ambient_r_k_per_w"])

    def test_sun_fraction_not_silently_zero_and_no_whole_case_pass(self):
        dark_limit = self.run_case(residual_solar_fraction=0, heat_capture_fraction=1)
        sun = self.run_case(residual_solar_fraction=1, heat_capture_fraction=1)
        self.assertGreater(sun["calculated_lumped_internal_air_c"], dark_limit["calculated_lumped_internal_air_c"])
        self.assertGreater(sun["required_capture_fraction_for_air_inequality_unclamped"], 1)
        for item in self.report["cases"]:
            self.assertFalse(item["installed_thermal_qualified"])
            self.assertEqual(item["candidate_acceptance"], "UNKNOWN_INSTALLED_CONTACT_HEAT_CAPTURE_SINK_AND_SHADE")
        self.assertIsNone(self.report["actual_installed_values"]["residual_solar_fraction"])

    def test_capture_fraction_and_air_coupling_are_not_plate_temperature(self):
        no_capture = self.run_case(residual_solar_fraction=0, heat_capture_fraction=0)
        collected = self.run_case(residual_solar_fraction=0, heat_capture_fraction=.9)
        self.assertGreater(no_capture["calculated_lumped_internal_air_c"], collected["calculated_lumped_internal_air_c"])
        self.assertNotEqual(collected["calculated_collector_c"], collected["calculated_lumped_internal_air_c"])
        self.assertIsNone(self.report["actual_installed_values"]["heat_capture_fraction"])

    def test_roof_geometry_cannot_prove_full_shading(self):
        geometry = self.report["geometry"]
        self.assertAlmostEqual(geometry["roof_plan_area_m2"], .375*.275)
        self.assertAlmostEqual(geometry["roof_top_edge_complete_shadow_min_elevation_deg_x_section"], math.degrees(math.atan(75/50)))
        self.assertAlmostEqual(geometry["roof_bottom_edge_complete_shadow_min_elevation_deg_x_section"], math.degrees(math.atan(250/50)))
        self.assertGreater(geometry["roof_bottom_edge_complete_shadow_min_elevation_deg_x_section"], 78)
        self.assertAlmostEqual(self.report["shade_absorbed_power_if_baseline_irradiance_and_absorptivity_apply_w"], 41.25)
        self.assertEqual(self.report["frozen_comparison"]["potential_absorbed_sun_w"], 48)

    def test_invalid_parameters_fail(self):
        for field, value in (("heat_capture_fraction",1.1),("residual_solar_fraction",-.1),
                             ("sink_reference_multiplier",.5),("effective_contact_area_fraction",0),
                             ("material_conductivity_w_mk",float("nan")),("internal_convection_w_m2k",True)):
            with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                self.run_case(**{field:value})

    def test_supplier_hashes_pinned_without_redistributed_pdf(self):
        register = json.loads((CANDIDATE / "sources/thermal-sources.json").read_text())
        by_id = {row["id"]: row for row in register["sources"]}
        for id, source in self.report["source_evidence"].items():
            self.assertEqual(source["sha256"], by_id[id]["sha256"])
            self.assertFalse((CANDIDATE / "sources" / source["local_file"]).exists())

    def test_actual_installed_values_and_release_remain_unknown(self):
        self.assertTrue(all(value is None for value in self.report["actual_installed_values"].values()))
        self.assertFalse(self.report["thermal_qualified"])
        self.assertFalse(self.report["adopted"])
        self.assertFalse(self.report["purchase_authorized"])
        self.assertEqual(self.report["physical_tests_performed"], 0)

    def test_stored_results_reproduce(self):
        stored = json.loads((CANDIDATE / "thermal/results.json").read_text())
        self.assertEqual(stored, self.report)


if __name__ == "__main__":
    unittest.main()
