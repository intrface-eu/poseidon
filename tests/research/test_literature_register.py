from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LiteratureRegisterTests(unittest.TestCase):
    def test_sources_are_classified_and_gates_remain_open(self):
        data = json.loads((ROOT / "research/literature/acquisition-evidence-2026-09-08.json").read_text())
        self.assertIs(data["field_data_available"], False)
        self.assertIs(data["permission_or_emission_authorized"], False)
        rows = data["records"]
        self.assertEqual(len(rows), len({row["id"] for row in rows}))
        classes = {"primary_fulltext", "primary_abstract_only", "project_report",
                   "synthesis_fulltext", "unsupported_assumption"}
        self.assertEqual({row["evidence_class"] for row in rows}, classes)
        for row in rows:
            with self.subTest(source=row["id"]):
                for field in ("access", "location", "population", "finding", "limitations", "decision", "remaining_gate"):
                    self.assertTrue(row[field])
                if row["evidence_class"] != "unsupported_assumption":
                    self.assertTrue(row["urls"])
                    self.assertTrue(all(url.startswith("https://") for url in row["urls"]))
        self.assertEqual({row["topic"] for row in rows}, {
            "local_predation_detection", "prior_trials_habituation", "hearing_pressure_particle_motion",
            "non_target_effects", "flora_hypotheses", "unsupported_assumptions",
        })

    def test_primary_measurement_and_project_claims_not_conflated(self):
        data = json.loads((ROOT / "research/literature/acquisition-evidence-2026-09-08.json").read_text())
        rows = {row["id"]: row for row in data["records"]}
        self.assertEqual(rows["SCI-02"]["evidence_class"], "project_report")
        self.assertIn("non-functional against fish predation", rows["SCI-02"]["finding"])
        self.assertIn("not Sparus aurata", rows["SCI-04"]["population"])
        self.assertIn("not stimulation benefit", rows["SCI-07"]["finding"])
        self.assertIn("include zero", rows["SCI-06"]["finding"])


if __name__ == "__main__":
    unittest.main()
