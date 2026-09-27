"""Ephemeral Ed25519 keys and local simulated targets, not hardware update tests."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from poseidon_trident import Hub, HubError
from poseidon_trident.lifecycle import LocalLifecycle, sign_test_manifest

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    Ed25519PrivateKey = None


@unittest.skipIf(Ed25519PrivateKey is None, "run via API locked environment for cryptography")
class LocalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="poseidon-lifecycle-test-")
        self.root = Path(self.temp.name) / "hub"
        self.hub = Hub(self.root)
        self.now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
        self.lifecycle = LocalLifecycle(self.hub, now=lambda: self.now)
        self.identity = self.hub.current_identity()
        self.private = Ed25519PrivateKey.generate()
        self.lifecycle.add_key(self.identity, {"id": "synthetic-key", "site_ids": ["synthetic-site"], "public_key_hex": self.private.public_key().public_bytes_raw().hex()})
        self.hub.create_device({"id": "synthetic-reef", "site_id": "synthetic-site", "label": "Synthetic lifecycle test", "kind": "reef", "hardware_revision": "simulation-v1", "source_kind": "synthetic"})
        self.baseline = hashlib.sha256(b"synthetic baseline").hexdigest()
        self.lifecycle.create_target(self.identity, {"id": "synthetic-target", "device_id": "synthetic-reef", "simulation": True, "initial_sha256": self.baseline, "initial_version": "synthetic-0", "security_floor": 0})
        self.artifact = b"Synthetic signed artifact; never execute or flash."

    def tearDown(self):
        self.hub.close()
        self.temp.cleanup()

    def body(self, **changes):
        payload = {"schema_version": "poseidon.signed-manifest.v1", "id": "synthetic-update-1", "kind": "update", "target_kind": "reef", "hardware_revision": "simulation-v1", "version": "synthetic-1", "sequence": 1, "security_version": 1, "issued_at": "2026-09-08T00:00:00Z", "expires_at": "2026-09-09T00:00:00Z", "artifact_sha256": hashlib.sha256(self.artifact).hexdigest(), "artifact_size_bytes": len(self.artifact), "previous_sha256": self.baseline, "config": {"monitor_only": True, "telemetry_interval_s": 60, "offline_queue_limit": 128}}
        payload.update(changes)
        return {"manifest": sign_test_manifest(payload, "synthetic-key", self.private), "artifact_base64": base64.b64encode(self.artifact).decode()}

    def stage(self, **changes):
        return self.lifecycle.stage(self.identity, "synthetic-target", self.body(**changes))

    def move(self, action):
        return self.lifecycle.transition(self.identity, "synthetic-target", action)

    def assert_code(self, expected, callback):
        with self.assertRaises(HubError) as raised:
            callback()
        self.assertEqual(raised.exception.code, expected)

    def test_shared_signing_bytes_compatibility_export(self):
        from poseidon_proto.signing import signing_bytes as shared
        from poseidon_trident.lifecycle import signing_bytes as compatibility
        payload = self.body()["manifest"]["payload"]
        self.assertIs(shared, compatibility)
        self.assertEqual(shared(payload, "synthetic-key"), compatibility(payload, "synthetic-key"))

    def test_signed_stage_trial_and_health_confirmation(self):
        self.assertEqual(self.stage()["state"], "staged")
        self.assertEqual(self.move("activate")["state"], "trial")
        committed = self.move("confirm")
        self.assertEqual(committed["state"], "healthy")
        self.assertEqual(committed["security_floor"], 1)
        self.assertEqual(committed["current_sha256"], hashlib.sha256(self.artifact).hexdigest())
        self.assert_code("security_floor", lambda: self.move("rollback"))
        history = self.lifecycle.history(self.identity, "synthetic-target")["items"]
        self.assertEqual([item["action"] for item in history], ["create", "stage", "activate", "confirm"])
        self.assertTrue(all(item["actor_subject"] == self.identity["subject"] for item in history))
        self.assertNotIn("artifact_base64", committed)
        audit = self.hub.list_audit()["items"]
        self.assertIn("lifecycle.confirm", [entry["action"] for entry in audit])
        self.assertNotIn("artifact_base64", str(audit))

    def test_power_loss_restart_preserves_trial_and_explicit_recovery(self):
        self.stage()
        self.move("activate")
        self.hub.close()
        self.hub = Hub(self.root)
        self.lifecycle = LocalLifecycle(self.hub, now=lambda: self.now)
        self.assertEqual(self.lifecycle.get_target(self.identity, "synthetic-target")["state"], "trial")
        recovered = self.move("recover")
        self.assertEqual(recovered["state"], "rolled_back")
        self.assertEqual(recovered["current_sha256"], self.baseline)
        self.assertEqual(recovered["highest_sequence"], 1)
        self.assert_code("manifest_replay", self.stage)
        self.assertEqual(self.stage(sequence=2, id="synthetic-update-2")["state"], "staged")

    def test_restart_at_each_persisted_stage_never_autoconfirms(self):
        for state, transition in [("staged", None), ("trial", "activate"), ("healthy", "confirm")]:
            if state == "staged":
                self.stage(security_version=0)
            elif transition:
                self.move(transition)
            self.hub.close()
            self.hub = Hub(self.root)
            self.lifecycle = LocalLifecycle(self.hub, now=lambda: self.now)
            self.assertEqual(self.lifecycle.get_target(self.identity, "synthetic-target")["state"], state)
        self.assertEqual(self.move("rollback")["current_sha256"], self.baseline)

    def test_bad_signature_digest_size_target_base_and_time_rejected(self):
        body = self.body()
        body["manifest"]["payload"]["version"] = "tampered"
        self.assert_code("invalid_signature", lambda: self.lifecycle.stage(self.identity, "synthetic-target", body))
        for changes, expected in [(dict(artifact_sha256="0" * 64), "artifact_mismatch"), (dict(artifact_size_bytes=1), "artifact_mismatch"), (dict(hardware_revision="other"), "incompatible_manifest"), (dict(previous_sha256="1" * 64), "base_mismatch"), (dict(issued_at="2026-09-08T13:00:00Z"), "manifest_expired"), (dict(expires_at="2026-09-08T01:00:00Z"), "manifest_expired")]:
            with self.subTest(expected=expected):
                self.assert_code(expected, lambda: self.stage(**changes))
        self.assertEqual(self.lifecycle.get_target(self.identity, "synthetic-target")["highest_sequence"], -1)

    def test_revocation_and_expiry_rechecked_before_activation_and_confirm(self):
        self.stage()
        self.now += timedelta(days=2)
        self.assert_code("manifest_expired", lambda: self.move("activate"))
        self.now -= timedelta(days=2)
        self.move("activate")
        self.lifecycle.revoke_key(self.identity, "synthetic-key")
        self.assert_code("untrusted_manifest", lambda: self.move("confirm"))
        self.assertEqual(self.move("recover")["state"], "rolled_back")

    def test_cross_site_roles_and_trust_root_boundaries(self):
        for role in ["viewer", "reviewer", "device"]:
            identity = {"subject": "synthetic-reader", "role": role, "site_ids": ["synthetic-site"], "device_id": None, "auth_mode": "scoped_token"}
            self.assert_code("forbidden", lambda: self.lifecycle.stage(identity, "synthetic-target", self.body()))
        other = {"subject": "synthetic-admin", "role": "admin", "site_ids": ["other-site"], "device_id": None, "auth_mode": "scoped_token"}
        self.assertEqual(self.lifecycle.list_targets(other)["total"], 0)
        self.assert_code("not_found", lambda: self.lifecycle.get_target(other, "synthetic-target"))
        self.assert_code("forbidden", lambda: self.lifecycle.revoke_key(other, "synthetic-key"))

    def test_no_field_target_and_no_boolean_security_floor(self):
        self.hub.create_device({"id": "field-registry-only", "site_id": "synthetic-site", "label": "Test-only registry field enum", "kind": "reef", "hardware_revision": "simulation-v1", "source_kind": "field"})
        body = {"id": "another-target", "device_id": "field-registry-only", "simulation": True, "initial_sha256": self.baseline, "initial_version": "synthetic-0", "security_floor": 0}
        self.assert_code("simulation_only", lambda: self.lifecycle.create_target(self.identity, body))
        body["security_floor"] = True
        self.assert_code("invalid_lifecycle", lambda: self.lifecycle.create_target(self.identity, body))

    def test_invalid_base64_and_unknown_fields(self):
        body = self.body()
        body["artifact_base64"] = "not base64"
        self.assert_code("invalid_artifact", lambda: self.lifecycle.stage(self.identity, "synthetic-target", body))
        body = self.body()
        body["path"] = "/tmp/no"
        self.assert_code("invalid_lifecycle", lambda: self.lifecycle.stage(self.identity, "synthetic-target", body))
        bad_key = {"id": "bad", "site_ids": [{}], "public_key_hex": "0" * 64}
        self.assert_code("invalid_lifecycle", lambda: self.lifecycle.add_key(self.identity, bad_key))

    def test_state_conflicts_and_discard_staged_artifact_keep_replay_floor(self):
        self.assert_code("transition_conflict", lambda: self.move("confirm"))
        self.stage()
        self.assert_code("transition_conflict", self.stage)
        self.assertEqual(self.move("recover")["state"], "rolled_back")
        self.assert_code("manifest_replay", self.stage)


if __name__ == "__main__":
    unittest.main()
