"""Surface-v3 evidence checks: stdlib only, no CadQuery import or unittest skips."""
from __future__ import annotations
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT/"hardware/candidates/surface-v3"
CAD = CANDIDATE/"cad"
OUT = CAD/"generated/surface-v3"
sys.path.insert(0, str(CAD))
import surface_contract as contract
from surface_glb import Parsed, unpack, encode
spec = importlib.util.spec_from_file_location("surface_v3_checker", CAD/"check.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
sys.path.pop(0)


def save(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n")


class SurfaceV3EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.interface = contract.load()
        cls.manifest = contract.read_json(OUT/"manifest.json")
        cls.parts = {p["name"]: p for p in cls.manifest["parts"]}

    def scratch(self):
        parent = Path(os.environ.get("POSEIDON_SURFACE_V3_TEST_TMP") or tempfile.gettempdir()).resolve()
        return tempfile.TemporaryDirectory(prefix="surface-v3-", dir=parent)

    def changed(self, fn, message):
        p = copy.deepcopy(self.interface)
        fn(p)
        with self.assertRaisesRegex(ValueError, message):
            contract.validate(p)

    def archive_mutation(self, mutate, message):
        with self.scratch() as tmp:
            target = Path(tmp)/"copy"
            shutil.copytree(OUT, target)
            mutate(target)
            with self.assertRaisesRegex(ValueError, message):
                checker.audit(target)

    @staticmethod
    def rehash(target, name):
        manifest = contract.read_json(target/"manifest.json")
        row = next(r for r in manifest["artifacts"] if r["path"] == name)
        row.update(sha256=contract.digest(target/name), bytes=(target/name).stat().st_size)
        save(target/"manifest.json", manifest)

    @classmethod
    def rebind_glb(cls, target, doc, chunks):
        (target/contract.GLB_NAME).write_bytes(encode(doc, chunks))
        hierarchy = contract.read_json(target/"hierarchy.json")
        hierarchy["glb_sha256"] = contract.digest(target/contract.GLB_NAME)
        save(target/"hierarchy.json", hierarchy)
        cls.rehash(target, "hierarchy.json")
        cls.rehash(target, contract.GLB_NAME)

    def test_01_candidate_has_no_physical_authority(self):
        self.assertEqual(self.interface["configuration"], "surface-v3")
        self.assertEqual(self.interface["status"], contract.STATUS)
        for key in ("adopted", "build_authorized", "procurement_authorized", "active_emission_hardware_populated"):
            self.assertIs(self.interface[key], False)
        self.assertEqual(self.interface["physical_tests_performed"], 0)
        self.assertEqual(self.interface["required_sentence"], contract.SENTENCE)

    def test_02_all_66_parameters_are_traced(self):
        self.assertEqual(len(self.interface["parameters"]), 66)
        self.assertEqual(set(self.interface["parameters"]), contract.PARAMETER_NAMES)
        for key, row in self.interface["parameters"].items():
            self.assertTrue(row["basis"], key)
            self.assertTrue(row["unit"], key)
            self.assertIn(row["kind"], ("source_record", "design_assumption"))

    def test_03_missing_trace_rejected(self):
        self.changed(lambda p: p["parameters"].pop("pole_wall_mm"), "trace coverage")
        self.changed(lambda p: p["parameters"]["pole_wall_mm"].update(kind="verified_vendor"), "dimension trace")

    def test_04_unknown_dimension_rejected(self):
        self.changed(lambda p: p["parameters"].update(untraced={"value": 1}), "trace coverage")

    def test_05_vendor_panel_and_hub_envelopes_locked(self):
        self.changed(lambda p: p["parameters"]["panel_xyz_mm"].update(value=[668, 425, 26]), "Sourced dimension drift")
        self.changed(lambda p: p["parameters"]["hub_xyz_mm"].update(value=[275, 175, 67]), "Sourced dimension drift")

    def test_06_vendor_dimensions_cannot_be_relabelled_assumptions(self):
        self.changed(lambda p: p["parameters"]["panel_xyz_mm"].update(kind="design_assumption"), "Sourced dimension drift")

    def test_07_source_register_hash_and_no_downloads(self):
        sources = contract.validate(self.interface)
        self.assertEqual(len(sources), 10)
        self.assertIn("panel-datasheet", sources)
        self.assertIn("hub-drawing", sources)
        catalog = {r["path"]: r for r in contract.read_json(ROOT/"hardware/vendor-sources.json")["files"]}
        for row in sources.values():
            if row["path"].startswith("hardware/.vendor-cache/"):
                self.assertEqual(catalog[row["path"].removeprefix("hardware/.vendor-cache/")]["sha256"], row["sha256"])
            else:
                self.assertEqual(contract.digest(ROOT/row["path"]), row["sha256"])
        self.changed(lambda p: p.update(source_register_sha256="0"*64), "Source register hash")

    def test_08_supplier_hash_mismatch_rejected_without_cache(self):
        original = contract.read_json
        def tampered(path):
            data = original(path)
            if str(path).endswith("surface-v3/sources/source-register.json"):
                data["sources"][4]["sha256"] = "0"*64
            return data
        with mock.patch.object(contract, "read_json", side_effect=tampered):
            with self.assertRaisesRegex(ValueError, "Supplier source hash/locator"):
                contract.validate(self.interface)

    def test_09_baseline_excludes_mutable_catalogs(self):
        lock = contract.read_json(CANDIDATE/"baseline-lock.json")
        self.assertEqual(contract.baseline_check()["changed"], 0)
        self.assertFalse(any("showcase" in name or name == "HARDWARE.md" or "reports" in name for name in lock["files"]))
        self.assertIn("hardware/candidates/passive-v2/cad/model.py", lock["files"])
        self.assertIn("hardware/candidates/passive-v3/interface.json", lock["files"])

    def test_10_drainage_range_and_finite_dimensions(self):
        for angle in (2.9, 5.1, float("nan")):
            self.changed(lambda p: p["parameters"]["panel_tilt_deg"].update(value=angle), "tilt|Finite")
        self.changed(lambda p: p["parameters"]["pole_wall_mm"].update(value=-3), "Positive dimensions")

    def test_11_pole_depth_plus_freeboard_not_embedment(self):
        d = contract.layout(self.interface)
        self.assertEqual(d["pole_length_mm"], 6900)
        self.assertIsNone(self.interface["variants"]["pole"]["embedment_mm"])
        p = copy.deepcopy(self.interface)
        p["parameters"]["site_depth_mm"]["value"] = 7200
        contract.validate(p)
        self.assertEqual(contract.layout(p)["pole_length_mm"], 7700)

    def test_12_sixty_mm_pole_and_two_clearance_bolts(self):
        v = contract.values(self.interface)
        self.assertEqual(v["pole_od_mm"], 60)
        self.assertEqual(v["socket_id_mm"], 62)
        self.assertEqual(len(v["bolt_centres_below_tray_mm"]), 2)
        self.changed(lambda p: p["parameters"]["socket_id_mm"].update(value=60), "clearance")
        self.changed(lambda p: p["parameters"]["bolt_centres_below_tray_mm"].update(value=[30, 30]), "two cross-bolt")

    def test_13_variants_are_exclusive(self):
        self.changed(lambda p: p["variants"]["float"].update(exclusive_with="none"), "mutually exclusive")
        groups = self.interface["contract_groups"]
        self.assertEqual(groups["surface"], ["tray", "hub", "panelA", "panelB", "mastSocket"])

    def test_14_no_battery_or_thermal_promotion(self):
        self.changed(lambda p: p.update(power_parts_populated=["battery"]), "Power integration")
        self.changed(lambda p: p["thermal"].update(reevaluated=True), "Thermal question")
        self.changed(lambda p: p.update(adopted=True), "Authority boundary")
        self.assertEqual(self.interface["thermal"]["v2_absorbed_sun_w"], 48)
        self.assertEqual(self.interface["thermal"]["v2_enclosed_heat_w"], 21.9)

    def test_15_complete_archive_passes_without_kernel(self):
        result = checker.audit(OUT)
        self.assertFalse(result["kernel_executed"])
        self.assertFalse(result["saved_pass_flag_trusted"])
        self.assertEqual((result["parts"], result["physical_parts"], result["allocations"]), (23, 17, 6))
        self.assertEqual(result["artifacts_hashed"], 54)

    def test_16_each_visible_mesh_has_source_binding(self):
        h = contract.read_json(OUT/"hierarchy.json")
        self.assertEqual(set(p["name"] for p in h["parts"]), set(checker.PART_SPECS))
        for p in h["parts"]:
            self.assertEqual(contract.digest(OUT/p["step"]), p["step_sha256"])
            self.assertTrue(p["parameter_keys"])
            self.assertEqual(len(p["source_to_cad_matrix_mm"]), 4)
            self.assertGreater(p["gltf_geometry"]["triangle_count"], 0)

    def test_17_geometry_dimensions_and_gap(self):
        for name in ("SV3_PANEL_A", "SV3_PANEL_B"):
            self.assertEqual(self.parts[name]["source_bbox_mm"]["size_mm"], [668, 425, 25])
        self.assertEqual(self.parts["SV3_HUB_HAMMOND_1550WJ"]["source_bbox_mm"]["size_mm"], [275, 175, 66.6])
        gap = self.parts["SV3_PANEL_B"]["bbox"]["min_mm"][1]-self.parts["SV3_PANEL_A"]["bbox"]["max_mm"][1]
        self.assertAlmostEqual(gap, 50, places=6)

    def test_18_float_unknown_actual_mass_and_conditional_sign(self):
        mass = contract.read_json(OUT/"mass-displacement.json")
        self.assertIsNone(mass["actual_complete_mass_kg"])
        self.assertEqual(mass["actual_buoyancy_sign"], "UNKNOWN")
        scenario = mass["float_scenario"]
        self.assertEqual(scenario["fully_submerged_buoyancy_sign"], "POSITIVE")
        self.assertAlmostEqual(scenario["fully_submerged_displacement_m3"], 0.21384)
        self.assertAlmostEqual(scenario["dry_mass_kg"], 42.223734107, places=6)
        self.assertAlmostEqual(scenario["posed_displacement_m3"]*1025, scenario["dry_mass_kg"])
        self.changed(lambda p: p.update(assembled_mass_kg=42), "Unknown physical result")

    def test_19_no_vendor_solid_density_mass(self):
        mass = contract.read_json(OUT/"mass-displacement.json")
        rows = {r["name"]: r for r in mass["parts"]}
        for name in ("SV3_PANEL_A", "SV3_PANEL_B", "SV3_HUB_HAMMOND_1550WJ"):
            self.assertIsNone(rows[name]["density_assumed_kg_m3"])
        self.assertEqual(rows["SV3_PANEL_A"]["vendor_nominal_mass_kg"], 3.1)
        self.assertIsNone(rows["SV3_HUB_HAMMOND_1550WJ"]["modeled_dry_mass_kg"])
        for row in rows.values():
            if row["kind"] == "allocation":
                self.assertIsNone(row["modeled_dry_mass_kg"])

    def test_20_glb_world_waterline_and_float_extras(self):
        parsed = Parsed(OUT/contract.GLB_NAME)
        nodes = parsed.doc["nodes"]
        f = nodes[parsed.names["mountFloat"]]
        self.assertTrue(f["extras"]["defaultHidden"])
        self.assertAlmostEqual(f["extras"]["floatSurfaceY"], 0.242208351664, places=9)
        self.assertAlmostEqual(parsed.geometry("SV3_POLE_60MM")["min_m"][1], -6.4)
        self.assertAlmostEqual(parsed.geometry("SV3_TRAY_PLATE")["max_m"][1], 0.504)
        self.assertAlmostEqual(parsed.geometry("SV3_FLOAT_COLLAR")["max_m"][1], f["extras"]["floatSurfaceY"], places=6)

    def test_21_artifact_tamper_rejected(self):
        self.archive_mutation(lambda t: (t/"step/SV3_TRAY_PLATE.step").write_bytes(b"wrong STEP"), "Artifact hash")

    def test_22_saved_pass_flag_not_trusted(self):
        def mutate(t):
            m = contract.read_json(t/"manifest.json")
            m["checks"] = {"passed": True, "failed": 0}
            m["check_records"] = []
            next(r for r in m["parts"] if r["name"] == "SV3_PANEL_A")["bbox"]["size_mm"][0] = 1
            save(t/"manifest.json", m)
        self.archive_mutation(mutate, "bbox arithmetic")

    def test_23_wrong_glb_scale_rejected_even_after_rehash(self):
        def mutate(t):
            d, chunks = unpack(t/contract.GLB_NAME)
            next(n for n in d["nodes"] if n["name"] == "SURFACE_V3")["scale"] = [1, 1, 1]
            self.rebind_glb(t, d, chunks)
        self.archive_mutation(mutate, "mm-to-m root scale")

    def test_24_glb_position_data_checked_not_accessor_labels(self):
        def mutate(t):
            d, chunks = unpack(t/contract.GLB_NAME)
            node = next(n for n in d["nodes"] if n["name"] == "SV3_PANEL_A")
            prim = d["meshes"][node["mesh"]]["primitives"][0]
            a = d["accessors"][prim["attributes"]["POSITION"]]
            view = d["bufferViews"][a["bufferView"]]
            start = view.get("byteOffset", 0)+a.get("byteOffset", 0)
            binary = bytearray(chunks[1][1])
            struct.pack_into("<f", binary, start, 999999)
            chunks[1] = (chunks[1][0], bytes(binary))
            self.rebind_glb(t, d, chunks)
        self.archive_mutation(mutate, "extrema differ|scale/binary bbox")

    def test_25_allocation_cannot_be_promoted_to_physical(self):
        def mutate(t):
            m = contract.read_json(t/"manifest.json")
            next(r for r in m["parts"] if r["name"] == "SV3_SINK_OCCUPANCY_NOT_FINS")["kind"] = "physical_custom"
            save(t/"manifest.json", m)
        self.archive_mutation(mutate, "classification")

    def test_26_mass_evidence_recomputed_after_rehash(self):
        def mutate(t):
            mass = contract.read_json(t/"mass-displacement.json")
            mass["float_scenario"]["dry_mass_kg"] = 1
            save(t/"mass-displacement.json", mass)
            self.rehash(t, "mass-displacement.json")
        self.archive_mutation(mutate, "Mass/displacement arithmetic")

    def test_27_missing_part_cannot_hide_behind_pass(self):
        def mutate(t):
            m = contract.read_json(t/"manifest.json")
            m["parts"] = [p for p in m["parts"] if p["name"] != "SV3_PANEL_B"]
            save(t/"manifest.json", m)
        self.archive_mutation(mutate, "Part inventory")

    def test_28_existing_output_and_symlink_refused(self):
        with self.scratch() as tmp:
            t = Path(tmp)
            (t/"sentinel").write_text("untouched")
            with self.assertRaisesRegex(ValueError, "new or empty"):
                contract.prepare_output(t)
            alias = t/"redirect"
            alias.symlink_to(t, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                contract.prepare_output(alias/"child")
            self.assertEqual((t/"sentinel").read_text(), "untouched")

    def test_29_ordinary_import_does_not_load_cadquery(self):
        code = f"import sys; sys.path.insert(0,{str(CAD)!r}); import check; assert 'cadquery' not in sys.modules; print('stdlib-only')"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn("stdlib-only", result.stdout)

    def test_30_documentation_keeps_required_gates(self):
        text = (ROOT/"docs/hardware/surface-v3.md").read_text()
        self.assertIn(contract.SENTENCE, text)
        self.assertIn("v2 48 W absorbed-sun and 21.9 W enclosed-heat budgets are not re-evaluated here", text)
        for gate in ("embedment", "wave", "mooring", "battery", "unknown", "Do not normalize or resize in Blender"):
            self.assertIn(gate.lower(), (text+(CANDIDATE/"README.md").read_text()).lower())


if __name__ == "__main__":
    unittest.main()
