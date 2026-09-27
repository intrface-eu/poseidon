"""Stdlib candidate evidence tests. Live OCP/STEP tests use candidate check.py --geometry."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
CAD=ROOT/"hardware/candidates/passive-v2/cad"
OUT=CAD/"generated/passive-v2"
sys.path.insert(0,str(CAD))
import candidate_parameters as cp
spec=importlib.util.spec_from_file_location("passive_v2_cad_check",CAD/"check.py")
checker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
sys.path.pop(0)


def make_writable(root: Path) -> None:
    """Restore write permission on a copied tree; the source may be read-only."""
    for path in [root, *root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)


class CandidateV2CadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters=cp.load()
        cls.manifest=json.loads((OUT/"manifest.json").read_text())
        cls.assemblies={a["id"]:a for a in cls.manifest["assemblies"]}

    def test_distinct_non_adopted_revision(self):
        self.assertEqual(cp.REVISION,"HW-CAND-2.0")
        self.assertEqual(cp.CONFIGURATION,"passive-v2")
        self.assertEqual(cp.STATUS,"NON_ADOPTED_NOT_BUILD_AUTHORIZED")
        self.assertFalse(self.manifest["adopted"])
        self.assertFalse(self.manifest["build_authorized"])

    def test_all_frozen_wave1_files_unchanged(self):
        result=cp.baseline_check()
        self.assertEqual(result["changed"],0)

    def test_baseline_manifest_identity_preserved(self):
        old=json.loads((ROOT/"hardware/cad/generated/reference-v1/manifest.json").read_text())
        self.assertEqual(old["revision"],"HW-REF-1.1")
        self.assertEqual(old["configuration"],"reference-v1")
        self.assertNotEqual(old["configuration"],self.manifest["configuration"])

    def test_one_panel_numbers_cannot_pass(self):
        p=copy.deepcopy(self.parameters)
        p["panel"]["count"]=1
        with self.assertRaisesRegex(ValueError,"two physical panels"):
            cp.validate(p)

    def test_wrong_series_topology_rejected(self):
        p=copy.deepcopy(self.parameters)
        p["panel"]["series_count"]=1
        p["panel"]["parallel_count"]=2
        with self.assertRaisesRegex(ValueError,"2S1P"):
            cp.validate(p)

    def test_candidate_rejects_1p1_identity_binding(self):
        p=copy.deepcopy(self.parameters)
        p["configuration"]="reference-v1"
        p["revision"]="HW-REF-1.1"
        with self.assertRaisesRegex(ValueError,"must not bind"):
            cp.validate(p)

    def test_hub_requires_actual_bound_source(self):
        p=copy.deepcopy(self.parameters)
        p["hub"]["source_bound"]=False
        with self.assertRaisesRegex(ValueError,"not bound"):
            cp.validate(p)

    def test_verified_hub_size_cannot_be_resized_silently(self):
        p=copy.deepcopy(self.parameters)
        p["hub"]["size_mm"][0]+=10
        with self.assertRaisesRegex(ValueError,"source-bound"):
            cp.validate(p)

    def test_source_tim_thickness_drift_rejected(self):
        p=copy.deepcopy(self.parameters)
        p["tim"]["thickness_mm"]=1
        with self.assertRaisesRegex(ValueError,"source-bound"):
            cp.validate(p)

    def test_bend_worst_case_margin_and_failure(self):
        self.assertAlmostEqual(cp.arithmetic(self.parameters)["cable_worst_case_bend_margin_mm"],5.7)
        p=copy.deepcopy(self.parameters)
        p["cable_radius_mm"]=48
        with self.assertRaisesRegex(ValueError,"bend budget"):
            cp.validate(p)

    def test_solar_and_wind_area_are_two_real_modules(self):
        arithmetic=cp.arithmetic(self.parameters)
        self.assertEqual(arithmetic["physical_panel_count"],2)
        self.assertEqual(arithmetic["nameplate_array_power_w"],80)
        self.assertAlmostEqual(arithmetic["total_panel_face_area_m2"],0.5678)
        self.assertAlmostEqual(arithmetic["per_panel_face_area_m2"],0.2839)
        self.assertEqual(arithmetic["panel_area_ratio_to_baseline"],2)
        self.assertEqual(arithmetic["panel_group_size_mm"],[668,900,25])

    def test_frozen_thermal_comparison_cannot_be_reduced(self):
        p=copy.deepcopy(self.parameters)
        p["frozen_comparison"]["enclosed_peak_heat_w"]=5
        with self.assertRaisesRegex(ValueError,"comparison drift"):
            cp.validate(p)

    def test_two_panel_physical_bboxes_and_service_gap(self):
        parts={p["id"]:p for p in self.assemblies["C2-REEF"]["parts"]}
        panels=[parts["C2-REEF-PV-1"],parts["C2-REEF-PV-2"]]
        for p in panels:
            self.assertEqual(p["bom_id"],"V2-PV-001")
            for actual,expected in zip(p["bbox"]["size_mm"],[668,425,25]):
                self.assertAlmostEqual(actual,expected)
        self.assertAlmostEqual(panels[1]["bbox"]["min_mm"][1]-panels[0]["bbox"]["max_mm"][1],50)
        self.assertAlmostEqual(sum(p["volume_mm3"] for p in panels),2*668*425*25)

    def test_real_series_link_and_two_free_leads(self):
        parts={p["id"]:p for p in self.assemblies["C2-REEF"]["parts"]}
        jumper=parts["C2-REEF-SERIES-LINK"]
        self.assertEqual(jumper["features"]["from"],"PV1_POS")
        self.assertEqual(jumper["features"]["to"],"PV2_NEG")
        self.assertEqual(jumper["features"]["arc_count"],4)
        self.assertGreater(jumper["features"]["centreline_length_mm"],400)
        checks={c["id"]:c for c in self.assemblies["C2-REEF"]["checks"]}
        self.assertAlmostEqual(checks["series_link_actual_centreline_min_radius"]["actual"],56)
        self.assertEqual(parts["C2-REEF-FREE-LEAD-1"]["features"]["terminal"],"ARRAY_NEG")
        self.assertEqual(parts["C2-REEF-FREE-LEAD-2"]["features"]["terminal"],"ARRAY_POS")

    def test_geometric_contact_does_not_claim_thermal_capture(self):
        checks=[c for c in self.assemblies["C2-HUB"]["checks"] if "patch_area_mm2" in c]
        self.assertEqual(len(checks),4)
        for c in checks:
            self.assertLessEqual(c["distance_mm"],1e-5)
            self.assertEqual(c["patch_area_mm2"],14000)
        claims=self.manifest["thermal_claims"]
        for name in ("whole_box_air_pass","pi_junction_pass","component_heat_capture_fraction","residual_solar_fraction"):
            self.assertIsNone(claims[name])

    def test_true_shade_spacing_and_sink_fin_unknowns(self):
        checks={c["id"]:c for c in self.assemblies["C2-HUB"]["checks"]}
        self.assertAlmostEqual(checks["shade_to_enclosure_vertical_gap"]["actual"],75)
        self.assertAlmostEqual(checks["shade_side_overhang_x"]["actual"],50)
        self.assertGreaterEqual(checks["sink_outlet_to_roof"]["actual"],50)
        sink=next(p for p in self.assemblies["C2-HUB"]["parts"] if p["id"]=="C2-HUB-SINK-FINFIELD")
        self.assertTrue(sink["features"]["not_solid_metal"])
        self.assertIsNone(sink["features"]["fin_count_pitch_taper"])
        self.assertIsNone(sink["solid_equivalent_mass_kg"])

    def test_power_components_fit_and_source_conflicts_remain(self):
        parts={p["bom_id"]:p for p in self.assemblies["C2-REEF"]["parts"]}
        for id in ("V2-MPPT-001","V2-BMS-001","V2-LOADSW-001","V2-REG5-001","V2-REG3-001"):
            self.assertIn(id,parts)
        self.assertIn("CONSERVATIVE UNION",parts["V2-BMS-001"]["source_status"])
        self.assertIn("differs",parts["V2-LOADSW-001"]["source_status"])
        checks={c["id"]:c for c in self.assemblies["C2-REEF"]["checks"]}
        self.assertGreaterEqual(checks["loadswitch_terminal_to_lid"]["actual"],15)

    def test_no_wet_or_active_baseline_replacement(self):
        self.assertEqual(set(self.assemblies),{"C2-HUB","C2-REEF","C2-TOP"})
        self.assertFalse(self.manifest["active_hardware_populated"])
        self.assertEqual(self.manifest["physical_tests_performed"],[])

    def test_no_printable_or_pressure_parts(self):
        self.assertEqual(self.manifest["printable_whitelist"],[])
        self.assertEqual(self.manifest["stl_exports"],[])
        for a in self.assemblies.values():
            for p in a["parts"]:
                self.assertFalse(p["printable"])
                self.assertFalse(p["pressure_boundary"])
        self.assertFalse(list(OUT.rglob("*.stl")))

    def test_step_units_and_dimensioned_dxf(self):
        for a in self.assemblies.values():
            self.assertIn("SI_UNIT(.MILLI.,.METRE.)",(OUT/a["step"]).read_text())
            dxf=(OUT/a["drawing_dxf"]).read_text()
            self.assertRegex(dxf,r"\$INSUNITS\s+70\s+4\s")
            self.assertIn("DIMENSION",dxf)

    def test_stdlib_audit_does_not_claim_cad_runtime(self):
        result=checker.audit(OUT)
        self.assertFalse(result["geometry_runtime_executed"])
        self.assertEqual(result["assemblies"],3)

    def test_generator_refuses_nonempty_output_without_importing_cad(self):
        before=cp.digest(OUT/"manifest.json")
        run=subprocess.run([sys.executable,str(CAD/"generate.py"),"--output",str(OUT)],capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,2)
        self.assertIn("NEW or EMPTY",run.stderr)
        self.assertEqual(cp.digest(OUT/"manifest.json"),before)

    def test_artifact_path_escape_rejected(self):
        for bad in ("../manifest.json","/etc/passwd"):
            with self.assertRaises(ValueError):
                checker.artifact_path(OUT,bad)

    def test_tampered_candidate_units_rejected(self):
        with tempfile.TemporaryDirectory(prefix="qa-cad-test-") as tmp:
            m=copy.deepcopy(self.manifest)
            m["units"]["length"]="inch"
            (Path(tmp)/"manifest.json").write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,"units mismatch"):
                checker.audit(Path(tmp))

    def test_corrupted_candidate_step_detected_without_cad(self):
        with tempfile.TemporaryDirectory(prefix="qa-cad-test-") as tmp:
            copied=Path(tmp)/"copy"
            shutil.copytree(OUT,copied)
            make_writable(copied)
            target=copied/"step/C2-REEF.step"
            data=target.read_bytes()
            target.write_bytes(b"X"+data[1:])
            with self.assertRaisesRegex(ValueError,"checksum/size mismatch"):
                checker.audit(copied)


if __name__=="__main__":
    unittest.main()
