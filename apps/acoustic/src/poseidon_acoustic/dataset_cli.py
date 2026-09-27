"""Run with python3 -m poseidon_acoustic.dataset_cli; no devices or database writes."""

from __future__ import annotations

import argparse
from array import array
import hashlib
from pathlib import Path
import sys
import wave

from poseidon_proto import RecordingManifest, canonical_json

from .dataset import FORMAT, data_card, load_dataset, seal_dataset, write_new_json
from .errors import InputError
from .evaluation import compare_thresholds


def synthetic_demo(directory: Path) -> dict:
    """Create deterministic arithmetic fixtures, never biological observations."""
    directory.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, day in enumerate(("2026-01-01", "2026-01-02")):
        name = f"synthetic-{index + 1}"
        path = directory / f"{name}.wav"
        # The second recording has observed synthetic truth but zero candidates.
        frames = [0] * (1000 + index * 100)
        if index == 0:
            frames[200:300] = [12000] * 100
            frames[600:650] = [10000] * 50
        samples = array("h", frames)
        if sys.byteorder != "little":
            samples.byteswap()
        with path.open("xb") as stream:
            with wave.open(stream, "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(1000)
                writer.writeframes(samples.tobytes())
        manifest = RecordingManifest(
            schema_version=1, recording_id=name, site_id="synthetic-site",
            zone_id="synthetic-zone", device_id="synthetic-generator", started_at=f"{day}T12:00:00Z",
            provenance="synthetic", wav_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            calibration_status="uncalibrated",
        )
        write_new_json(directory / f"{name}.recording.json", manifest.to_dict())
        duration = len(frames) / 1000
        intervals = [(0, 0.2, "hard_negative"), (0.2, 0.3, "observed_predation"),
                     (0.3, 0.8, "hard_negative"), (0.8, 0.9, "unknown"),
                     (0.9, duration, "unusable")]
        rows.append({
            "wav_path": path.name, "recording_manifest_path": f"{name}.recording.json",
            "split": "validation", "recording_group": name, "local_date": day, "timezone": "UTC",
            "observations": [{"observation_id": f"{name}-obs-{i}", "start_s": start, "end_s": end,
                              "label": label, "observer_id": "synthetic-generator-not-human",
                              "evidence_ref": "synthetic arithmetic fixture; no animal or field observation",
                              "confidence": "high", "visibility": "visible", "timing_uncertainty_s": 0.0}
                             for i, (start, end, label) in enumerate(intervals)],
        })
    spec = {"format": FORMAT, "dataset_name": "synthetic-independent-observations",
            "protocol_ref": "software-arithmetic-fixture-v1; not a study protocol",
            "license": "Project-generated synthetic fixture; no third-party or field media",
            "site_holdout": False, "recordings": rows}
    write_new_json(directory / "spec.json", spec)
    dataset = seal_dataset(directory / "spec.json", directory / "dataset.json")
    report = compare_thresholds(directory / "dataset.json", [0.2, 0.4], window_ms=10)
    write_new_json(directory / "evaluation.json", report)
    with (directory / "DATA_CARD.md").open("x", encoding="utf-8") as stream:
        stream.write(data_card(dataset))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    seal = commands.add_parser("seal", help="checksum sources and freeze independent observations")
    seal.add_argument("spec", type=Path)
    seal.add_argument("output", type=Path)
    validate = commands.add_parser("validate", help="recheck content identity, all bytes and split leakage")
    validate.add_argument("dataset", type=Path)
    card = commands.add_parser("card")
    card.add_argument("dataset", type=Path)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("dataset", type=Path)
    evaluate.add_argument("output", type=Path)
    evaluate.add_argument("--threshold", type=float, action="append", required=True)
    evaluate.add_argument("--split", choices=("train", "validation", "holdout"), default="validation")
    evaluate.add_argument("--window-ms", type=float, default=20)
    evaluate.add_argument("--min-iou", type=float, default=0.1)
    evaluate.add_argument("--max-timing-uncertainty-s", type=float, default=0.1)
    importer = commands.add_parser("import-platform", help="bind stored observation export and explicit protocol acceptance")
    importer.add_argument("export", type=Path)
    importer.add_argument("policy", type=Path)
    importer.add_argument("output", type=Path)
    demo = commands.add_parser("demo", help="create explicitly synthetic fixture in a NEW directory")
    demo.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "seal":
            result = seal_dataset(args.spec, args.output)
        elif args.command == "validate":
            dataset = load_dataset(args.dataset)
            result = {"dataset_id": dataset["dataset_id"], "recordings": len(dataset["recordings"]),
                      "source_integrity": "verified", "provenance_truth_verified": False}
        elif args.command == "card":
            print(data_card(load_dataset(args.dataset)), end="")
            return 0
        elif args.command == "evaluate":
            result = compare_thresholds(args.dataset, args.threshold, split=args.split,
                                        window_ms=args.window_ms, min_iou=args.min_iou,
                                        max_timing_uncertainty_s=args.max_timing_uncertainty_s)
            write_new_json(args.output, result)
        elif args.command == "import-platform":
            from .observation_import import import_file

            result = import_file(args.export, args.policy, args.output)
        else:
            result = synthetic_demo(args.output)
    except (InputError, OSError, ValueError) as exc:
        print(f"dataset: {exc}", file=sys.stderr)
        return 2
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
