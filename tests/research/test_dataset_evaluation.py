from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from poseidon_acoustic.dataset import load_dataset, seal_dataset
from poseidon_acoustic.dataset_cli import synthetic_demo
from poseidon_acoustic.errors import InputError
from poseidon_acoustic.evaluation import _matching, compare_thresholds, score_intervals, wilson


class DatasetEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "fixture"
        self.report = synthetic_demo(self.root)
        self.dataset = load_dataset(self.root / "dataset.json")

    def reseal(self, mutate):
        spec = json.loads((self.root / "spec.json").read_text())
        mutate(spec)
        (self.root / "test-spec.json").write_text(json.dumps(spec))
        return seal_dataset(self.root / "test-spec.json", self.root / "test-dataset.json")

    def test_known_counts_and_zero_candidate_false_negative(self):
        first, second = self.report["runs"]
        self.assertEqual(first["aggregate"]["true_positives"], 1)
        self.assertEqual(first["aggregate"]["false_positives"], 1)
        self.assertEqual(first["aggregate"]["false_negatives"], 1)
        self.assertEqual(first["aggregate"]["precision"], 0.5)
        self.assertEqual(first["aggregate"]["recall"], 0.5)
        self.assertAlmostEqual(first["aggregate"]["scored_seconds"], 1.6)
        self.assertAlmostEqual(first["aggregate"]["false_alerts_per_hour"], 2250)
        zero = first["by_recording"][1]
        self.assertEqual(zero["prediction_count"], 0)
        self.assertEqual(len(zero["false_negative_ids"]), 1)
        self.assertEqual(second["aggregate"]["false_negatives"], 2)
        self.assertIsNone(second["aggregate"]["precision"])
        self.assertEqual(second["aggregate"]["recall"], 0)
        self.assertEqual(self.report["provenance"], "synthetic")
        self.assertIs(self.report["biological_performance_claim"], False)

    def test_reproducible_across_paths(self):
        other = Path(self.temp.name) / "second"
        report = synthetic_demo(other)
        self.assertEqual(self.report, report)
        self.assertEqual((self.root / "dataset.json").read_bytes(), (other / "dataset.json").read_bytes())

    def test_no_overwrite(self):
        before = (self.root / "dataset.json").read_bytes()
        with self.assertRaises(FileExistsError):
            seal_dataset(self.root / "spec.json", self.root / "dataset.json")
        with self.assertRaises(FileExistsError):
            synthetic_demo(self.root)
        self.assertEqual(before, (self.root / "dataset.json").read_bytes())

    def test_source_mutation_rejected(self):
        path = self.root / "synthetic-1.wav"
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(InputError, "checksum"):
            load_dataset(self.root / "dataset.json")

    def test_observation_mutation_rejected(self):
        path = self.root / "dataset.json"
        raw = json.loads(path.read_text())
        raw["recordings"][0]["observations"][0]["evidence_ref"] = "changed"
        path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(InputError, "content hash"):
            load_dataset(path)

    def test_same_recording_group_leakage_rejected(self):
        def mutate(spec):
            spec["recordings"][1]["recording_group"] = spec["recordings"][0]["recording_group"]
            spec["recordings"][1]["split"] = "holdout"
        with self.assertRaisesRegex(InputError, "recording_group"):
            self.reseal(mutate)

    def test_same_site_leakage_rejected_when_enabled(self):
        def mutate(spec):
            spec["site_holdout"] = True
            spec["recordings"][1]["split"] = "holdout"
        with self.assertRaisesRegex(InputError, "site"):
            self.reseal(mutate)

    def test_day_leakage_rejected(self):
        path = self.root / "synthetic-2.recording.json"
        manifest = json.loads(path.read_text())
        manifest["started_at"] = "2026-01-01T13:00:00Z"
        path.write_text(json.dumps(manifest))
        def mutate(spec):
            spec["recordings"][1]["local_date"] = "2026-01-01"
            spec["recordings"][1]["split"] = "holdout"
        with self.assertRaisesRegex(InputError, "day"):
            self.reseal(mutate)

    def test_recording_spanning_midnight_blocks_both_days(self):
        path = self.root / "synthetic-1.recording.json"
        manifest = json.loads(path.read_text())
        manifest["started_at"] = "2026-01-01T23:59:59.500000Z"
        path.write_text(json.dumps(manifest))
        def mutate(spec):
            spec["recordings"][1]["split"] = "holdout"
        with self.assertRaisesRegex(InputError, "day"):
            self.reseal(mutate)

    def test_midnight_in_final_sample_duration_is_covered(self):
        path = self.root / "synthetic-1.recording.json"
        manifest = json.loads(path.read_text())
        manifest["started_at"] = "2026-01-01T23:59:59.000500Z"
        path.write_text(json.dumps(manifest))
        def mutate(spec):
            spec["recordings"][1]["split"] = "holdout"
        with self.assertRaisesRegex(InputError, "day"):
            self.reseal(mutate)

    def test_duplicate_source_rejected(self):
        def mutate(spec):
            spec["recordings"].append(copy.deepcopy(spec["recordings"][0]))
        with self.assertRaisesRegex(InputError, "duplicate recording"):
            self.reseal(mutate)

    def test_declared_date_cannot_hide_leakage(self):
        def mutate(spec):
            spec["recordings"][0]["local_date"] = "2027-01-01"
        with self.assertRaisesRegex(InputError, "local_date"):
            self.reseal(mutate)

    def test_symlink_and_traversal_sources_rejected(self):
        (self.root / "alias.wav").symlink_to(self.root / "synthetic-1.wav")
        for bad in ("../outside.wav", "alias.wav", "/dev/zero"):
            with self.subTest(path=bad):
                def mutate(spec):
                    spec["recordings"][0]["wav_path"] = bad
                with self.assertRaises(InputError):
                    self.reseal(mutate)

    def test_observation_overlap_and_nan_rejected(self):
        for start in (0.1, float("nan"), True):
            with self.subTest(start=start):
                def mutate(spec):
                    spec["recordings"][0]["observations"][1]["start_s"] = start
                with self.assertRaises(InputError):
                    self.reseal(mutate)

    def test_unknown_unusable_and_unreviewed_not_negatives(self):
        row = copy.deepcopy(self.dataset["recordings"][0])
        row["observations"].pop(0)
        predictions = [dict(prediction_id=str(i), start_s=start, end_s=end)
                       for i, (start, end) in enumerate(((0, 0.1), (0.82, 0.85), (0.92, 0.95)))]
        result = score_intervals(row, predictions)
        self.assertEqual(result["false_positives"], 0)
        self.assertEqual(len(result["excluded_prediction_ids"]), 3)
        self.assertAlmostEqual(result["scored_seconds"], 0.6)
        self.assertAlmostEqual(result["unreviewed_seconds"], 0.2)
        self.assertEqual(result["false_negatives"], 1)

    def test_boundary_straddling_prediction_excluded_but_truth_retained(self):
        row = copy.deepcopy(self.dataset["recordings"][0])
        row["observations"][0]["label"] = "unknown"
        result = score_intervals(row, [dict(prediction_id="p", start_s=0.15, end_s=0.3)])
        self.assertEqual(result["false_negatives"], 1)
        self.assertEqual(result["excluded_prediction_ids"], ["p"])

    def test_duplicate_predictions_cannot_count_truth_twice(self):
        row = self.dataset["recordings"][0]
        result = score_intervals(row, [dict(prediction_id=str(i), start_s=0.2, end_s=0.3) for i in (1, 2)])
        self.assertEqual(result["true_positives"], 1)
        self.assertEqual(result["false_positives"], 1)

    def test_maximum_matching_avoids_greedy_false_negative(self):
        self.assertEqual(len(_matching([[0, 1], [0]])), 2)
        self.assertEqual(len(_matching([[0], [0]])), 1)
        self.assertEqual(_matching([]), {})

    def test_matching_matches_exhaustive_small_graphs(self):
        from itertools import product

        def brute(edges, prediction=0, used=frozenset()):
            if prediction == len(edges):
                return 0
            return max([brute(edges, prediction + 1, used)] + [
                1 + brute(edges, prediction + 1, used | {truth})
                for truth in edges[prediction] if truth not in used
            ])

        for bits in product((False, True), repeat=9):
            edges = [[j for j in range(3) if bits[3 * i + j]] for i in range(3)]
            matched = _matching(edges)
            self.assertEqual(len(matched), brute(edges))
            self.assertEqual(len(matched), len(set(matched.values())))

    def test_half_open_touch_does_not_match(self):
        row = self.dataset["recordings"][0]
        result = score_intervals(row, [dict(prediction_id="p", start_s=0.3, end_s=0.4)])
        self.assertEqual(result["true_positives"], 0)
        self.assertEqual(result["false_negatives"], 1)
        self.assertEqual(result["false_positives"], 1)

    def test_excess_uncertainty_excluded_and_reported(self):
        row = copy.deepcopy(self.dataset["recordings"][0])
        row["observations"][1]["timing_uncertainty_s"] = 0.2
        result = score_intervals(row, [])
        self.assertEqual(result["false_negatives"], 0)
        self.assertAlmostEqual(result["excess_timing_uncertainty_seconds"], 0.1)
        self.assertIsNone(result["recall"])

    def test_missing_visibility_is_not_negative_evidence(self):
        row = copy.deepcopy(self.dataset["recordings"][0])
        for obs in row["observations"]:
            obs["visibility"] = "not_visible"
        result = score_intervals(row, [dict(prediction_id="p", start_s=0.3, end_s=0.4)])
        self.assertEqual(result["scored_seconds"], 0)
        self.assertEqual(result["excluded_prediction_ids"], ["p"])
        self.assertIsNone(result["recall"])
        self.assertAlmostEqual(result["visibility_seconds"]["not_visible"], 1)

    def test_empty_coverage_is_not_perfect_performance(self):
        row = copy.deepcopy(self.dataset["recordings"][0])
        row["observations"] = []
        result = score_intervals(row, [])
        self.assertIsNone(result["precision"])
        self.assertIsNone(result["recall"])
        self.assertIsNone(result["false_alerts_per_hour"])
        self.assertEqual(result["scored_coverage_fraction"], 0)

    def test_invalid_prediction_and_config_rejected(self):
        row = self.dataset["recordings"][0]
        for prediction in [dict(prediction_id="p", start_s=0, end_s=2),
                           dict(prediction_id="p", start_s=float("inf"), end_s=1)]:
            with self.assertRaises(InputError):
                score_intervals(row, [prediction])
        for iou in (0, 2, float("nan"), True):
            with self.assertRaises(InputError):
                score_intervals(row, [], min_iou=iou)
        with self.assertRaises(InputError):
            compare_thresholds(self.root / "dataset.json", [0.2, 0.2])
        with self.assertRaisesRegex(InputError, "frozen threshold"):
            compare_thresholds(self.root / "dataset.json", [0.2, 0.4], split="holdout")

    def test_wilson_interval_contains_known_fraction(self):
        low, high = wilson(5, 10)
        self.assertAlmostEqual(low, 0.2365930905)
        self.assertAlmostEqual(high, 0.7634069095)
        self.assertIsNone(wilson(0, 0))

    def test_cli_validate_and_error(self):
        result = subprocess.run([sys.executable, "-m", "poseidon_acoustic.dataset_cli", "validate",
                                 str(self.root / "dataset.json")], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["source_integrity"], "verified")
        result = subprocess.run([sys.executable, "-m", "poseidon_acoustic.dataset_cli", "demo",
                                 str(self.root)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
