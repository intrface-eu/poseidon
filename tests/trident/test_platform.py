from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from poseidon_trident import Hub, HubError
from poseidon_trident.platform_schema import PLATFORM_COLUMNS
from poseidon_trident.companion_schema import COMPANION_COLUMNS
from poseidon_trident.workspace import _EXPECTED_COLUMNS, HUB_SCHEMA_VERSION
from poseidon_trident.control_schema import CONTROL_COLUMNS

from _support import active_wav, manifest_bytes, mp4_bytes, wav_bytes


FIXTURES = Path(__file__).resolve().parents[2] / "contracts/v1/fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.valid.json").read_text())


def device(device_id="device-1", site="site-1"):
    return {"id": device_id, "site_id": site, "label": "Synthetic backend test device", "kind": "reef",
            "hardware_revision": "synthetic-r1", "source_kind": "synthetic"}


def session(session_id="session-1", device_id="device-1", site="site-1"):
    return fixture("acquisition-session") | {"id": session_id, "site_id": site, "device_id": device_id}


def observation(observation_id="observation-1"):
    return fixture("independent-observation") | {"id": observation_id, "end_s": 0.02}


def telemetry(device_id="device-1", site="site-1", boot="1", sequence=1):
    return fixture("telemetry-envelope") | {"device_id": device_id, "site_id": site, "boot_id": boot, "sequence": sequence}


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.hub = Hub(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.hub.close)

    def credential(self, subject="reviewer-1", role="reviewer", sites=None, device_id=None):
        issued = self.hub.create_principal({"subject": subject, "role": role, "site_ids": sites or ["site-1"], "device_id": device_id})
        return self.hub.for_principal(self.hub.authenticate(issued["token"])), issued

    def recording(self, recording_id="recording-1", device_id="device-1", site="site-1", *, silent=False, bind=True):
        raw = wav_bytes([(0,)] * 60) if silent else active_wav()
        job = self.hub.submit_recording(io.BytesIO(raw), manifest_bytes(raw, recording_id=recording_id, device_id=device_id, site_id=site))
        self.hub.process_next_job()
        if bind:
            try:
                self.hub.get_device(device_id)
            except HubError:
                self.hub.create_device(device(device_id, site))
            session_id = "session-" + recording_id
            self.hub.create_session(session(session_id, device_id, site))
            self.hub.bind_recording_session(recording_id, session_id)
        return job

    def assert_code(self, code, method, *args, **kwargs):
        with self.assertRaises(HubError) as caught:
            method(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_zero_candidate_observations_history_and_source_survive_restart(self):
        self.recording(silent=True)
        self.assertEqual(self.hub.get_recording("recording-1")["event_count"], 0)
        reviewer, _ = self.credential()
        body = observation()
        body["review_context"] = {"protocol_id": "synthetic-protocol", "evidence_refs": ["synthetic-video"],
                                  "visibility": "limited", "sync_uncertainty_s": None, "reviewed_coverage": True}
        first = reviewer.create_observation("recording-1", body)
        second = reviewer.update_observation("recording-1", body["id"], body | {"expected_revision": 1, "label": "not_visible"})
        self.assertEqual(first["actor_subject"], "reviewer-1")
        self.assertEqual(first["auth_mode"], "scoped_token")
        self.assertEqual(first["provenance"], {"source_kind": "synthetic", "recording_sha256": self.hub.get_recording("recording-1")["wav_sha256"]})
        self.assertEqual(second["created_at"], first["created_at"])
        self.assertEqual(second["review_context"], body["review_context"])
        self.assert_code("observation_conflict", reviewer.update_observation, "recording-1", body["id"], body | {"expected_revision": 1})
        self.hub.close()
        with Hub(self.root) as reopened:
            self.assertEqual(reopened.observation_history("recording-1", body["id"])["items"], [first, second])
            self.assertEqual(reopened.list_observations("recording-1")["items"], [second])
            self.assertEqual(reopened.list_events()["total"], 0)

    def test_observation_validation_and_identity_cannot_move_recordings(self):
        self.recording()
        self.recording("recording-2")
        for change in ({"end_s": 99}, {"start_s": True}, {"start_s": float("nan")}, {"end_s": float("inf")},
                       {"label": "feeding_observed", "notes": " "}, {"actor_subject": "forged"}, {"observer": " "}, {"expected_revision": True}):
            with self.subTest(change=change):
                error = self.assert_code("invalid_request" if "end_s" not in change or change["end_s"] != 99 else "invalid_observation",
                                         self.hub.create_observation, "recording-1", observation() | change)
                self.assertEqual(error.status_code, 400)
        self.hub.create_observation("recording-1", observation())
        self.assert_code("observation_conflict", self.hub.create_observation, "recording-2", observation())
        self.assert_code("observation_not_found", self.hub.update_observation, "recording-2", "observation-1", observation() | {"expected_revision": 1})
        self.assert_code("invalid_request", self.hub.update_observation, "recording-1", "other-id", observation() | {"expected_revision": 1})

    def test_observation_concurrent_revision_has_one_winner(self):
        self.recording()
        reviewer, _ = self.credential()
        reviewer.create_observation("recording-1", observation())
        def save(index):
            try:
                return reviewer.update_observation("recording-1", "observation-1", observation() | {"expected_revision": 1, "notes": str(index)})["revision"]
            except HubError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, [1, 2]))
        self.assertCountEqual(results, [2, "observation_conflict"])
        self.assertEqual(self.hub.observation_history("recording-1", "observation-1")["total"], 2)

    def test_legacy_unbound_recordings_hidden_even_with_manifest_site_match(self):
        job = self.recording(bind=False)
        viewer, _ = self.credential(role="viewer")
        self.assertEqual(viewer.list_recordings()["total"], 0)
        self.assertEqual(viewer.list_events()["total"], 0)
        self.assertEqual(viewer.list_jobs()["total"], 0)
        self.assertEqual(viewer.status()["recordings"], 0)
        self.assert_code("recording_not_found", viewer.get_job, job["id"])
        self.assert_code("recording_not_found", viewer.get_recording, "recording-1")
        self.assert_code("forbidden", viewer.submit_demo)
        self.assertEqual(self.hub.list_recordings()["total"], 1)

    def test_all_legacy_reads_counts_and_media_enforce_site_and_device_scope(self):
        jobs = [self.recording(), self.recording("recording-2", "device-2"), self.recording("recording-3", "device-3", "site-2")]
        self.hub.attach_video("recording-3", io.BytesIO(mp4_bytes()))
        viewer, _ = self.credential(role="viewer")
        bound_device, _ = self.credential("device-principal", "device", device_id="device-1")
        self.assertEqual(viewer.list_recordings(limit=1)["total"], 2)
        self.assertEqual(viewer.list_recordings(limit=1, offset=2)["items"], [])
        self.assertEqual(viewer.list_jobs(limit=1)["total"], 2)
        self.assertEqual(viewer.list_events(limit=1)["total"], 2)
        self.assertEqual(viewer.status()["recordings"], 2)
        self.assertEqual(viewer.status()["events"], 2)
        for method in (viewer.get_recording, viewer.waveform, viewer.video_path, viewer.get_recording_session, viewer.list_observations):
            self.assert_code("recording_not_found", method, "recording-3")
        self.assert_code("recording_not_found", viewer.get_job, jobs[2]["id"])
        hidden_event = self.hub.list_events(recording_id="recording-3")["items"][0]["event_id"]
        self.assert_code("recording_not_found", viewer.get_event, hidden_event)
        self.assertEqual(bound_device.list_recordings()["total"], 1)
        self.assertEqual(bound_device.list_jobs()["total"], 1)
        self.assertEqual(bound_device.status()["events"], 1)
        self.assert_code("recording_not_found", bound_device.get_recording, "recording-2")
        self.assertEqual(bound_device.list_devices()["total"], 1)
        self.assertEqual(bound_device.list_sessions()["total"], 1)

    def test_viewer_device_and_reviewer_write_boundaries(self):
        self.recording()
        viewer, _ = self.credential("viewer", "viewer")
        device_actor, _ = self.credential("sensor", "device", device_id="device-1")
        reviewer, _ = self.credential()
        event_id = self.hub.list_events()["items"][0]["event_id"]
        for actor in (viewer, device_actor):
            self.assert_code("forbidden", actor.create_observation, "recording-1", observation())
            self.assert_code("forbidden", actor.save_review, event_id, "uncertain", "", "declared", 0)
            self.assert_code("forbidden", actor.attach_video, "recording-1", io.BytesIO(mp4_bytes()))
            self.assert_code("forbidden", actor.create_device, device("other"))
            self.assert_code("forbidden", actor.list_audit)
        reviewer.save_review(event_id, "uncertain", "", "declared", 0)
        reviewer.attach_video("recording-1", io.BytesIO(mp4_bytes()))
        self.assert_code("forbidden", reviewer.create_session, session("new"))
        self.assert_code("forbidden", reviewer.create_device, device("other"))

    def test_session_metadata_provenance_immutable_and_no_manifest_rewrite(self):
        self.recording(bind=False)
        manifest_path = self.root / "recordings/recording-1/manifest.json"
        before = manifest_path.read_bytes()
        self.hub.create_device(device())
        body = session()
        body["clock_relation"] = fixture("clock-relation")
        self.assertEqual(self.hub.create_session(body), body)
        self.assertEqual(self.hub.create_session(body), body)
        self.assertEqual(self.hub.bind_recording_session("recording-1", "session-1"), body)
        self.assertEqual(self.hub.bind_recording_session("recording-1", "session-1"), body)
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assert_code("session_conflict", self.hub.create_session, body | {"notes": "changed"})
        self.hub.create_session(session("other-session"))
        self.assert_code("session_binding_conflict", self.hub.bind_recording_session, "recording-1", "other-session")
        self.hub.create_device(device("other-device"))
        self.hub.create_session(session("wrong-device", "other-device"))
        self.assert_code("session_source_mismatch", self.hub.bind_recording_session, "recording-1", "wrong-device")
        self.assertEqual(self.hub.get_recording_session("recording-1"), body)
        self.assertEqual(self.hub.create_session(fixture("acquisition-session"))["device_id"], None)

    def test_scoped_admin_cannot_grant_or_manage_larger_scope(self):
        admin, _ = self.credential("site-admin", "admin")
        _, broader = self.credential("multi-site", "admin", ["site-1", "site-2"])
        self.assertEqual(admin.list_principals()["total"], 1)
        self.assert_code("forbidden", admin.create_principal, {"subject": "escape", "role": "admin", "site_ids": ["site-2"], "device_id": None})
        self.assert_code("principal_not_found", admin.rotate_principal, broader["principal"]["id"])
        self.assert_code("principal_not_found", admin.revoke_principal, broader["principal"]["id"])
        self.assert_code("not_found", admin.create_device, device("outside", "site-2"))
        narrow = admin.create_principal({"subject": "narrow", "role": "viewer", "site_ids": ["site-1"], "device_id": None})
        self.assertEqual(narrow["principal"]["role"], "viewer")

    def test_credentials_hash_only_rotate_revoke_and_restart(self):
        actor, issued = self.credential()
        principal_id = issued["principal"]["id"]
        rotated = self.hub.rotate_principal(principal_id)
        self.assert_code("unauthorized", self.hub.authenticate, issued["token"])
        self.assert_code("unauthorized", actor.current_identity)
        self.assertEqual(self.hub.authenticate(rotated["token"])["subject"], "reviewer-1")
        database = (self.root / "hub.sqlite3").read_bytes()
        self.assertNotIn(issued["token"].encode(), database)
        self.assertNotIn(rotated["token"].encode(), database)
        self.assertNotIn(rotated["token"], json.dumps(self.hub.list_audit()))
        self.hub.close()
        with Hub(self.root) as reopened:
            self.assertEqual(reopened.authenticate(rotated["token"])["subject"], "reviewer-1")
            reopened.revoke_principal(principal_id)
            self.assert_code("unauthorized", reopened.authenticate, rotated["token"])
            self.assert_code("principal_revoked", reopened.rotate_principal, principal_id)

    def test_device_enrollment_validation_and_revocation_cascades(self):
        self.assert_code("invalid_device", self.hub.create_principal, {"subject": "missing", "role": "device", "site_ids": ["site-1"], "device_id": "missing"})
        self.hub.create_device(device())
        actor, issued = self.credential("sensor", "device", device_id="device-1")
        self.hub.revoke_device("device-1")
        self.assert_code("unauthorized", self.hub.authenticate, issued["token"])
        self.assert_code("unauthorized", actor.list_telemetry)
        self.assert_code("invalid_device", self.hub.create_principal, {"subject": "reenroll", "role": "device", "site_ids": ["site-1"], "device_id": "device-1"})
        self.assert_code("device_conflict", self.hub.create_device, device())

    def test_telemetry_idempotency_boot_and_sequence_highwater_persist(self):
        self.hub.create_device(device())
        actor, issued = self.credential("sensor", "device", device_id="device-1")
        body = telemetry(boot="9", sequence=3)
        first = actor.ingest_telemetry(body)
        self.assertFalse(first["duplicate"])
        self.assertEqual(actor.ingest_telemetry(body), first | {"duplicate": True})
        self.assert_code("telemetry_conflict", actor.ingest_telemetry, body | {"delivery_age_s": 1})
        self.assert_code("telemetry_sequence", actor.ingest_telemetry, body | {"sequence": 2})
        self.assert_code("telemetry_boot", actor.ingest_telemetry, body | {"boot_id": "8", "sequence": 100})
        actor.ingest_telemetry(telemetry(boot="10", sequence=0))
        actor.ingest_telemetry(telemetry(boot="18446744073709551615", sequence=0))
        self.assertTrue(actor.ingest_telemetry(body)["duplicate"])
        self.assert_code("telemetry_boot", actor.ingest_telemetry, telemetry(boot="11"))
        self.hub.close()
        with Hub(self.root) as reopened:
            actor = reopened.for_principal(reopened.authenticate(issued["token"]))
            self.assertTrue(actor.ingest_telemetry(body)["duplicate"])
            self.assert_code("telemetry_boot", actor.ingest_telemetry, telemetry(boot="11"))
            self.assertEqual(actor.list_telemetry()["total"], 3)
            with closing(sqlite3.connect(self.root / "hub.sqlite3")) as connection, connection:
                self.assertEqual(connection.execute("SELECT typeof(boot_id) FROM telemetry LIMIT 1").fetchone()[0], "text")

    def test_telemetry_ingest_and_queries_exact_device_scope(self):
        actors = []
        for index, site in ((1, "site-1"), (2, "site-1"), (3, "site-2")):
            self.hub.create_device(device(f"device-{index}", site))
            actor, _ = self.credential(f"sensor-{index}", "device", [site], f"device-{index}")
            actor.ingest_telemetry(telemetry(f"device-{index}", site))
            actors.append(actor)
        self.assertEqual(actors[0].list_telemetry()["total"], 1)
        self.assertEqual(actors[0].list_telemetry(device_id="device-2")["total"], 0)
        self.assertEqual(actors[0].list_telemetry(site_id="site-2")["total"], 0)
        self.assert_code("not_found", actors[0].ingest_telemetry, telemetry("device-2"))
        self.assert_code("not_found", actors[0].ingest_telemetry, telemetry("device-1", "site-2"))
        self.assert_code("forbidden", self.hub.ingest_telemetry, telemetry())
        viewer, _ = self.credential("viewer", "viewer")
        self.assertEqual(viewer.list_telemetry(limit=1)["total"], 2)
        self.assertEqual(viewer.list_telemetry(limit=1, offset=2)["items"], [])
        self.assert_code("forbidden", viewer.ingest_telemetry, telemetry())

    def test_telemetry_invalid_claims_age_and_units(self):
        self.hub.create_device(device())
        actor, _ = self.credential("sensor", "device", device_id="device-1")
        for change in ({"delivery_age_s": 604801}, {"delivery_age_s": True}, {"sequence": -1}, {"boot_id": "01"},
                       {"boot_id": "18446744073709551616"}, {"boot_id": 1}, {"observed_at": "2026-01-01T00:00:00Z"}, {"actor_subject": "forged"}):
            with self.subTest(change=change):
                self.assert_code("invalid_request", actor.ingest_telemetry, telemetry() | change)
        body = telemetry()
        body["measurements"][0]["value"] = float("nan")
        self.assert_code("invalid_request", actor.ingest_telemetry, body)
        body = telemetry()
        body["measurements"][0]["unit"] = "dB"
        self.assert_code("invalid_request", actor.ingest_telemetry, body)
        body = telemetry()
        body["provenance"]["source_kind"] = "field"
        self.assert_code("telemetry_source_mismatch", actor.ingest_telemetry, body)
        for days in (-8, 1):
            body = telemetry()
            body["clock_quality"] = {"status": "synchronized", "method": "ntp", "uncertainty_ms": 1, "offset_ms": None, "reference": "synthetic-clock-test"}
            body["observed_at"] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace("+00:00", "Z")
            self.assert_code("telemetry_age", actor.ingest_telemetry, body)
        self.assertEqual(actor.list_telemetry()["total"], 0)
        self.assertIsNone(actor.ingest_telemetry(telemetry())["envelope"]["observed_at"])

    def test_immutable_aquilon_mapping_unique_dev_eui_and_calibration_scope(self):
        self.hub.create_device(device())
        self.hub.create_device(device("device-2"))
        mapping = {"dev_eui": "0011223344556677", "calibration_refs": [{"code": 7, "sensor_kind": "temperature", "calibration_id": "synthetic-reference"}]}
        self.assertEqual(self.hub.put_aquilon_mapping("device-1", mapping), mapping)
        self.assertEqual(self.hub.put_aquilon_mapping("device-1", mapping), mapping)
        self.assert_code("mapping_conflict", self.hub.put_aquilon_mapping, "device-2", mapping)
        self.assert_code("mapping_conflict", self.hub.put_aquilon_mapping, "device-1", mapping | {"dev_eui": "1111223344556677"})
        actor, _ = self.credential("sensor", "device", device_id="device-1")
        self.assertEqual(actor.get_aquilon_mapping("device-1"), mapping)
        self.assert_code("not_found", actor.get_aquilon_mapping, "device-2")
        viewer, _ = self.credential("viewer", "viewer")
        self.assert_code("forbidden", viewer.get_aquilon_mapping, "device-1")
        body = telemetry()
        body["provenance"]["transport"] = "aquilon"
        body["radio"] = {"dev_eui": mapping["dev_eui"], "uptime_s": 1, "power_mode": "normal", "clock_claim": "unsynchronized",
                         "observed_at_unix_s": None, "network_received_at": None, "frame_sha256": "0" * 64, "calibration_code": 7}
        body["measurements"][0] |= {"quality": "calibrated", "calibration_id": "synthetic-reference"}
        bad = deepcopy(body)
        bad["measurements"][0]["calibration_id"] = "other-certificate"
        self.assert_code("telemetry_calibration", actor.ingest_telemetry, bad)
        bad = deepcopy(body)
        bad["radio"]["dev_eui"] = "1111223344556677"
        self.assert_code("telemetry_mapping", actor.ingest_telemetry, bad)
        self.assertEqual(actor.ingest_telemetry(body)["envelope"], body)

    def test_audit_is_scoped_and_stamps_real_actor_not_declared_observer(self):
        self.recording()
        self.recording("recording-2", "device-2", "site-2")
        reviewer, _ = self.credential()
        reviewer.create_observation("recording-1", observation() | {"observer": "Unverified display name"})
        admin, _ = self.credential("site-admin", "admin")
        audit = admin.list_audit(limit=200)
        self.assertTrue(all(item["site_id"] == "site-1" for item in audit["items"]))
        self.assertTrue(any(item["action"] == "observation.create" and item["actor_subject"] == "reviewer-1" for item in audit["items"]))
        self.assertFalse(any(item["actor_subject"] == "Unverified display name" for item in audit["items"]))
        self.assertEqual(admin.list_audit(offset=audit["total"])["items"], [])


