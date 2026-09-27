"""Real ephemeral signatures, synthetic non-executable images, host state only."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firmware/update/src"))
sys.path.insert(0, str(ROOT / "libs/proto-py/src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from poseidon_proto.platform import canonical_json, validate_contract
from poseidon_proto.signing import signing_bytes
from reef_update import BootStore, ImageVerifier, Manifest, Rejected
from reef_update.platform_manifest import PlatformImageVerifier, REFERENCE_SLOT_BYTES


class PlatformManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="reef-platform-synthetic-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "boot.sqlite"
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.bootstrap = hashlib.sha256(b"SYNTHETIC-KNOWN-GOOD-NOT-EXECUTABLE").hexdigest()
        self.image = b"SYNTHETIC-PLATFORM-UPDATE-NOT-EXECUTABLE" * 5
        self.now = int(datetime(2026, 9, 8, 12, tzinfo=timezone.utc).timestamp())
        self.verifier = PlatformImageVerifier("synthetic-esp32-ref", {"synthetic-key": self.public,
                                                                    "synthetic-key-alias": self.public})
        self.store = BootStore(self.path, self.verifier, create=True, initial_version="release-z",
                               initial_sha256=self.bootstrap)
        self.addCleanup(lambda: self.store.close())

    def envelope(self, **changes):
        fixture = json.loads((ROOT / "contracts/v1/fixtures/signed-manifest.valid.json").read_text())
        payload = fixture["payload"]
        payload.update(id="synthetic-reef-update-1", kind="update", target_kind="reef",
                       hardware_revision="synthetic-esp32-ref", version="release-a", sequence=1,
                       security_version=2, artifact_sha256=hashlib.sha256(self.image).hexdigest(),
                       artifact_size_bytes=len(self.image), previous_sha256=self.bootstrap)
        payload.update(changes)
        signature = self.key.sign(signing_bytes(payload, "synthetic-key"))
        fixture["signature"].update(key_id="synthetic-key", value=base64.b64encode(signature).decode("ascii"))
        return fixture

    def stage(self, envelope=None):
        envelope = self.envelope() if envelope is None else envelope
        self.store.stage(canonical_json(envelope), b"", self.image, now=self.now)

    def reopen(self):
        self.store.close()
        self.store = BootStore(self.path, self.verifier)

    def test_shared_signing_bytes_and_real_positive_fixture(self):
        envelope = self.envelope()
        self.assertEqual(validate_contract("signed-manifest", envelope), envelope)
        expected = b"poseidon.signed-manifest.v1\0synthetic-key\0" + canonical_json(envelope["payload"])
        self.assertEqual(signing_bytes(envelope["payload"], "synthetic-key"), expected)
        self.key.public_key().verify(base64.b64decode(envelope["signature"]["value"]), expected)
        candidate = self.verifier.verify(canonical_json(envelope), b"", self.image, now=self.now,
                    security_floor=1, current_version="release-z", last_command_id=0,
                    current_digest=self.bootstrap)
        self.assertEqual((candidate.version, candidate.command_id), ("release-a", 1))

    def test_stage_retains_original_envelope_and_confirmed_digest(self):
        envelope = self.envelope()
        self.stage(envelope)
        raw, detached = self.store.db.execute("SELECT manifest,signature FROM image").fetchone()
        self.assertEqual(raw, canonical_json(envelope))
        self.assertEqual(detached, b"")
        self.store.schedule(now=self.now)
        self.assertEqual(self.store.boot(now=self.now)["version"], "release-a")
        self.store.confirm(running_sha256=hashlib.sha256(self.image).hexdigest(), running_version="release-a", healthy=True, now=self.now)
        self.reopen()
        state = self.store.snapshot()
        self.assertEqual((state["current_version"], state["security_floor"]), ("release-a", 2))
        self.assertEqual(state["current_sha256"], hashlib.sha256(self.image).hexdigest())
        self.assertEqual(state["verifier_profile"], "poseidon.signed-manifest.v1")

    def test_unsigned_schema_fixture_and_signature_domain_mutations_rejected(self):
        unsigned = json.loads((ROOT / "contracts/v1/fixtures/signed-manifest.valid.json").read_text())
        validate_contract("signed-manifest", unsigned)
        wrong_domain = self.envelope()
        wrong_domain["signature"]["value"] = base64.b64encode(self.key.sign(canonical_json(wrong_domain["payload"]))).decode()
        changed_key = self.envelope()
        changed_key["signature"]["key_id"] = "synthetic-key-alias"
        missing_key = self.envelope()
        missing_key["signature"]["key_id"] = "missing-key"
        for envelope in (unsigned, wrong_domain, changed_key, missing_key):
            with self.subTest(envelope=envelope["payload"]["id"]):
                with self.assertRaises(Rejected):
                    self.stage(envelope)
        self.assertEqual(self.store.snapshot()["last_command_id"], 0)

    def test_signed_field_mutations_without_resigning_reject(self):
        for field, value in {"hardware_revision": "wrong", "target_kind": "hub", "kind": "release",
                             "sequence": 2, "security_version": 3, "artifact_sha256": "0" * 64,
                             "artifact_size_bytes": 1, "version": "changed",
                             "previous_sha256": None, "expires_at": "2026-09-10T00:00:00Z"}.items():
            with self.subTest(field=field):
                envelope = self.envelope()
                envelope["payload"][field] = value
                with self.assertRaisesRegex(Rejected, "signature"):
                    self.stage(envelope)

    def test_correct_signature_still_checks_target_kind_base_and_security(self):
        for changes in ({"hardware_revision": "wrong"}, {"target_kind": "hub"}, {"kind": "config"},
                        {"previous_sha256": None}, {"previous_sha256": "0" * 64},
                        {"security_version": 0}, {"sequence": 0}):
            with self.subTest(changes=changes):
                with self.assertRaises(Rejected):
                    self.stage(self.envelope(**changes))
        self.assertEqual(self.store.snapshot()["last_command_id"], 0)

    def test_trusted_time_issued_expiry_and_size_limits(self):
        raw = canonical_json(self.envelope())
        for now in (None, self.now - 86400, self.now + 86400, True):
            with self.subTest(now=now):
                with self.assertRaises(Rejected):
                    self.store.stage(raw, b"", self.image, now=now)
        for image in (b"", self.image + b"tampered"):
            with self.assertRaises(Rejected):
                self.store.stage(raw, b"", image, now=self.now)
        bounded = PlatformImageVerifier("synthetic-esp32-ref", {"synthetic-key": self.public}, max_image_bytes=1)
        with self.assertRaisesRegex(Rejected, "size"):
            bounded.verify(raw, b"", self.image, now=self.now, security_floor=1,
                           current_version="release-z", last_command_id=0, current_digest=self.bootstrap)
        self.assertEqual(REFERENCE_SLOT_BYTES, 0x1F0000)

    def test_canonical_json_shape_duplicate_keys_booleans_and_signature_pad_bits(self):
        envelope = self.envelope()
        raw = canonical_json(envelope)
        invalid = [raw + b" ", json.dumps(envelope, indent=2).encode(), b"[" * 2000 + b"]" * 2000,
                   raw[:-1] + b',"payload":{}}', b"x" * 8193,
                   canonical_json(self.envelope(sequence=True)), canonical_json(self.envelope(sequence=1.0))]
        # Low unused base64 bits must be zero even when decoded signature bytes match.
        padded = deepcopy(envelope)
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        sig = padded["signature"]["value"]
        padded["signature"]["value"] = sig[:-3] + alphabet[alphabet.index(sig[-3]) + 1] + "=="
        invalid.append(canonical_json(padded))
        for body in invalid:
            with self.subTest(body=body[:30]):
                with self.assertRaises(Rejected):
                    self.store.stage(body, b"", self.image, now=self.now)

    def test_integer_digit_limit_is_a_typed_rejection_without_global_changes(self):
        limit = sys.get_int_max_str_digits()
        raw = b'{"schema_version":' + b"9" * 5000 + b"}"
        self.assertLess(len(raw), 8192)
        with self.assertRaises(Rejected):
            PlatformImageVerifier.parse(raw)
        with self.assertRaises(Rejected):
            self.store.stage(raw, b"", self.image, now=self.now)
        self.assertEqual(sys.get_int_max_str_digits(), limit)
        self.assertEqual(self.store.snapshot()["last_command_id"], 0)
        with self.assertRaisesRegex(Rejected, "duplicate manifest field"):
            PlatformImageVerifier.parse(b'{"payload":{},"payload":{}}')
        with self.assertRaisesRegex(Rejected, "noncanonical platform envelope"):
            PlatformImageVerifier.parse(canonical_json(self.envelope()) + b" ")

    def test_formats_and_stores_never_autodetect_or_fallback(self):
        raw = canonical_json(self.envelope())
        with self.assertRaises(Rejected):
            self.store.stage(raw, b"\0" * 64, self.image, now=self.now)
        private = Manifest("poseidon.reef.image.v1-proposal", "synthetic-esp32-ref", 2, 2, 1,
                           self.now + 100, len(self.image), hashlib.sha256(self.image).hexdigest(), "synthetic-key").canonical()
        with self.assertRaises(Rejected):
            self.store.stage(private, b"", self.image, now=self.now)
        legacy = ImageVerifier("synthetic-esp32-ref", {"synthetic-key": self.public})
        with self.assertRaises(Rejected):
            legacy.verify(raw, b"\0" * 64, self.image, now=self.now, security_floor=1,
                          current_version=1, last_command_id=0)
        with self.assertRaises(Rejected):
            BootStore(self.path, legacy)

    def test_sequence_order_not_lexical_release_name_and_digest_chain(self):
        self.stage()
        self.store.schedule(now=self.now)
        self.store.boot(now=self.now)
        self.store.confirm(running_sha256=hashlib.sha256(self.image).hexdigest(), running_version="release-a", healthy=True, now=self.now)
        self.image = b"SYNTHETIC-SECOND-IMAGE"
        with self.assertRaisesRegex(Rejected, "previous"):
            self.stage(self.envelope(sequence=2, version="release-0"))
        envelope = self.envelope(sequence=2, version="release-0", previous_sha256=self.store.snapshot()["current_sha256"])
        self.stage(envelope)
        self.store.schedule(now=self.now)
        self.assertEqual(self.store.boot(now=self.now)["version"], "release-0")

    def test_repeated_version_label_requires_the_actual_candidate_digest(self):
        self.stage(self.envelope(version="release-z"))
        self.store.schedule(now=self.now)
        decision = self.store.boot(now=self.now)
        candidate_digest = hashlib.sha256(self.image).hexdigest()
        self.assertEqual(decision["version"], "release-z")
        self.assertEqual(decision["image_sha256"], candidate_digest)
        self.assertNotEqual(candidate_digest, self.bootstrap)
        for wrong_digest in (self.bootstrap, "0" * 64, None, b"not-a-digest"):
            with self.subTest(digest=wrong_digest):
                with self.assertRaisesRegex(Rejected, "wrong running image"):
                    self.store.confirm(running_version="release-z", running_sha256=wrong_digest,
                                       healthy=True, now=self.now)
                self.assertEqual(self.store.snapshot()["current_sha256"], self.bootstrap)
                self.assertEqual(self.store.snapshot()["security_floor"], 1)
                self.assertEqual(self.store.snapshot()["phase"], "trial")
        self.store.confirm(running_version="release-z", running_sha256=candidate_digest,
                           healthy=True, now=self.now)
        self.assertEqual(self.store.snapshot()["current_sha256"], candidate_digest)
        self.assertEqual(self.store.snapshot()["security_floor"], 2)

    def test_uint32_sequence_exhaustion_and_replay_after_rollback(self):
        self.stage(self.envelope(sequence=2**32 - 1))
        self.store.schedule(now=self.now)
        self.store.boot(now=self.now)
        self.reopen()
        self.assertEqual(self.store.boot(now=None)["version"], "release-z")
        self.assertEqual(self.store.snapshot()["current_sha256"], self.bootstrap)
        with self.assertRaisesRegex(Rejected, "replay"):
            self.stage(self.envelope(sequence=1))
        with self.assertRaises(Rejected):
            self.stage(self.envelope(sequence=2**32))

    def test_staging_interruptions_do_not_consume_sequence(self):
        for point in ("after_image_write", "before_state_write", "before_commit"):
            def cut(actual):
                if actual == point:
                    raise RuntimeError("synthetic power cut")
            self.store.fault = cut
            with self.assertRaisesRegex(RuntimeError, "power cut"):
                self.stage()
            self.reopen()
            self.assertEqual(self.store.snapshot()["last_command_id"], 0)
            self.assertEqual(self.store.db.execute("SELECT count(*) FROM image").fetchone()[0], 0)
        self.stage()

    def test_confirmation_interrupt_reverts_image_digest_and_version(self):
        self.stage()
        self.store.schedule(now=self.now)
        self.store.boot(now=self.now)
        self.store.fault = lambda point: (_ for _ in ()).throw(RuntimeError("cut")) if point == "before_commit" else None
        with self.assertRaises(RuntimeError):
            self.store.confirm(running_sha256=hashlib.sha256(self.image).hexdigest(), running_version="release-a", healthy=True, now=self.now)
        self.reopen()
        self.assertEqual(self.store.boot(now=None)["reason"], "unconfirmed_trial_rollback")
        self.assertEqual(self.store.snapshot()["current_sha256"], self.bootstrap)
        self.assertEqual(self.store.snapshot()["last_command_id"], 1)

    def test_revocation_or_corrupt_stored_envelope_blocks_trial(self):
        self.stage()
        self.store.schedule(now=self.now)
        self.verifier.keys.pop("synthetic-key")
        self.assertEqual(self.store.boot(now=self.now)["reason"], "candidate_rejected")
        self.assertEqual(self.store.snapshot()["current_sha256"], self.bootstrap)

    def test_schema_config_is_retained_but_not_applied(self):
        envelope = self.envelope()
        self.stage(envelope)
        self.store.schedule(now=self.now)
        self.store.boot(now=self.now)
        self.store.confirm(running_sha256=hashlib.sha256(self.image).hexdigest(), running_version="release-a", healthy=True, now=self.now)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM configuration").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
