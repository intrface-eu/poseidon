"""Check the published unperformed forms stay honest and tied to usable procedures."""
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "docs/manufacturing/templates/unperformed-records.json"
FORM_IDS = {
    "IN-01", "AT-01", "PROV-01", "CAL-01", "EOL-01", "NCR-01", "ECO-01", "PKG-01",
    "SVC-01", "REP-01", "SP-01", "WAR-01", "INC-01", "REC-01", "VULN-01", "EOS-01",
    "COST-01", "RFQ-01", "QUAL-01", "TEST-01", "LIMIT-01", "EVID-01", "YLD-01",
}


class DossierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = json.loads(BUNDLE.read_text())

    def test_bundle_cannot_look_like_qualified_manufacture(self) -> None:
        self.assertEqual(self.bundle["schema"], "poseidon.manufacturing.unperformed-templates.v1")
        self.assertIs(self.bundle["is_template"], True)
        self.assertEqual(self.bundle["status"], "not_performed")
        self.assertIsNone(self.bundle["result"])
        self.assertEqual(self.bundle["physical_tests_performed"], 0)
        self.assertEqual(self.bundle["physical_evidence"], [])
        self.assertTrue(self.bundle["authorization"])
        self.assertTrue(all(value is False for value in self.bundle["authorization"].values()))

    def test_reference_is_passive_provisional_not_an_actual_unit(self) -> None:
        reference = self.bundle["reference_configuration"]
        hardware = json.loads((ROOT / reference["interface_path"]).read_text())
        self.assertEqual(reference["id"], hardware["configuration"])
        self.assertEqual(reference["revision"], hardware["revision"])
        self.assertEqual(reference["status"], "PROVISIONAL_REFERENCE_NOT_FOR_FABRICATION")
        self.assertEqual(reference["variant"], "passive_monitor")
        self.assertIs(reference["acoustic_output_hardware_populated"], False)
        self.assertIs(reference["powered_wiper_populated"], False)
        for key in ("actual_unit_serial", "actual_firmware_release", "actual_calibration_id", "interface_hash_to_bind_before_actual_work"):
            self.assertIsNone(reference[key])

    def test_all_forms_are_unperformed_and_have_valid_references(self) -> None:
        forms = self.bundle["forms"]
        self.assertEqual({form["form_id"] for form in forms}, FORM_IDS)
        self.assertEqual(len(forms), len(FORM_IDS))
        requirements = set(re.findall(r"\| (REQ-[A-Z]+-\d+) \|", (ROOT / "docs/requirements/production-requirements.md").read_text()))
        for form in forms:
            with self.subTest(form=form["form_id"]):
                self.assertIs(form["is_template"], True)
                self.assertEqual(form["status"], "not_performed")
                self.assertIsNone(form["result"])
                self.assertEqual(form["physical_evidence"], [])
                if form["form_id"] in {"TEST-01", "LIMIT-01", "EVID-01"}:
                    # Generic record shells bind actual requirements only during authorized work.
                    self.assertNotIn("requirements", form)
                else:
                    self.assertTrue(form["requirements"])
                    self.assertTrue(set(form["requirements"]) <= requirements)
                self.assertTrue((ROOT / form["procedure"].split("#")[0]).is_file())
                self.assertTrue(set(form.get("reference_test_ids", [])) <= {f"PV-{i:02}" for i in range(1, 15)})
                for key, value in form.items():
                    if key.startswith("actual_"):
                        self.assertIn(value, (None, []), key)

    def test_row_templates_have_no_measurements_secrets_or_issued_identity(self) -> None:
        rows = self.bundle["row_templates"]
        self.assertEqual(set(rows), {"measurement", "artifact_reference", "component_consumption", "station_attempt", "yield_unit_ledger", "cost_line", "affected_unit_disposition"})
        for name, row in rows.items():
            with self.subTest(row=name):
                self.assertIs(row["is_template"], True)
                for key, value in row.items():
                    if key == "is_template":
                        continue
                    if key == "status":
                        self.assertEqual(value, "not_performed")
                    elif key == "source_class" and name == "cost_line":
                        self.assertEqual(value, "unpriced")
                    else:
                        self.assertIn(value, (None, []), key)
        common = self.bundle["common_actual_record_fields"]
        self.assertEqual(common["execution_status"], "not_performed")
        self.assertIsNone(common["acceptance_result"])
        self.assertEqual(common["raw_evidence"], [])
        self.assertIsNone(common["approval_record_id"])

    def test_procedures_have_real_content_and_local_links_resolve(self) -> None:
        paths = sorted((ROOT / "docs/manufacturing").glob("*.md")) + sorted((ROOT / "docs/qualification/procedures").glob("*.md"))
        self.assertGreaterEqual(len(paths), 6)
        for path in paths:
            content = path.read_text()
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertGreater(len(content), 1500)
                self.assertRegex(content.lower(), r"not.performed|unperformed|not authorized|not executed")
                self.assertIn(self.bundle["reference_configuration"]["revision"], content)
                for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
                    if "://" in target or target.startswith("#"):
                        continue
                    self.assertTrue((path.parent / target.split("#")[0]).resolve().is_file(), target)


if __name__ == "__main__":
    unittest.main()
