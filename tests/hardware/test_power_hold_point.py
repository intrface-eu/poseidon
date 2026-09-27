import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PowerHoldPointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hold = json.loads((ROOT / "hardware/validation/thermal-power-hold-point.json").read_text())
        cls.baseline_path = ROOT / cls.hold["baseline_evidence"]
        cls.baseline = json.loads(cls.baseline_path.read_text())

    def test_failed_baseline_is_preserved_by_hash(self):
        self.assertEqual(hashlib.sha256(self.baseline_path.read_bytes()).hexdigest(), self.hold["baseline_evidence_sha256"])
        self.assertFalse(self.baseline["thermal"]["shade_screen_passes"])
        self.assertFalse(self.baseline["solar"]["sustainable_under_assumptions"])
        self.assertFalse(self.baseline["solar"]["hot_voc_start_screen_passes"])

    def test_required_heat_path_values_follow_same_inputs(self):
        blocker = self.hold["blockers"][0]
        values = blocker["unchanged_inputs"]
        limits = blocker["nominal_zero_uncertainty_screen_only"]
        headroom = values["pi_vendor_max_ambient_c"] - values["ambient_c"]
        heat = self.baseline["thermal"]["peak_enclosed_heat_w"]
        self.assertAlmostEqual(values["modeled_peak_enclosed_heat_w"], heat, places=8)
        self.assertAlmostEqual(limits["maximum_shade_rth_k_per_w"], headroom / heat, places=8)
        self.assertAlmostEqual(limits["maximum_sun_rth_k_per_w"], headroom / (heat + values["assumed_absorbed_sun_w"]), places=8)
        self.assertLess(limits["maximum_sun_rth_k_per_w"], limits["maximum_shade_rth_k_per_w"])
        self.assertLess(limits["maximum_shade_rth_k_per_w"], values["assumed_enclosure_rth_k_per_w"])

    def test_vendor_temperature_limit_matches_source(self):
        sources = json.loads((ROOT / "hardware/bom/sources.json").read_text())
        pi = next(source for source in sources["sources"] if source["id"] == "SRC-PI4")
        self.assertEqual(self.hold["blockers"][0]["unchanged_inputs"]["pi_vendor_max_ambient_c"], pi["verified_facts"]["operating_ambient_c"][1])

    def test_no_measurement_or_release_claim(self):
        self.assertEqual(self.hold["status"], "BLOCKED_NOT_AUTHORIZATION")
        self.assertEqual(self.hold["physical_tests_performed"], 0)
        self.assertFalse(self.hold["configuration_changes_adopted"])
        test = self.hold["blockers"][0]["measurement_hold_point"]
        self.assertFalse(test["activity_authorized"])
        self.assertIsNone(test["test_result"])
        self.assertEqual(test["raw_evidence"], [])

    def test_proposed_extra_panel_not_silently_populated(self):
        bom = json.loads((ROOT / "hardware/bom/reference-v1.json").read_text())
        panel = next(part for part in bom["parts"] if part["id"] == "REEF-PV-001")
        self.assertEqual(panel["reference_qty"], 1)
        interface = json.loads((ROOT / "hardware/interfaces/reference-v1.json").read_text())
        self.assertEqual(interface["revision"], self.hold["reference_revision"])
        cad = json.loads((ROOT / "hardware/cad/generated/reference-v1/manifest.json").read_text())
        reef = next(assembly for assembly in cad["assemblies"] if assembly["id"] == "REEF")
        self.assertEqual(sum(part["bom_id"] == "REEF-PV-001" for part in reef["parts"]), 1)


if __name__ == "__main__":
    unittest.main()
