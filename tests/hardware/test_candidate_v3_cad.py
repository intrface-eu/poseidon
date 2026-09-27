"""Source-bound v3 evidence tests (stdlib only). Live CAD-kernel negative tests live in tests/hardware/kernel.

All scratch files use system temp. Copies restore write bits; no source-tree writes,
package installs, bytecode or geometry-environment mutation occur.
"""
from __future__ import annotations
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "hardware/candidates/passive-v3"
CAD = CANDIDATE / "cad"
OUT = CAD / "generated/passive-v3"
sys.path.insert(0, str(CAD))
import v3_contract as contract
spec = importlib.util.spec_from_file_location("passive_v3_checker", CAD / "check.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
sys.path.pop(0)


def writable(root):
    for path in [root, *root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)


def save(path, value):
    path.write_text(json.dumps(value, indent=2)+"\n")


class CandidateV3EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.interface = contract.load()
        cls.manifest = contract.read_json(OUT / "manifest.json")

    def changed_interface_rejected(self, change, regex):
        p = copy.deepcopy(self.interface)
        change(p)
        with self.assertRaisesRegex(ValueError, regex):
            contract.validate(p)

    def test_nonadopted_intrface_identity(self):
        self.assertEqual(self.interface["product"], "Poseidon Trident")
        self.assertEqual(self.interface["company"], "Intrface")
        self.assertEqual(self.interface["reuse_rights"]["vendor_cad"], "UNVERIFIED_NOT_CC0")
        self.assertTrue(self.interface["reuse_rights"]["derived_assembly_wholly_original"])
        self.assertTrue(self.interface["reuse_rights"]["public_redistribution_authorized"])
        self.assertFalse(self.interface["reuse_rights"]["vendor_files_public_redistribution_authorized"])
        self.assertEqual(self.interface["reuse_rights"]["original_design_license"], "CERN-OHL-S-2.0")
        self.assertEqual(self.interface["configuration"], "passive-v3")
        self.assertFalse(self.interface["adopted"])
        self.assertFalse(self.interface["build_authorized"])
        self.assertEqual(self.interface["physical_tests_performed"], [])

    def test_immutable_baseline_excludes_b3_catalog(self):
        self.assertEqual(contract.baseline_check()["changed"], 0)
        lock = contract.read_json(CANDIDATE / "baseline-lock.json")
        self.assertFalse(set(lock["files"]) & contract.EXCLUDED_BASELINE)
        self.assertIn("hardware/candidates/passive-v2/cad/model.py", lock["files"])
        self.assertIn("B3", lock["exclusion_reason"])

    def test_241_dimensions_have_hashed_sources_or_local_allocation(self):
        _, traces = contract.validate(self.interface)
        self.assertEqual(len(traces), 241)
        for record in traces.values():
            self.assertEqual(len(record["source_sha256"]), 64)
            self.assertTrue(record["locator"])
            self.assertEqual(record["retrieved"], "2026-09-09")
        self.assertEqual(traces["design.hydrophone_center_x_mm"]["kind"], "local_design_allocation")
        self.assertEqual(traces["tube.od"]["kind"], "published_vendor_dimension")
        self.assertEqual(traces["tube.bbox_size_x"]["kind"], "measured_vendor_cad_dimension")

    def test_target_depth_and_duration_not_rating(self):
        target = self.interface["target_envelope"]
        self.assertEqual((target["depth_m"], target["continuous_immersion_days"]), (30, 90))
        self.assertIsNone(target["verified_assembly_depth_m"])
        self.assertIsNone(target["verified_assembly_immersion_days"])

    def test_target_cannot_be_promoted_to_rating(self):
        self.changed_interface_rejected(lambda p: p["target_envelope"].update(verified_assembly_depth_m=30), "Targets are not assembly ratings")

    def test_preamp_remains_dry_empty_reserve_not_board(self):
        receive = self.interface["receive_chain"]
        self.assertIn("ABOVE WATER", receive["preamp"])
        self.assertFalse(receive["underwater_preamp_populated"])
        self.assertIsNone(receive["underwater_preamp_dimensions_mm"])
        self.assertEqual(self.interface["allocations"]["empty_preamp_reserve_size_mm"], [40, 40, 40])
        self.assertTrue(any("EMPTY_PREAMP" in p["name"] for p in self.manifest["empty_nonphysical"]))

    def test_underwater_preamp_population_rejected(self):
        self.changed_interface_rejected(lambda p: p["receive_chain"].update(underwater_preamp_populated=True), "Preamp must stay above water")

    def test_polycarbonate_cannot_be_changed_to_acrylic(self):
        self.changed_interface_rejected(lambda p: p["pressure_boundary"].update(dome="acrylic"), "polycarbonate")

    def test_as1_standard_cable_cannot_claim_30m_usb_or_analog(self):
        self.assertEqual(self.interface["receive_chain"]["standard_as1_cable_m"], 9)
        self.changed_interface_rejected(lambda p: p["receive_chain"].update(camera_usb_transport_30m_verified=True), "30 m transport unresolved")
        self.changed_interface_rejected(lambda p: p["receive_chain"].update(analog_transport_verified=True), "30 m transport unresolved")

    def test_tube_length_follows_camera_service_and_empty_budget(self):
        budget = contract.stack_budget(self.interface)
        self.assertAlmostEqual(budget["required_mm"], 234.55)
        self.assertAlmostEqual(budget["margin_mm"], 65.45)
        self.assertLess(budget["rejected_200mm_margin_mm"], 0)

    def test_vendor_dimension_tamper_rejected(self):
        self.changed_interface_rejected(lambda p: p["dimensions"].update({"tube.od": 120}), "Traced dimension drift")

    def test_local_allocation_drift_is_not_a_vendor_fact(self):
        self.changed_interface_rejected(lambda p: p["allocations"].update(hydrophone_center_x_mm=60), "Local design allocation drift")

    def test_untraced_dimension_is_rejected(self):
        self.changed_interface_rejected(lambda p: p["dimensions"].update({"invented.preamp_board": 32}), "Dimension trace coverage")

    def test_missing_source_dimensions_stay_null(self):
        option = self.interface["connector_option"]
        self.assertIn("COB-1160", option["name"])
        self.assertEqual(option["hex_af_mm"], 16)
        self.assertIsNone(option["body_length_mm"])
        self.assertFalse(option["cad_exported"])
        self.assertTrue(all(v is None for v in self.interface["unresolved"].values()))

    def test_unknown_cobalt_cannot_be_populated(self):
        self.changed_interface_rejected(lambda p: p["connector_option"].update(populated=True), "Incomplete Cobalt")

    def test_sealed_boundary_claim_is_rejected(self):
        self.changed_interface_rejected(lambda p: p["pressure_boundary"].update(sealed_in_model=True), "Incomplete closure")

    def test_14_unperformed_gates_and_no_active_hardware(self):
        self.assertEqual(len(self.interface["open_gates"]), 14)
        self.assertTrue(all(g["status"] == "not_performed" and g["result"] is None for g in self.interface["open_gates"]))
        self.assertFalse(self.interface["active_emission_hardware_populated"])
        self.assertFalse(self.interface["future_projector"]["populated"])

    def test_future_projector_cannot_enter_mass_or_interference(self):
        self.changed_interface_rejected(lambda p: p["future_projector"].update(included_in_mass=True), "Empty future projector")
        self.changed_interface_rejected(lambda p: p["future_projector"].update(included_in_physical_interference=True), "Empty future projector")

    def test_archived_kernel_checks_cover_every_physical_pair(self):
        parts = self.manifest["parts"]
        pairs = [c for c in self.manifest["check_records"] if c["id"].startswith("interference:")]
        self.assertEqual(len(parts), 25)
        self.assertEqual(len(pairs), 300)
        self.assertTrue(all(c["passed"] and "OCP Boolean" in c["evidence"] and "EMPTY" not in c["id"] for c in pairs))
        self.assertEqual(len([c for c in self.manifest["check_records"] if c["id"].startswith("step_roundtrip:")]), 27)

    def test_unknown_vendor_internals_not_solid_metal_mass(self):
        parts = {p["name"]: p for p in self.manifest["parts"]}
        for name in ("V3_CAMERA_BR_LOW_LIGHT_USB_VENDOR_INTERNALS", "V3_WETLINK_M10_7P5_SOURCE_REVISION_CONFLICT"):
            self.assertIsNone(parts[name]["modeled_mass_kg"])
            self.assertIsNone(parts[name]["density_assumption_kg_m3"])
        hydro = parts["V3_AS1_RECEIVE_ONLY_SOURCE_ENVELOPE"]
        self.assertEqual(hydro["source_mass_kg"], 0.008)
        self.assertIsNone(hydro["density_assumption_kg_m3"])

    def test_displacement_distinguishes_shell_sealed_and_flooded_regions(self):
        checker.mass_audit(self.manifest)
        m = self.manifest["mass_displacement"]
        self.assertGreater(m["conditional_sealed_external_envelope_volume_mm3"], m["pressure_shell_material_volume_mm3"])
        self.assertGreater(m["flooded_external_mount_and_stub_solid_volume_mm3"], 0)
        self.assertIsNone(m["actual_unit_buoyancy_sign"])
        self.assertFalse(m["sealed_boundary_present"])
        self.assertIn(m["modeled_buoyancy_sign"], ("positive", "negative", "neutral"))

    def test_mass_arithmetic_tamper_rejected(self):
        m = copy.deepcopy(self.manifest)
        m["mass_displacement"]["known_or_assumed_mass_subtotal_kg"] += 1
        with self.assertRaisesRegex(ValueError, "subtotal drift"):
            checker.mass_audit(m)

    def test_stdlib_audit_is_not_a_kernel_claim(self):
        result = checker.audit(OUT)
        self.assertFalse(result["geometry_runtime_executed"])
        self.assertTrue(result["glb"]["binary_positions_read"])
        self.assertEqual(result["glb"]["units"], "m")
        self.assertEqual(result["glb"]["stable_part_nodes"], 28)
        self.assertNotIn("cadquery", checker.__dict__)

    def test_nonempty_output_refused_before_cad_import(self):
        with tempfile.TemporaryDirectory(prefix="v3-refusal-") as tmp:
            marker = Path(tmp) / "owned.txt"
            marker.write_text("preserve")
            run = subprocess.run([sys.executable, str(CAD / "generate.py"), "--output", tmp], capture_output=True, text=True, timeout=30, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(run.returncode, 2)
            self.assertIn("NEW or EMPTY", run.stderr)
            self.assertEqual(marker.read_text(), "preserve")
            self.assertEqual(list(Path(tmp).iterdir()), [marker])

    def test_output_symlink_and_path_escape_refused(self):
        with tempfile.TemporaryDirectory(prefix="v3-symlink-") as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "NEW or EMPTY"):
                contract.prepare_output(link)
            for name in ("../interface.json", "/etc/passwd"):
                with self.assertRaisesRegex(ValueError, "Unsafe relative path"):
                    contract.safe_file(OUT, name)

    def test_corrupted_export_detected_without_kernel(self):
        with tempfile.TemporaryDirectory(prefix="v3-export-tamper-") as tmp:
            out = Path(tmp) / "copy"
            shutil.copytree(OUT, out)
            writable(out)
            step = out / "step/V3_AS1_RECEIVE_ONLY_SOURCE_ENVELOPE.step"
            step.write_bytes(b"X"+step.read_bytes()[1:])
            with self.assertRaisesRegex(ValueError, "Artifact hash/size mismatch"):
                checker.audit(out)

    def test_local_design_capture_hash_tamper_detected(self):
        with tempfile.TemporaryDirectory(prefix="v3-source-tamper-") as tmp:
            clone = Path(tmp) / "candidate"
            clone.mkdir()
            shutil.copytree(CANDIDATE / "sources", clone / "sources")
            writable(clone)
            source = clone / "sources/design-inputs.json"
            source.write_bytes(source.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "Source hash drift"):
                contract.validate(self.interface, candidate=clone)

    def test_glb_units_root_scale_axis_and_empty_population_fail_without_kernel(self):
        mutations = [
            ("units", lambda doc: doc["asset"]["extras"].update(length_unit="millimetre"), "units declaration drift"),
            ("root_scale", lambda doc: doc["nodes"][0].update(scale=[1, 1, 1]), "metre-scale/source bbox mismatch"),
            ("root_axis", lambda doc: doc["nodes"][0].update(rotation=[0, 0, 0, 1]), "metre-scale/source bbox mismatch"),
            ("empty_population", lambda doc: next(n for n in doc["nodes"] if n.get("name", "").startswith("EMPTY_FUTURE_PROJECTOR"))["extras"].update(physical=True), "physical/material classification drift"),
        ]
        for label, mutate, pattern in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory(prefix="v3-glb-tamper-") as tmp:
                data = (OUT / "INTRFACE_PASSIVE_V3.glb").read_bytes()
                import struct
                n = struct.unpack_from("<I", data, 12)[0]
                doc = json.loads(data[20:20+n])
                mutate(doc)
                chunk = json.dumps(doc, separators=(",", ":")).encode()
                chunk += b" "*((-len(chunk)) % 4)
                body = struct.pack("<I4s", len(chunk), b"JSON")+chunk+data[20+n:]
                path = Path(tmp) / "bad.glb"
                path.write_bytes(struct.pack("<4sII", b"glTF", 2, len(body)+12)+body)
                with self.assertRaisesRegex(ValueError, pattern):
                    checker.glb_audit(path, {p["name"]: p for p in self.manifest["parts"]+self.manifest["empty_nonphysical"]})


if __name__ == "__main__":
    unittest.main()
