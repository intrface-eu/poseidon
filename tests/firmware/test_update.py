"""Synthetic host-only update tests; no production keys, flash, GPIO or RF."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firmware/update/src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from reef_update import (BootStore, ConfigurationController, ImageVerifier, Manifest,
                         Rejected, encode_configuration)


class PowerCut(RuntimeError):
    pass


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="reef-update-synthetic-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state.sqlite3"
        # Ephemeral test keys exist only in memory. Never provisioning material.
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.verifier = ImageVerifier("synthetic-esp32-reference", {"synthetic-test": self.public})
        self.store = BootStore(self.path, self.verifier, create=True)
        self.addCleanup(lambda: self.store.close())
        self.image = b"SYNTHETIC-NOT-EXECUTABLE-IMAGE\x00" * 8

    def artifact(self, **overrides):
        values = dict(schema="poseidon.reef.image.v1-proposal", board="synthetic-esp32-reference",
                      version=2, security_version=2, command_id=1, expires_at=2000,
                      image_size=len(self.image), image_sha256=hashlib.sha256(self.image).hexdigest(),
                      key_id="synthetic-test")
        values.update(overrides)
        raw = Manifest(**values).canonical()
        return raw, self.key.sign(raw), self.image

    def stage(self, **overrides):
        self.store.stage(*self.artifact(**overrides), now=1000)

    def reopen(self):
        self.store.close()
        self.store = BootStore(self.path, self.verifier)

    def test_signed_image_trial_and_confirmation(self):
        self.stage()
        self.store.schedule(now=1000)
        self.assertEqual(self.store.boot(now=1001), {"version": 2,
            "image_sha256": hashlib.sha256(self.image).hexdigest(), "trial": True, "reason": "candidate_trial"})
        self.store.confirm(running_sha256=hashlib.sha256(self.image).hexdigest(), running_version=2, healthy=True, now=1002)
        self.reopen()
        self.assertEqual(self.store.boot(now=1003)["version"], 2)
        self.assertEqual(self.store.snapshot()["security_floor"], 2)

    def test_unconfirmed_trial_rolls_back_after_restart(self):
        self.stage()
        self.store.schedule(now=1000)
        self.store.boot(now=1001)
        self.reopen()
        self.assertEqual(self.store.boot(now=None), {"version": 1,
            "image_sha256": None, "trial": False, "reason": "unconfirmed_trial_rollback"})
        self.assertEqual(self.store.snapshot()["security_floor"], 1)
        with self.assertRaisesRegex(Rejected, "replayed"):
            self.stage()

    def test_reject_unsigned_tampered_untrusted_and_wrong_board(self):
        raw, signature, image = self.artifact()
        cases = [(raw, b"", image), (raw, b"\0" * 64, image),
                 (raw, signature, image + b"x"), self.artifact(board="other-board"),
                 self.artifact(key_id="unknown"), self.artifact(image_sha256="0" * 64)]
        for case in cases:
            with self.subTest(case=hashlib.sha256(case[0]).hexdigest()):
                with self.assertRaises(Rejected):
                    self.store.stage(*case, now=1000)
                self.assertEqual(self.store.snapshot()["phase"], "confirmed")

    def test_expiry_unknown_clock_downgrade_and_limits(self):
        for args, now in [(self.artifact(), None), (self.artifact(), 2000),
                          (self.artifact(version=1), 1000),
                          (self.artifact(command_id=0), 1000),
                          (self.artifact(security_version=True), 1000)]:
            with self.subTest(now=now, manifest=args[0]):
                with self.assertRaises(Rejected):
                    self.store.stage(*args, now=now)
        bounded = ImageVerifier(self.verifier.board, {"synthetic-test": self.public}, max_image_bytes=5)
        with self.assertRaisesRegex(Rejected, "size"):
            bounded.verify(*self.artifact(), now=1000, security_floor=1, current_version=1, last_command_id=0)

    def test_security_floor_and_version_never_decrease(self):
        self.stage()
        self.store.schedule(now=1000)
        self.store.boot(now=1000)
        self.store.confirm(running_sha256=hashlib.sha256(self.image).hexdigest(), running_version=2, healthy=True, now=1000)
        with self.assertRaisesRegex(Rejected, "downgrade"):
            self.stage(version=3, security_version=1, command_id=2)
        with self.assertRaisesRegex(Rejected, "downgrade"):
            self.stage(version=2, security_version=2, command_id=2)
        self.stage(version=3, security_version=2, command_id=2)

    def test_manifest_canonical_shape_and_duplicate_rejection(self):
        raw, _, image = self.artifact()
        obj = json.loads(raw)
        malformed = [b"[]", b"{", b"x" * 1025, raw + b" ",
                     raw[:-1] + b',"version":3}',
                     json.dumps(obj, indent=2).encode(),
                     Manifest(**(obj | {"board": "bad board"})).canonical()]
        for body in malformed:
            with self.subTest(body=body[:40]):
                with self.assertRaises(Rejected):
                    self.store.stage(body, self.key.sign(body), image, now=1000)

    def test_stage_power_cuts_rollback_image_and_replay_floor(self):
        for point in ("after_image_write", "before_state_write", "before_commit"):
            with self.subTest(point=point):
                def cut(actual):
                    if actual == point:
                        raise PowerCut(point)
                self.store.fault = cut
                with self.assertRaises(PowerCut):
                    self.stage()
                self.reopen()
                self.assertEqual(self.store.snapshot()["last_command_id"], 0)
                self.assertEqual(self.store.db.execute("SELECT count(*) FROM image").fetchone()[0], 0)
        self.stage()

    def test_scheduled_trial_persists_before_boot_decision(self):
        self.stage()
        self.store.schedule(now=1000)
        self.store.fault = lambda point: (_ for _ in ()).throw(PowerCut(point)) if point == "before_commit" else None
        with self.assertRaises(PowerCut):
            self.store.boot(now=1000)
        self.reopen()
        self.assertEqual(self.store.snapshot()["phase"], "pending")
        self.assertTrue(self.store.boot(now=1000)["trial"])
        self.reopen()
        self.assertFalse(self.store.boot(now=1000)["trial"])

    def test_confirmation_interruption_rolls_back_on_next_boot(self):
        self.stage()
        self.store.schedule(now=1000)
        self.store.boot(now=1000)
        self.store.fault = lambda point: (_ for _ in ()).throw(PowerCut(point)) if point == "before_commit" else None
        with self.assertRaises(PowerCut):
            self.store.confirm(running_sha256=hashlib.sha256(self.image).hexdigest(), running_version=2, healthy=True, now=1000)
        self.reopen()
        self.assertEqual(self.store.boot(now=1000)["version"], 1)

    def test_pending_expiry_or_corruption_recovers_known_good(self):
        self.stage()
        self.store.schedule(now=1000)
        with self.store.db:
            self.store.db.execute("UPDATE image SET body=? WHERE id=1", (b"CORRUPT",))
        self.assertEqual(self.store.boot(now=1000)["reason"], "candidate_rejected")
        self.stage(command_id=2)
        self.store.schedule(now=1000)
        self.assertEqual(self.store.boot(now=2000)["reason"], "candidate_rejected")

    def test_invalid_state_transitions_and_health(self):
        with self.assertRaises(Rejected):
            self.store.schedule(now=1000)
        self.stage()
        with self.assertRaises(Rejected):
            self.stage(command_id=2)
        self.assertFalse(self.store.boot(now=1000)["trial"])
        self.store.schedule(now=1000)
        self.store.boot(now=1000)
        for version, healthy in ((2, False), (1, True), (True, True)):
            with self.assertRaises(Rejected):
                self.store.confirm(running_sha256=hashlib.sha256(self.image).hexdigest(), running_version=version, healthy=healthy, now=1000)
        with self.assertRaises(Rejected):
            self.store.cancel()

    def test_cancel_retains_replay_floor(self):
        self.stage()
        self.store.cancel()
        self.reopen()
        with self.assertRaisesRegex(Rejected, "replayed"):
            self.stage()
        self.stage(command_id=2)

    def test_factory_recreation_missing_and_corrupt_store_rejected(self):
        with self.assertRaises(Rejected):
            BootStore(self.path, self.verifier, create=True)
        with self.assertRaises(Rejected):
            BootStore(Path(self.tmp.name) / "missing.sqlite", self.verifier)
        broken = Path(self.tmp.name) / "broken.sqlite"
        broken.write_bytes(b"SYNTHETIC CORRUPTION")
        with self.assertRaises(sqlite3.DatabaseError):
            BootStore(broken, self.verifier)
        self.assertEqual(broken.read_bytes(), b"SYNTHETIC CORRUPTION")

    def test_corrupt_boot_metadata_never_returns_a_boot_decision(self):
        original = self.store.snapshot()
        for value in ([], {}, original | {"current_version": -1},
                      original | {"security_floor": True}, original | {"phase": "unknown"},
                      original | {"candidate": {}}, original | {"board": "wrong"}):
            with self.subTest(value=value):
                with self.store.db:
                    self.store.db.execute("UPDATE state SET body=? WHERE id=1", (json.dumps(value),))
                with self.assertRaises(Rejected):
                    self.store.boot(now=1000)
        with self.store.db:
            self.store.db.execute("UPDATE state SET body=? WHERE id=1", (json.dumps(original),))
        self.assertEqual(self.store.boot(now=1000)["version"], 1)

    def test_configuration_ack_duplicate_and_restart(self):
        controller = ConfigurationController(self.store, boot_id=9)
        payload = encode_configuration(9, 1, 1100, 600)
        self.assertEqual(len(payload), 21)
        self.assertEqual(controller.apply(payload, authenticated=True, now=1000)["status"], "applied")
        self.reopen()
        controller = ConfigurationController(self.store, boot_id=9)
        ack = controller.apply(payload, authenticated=True, now=1001)
        self.assertEqual((ack["status"], ack["interval_s"]), ("duplicate", 600))

    def test_configuration_full_uint64_boot_and_command_wrap(self):
        boot = 2**64 - 1
        controller = ConfigurationController(self.store, boot_id=boot)
        payload = encode_configuration(boot, 2**32 - 1, 1100, 600)
        self.assertEqual(controller.apply(payload, authenticated=True, now=1000)["boot_id"], str(boot))
        self.reopen()
        controller = ConfigurationController(self.store, boot_id=boot)
        self.assertEqual(controller.apply(payload, authenticated=True, now=1000)["status"], "duplicate")
        with self.assertRaisesRegex(Rejected, "stale"):
            controller.apply(encode_configuration(boot, 1, 1100, 300), authenticated=True, now=1000)
        old_boot = ConfigurationController(self.store, boot_id=boot - 1)
        with self.assertRaisesRegex(Rejected, "stale"):
            old_boot.apply(encode_configuration(boot - 1, 1, 1100, 300), authenticated=True, now=1000)
        with self.assertRaises(Rejected):
            encode_configuration(2**64, 1, 1100, 300)

    def test_configuration_rejects_wrong_target_auth_clock_replay_and_expiry(self):
        controller = ConfigurationController(self.store, boot_id=9)
        good = encode_configuration(9, 2, 1100, 600)
        controller.apply(good, authenticated=True, now=1000)
        cases = [(good, False, 1000), (good, True, None), (good, True, 1100),
                 (encode_configuration(8, 3, 1100, 600), True, 1000),
                 (encode_configuration(9, 1, 1100, 600), True, 1000),
                 (encode_configuration(9, 2, 1100, 601), True, 1000),
                 (encode_configuration(9, 3, 100000, 600), True, 1000),
                 (good + b"\0", True, 1000), (b"", True, 1000)]
        for payload, auth, now in cases:
            with self.subTest(payload=payload, auth=auth, now=now):
                with self.assertRaises(Rejected):
                    controller.apply(payload, authenticated=auth, now=now)

    def test_configuration_bounds_and_interrupted_commit(self):
        for boot, command, expiry, interval in [(0, 1, 1100, 300), (9, 0, 1100, 300),
                                              (9, 2**32, 1100, 300), (9, 1, 1100, 59),
                                              (9, 1, 1100, 86401), (True, 1, 1100, 300)]:
            with self.assertRaises(Rejected):
                encode_configuration(boot, command, expiry, interval)
        for point in ("after_config_write", "before_state_write", "before_commit"):
            controller = ConfigurationController(self.store, boot_id=9)
            self.store.fault = lambda actual: (_ for _ in ()).throw(PowerCut(actual)) if actual == point else None
            with self.assertRaises(PowerCut):
                controller.apply(encode_configuration(9, 1, 1100, 600), authenticated=True, now=1000)
            self.reopen()
            self.assertEqual(self.store.db.execute("SELECT command,interval FROM configuration").fetchone(), (0, 300))
        controller = ConfigurationController(self.store, boot_id=9)
        self.assertEqual(controller.apply(encode_configuration(9, 1, 1100, 600), authenticated=True, now=1000)["status"], "applied")


if __name__ == "__main__":
    unittest.main()
