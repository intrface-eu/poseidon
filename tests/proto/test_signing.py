"""Signing-byte parity needs no Hub, installed crypto package or private key."""
import json
import subprocess
import sys
import unittest

from poseidon_proto.models import ModelValidationError
from poseidon_proto.platform import SCHEMA_DIR, canonical_json
from poseidon_proto.signing import signing_bytes


class SigningBytesTests(unittest.TestCase):
    def test_approved_domain_and_golden_payload_bytes(self):
        manifest = json.loads((SCHEMA_DIR / "fixtures/signed-manifest.valid.json").read_text())
        payload = manifest["payload"]
        expected = b"poseidon.signed-manifest.v1\0synthetic-test-key\0" + canonical_json(payload)
        self.assertEqual(signing_bytes(payload, "synthetic-test-key"), expected)
        self.assertNotEqual(signing_bytes(payload, "other-key"), expected)

    def test_unicode_ascii_canonicalization_and_key_validation(self):
        self.assertEqual(signing_bytes({"z": 1, "a": "é"}, "key"), b'poseidon.signed-manifest.v1\0key\0{"a":"\\u00e9","z":1}')
        for key in ["", "bad\n", "key\0suffix", "é", True, 1]:
            with self.assertRaises(ModelValidationError):
                signing_bytes({}, key)

    def test_proto_import_has_no_hub_or_crypto_dependency(self):
        code = "from poseidon_proto.signing import signing_bytes; import sys; assert not any(n.startswith(('poseidon_trident','cryptography')) for n in sys.modules)"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
