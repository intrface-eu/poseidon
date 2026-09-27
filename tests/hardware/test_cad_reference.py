"""Stdlib-only CAD evidence tests, NOT live geometry tests.

Run the CAD environment's check_manifest.py --geometry to reexecute OCP/STEP/STL.
These tests deliberately report geometry_runtime_executed=False for their audit.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CAD = ROOT / "hardware/cad"
GENERATED = CAD / "generated/reference-v1"
sys.path.insert(0, str(CAD))
import parameters as cp
import check_manifest as cm
sys.path.pop(0)


def make_writable(root: Path) -> None:
    """Restore write permission on a copied tree; the source may be read-only."""
    for path in [root, *root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)


class CadParametersTests(unittest.TestCase):
    def test_revision_and_units_contract(self):
        self.assertEqual(cp.REVISION, "HW-REF-1.1")
        self.assertEqual(cp.CONFIGURATION, "reference-v1")
        self.assertEqual(cp.interface_evidence(cp.read_parameters())["bindings_checked"], 9)

    def test_primary_pi_features_are_exact(self):
        p = cp.read_parameters()
        self.assertEqual(p["pi_outline_mm"], [85, 56])
        self.assertEqual(p["pi_corner_radius_mm"], 3)
        self.assertEqual(p["pi_hole_diameter_mm"], 2.7)
        holes = p["pi_hole_centres_from_lower_left_mm"]
        self.assertEqual(holes, [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]])
        self.assertAlmostEqual(holes[1][0] - holes[0][0], 58)
        self.assertAlmostEqual(holes[2][1] - holes[0][1], 49)

    def test_source_hashes_and_stable_feature_evidence(self):
        source = cp.source_evidence()
        self.assertEqual(len(source["sha256"]), 64)
        self.assertEqual(source["sha256"], cp.purchased_source_hash(cp.PI_PDF.name))
        self.assertEqual(source["retrieved_date"], "2026-09-08")
        self.assertIn("not_verified", source)
        extra = {s["id"]: s for s in cp.additional_source_evidence()}
        self.assertEqual(extra["SRC-VICTRON-SOLAR"]["verified_features"]["cad_xyz_mm"], [668, 425, 25])
        self.assertEqual(extra["SRC-VICTRON-BATTERY"]["verified_features"]["vendor_mass_kg"], 7)

    def test_updated_battery_panel_and_power_envelopes(self):
        p = cp.read_parameters()
        self.assertEqual(p["battery_mm"], [188, 147, 199])
        self.assertEqual(p["solar_mm"], [668, 425, 25])
        self.assertEqual(p["converter_mm"], [159, 97, 38])
        self.assertEqual(p["mppt_mm"], [113, 40, 100])
        self.assertGreaterEqual(p["battery_terminal_service_mm"], 40)

    def test_numerical_tolerance_budget(self):
        checks = {c["id"]: c for c in cp.arithmetic_checks(cp.read_parameters())}
        expected = {"tray_worst_case_side_gap_x": 9.7, "tray_worst_case_side_gap_y": 9.7,
                    "camera_worst_case_radial_gap": 1.05, "hydrophone_worst_case_radial_gap": 0.65,
                    "cable_worst_case_bend_radius_margin": 5.7,
                    "pi_hole_to_m2p5_worst_case_diametral_gap": 0.1,
                    "pi_template_worst_case_diametral_gap": 0.55}
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertAlmostEqual(checks[name]["actual"], value)
                self.assertTrue(checks[name]["passed"])

    def test_reject_non_finite_zero_negative_and_boolean(self):
        for bad in (math.nan, math.inf, -math.inf, 0, -1, True, "56"):
            with self.subTest(bad=bad):
                p = cp.read_parameters()
                p["cable_bend_radius_mm"] = bad
                with self.assertRaises(ValueError):
                    cp.validate_parameters(p)

    def test_reject_tolerance_failure(self):
        for key, value in (("camera_clamp_bore_mm", 110.2), ("hydrophone_clamp_bore_mm", 32.2),
                           ("cable_bend_radius_mm", 48), ("tray_mm", [359, 259, 4])):
            with self.subTest(key=key):
                p = cp.read_parameters()
                p[key] = value
                with self.assertRaises(ValueError):
                    cp.validate_parameters(p)

    def test_reject_verified_pi_mounting_drift(self):
        p = cp.read_parameters()
        p["pi_hole_centres_from_lower_left_mm"][1][0] = 65
        with self.assertRaises(ValueError):
            cp.validate_parameters(p)

    def test_configurable_research_array(self):
        for pitch in (180, 300, 450, 600):
            p = cp.read_parameters(array_pitch=pitch)
            check = next(c for c in cp.arithmetic_checks(p) if c["id"] == "array_sensor_surface_separation")
            self.assertEqual(check["actual"], pitch - 32)
        for pitch in (179.9, 600.1):
            with self.assertRaises(ValueError):
                cp.read_parameters(array_pitch=pitch)

    def test_interface_dimension_and_units_drift_rejected(self):
        original = json.loads((ROOT / "hardware/interfaces/reference-v1.json").read_text())
        with tempfile.TemporaryDirectory(prefix="qa-interface-") as tmp:
            file = Path(tmp) / "interface.json"
            for mutation in ("units", "dimensions", "revision"):
                changed = copy.deepcopy(original)
                if mutation == "units":
                    changed["units"]["length"] = "inch"
                elif mutation == "dimensions":
                    changed["mechanical_envelopes"][0]["envelope_mm"][0] = 401
                else:
                    changed["revision"] = "HW-REF-0.0"
                file.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    cp.interface_evidence(cp.read_parameters(), file)

    def test_unknown_parameter_names_rejected(self):
        with tempfile.TemporaryDirectory(prefix="qa-parameters-") as tmp:
            file = Path(tmp) / "parameters.json"
            file.write_text('{"pressure_rating_bar": 100}')
            with self.assertRaises(ValueError):
                cp.read_parameters(file)


class CadArchivedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (GENERATED / "manifest.json").is_file():
            raise AssertionError("Canonical CAD artifacts absent; run the documented CAD generator first. This is NOT a skipped geometry success.")
        cls.manifest = json.loads((GENERATED / "manifest.json").read_text())
        cls.assemblies = {a["id"]: a for a in cls.manifest["assemblies"]}

    def test_manifest_audit_explicitly_does_not_execute_cad(self):
        result = cm.audit(GENERATED)
        self.assertFalse(result["geometry_runtime_executed"])
        self.assertEqual(result["mode"], "stdlib_manifest_audit")
        self.assertEqual(result["assemblies"], 12)
        self.assertGreater(result["archived_runtime_and_arithmetic_checks"], 400)

    def test_every_major_assembly_has_actual_step_and_dxf(self):
        self.assertTrue(cm.REQUIRED_ASSEMBLIES <= self.assemblies.keys())
        for a in self.assemblies.values():
            with self.subTest(assembly=a["id"]):
                step = (GENERATED / a["step"]).read_text()
                self.assertIn("SI_UNIT(.MILLI.,.METRE.)", step)
                self.assertIn("MANIFOLD_SOLID_BREP", step)
                dxf = (GENERATED / a["drawing_dxf"]).read_text()
                self.assertRegex(dxf, r"\$INSUNITS\s+70\s+4\s")
                self.assertIn("DIMENSION", dxf)
                self.assertGreater(len(a["parts"]), 2)

    def test_expected_hub_and_component_bounding_boxes(self):
        self.assertEqual(self.assemblies["HUB"]["bbox"]["size_mm"], [400, 300, 180])
        reef = {p["id"]: p for p in self.assemblies["REEF"]["parts"]}
        self.assertEqual(reef["REEF-BATTERY-ENV"]["bbox"]["size_mm"], [188, 147, 199])
        self.assertEqual(reef["REEF-SOLAR-ENV"]["bbox"]["size_mm"], [668, 425, 25])
        hub = {p["id"]: p for p in self.assemblies["HUB"]["parts"]}
        self.assertEqual(hub["HUB-POWER-ENV"]["bbox"]["size_mm"], [159, 97, 38])
        self.assertEqual(reef["REEF-CHARGE-ENV"]["bbox"]["size_mm"], [113, 40, 100])

    def test_passive_top_has_no_wiper_array_or_projector(self):
        parts = self.assemblies["TOP_PASSIVE"]["parts"]
        for p in parts:
            self.assertFalse(p["id"].startswith(("WIPER__", "PROJECTOR__", "ARRAY__")))
        research_ids = [p["id"] for p in self.assemblies["TOP_RESEARCH"]["parts"]]
        for prefix in ("WIPER__", "PROJECTOR__", "ARRAY__"):
            self.assertTrue(any(id.startswith(prefix) for id in research_ids))

    def test_printable_whitelist_excludes_pressure_and_critical_loads(self):
        printed = []
        for a in self.assemblies.values():
            for p in a["parts"]:
                self.assertFalse(p["pressure_boundary"])
                if p["printable"]:
                    printed.append(p["id"])
                    self.assertFalse(p["critical_load"])
                    self.assertEqual(p["material_id"], "PETG")
        self.assertEqual(set(printed), cm.PRINTABLE_IDS)
        self.assertEqual(len(printed), 4)

    def test_live_cad_evidence_has_numeric_clearance_and_roundtrip_results(self):
        for a in self.assemblies.values():
            roundtrip = next(c for c in a["checks"] if c["id"] == a["id"] + "_step_roundtrip")
            self.assertLessEqual(roundtrip["bbox_max_delta_mm"], 1e-4)
            self.assertLessEqual(roundtrip["volume_delta_mm3"], roundtrip["volume_tolerance_mm3"])
            self.assertEqual(roundtrip["expected_solids"], roundtrip["imported_solids"])
            interference = next(c for c in a["checks"] if c["id"] == a["id"] + "_physical_interference")
            self.assertEqual(interference["intersections"], [])
        checks = {c["id"]: c for c in self.assemblies["REEF"]["checks"]}
        self.assertAlmostEqual(checks["reef_battery_terminal_keepout_to_shelf"]["actual"], 73)
        self.assertGreaterEqual(checks["reef_battery_to_electronics_shelf"]["actual"], 100)

    def test_pressure_positioning_has_four_real_mount_holes(self):
        a = self.assemblies["PRESSURE_POSITIONING_FIXTURE"]
        checks = [c for c in a["checks"] if c["id"].startswith("pressure_base_mount_hole_")]
        self.assertEqual(len(checks), 4)
        for c in checks:
            self.assertTrue(c["passed"])
            self.assertLess(c["probe_overlap_mm3"], 1e-6)
            self.assertGreater(c["retained_rim_fraction"], 0.99)
        part = next(p for p in a["parts"] if p["id"] == "CAD-PRESS-POS-BASE-01")
        self.assertEqual(part["features"]["mount_holes_mm"], [[-15, -85], [265, -85], [-15, 85], [265, 85]])
        self.assertFalse(part["printable"])

    def test_no_envelope_density_mass_invented(self):
        for a in self.assemblies.values():
            for p in a["parts"]:
                if p["material_id"] in ("VENDOR_ENVELOPE", "CABLE_ENVELOPE"):
                    self.assertIsNone(p["solid_equivalent_mass_kg"])
        battery = next(p for p in self.assemblies["REEF"]["parts"] if p["id"] == "REEF-BATTERY-ENV")
        self.assertEqual(battery["features"]["vendor_mass_kg"], 7)

    def test_artifact_path_traversal_rejected(self):
        for bad in ("../manifest.json", "/etc/passwd", "step/../../manifest.json"):
            with self.assertRaises(ValueError):
                cm.safe_artifact(GENERATED, bad)

    def test_tampered_manifest_units_rejected(self):
        with tempfile.TemporaryDirectory(prefix="qa-tamper-") as tmp:
            m = copy.deepcopy(self.manifest)
            m["units"]["length"] = "inch"
            (Path(tmp) / "manifest.json").write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError, "units"):
                cm.audit(Path(tmp))

    def test_tampered_numeric_evidence_rejected(self):
        with tempfile.TemporaryDirectory(prefix="qa-tamper-") as tmp:
            m = copy.deepcopy(self.manifest)
            m["checks"][0]["actual"] += 1
            (Path(tmp) / "manifest.json").write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError, "arithmetic"):
                cm.audit(Path(tmp))

    def test_missing_major_assembly_rejected(self):
        with tempfile.TemporaryDirectory(prefix="qa-tamper-") as tmp:
            m = copy.deepcopy(self.manifest)
            m["assemblies"] = [a for a in m["assemblies"] if a["id"] != "FARM"]
            (Path(tmp) / "manifest.json").write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError, "Missing major"):
                cm.audit(Path(tmp))

    def test_corrupted_step_detected_by_hash_without_cad_runtime(self):
        with tempfile.TemporaryDirectory(prefix="qa-artifact-tamper-") as tmp:
            copydir = Path(tmp) / "copy"
            shutil.copytree(GENERATED, copydir)
            make_writable(copydir)
            path = copydir / "step/HUB.step"
            content = path.read_bytes()
            path.write_bytes(b"X" + content[1:])
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                cm.audit(copydir)


if __name__ == "__main__":
    unittest.main()
