from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from poseidon_acoustic.dataset import load_dataset, seal_dataset, write_new_json
from poseidon_acoustic.dataset_cli import synthetic_demo
from poseidon_acoustic.errors import InputError
from poseidon_acoustic.observation_import import EXPORT_FORMAT, convert_observations, import_file, validate_import

ROOT = Path(__file__).resolve().parents[2]


class ObservationImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "dataset"
        synthetic_demo(self.root)
        source = load_dataset(self.root / "dataset.json")["recordings"][0]
        request = json.loads((ROOT / "contracts/v1/fixtures/independent-observation.valid.json").read_text())
        self.row = {**request, "recording_id": source["recording_id"], "revision": 1,
                    "actor_subject": "synthetic-actor-not-observer", "auth_mode": "scoped_token",
                    "created_at": "2026-01-01T12:00:00Z", "updated_at": "2026-01-01T12:00:00Z",
                    "provenance": {"recording_sha256": source["wav_sha256"], "source_kind": "synthetic"}}
        self.export = {"format": EXPORT_FORMAT, "recording_id": source["recording_id"],
                       "recording_sha256": source["wav_sha256"], "source_kind": "synthetic", "observations": [self.row]}
        self.policy = {"protocol_id": "synthetic-protocol", "acceptance_ref": "synthetic-software-test-only",
                       "accepted_by": "synthetic-test-not-a-reviewer", "accept_feeding_observed_as_feeding": True,
                       "accept_no_feeding_observed_as_reviewed_negative": True, "allow_limited_visibility": False,
                       "max_sync_uncertainty_s": 0.1, "confidence": "low"}

    def context(self, label="feeding_observed"):
        self.row["label"] = label
        self.row["review_context"] = {"protocol_id": "synthetic-protocol", "evidence_refs": ["synthetic-video-evidence"],
                                       "visibility": "clear", "sync_uncertainty_s": 0.02, "reviewed_coverage": True}

    def test_canonical_missing_context_excluded_not_invented(self):
        result = convert_observations(self.export, self.policy)
        self.assertEqual(result["observations"], [])
        self.assertIn("missing_review_context", result["excluded"][0]["reasons"])
        self.assertEqual(result["source_export"], self.export)

    def test_explicit_feeding_acceptance_and_lossless_raw_context(self):
        self.context()
        result = convert_observations(self.export, self.policy)
        observation = result["observations"][0]
        self.assertEqual(observation["label"], "observed_predation")
        self.assertEqual(observation["visibility"], "visible")
        self.assertEqual(observation["timing_uncertainty_s"], 0.02)
        self.assertEqual(observation["confidence"], "low")
        self.assertIs(result["stock_loss_claim"], False)
        self.assertEqual(result["source_export"]["observations"][0], self.row)
        self.assertNotEqual(observation["observer_id"], self.row["actor_subject"])
        self.assertIn(result["source_export_sha256"], observation["evidence_ref"])
        self.policy["accept_feeding_observed_as_feeding"] = False
        result = convert_observations(self.export, self.policy)
        self.assertEqual(result["observations"], [])
        self.assertIn("feeding_mapping_not_accepted", result["excluded"][0]["reasons"])

    def test_missing_or_unaccepted_context_excludes_each_condition(self):
        self.context("no_feeding_observed")
        original = copy.deepcopy(self.row["review_context"])
        for key, bad, reason in [
            ("protocol_id", "other", "unaccepted_protocol"),
            ("reviewed_coverage", False, "not_independently_reviewed_coverage"),
            ("evidence_refs", [], "missing_evidence_reference"),
            ("visibility", "unknown", "unaccepted_visibility"),
            ("visibility", "limited", "unaccepted_visibility"),
            ("sync_uncertainty_s", None, "unknown_sync_uncertainty"),
            ("sync_uncertainty_s", 0.2, "excess_sync_uncertainty"),
        ]:
            with self.subTest(condition=reason):
                self.row["review_context"] = {**original, key: bad}
                result = convert_observations(self.export, self.policy)
                self.assertEqual(result["observations"], [])
                self.assertIn(reason, result["excluded"][0]["reasons"])

    def test_unknown_and_not_visible_masks_stay_excluded_labels(self):
        for label, expected in [("uncertain", "unknown"), ("not_visible", "unusable")]:
            self.context(label)
            self.row["review_context"]["visibility"] = "not_visible"
            result = convert_observations(self.export, self.policy)
            self.assertEqual(result["observations"][0]["label"], expected)
            self.assertEqual(result["observations"][0]["visibility"], "not_visible")

    def test_negative_mapping_requires_explicit_acceptance(self):
        self.context("no_feeding_observed")
        self.policy["accept_no_feeding_observed_as_reviewed_negative"] = False
        result = convert_observations(self.export, self.policy)
        self.assertEqual(result["observations"], [])
        self.assertIn("negative_mapping_not_accepted", result["excluded"][0]["reasons"])

    def test_conflicting_recording_hash_rejected(self):
        self.context()
        self.row["provenance"]["recording_sha256"] = "0" * 64
        with self.assertRaisesRegex(InputError, "provenance mismatch"):
            convert_observations(self.export, self.policy)

    def test_history_duplicate_and_excluded_overlap_rejected(self):
        self.context()
        self.export["observations"].append(copy.deepcopy(self.row))
        with self.assertRaisesRegex(InputError, "revision"):
            convert_observations(self.export, self.policy)
        self.export["observations"][1]["id"] = "overlapping-mask"
        self.export["observations"][1].pop("review_context")
        with self.assertRaisesRegex(InputError, "adjudication"):
            convert_observations(self.export, self.policy)

    def test_unknown_fields_and_invalid_policy_rejected(self):
        self.row["future_metadata"] = "must not silently drop"
        with self.assertRaises(InputError):
            convert_observations(self.export, self.policy)
        self.row.pop("future_metadata")
        self.policy["accept_feeding_observed_as_feeding"] = 1
        with self.assertRaises(InputError):
            convert_observations(self.export, self.policy)

    def test_dataset_binds_import_and_rejects_drift(self):
        self.context()
        result = convert_observations(self.export, self.policy)
        write_new_json(self.root / "observations.import.json", result)
        spec = json.loads((self.root / "spec.json").read_text())
        spec["protocol_ref"] = self.policy["protocol_id"]
        spec["recordings"][0]["observation_import_path"] = "observations.import.json"
        spec["recordings"][0]["observations"] = result["observations"]
        write_new_json(self.root / "import-spec.json", spec)
        sealed = seal_dataset(self.root / "import-spec.json", self.root / "import-dataset.json")
        self.assertIn("observation_import_sha256", sealed["recordings"][0])
        self.assertEqual(sealed, load_dataset(self.root / "import-dataset.json"))
        result["source_export"]["observations"][0]["notes"] = "tampered"
        (self.root / "observations.import.json").write_text(json.dumps(result))
        with self.assertRaisesRegex(InputError, "content mismatch"):
            load_dataset(self.root / "import-dataset.json")

    def test_import_cli_and_wrong_recording_binding(self):
        self.context()
        write_new_json(self.root / "export.json", self.export)
        write_new_json(self.root / "acceptance.json", self.policy)
        result = subprocess.run([sys.executable, "-m", "poseidon_acoustic.dataset_cli", "import-platform",
                                 str(self.root / "export.json"), str(self.root / "acceptance.json"),
                                 str(self.root / "converted.json")], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        converted = validate_import(self.root / "converted.json", self.export["recording_id"],
                                    self.export["recording_sha256"], "synthetic")
        self.assertEqual(len(converted["observations"]), 1)
        with self.assertRaisesRegex(InputError, "bind this recording"):
            validate_import(self.root / "converted.json", "other", self.export["recording_sha256"], "synthetic")
        with self.assertRaises(FileExistsError):
            import_file(self.root / "export.json", self.root / "acceptance.json", self.root / "converted.json")


if __name__ == "__main__":
    unittest.main()
