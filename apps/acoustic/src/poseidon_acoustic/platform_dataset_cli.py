"""Local Platform export and real in-process API synthetic demonstration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tempfile

from .dataset import read_json, write_new_json
from .dataset_cli import synthetic_demo
from .errors import InputError
from .platform_dataset import ApiReader, ExportLimits, PLAN_FORMAT, build_dataset


def demo(output: Path) -> dict:
    """Real Hub/API components in an owned temporary workspace, no listening server."""
    from fastapi.testclient import TestClient
    from poseidon_api import create_app

    with tempfile.TemporaryDirectory(prefix="poseidon-platform-dataset-") as temporary:
        root = Path(temporary)
        sources = root / "sources"
        synthetic_demo(sources)
        original = read_json(sources / "dataset.json")["recordings"][1]
        manifest = read_json(sources / original["recording_manifest_path"])
        plan = {"format": PLAN_FORMAT, "dataset_name": "synthetic-platform-zero-candidate",
                "protocol_ref": "synthetic-protocol", "license": "Project-generated synthetic software fixture only",
                "site_holdout": False, "recordings": [{key: original[key] for key in (
                    "recording_id", "wav_path", "recording_manifest_path", "recording_group", "local_date", "timezone", "split")}]}
        policy = {"protocol_id": "synthetic-protocol", "acceptance_ref": "synthetic-software-test-not-human-approval",
                  "accepted_by": "synthetic-generator-not-reviewer", "accept_feeding_observed_as_feeding": True,
                  "accept_no_feeding_observed_as_reviewed_negative": True, "allow_limited_visibility": False,
                  "max_sync_uncertainty_s": 0.1, "confidence": "low"}
        write_new_json(sources / "platform-plan.json", plan)
        write_new_json(sources / "acceptance.json", policy)
        workspace = root / "hub"
        app = create_app(workspace, start_worker=False)
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + (workspace / "access.token").read_text().strip()
            response = client.post("/api/v1/recordings", files={
                "wav": ("synthetic.wav", (sources / original["wav_path"]).read_bytes(), "audio/wav"),
                "manifest": ("manifest.json", json.dumps(manifest).encode(), "application/json")})
            if response.status_code != 202:
                raise InputError("synthetic API import failed")
            app.state.hub.process_next_job()
            path = f"/api/v1/recordings/{original['recording_id']}"
            if client.get(path).json()["event_count"] != 0:
                raise InputError("synthetic zero-candidate fixture unexpectedly has candidates")
            for observation in original["observations"]:
                label = {"observed_predation": "feeding_observed", "hard_negative": "no_feeding_observed",
                         "unknown": "uncertain", "unusable": "not_visible"}[observation["label"]]
                body = {"id": observation["observation_id"], "start_s": observation["start_s"],
                        "end_s": observation["end_s"], "label": label,
                        "notes": "Synthetic software observation; no animal observed.",
                        "observer": "Synthetic declared observer", "expected_revision": 0,
                        "review_context": {"protocol_id": "synthetic-protocol", "evidence_refs": ["synthetic-evidence"],
                                           "visibility": "not_visible" if label == "not_visible" else "clear",
                                           "sync_uncertainty_s": 0.0, "reviewed_coverage": True}}
                created = client.post(path + "/observations", json=body)
                if created.status_code != 201:
                    raise InputError("synthetic API observation creation failed")
                if label == "feeding_observed":
                    revised = client.put(path + "/observations/" + body["id"], json={
                        **body, "expected_revision": 1, "notes": "Synthetic revision two; feeding label is not stock loss."})
                    if revised.status_code != 200:
                        raise InputError("synthetic API observation revision failed")
            receipt = build_dataset(ApiReader(client, ExportLimits(page_size=2)), sources / "platform-plan.json",
                                    sources / "acceptance.json", output, thresholds=[0.2], window_ms=10)
        evaluation = read_json(output / "evaluation.json")
        counts = evaluation["runs"][0]["aggregate"]
        if counts["false_negatives"] != 1 or counts["recall"] != 0 or counts["false_positives"] != 0:
            raise InputError("zero-candidate independent truth did not reach evaluation")
        return {**receipt, "provenance": "synthetic", "real_hub_api_exercised": True,
                "server_listening": False, "candidate_count": 0, "independent_false_negatives": 1}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demonstration = commands.add_parser("demo")
    demonstration.add_argument("--output-dir", type=Path, required=True)
    export = commands.add_parser("export-api", help="GET from an existing authorized loopback API; never starts a service")
    export.add_argument("--origin", required=True, help="http://127.0.0.1:PORT only")
    export.add_argument("--token-file", required=True, type=Path)
    export.add_argument("--plan", required=True, type=Path)
    export.add_argument("--acceptance", required=True, type=Path)
    export.add_argument("--output-dir", required=True, type=Path)
    export.add_argument("--threshold", required=True, type=float, action="append")
    export.add_argument("--split", choices=("train", "validation", "holdout"), default="validation")
    export.add_argument("--page-size", type=int, default=50)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            result = demo(args.output_dir)
        else:
            import httpx
            from .dataset import contained_file

            match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]{1,5})", args.origin)
            if match is None or not 1 <= int(match[1]) <= 65535:
                raise InputError("origin must be literal authorized loopback http://127.0.0.1:PORT")
            path = contained_file(args.token_file.parent, args.token_file.name)
            if path.stat().st_mode & 0o077:
                raise InputError("credential file must be private (no group/other permissions)")
            with path.open("rb") as stream:
                raw = stream.read(513)
            if len(raw) > 512:
                raise InputError("credential length exceeds bound")
            token = raw.decode("ascii").strip()
            if not token or any(not 33 <= ord(character) <= 126 for character in token):
                raise InputError("credential must be nonempty printable single-line text")
            limits = ExportLimits(page_size=args.page_size)
            with httpx.Client(base_url=args.origin, headers={"Authorization": "Bearer " + token},
                              timeout=limits.request_timeout_s, follow_redirects=False, trust_env=False) as client:
                result = build_dataset(ApiReader(client, limits), args.plan, args.acceptance, args.output_dir,
                                       thresholds=args.threshold, evaluation_split=args.split)
    except (InputError, OSError, ValueError, ImportError) as exc:
        print(f"platform dataset: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
