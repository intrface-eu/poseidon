"""Real Hub/FastAPI integration; run in the locked AEOLUS API environment.

All media, observations and credentials live in owned temporary directories.
No TCP listener, background job worker, device access or field evidence is used.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from poseidon_api import create_app

from poseidon_acoustic.dataset import load_dataset, read_json, write_new_json
from poseidon_acoustic.dataset_cli import synthetic_demo
from poseidon_acoustic.errors import InputError
from poseidon_acoustic.platform_dataset import ApiReader, ExportLimits, PLAN_FORMAT, build_dataset, capture_snapshot, digest, validate_snapshot
from poseidon_acoustic.observation_import import convert_observations

ROOT = Path(__file__).resolve().parents[3]


class MutatingClient:
    def __init__(self, client, change):
        self.client, self.change = client, change
        self.calls = []

    @contextmanager
    def stream(self, method, path, **kwargs):
        self.calls.append((path, kwargs.get("params")))
        with self.client.stream(method, path, **kwargs) as response:
            content = response.read()
            altered = self.change(path, kwargs.get("params"), response.status_code, content)
            class Reply:
                status_code = response.status_code

                def iter_bytes(self, chunk_size):
                    for start in range(0, len(altered), chunk_size):
                        yield altered[start:start + chunk_size]
            yield Reply()


class PlatformDatasetApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        synthetic_demo(self.sources)
        self.row = read_json(self.sources / "dataset.json")["recordings"][1]
        self.manifest = read_json(self.sources / self.row["recording_manifest_path"])
        self.workspace = self.root / "hub"
        self.app = create_app(self.workspace, start_worker=False)
        self.client = self.enterContext(TestClient(self.app))
        self.token = (self.workspace / "access.token").read_text().strip()
        self.client.headers["Authorization"] = "Bearer " + self.token
        response = self.client.post("/api/v1/recordings", files={
            "wav": ("synthetic.wav", (self.sources / self.row["wav_path"]).read_bytes(), "audio/wav"),
            "manifest": ("manifest.json", json.dumps(self.manifest).encode(), "application/json")})
        self.assertEqual(response.status_code, 202)
        self.app.state.hub.process_next_job()
        self.path = "/api/v1/recordings/" + self.row["recording_id"]
        self.assertEqual(self.client.get(self.path).json()["event_count"], 0)
        self.policy = {"protocol_id": "synthetic-protocol", "acceptance_ref": "synthetic-software-test-not-human-approval",
                       "accepted_by": "synthetic-test-not-reviewer", "accept_feeding_observed_as_feeding": True,
                       "accept_no_feeding_observed_as_reviewed_negative": True, "allow_limited_visibility": False,
                       "max_sync_uncertainty_s": 0.1, "confidence": "low"}
        self.bodies = []
        for index, (start, end, label) in enumerate([(0, 0.2, "no_feeding_observed"),
                (0.2, 0.3, "feeding_observed"), (0.3, 0.8, "no_feeding_observed"),
                (0.8, 1.1, "not_visible")]):
            body = {"id": f"synthetic-observation-{index}", "start_s": start, "end_s": end, "label": label,
                    "notes": "Synthetic software label, no animal observed.", "observer": "Synthetic declared observer",
                    "expected_revision": 0, "review_context": {"protocol_id": "synthetic-protocol",
                        "evidence_refs": ["synthetic-video"], "visibility": "not_visible" if label == "not_visible" else "clear",
                        "sync_uncertainty_s": 0.02, "reviewed_coverage": True}}
            self.assertEqual(self.client.post(self.path + "/observations", json=body).status_code, 201)
            self.bodies.append(body)
        self.revise_positive()
        self.plan = {"format": PLAN_FORMAT, "dataset_name": "synthetic-platform-integration",
                     "protocol_ref": "synthetic-protocol", "license": "Project synthetic test data only",
                     "site_holdout": False, "recordings": [{key: self.row[key] for key in (
                         "recording_id", "wav_path", "recording_manifest_path", "recording_group", "local_date", "timezone", "split")}]}
        write_new_json(self.sources / "plan.json", self.plan)
        write_new_json(self.sources / "policy.json", self.policy)

    def revise_positive(self, revision=1, **changes):
        body = {**self.bodies[1], "expected_revision": revision,
                "notes": f"Synthetic revision {revision + 1}; feeding is not stock loss.", **changes}
        response = self.client.put(self.path + "/observations/" + body["id"], json=body)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def build(self, reader=None, output=None):
        return build_dataset(reader or ApiReader(self.client, ExportLimits(page_size=1)),
                             self.sources / "plan.json", self.sources / "policy.json",
                             output or self.root / "export", thresholds=[0.2], window_ms=10)

    def test_real_paginated_history_export_reaches_zero_candidate_false_negative(self):
        source_before = (self.sources / self.row["wav_path"]).read_bytes()
        receipt = self.build()
        destination = self.root / "export"
        dataset = load_dataset(destination / "dataset.json")
        self.assertIn("platform_snapshot_sha256", dataset["recordings"][0])
        snapshot = read_json(destination / "recording-0000.platform-snapshot.json")
        self.assertEqual(len(snapshot["scan"]["pages"]), 5)
        self.assertEqual(snapshot["scan"]["pages"][-1]["items"], [])
        positive = snapshot["scan"]["histories"][1]
        self.assertEqual(len(positive["pages"]), 3)
        self.assertEqual(positive["pages"][1]["items"][0]["revision"], 2)
        result = read_json(destination / "evaluation.json")["runs"][0]
        self.assertEqual(result["by_recording"][0]["prediction_count"], 0)
        self.assertEqual(result["aggregate"]["false_negatives"], 1)
        self.assertEqual(result["aggregate"]["recall"], 0)
        self.assertAlmostEqual(result["aggregate"]["scored_seconds"], 0.8)
        self.assertIsNone(result["aggregate"]["precision"])
        self.assertIs(snapshot["server_atomic_snapshot"], False)
        self.assertEqual(receipt["selected_recordings"], 1)
        self.assertEqual(source_before, (self.sources / self.row["wav_path"]).read_bytes())
        for path in destination.iterdir():
            self.assertNotIn(self.token.encode(), path.read_bytes())
        self.assertTrue((destination / "export-complete.json").exists())

    def test_truncated_page_prevents_complete_export(self):
        def alter(path, params, status, raw):
            if path == self.path + "/observations" and params["offset"] == 0:
                page = json.loads(raw); page["items"] = []; return json.dumps(page).encode()
            return raw
        with self.assertRaisesRegex(InputError, "truncated"):
            self.build(ApiReader(MutatingClient(self.client, alter), ExportLimits(page_size=1)))
        self.assertFalse((self.root / "export/export-complete.json").exists())

    def test_changed_total_and_duplicate_page_rows_rejected(self):
        for mode in ("total", "duplicate"):
            def alter(path, params, status, raw):
                if path == self.path + "/observations" and params["offset"] == 1:
                    page = json.loads(raw)
                    if mode == "total":
                        page["total"] += 1
                    else:
                        page["items"] = self.client.get(path, params={"limit": 1, "offset": 0}).json()["items"]
                    return json.dumps(page).encode()
                return raw
            with self.subTest(mode=mode), self.assertRaises(InputError):
                capture_snapshot(ApiReader(MutatingClient(self.client, alter), ExportLimits(page_size=1)), self.row["recording_id"], self.policy)

    def test_missing_terminal_page_proof_rejected_on_offline_reload(self):
        snapshot = capture_snapshot(ApiReader(self.client, ExportLimits(page_size=1)), self.row["recording_id"], self.policy)
        imported = convert_observations(snapshot["scan"]["export"], self.policy)
        snapshot["scan"]["pages"].pop()
        snapshot["matching_second_scan_sha256"] = digest(snapshot["scan"])
        snapshot["snapshot_id"] = "platform_snapshot_" + digest({key: value for key, value in snapshot.items() if key != "snapshot_id"})
        with self.assertRaisesRegex(InputError, "missing or duplicate"):
            validate_snapshot(snapshot, imported)

    def test_history_omission_or_wrong_revision_rejected(self):
        def alter(path, params, status, raw):
            if path.endswith("/history") and "synthetic-observation-1" in path and params["offset"] == 0:
                page = json.loads(raw); page["items"][0]["revision"] = 2; return json.dumps(page).encode()
            return raw
        with self.assertRaisesRegex(InputError, "missing, duplicated or reordered"):
            capture_snapshot(ApiReader(MutatingClient(self.client, alter), ExportLimits(page_size=1)), self.row["recording_id"], self.policy)

    def test_revision_change_between_complete_scans_is_not_hidden(self):
        scans = 0
        def alter(path, params, status, raw):
            nonlocal scans
            if path == self.path + "/observations" and params["offset"] == 0:
                scans += 1
                if scans == 2:
                    self.revise_positive(revision=2)
                    return self.client.get(path, params=params).content
            return raw
        with self.assertRaisesRegex(InputError, "changed between complete scans"):
            capture_snapshot(ApiReader(MutatingClient(self.client, alter), ExportLimits(page_size=1)), self.row["recording_id"], self.policy)

    def test_missing_context_and_unaccepted_protocol_stay_unscored(self):
        body = {**self.bodies[1], "expected_revision": 2}
        body.pop("review_context")
        self.assertEqual(self.client.put(self.path + "/observations/" + body["id"], json=body).status_code, 200)
        self.build()
        imported = read_json(self.root / "export/recording-0000.observation-import.json")
        self.assertIn("missing_review_context", imported["excluded"][0]["reasons"])
        result = read_json(self.root / "export/evaluation.json")["runs"][0]["aggregate"]
        self.assertIsNone(result["recall"])
        self.assertAlmostEqual(result["scored_seconds"], 0.7)

    def test_explicit_protocol_refusal_never_maps_feeding(self):
        self.policy["accept_feeding_observed_as_feeding"] = False
        (self.sources / "policy.json").write_text(json.dumps(self.policy))
        self.build()
        imported = read_json(self.root / "export/recording-0000.observation-import.json")
        self.assertIn("feeding_mapping_not_accepted", imported["excluded"][0]["reasons"])

    def test_authentication_failure_is_sanitized_and_source_untouched(self):
        self.client.headers["Authorization"] = "Bearer invalid-synthetic-credential"
        with self.assertRaisesRegex(InputError, "HTTP 401") as context:
            self.build()
        self.assertNotIn("invalid-synthetic-credential", str(context.exception))
        self.assertFalse((self.root / "export/export-complete.json").exists())

    def test_scoped_viewer_cannot_export_hidden_unbound_recording(self):
        issued = self.client.post("/api/v1/principals", json={"subject": "synthetic-scoped-viewer", "role": "viewer",
            "site_ids": ["another-synthetic-site"], "device_id": None})
        self.assertEqual(issued.status_code, 201)
        self.client.headers["Authorization"] = "Bearer " + issued.json()["token"]
        with self.assertRaisesRegex(InputError, "HTTP 404"):
            self.build()
        self.assertFalse((self.root / "export/export-complete.json").exists())

    def test_local_manifest_mismatch_rejected(self):
        path = self.sources / self.row["recording_manifest_path"]
        value = read_json(path); value["site_id"] = "wrong-site"; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(InputError, "local manifest differs"):
            self.build()

    def test_source_tamper_and_existing_destination_fail_without_overwrite(self):
        source = self.sources / self.row["wav_path"]
        before = source.read_bytes(); source.write_bytes(before[:-1] + bytes([before[-1] ^ 1]))
        with self.assertRaisesRegex(InputError, "source changed or differs"):
            self.build()
        self.assertFalse((self.root / "export/export-complete.json").exists())
        with self.assertRaises(FileExistsError):
            self.build()

    def test_bounds_on_requests_bytes_population_and_source(self):
        for limits in [ExportLimits(max_requests=1), ExportLimits(max_page_bytes=10),
                       ExportLimits(max_total_json_bytes=100), ExportLimits(max_observations=1),
                       ExportLimits(max_revisions=1), ExportLimits(max_source_bytes=1)]:
            output = self.root / ("bounded-" + str(len(list(self.root.iterdir()))))
            with self.subTest(limits=limits), self.assertRaises(InputError):
                self.build(ApiReader(self.client, limits), output)
            self.assertFalse((output / "export-complete.json").exists())

    def test_snapshot_mutation_invalidates_sealed_dataset(self):
        self.build()
        path = self.root / "export/recording-0000.platform-snapshot.json"
        value = read_json(path); value["identity"]["subject"] = "changed"; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(InputError, "content hash mismatch"):
            load_dataset(self.root / "export/dataset.json")

    def test_completion_sync_failure_retracts_receipt_and_preserves_data(self):
        from unittest.mock import patch
        from poseidon_acoustic import platform_dataset as module

        original = module._publish_complete
        real_fsync = module.os.fsync
        calls = 0

        def interrupted_sync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic directory sync failure")
            return real_fsync(fd)

        def interrupted_publish(output, receipt):
            with patch.object(module.os, "fsync", side_effect=interrupted_sync):
                return original(output, receipt)

        with patch.object(module, "_publish_complete", side_effect=interrupted_publish):
            with self.assertRaisesRegex(OSError, "synthetic directory sync"):
                self.build()
        self.assertFalse((self.root / "export/export-complete.json").exists())
        self.assertTrue((self.root / "export/dataset.json").exists())
        self.assertTrue((self.root / "export/.export-complete.pending").exists())

    def test_resealed_local_identity_cannot_disagree_with_platform_snapshot(self):
        from poseidon_acoustic.dataset import seal_dataset

        self.build()
        target = self.root / "export/recording-0000.recording.json"
        manifest = read_json(target); manifest["site_id"] = "wrong-site"; target.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(InputError, "snapshot identity differs"):
            seal_dataset(self.root / "export/spec.json", self.root / "export/tampered-new-dataset.json")

    def test_cli_refuses_nonloopback_and_control_character_credentials(self):
        from contextlib import redirect_stderr
        import io
        from poseidon_acoustic.platform_dataset_cli import main

        token = self.root / "test-credential"
        token.write_bytes(b"synthetic-secret" + bytes([0])); token.chmod(0o600)
        for origin in ("https://example.com", "http://127.0.0.1:1"):
            captured = io.StringIO()
            with redirect_stderr(captured):
                code = main(["export-api", "--origin", origin, "--token-file", str(token),
                             "--plan", str(self.sources / "plan.json"), "--acceptance", str(self.sources / "policy.json"),
                             "--output-dir", str(self.root / "cli-export"), "--threshold", "0.2"])
            self.assertEqual(code, 2)
            self.assertNotIn("synthetic-secret", captured.getvalue())
            self.assertFalse((self.root / "cli-export").exists())

    def test_no_observation_population_is_complete_but_not_negative_coverage(self):
        # Import another distinct silent fixture with no observation records.
        manifest = copy.deepcopy(self.manifest); manifest["recording_id"] = "synthetic-empty-observations"
        response = self.client.post("/api/v1/recordings", files={
            "wav": ("synthetic.wav", (self.sources / self.row["wav_path"]).read_bytes(), "audio/wav"),
            "manifest": ("manifest.json", json.dumps(manifest).encode(), "application/json")})
        self.assertEqual(response.status_code, 202); self.app.state.hub.process_next_job()
        snapshot = capture_snapshot(ApiReader(self.client, ExportLimits(page_size=1)), manifest["recording_id"], self.policy)
        self.assertEqual(snapshot["scan"]["pages"], [{"items": [], "total": 0, "limit": 1, "offset": 0}])
        imported = convert_observations(snapshot["scan"]["export"], self.policy)
        self.assertEqual(imported["observations"], [])


if __name__ == "__main__":
    unittest.main()