class MigrationTests(unittest.TestCase):
    def legacy_workspace(self, root):
        with Hub(root) as hub:
            job = hub.submit_demo()
            hub.process_next_job()
            event = hub.list_events()["items"][0]
            hub.save_review(event["event_id"], "uncertain", "Synthetic migration test", "Declared test reviewer", 0)
        with closing(sqlite3.connect(root / "hub.sqlite3")) as connection, connection:
            for table in reversed({**PLATFORM_COLUMNS, **COMPANION_COLUMNS, **CONTROL_COLUMNS}):
                connection.execute(f"DROP TABLE {table}")
            connection.execute("PRAGMA user_version = 1")
            connection.execute("UPDATE metadata SET value = '1' WHERE key = 'workspace_schema'")
        return job

    def test_v1_additive_migration_preserves_old_rows_media_token_and_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "workspace"
            job = self.legacy_workspace(root)
            paths = [root / "evidence.sqlite3", root / "access.token", root / "recordings" / job["recording_id"] / "manifest.json", root / "recordings" / job["recording_id"] / "source.wav"]
            hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
            with closing(sqlite3.connect(root / "hub.sqlite3")) as connection, connection:
                rows = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in _EXPECTED_COLUMNS if table != "metadata"}
            with Hub(root) as hub:
                self.assertEqual(hub.list_recordings()["total"], 1)
                self.assertEqual(hub.list_observations(job["recording_id"])["total"], 0)
                self.assertIsNone(hub.get_recording_session(job["recording_id"]))
            with closing(sqlite3.connect(root / "hub.sqlite3")) as connection, connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], HUB_SCHEMA_VERSION)
                for table, before in rows.items():
                    self.assertEqual(connection.execute(f"SELECT * FROM {table}").fetchall(), before)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual({path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}, hashes)
            with Hub(root) as reopened:
                self.assertEqual(reopened.list_devices()["total"], 0)

    def test_failed_migration_rolls_back_and_old_store_remains_openable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "workspace"
            self.legacy_workspace(root)
            with patch("poseidon_trident.workspace.PLATFORM_SQL", "CREATE TABLE interrupted (id TEXT); INVALID SQL;"):
                with self.assertRaises(HubError) as caught:
                    Hub(root)
                self.assertEqual(caught.exception.code, "migration_failed")
            with closing(sqlite3.connect(root / "hub.sqlite3")) as connection, connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'interrupted'").fetchone())
            with Hub(root) as hub:
                self.assertEqual(hub.list_recordings()["total"], 1)

    def test_unrelated_v1_schema_is_rejected_before_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "workspace"
            self.legacy_workspace(root)
            with closing(sqlite3.connect(root / "hub.sqlite3")) as connection, connection:
                connection.execute("CREATE TABLE user_notes (note TEXT)")
            with self.assertRaises(HubError) as caught:
                Hub(root)
            self.assertEqual(caught.exception.code, "incompatible_workspace")
            with closing(sqlite3.connect(root / "hub.sqlite3")) as connection, connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name = 'principals'").fetchone())


if __name__ == "__main__":
    unittest.main()
