"""Independent interval evaluation of the unchanged normalized-RMS baseline."""

from __future__ import annotations

from collections import deque
import hashlib
import math
from pathlib import Path
from typing import Any

from poseidon_proto import canonical_json

from .dataset import SPLITS, contained_file, load_dataset, number, sha256_file
from .detector import DetectorConfig, detect_wav
from .errors import InputError
from .replay import load_manifest

EVALUATOR_VERSION = "independent-intervals-provisional-v1"


def wilson(successes: int, trials: int) -> list[float] | None:
    """95% Wilson score interval; not a cluster-adjusted field-study interval."""
    if not trials:
        return None
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    radius = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def metrics(tp: int, fp: int, fn: int, seconds: float) -> dict[str, Any]:
    return {
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "precision_wilson_95": wilson(tp, tp + fp), "recall_wilson_95": wilson(tp, tp + fn),
        "scored_seconds": seconds,
        "false_alerts_per_hour": fp * 3600 / seconds if seconds else None,
    }


def _union(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _iou(first: tuple[float, float], second: tuple[float, float]) -> float:
    overlap = max(0.0, min(first[1], second[1]) - max(first[0], second[0]))
    return overlap / (max(first[1], second[1]) - min(first[0], second[0]))


def _matching(edges: list[list[int]]) -> dict[int, int]:
    """Deterministic maximum-cardinality bipartite match; each event counts once."""
    matched_truth: dict[int, int] = {}
    matched_prediction: dict[int, int] = {}
    for initial in range(len(edges)):
        queue = deque([initial])
        parent: dict[int, tuple[int, int] | None] = {initial: None}
        finish: tuple[int, int] | None = None
        while queue and finish is None:
            pred = queue.popleft()
            for truth in edges[pred]:
                other = matched_truth.get(truth)
                if other is None:
                    finish = (pred, truth)
                    break
                if other not in parent:
                    parent[other] = (pred, truth)
                    queue.append(other)
        if finish is None:
            continue
        pred, truth = finish
        while True:
            matched_truth[truth] = pred
            matched_prediction[pred] = truth
            predecessor = parent[pred]
            if predecessor is None:
                break
            pred, truth = predecessor
    return matched_prediction


def score_intervals(
    recording: dict[str, Any], predictions: list[dict[str, Any]], *,
    min_iou: float = 0.1, max_timing_uncertainty_s: float = 0.1,
) -> dict[str, Any]:
    """Score a validated dataset recording, including zero-candidate recordings.

    A prediction touching unscored time is excluded as a whole. Positives remain
    false negatives if no eligible prediction matches; exclusions never erase truth.
    """
    min_iou = number(min_iou, "min_iou")
    max_timing_uncertainty_s = number(max_timing_uncertainty_s, "max_timing_uncertainty_s")
    if not 0 < min_iou <= 1:
        raise InputError("min_iou must be greater than zero and <=1")
    if type(predictions) is not list or len(predictions) > 10000:
        raise InputError("at most 10000 predictions per recording are supported")
    observations = recording["observations"]
    scored = [obs for obs in observations
              if obs["label"] in {"observed_predation", "hard_negative"}
              and obs["visibility"] in {"visible", "limited"}
              and obs["timing_uncertainty_s"] <= max_timing_uncertainty_s]
    truth = [obs for obs in scored if obs["label"] == "observed_predation"]
    coverage = _union([(obs["start_s"], obs["end_s"]) for obs in scored])
    eligible: list[dict[str, Any]] = []
    excluded: list[str] = []
    ids: set[str] = set()
    for pred in predictions:
        if type(pred) is not dict or set(pred) != {"prediction_id", "start_s", "end_s"}:
            raise InputError("prediction requires prediction_id, start_s and end_s")
        pid = pred["prediction_id"]
        if type(pid) is not str or not pid or pid in ids:
            raise InputError("prediction_id must be unique nonempty text")
        ids.add(pid)
        start, end = number(pred["start_s"], "prediction start"), number(pred["end_s"], "prediction end")
        if not start < end <= recording["duration_s"]:
            raise InputError("prediction lies outside recording")
        if any(left <= start and end <= right for left, right in coverage):
            eligible.append(pred)
        else:
            excluded.append(pid)
    eligible.sort(key=lambda pred: (pred["start_s"], pred["end_s"], pred["prediction_id"]))
    if len(eligible) * len(truth) > 2_000_000:
        raise InputError("interval comparison budget exceeded; use smaller recording units")
    edges = [[index for index, obs in enumerate(truth)
              if _iou((pred["start_s"], pred["end_s"]), (obs["start_s"], obs["end_s"])) >= min_iou]
             for pred in eligible]
    matches = _matching(edges)
    matched_truth = set(matches.values())
    tp = len(matches)
    result = metrics(tp, len(eligible) - tp, len(truth) - tp,
                     sum(end - start for start, end in coverage))
    reviewed_seconds = sum(obs["end_s"] - obs["start_s"] for obs in observations)
    result.update({
        "recording_id": recording["recording_id"], "site_id": recording["site_id"],
        "local_date": recording["local_date"], "covered_dates": recording["covered_dates"],
        "source_seconds": recording["duration_s"], "reviewed_seconds": reviewed_seconds,
        "unreviewed_seconds": max(0.0, recording["duration_s"] - reviewed_seconds),
        "scored_coverage_fraction": result["scored_seconds"] / recording["duration_s"],
        "label_seconds": {label: sum(obs["end_s"] - obs["start_s"] for obs in observations
                                     if obs["label"] == label)
                          for label in ("observed_predation", "hard_negative", "unknown", "unusable")},
        "excess_timing_uncertainty_seconds": sum(obs["end_s"] - obs["start_s"] for obs in observations
            if obs["label"] in {"observed_predation", "hard_negative"}
            and obs["timing_uncertainty_s"] > max_timing_uncertainty_s),
        "visibility_seconds": {level: sum(obs["end_s"] - obs["start_s"] for obs in observations
                                          if obs["visibility"] == level)
                               for level in ("visible", "limited", "not_visible", "not_applicable")},
        "observation_confidence_counts": {level: sum(obs["confidence"] == level for obs in observations)
                                          for level in ("high", "medium", "low")},
        "prediction_count": len(predictions), "excluded_prediction_ids": excluded,
        "matches": [{"prediction_id": eligible[pred]["prediction_id"],
                     "observation_id": truth[obs]["observation_id"]}
                    for pred, obs in sorted(matches.items())],
        "false_positive_ids": [pred["prediction_id"] for i, pred in enumerate(eligible) if i not in matches],
        "false_negative_ids": [obs["observation_id"] for i, obs in enumerate(truth) if i not in matched_truth],
    })
    return result


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = metrics(sum(row["true_positives"] for row in rows),
                     sum(row["false_positives"] for row in rows),
                     sum(row["false_negatives"] for row in rows),
                     sum(row["scored_seconds"] for row in rows))
    source_seconds = sum(row["source_seconds"] for row in rows)
    result.update({
        "recordings": len(rows), "source_seconds": source_seconds,
        "reviewed_seconds": sum(row["reviewed_seconds"] for row in rows),
        "unreviewed_seconds": sum(row["unreviewed_seconds"] for row in rows),
        "excluded_predictions": sum(len(row["excluded_prediction_ids"]) for row in rows),
        "scored_coverage_fraction": result["scored_seconds"] / source_seconds if source_seconds else None,
    })
    return result


def compare_thresholds(
    dataset_path: Path, thresholds: list[float], *, split: str = "validation",
    window_ms: float = 20.0, min_iou: float = 0.1, max_timing_uncertainty_s: float = 0.1,
) -> dict[str, Any]:
    if split not in SPLITS:
        raise InputError("unknown evaluation split")
    if not thresholds or len(thresholds) > 32:
        raise InputError("supply 1..32 thresholds")
    configs = [DetectorConfig(value, window_ms) for value in thresholds]
    if len({config.threshold for config in configs}) != len(configs):
        raise InputError("duplicate thresholds")
    if split == "holdout" and len(configs) != 1:
        raise InputError("holdout accepts one frozen threshold; comparisons belong on validation")
    data = load_dataset(dataset_path)
    recordings = [row for row in data["recordings"] if row["split"] == split]
    if not recordings:
        raise InputError(f"dataset has no {split} recordings")
    if len({row["provenance"] for row in recordings}) != 1:
        raise InputError("do not aggregate synthetic and field recordings in one evaluation split")
    runs = []
    for config in configs:
        results = []
        for row in recordings:
            wav = contained_file(dataset_path.parent, row["wav_path"])
            manifest = load_manifest(contained_file(dataset_path.parent, row["recording_manifest_path"]))
            if (manifest.wav_sha256 != row["wav_sha256"] or manifest.recording_id != row["recording_id"]
                    or sha256_file(contained_file(dataset_path.parent, row["recording_manifest_path"]))
                    != row["manifest_sha256"]):
                raise InputError("recording manifest changed before evaluation")
            if sha256_file(wav) != row["wav_sha256"]:
                raise InputError("source changed before evaluation")
            detection = detect_wav(wav, manifest, config)
            if sha256_file(wav) != row["wav_sha256"]:
                raise InputError("source changed during evaluation")
            predictions = [{"prediction_id": event.event_id, "start_s": event.start_time_s,
                            "end_s": event.end_time_s} for event in detection.events]
            result = score_intervals(row, predictions, min_iou=min_iou,
                                     max_timing_uncertainty_s=max_timing_uncertainty_s)
            result["detector_run_id"] = detection.run_id
            result["detector_config_id"] = detection.detector_config_id
            results.append(result)
        runs.append({
            "threshold_normalized_rms": config.threshold, "window_ms": config.window_ms,
            "aggregate": _aggregate(results), "by_recording": results,
            "by_site": {site: _aggregate([row for row in results if row["site_id"] == site])
                        for site in sorted({row["site_id"] for row in results})},
            "by_start_day": {day: _aggregate([row for row in results if row["local_date"] == day])
                             for day in sorted({row["local_date"] for row in results})},
        })
    report = {
        "evaluator_version": EVALUATOR_VERSION, "dataset_id": data["dataset_id"], "split": split,
        "provenance": recordings[0]["provenance"], "biological_performance_claim": False,
        "interval_convention": "half-open recording-relative seconds",
        "matching": "maximum-cardinality one-to-one IoU; no timing dilation",
        "min_iou": number(min_iou, "min_iou"),
        "max_timing_uncertainty_s": number(max_timing_uncertainty_s, "max_timing_uncertainty_s"),
        "confidence_method": "Wilson 95% event-binomial, descriptive only; not cluster-adjusted",
        "false_alert_denominator": "all independently scorable seconds, including positive intervals",
        "exclusion_policy": "whole prediction excluded if it touches unreviewed/unknown/unusable/excess-uncertainty time",
        "limitations": ["Label truth and permissions are not verified by checksums.",
                        "Repeated holdout calls are not prevented; freeze protocol and access externally.",
                        "Day strata use recording start day; covered_dates preserve midnight span.",
                        "No range, target-platform resource, biological accuracy or safety measurement."],
        "runs": runs,
    }
    report["report_id"] = "evaluation_" + hashlib.sha256(canonical_json(report).encode()).hexdigest()
    return report
