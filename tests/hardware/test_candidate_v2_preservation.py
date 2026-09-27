import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE=ROOT/"hardware/candidates/passive-v2"
SPEC=importlib.util.spec_from_file_location("candidate_preservation_v2",CANDIDATE/"check_candidate.py")
CHECK=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class CandidatePreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.interface=json.loads((CANDIDATE/"interface.json").read_text())
        cls.baseline=json.loads((ROOT/"hardware/analysis/scenario.json").read_text())

    def test_historical_lock_excludes_supplier_capture_files(self):
        CHECK.verify_baseline()
        paths = json.loads((CANDIDATE / "baseline-lock.json").read_text())["files"]
        self.assertFalse(any("/sources/" in path for path in paths))

    def test_two_panel_wind_load_doubles_without_site_claim(self):
        report=CHECK.wind_comparison(self.interface,self.baseline)
        self.assertAlmostEqual(report["candidate_panel_area_m2"],.5678)
        self.assertEqual(report["candidate_panel_area_ratio"],2)
        final=report["rows"][-1]
        self.assertAlmostEqual(final["two_panel_candidate_force_n"],260.833125)
        self.assertAlmostEqual(final["two_panel_candidate_force_n"],2*final["one_panel_reference_force_n"])
        self.assertFalse(report["frame_strength_qualified"])

    def test_one_panel_cannot_masquerade_as_two_panel_candidate(self):
        bad=copy.deepcopy(self.interface)
        bad["mechanical"]["reef"]["panel_count"]=1
        with self.assertRaisesRegex(ValueError,"two actual"):
            CHECK.wind_comparison(bad,self.baseline)

    def test_gap_and_footprint_are_numerical(self):
        bad=copy.deepcopy(self.interface)
        bad["mechanical"]["reef"]["panel_pair_footprint_xy_mm"]=[668,850]
        with self.assertRaisesRegex(ValueError,"physical gap"):
            CHECK.wind_comparison(bad,self.baseline)

    def test_check_preserves_unknown_thermal_disposition(self):
        report=CHECK.build()
        self.assertEqual(report["thermal_screen"],"UNKNOWN_INSTALLED_CONTACT_HEAT_CAPTURE_SINK_AND_SHADE")
        self.assertEqual(report["thermal_sensitivity_cases"],26)
        self.assertFalse(report["adopted"])
        self.assertEqual(report["physical_tests_performed"],0)

    def test_stored_review_reproduces(self):
        stored=json.loads((CANDIDATE/"review-results.json").read_text())
        self.assertEqual(CHECK.build(),stored)


if __name__ == "__main__":
    unittest.main()
