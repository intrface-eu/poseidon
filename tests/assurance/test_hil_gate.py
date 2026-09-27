"""Synthetic signature/refusal checks only; no controller credential or HIL run.

Run with the existing locked API/update interpreter (cryptography==46.0.3).
Missing cryptography is a test failure, never a skipped positive validation.
"""
from __future__ import annotations

import base64
import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libs/proto-py/src"))
from poseidon_proto.signing import signing_bytes

SPEC = importlib.util.spec_from_file_location("hil_gate", ROOT / "scripts/assurance/hil_gate.py")
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@contextmanager
def synthetic_metadata_pin():
    """Mock Linux FD pin semantics using owned regular files, not Linux proof."""
    real_open = os.open
    flag = getattr(os, "O_PATH", 1 << 28)
    files = {}

    def opened(path, flags):
        if flags & flag:
            descriptor = real_open(path, os.O_RDONLY | os.O_NOFOLLOW)
            files[descriptor] = path
            return descriptor
        prefix = "/proc/self/fd/"
        if str(path).startswith(prefix):
            path = files[int(str(path)[len(prefix):])]
        return real_open(path, flags)

    with patch.object(gate.os, "O_PATH", flag, create=True), patch.object(gate.os, "open", side_effect=opened):
        yield


class HilRefusalTests(unittest.TestCase):
    def cli(self, *args: str, no_site: bool = False):
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHONPATH": str(ROOT / "libs/proto-py/src")}
        return subprocess.run([sys.executable, *(["-S"] if no_site else []), str(ROOT / "scripts/assurance/hil_gate.py"), *args],
                              env=environment, capture_output=True, text=True, timeout=10)

    def test_no_authorization_refuses_without_site_packages(self):
        result = self.cli(no_site=True)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("controller-signed authorization file is required", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_trust_refuses_without_site_packages(self):
        result = self.cli("--authorization", "/synthetic-not-read.json", no_site=True)
        self.assertEqual(result.returncode, 3)
        self.assertIn("explicit trusted controller key source", result.stderr)

    def test_bad_arguments_refuse(self):
        for args in (("--execute",), ("--authorization",), ("--authorization", "", "--trusted-controller-keys", "")):
            with self.subTest(args=args):
                self.assertEqual(self.cli(*args).returncode, 3)

    def test_missing_files_refuse(self):
        result = self.cli("--authorization", "/synthetic-missing-auth.json", "--trusted-controller-keys", "/synthetic-missing-keys.json")
        self.assertEqual(result.returncode, 3)

    def test_mocked_device_metadata_is_rejected_before_any_open(self):
        # No actual /dev path is probed or opened.
        device = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_size=12)
        with patch.object(Path, "lstat", return_value=device), patch.object(gate.os, "open") as opened:
            with self.assertRaises(gate.Refused):
                gate.load_object(Path("/SYNTHETIC-not-a-device"))
        opened.assert_not_called()

    def test_regular_file_loading_refuses_without_metadata_pin_support(self):
        with tempfile.TemporaryDirectory(prefix="poseidon-synthetic-hil-unavailable-") as temporary:
            path = Path(temporary).resolve() / "SYNTHETIC.json"
            path.write_text('{}')
            with patch.object(gate.os, "O_PATH", None, create=True), patch.object(gate.os, "open") as opened:
                with self.assertRaisesRegex(gate.Refused, "Linux O_PATH"):
                    gate.load_object(path)
                opened.assert_not_called()

    def test_mocked_replacement_device_cannot_reach_data_open(self):
        with tempfile.TemporaryDirectory(prefix="poseidon-synthetic-hil-replaced-") as temporary:
            path = Path(temporary).resolve() / "SYNTHETIC.json"
            path.write_text('{}')
            device = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600)
            with patch.object(gate.os, "O_PATH", 1 << 28, create=True), patch.object(gate.os, "open", return_value=999) as opened, patch.object(gate.os, "fstat", return_value=device), patch.object(gate.os, "close") as closed:
                with self.assertRaisesRegex(gate.Refused, "metadata pinning"):
                    gate.load_object(path)
                self.assertEqual(opened.call_count, 1)
                closed.assert_called_once_with(999)

    def test_real_regular_reader_matches_platform_limit_without_skips(self):
        with tempfile.TemporaryDirectory(prefix="poseidon-synthetic-hil-reader-") as temporary:
            path = Path(temporary).resolve() / "SYNTHETIC.json"
            path.write_text('{"synthetic":true}')
            if hasattr(os, "O_PATH"):
                self.assertEqual(gate.load_object(path), {"synthetic": True})
            else:
                with self.assertRaisesRegex(gate.Refused, "Linux O_PATH"):
                    gate.load_object(path)

    def test_make_maps_guard_three_to_process_two(self):
        with tempfile.TemporaryDirectory(prefix="poseidon-synthetic-hil-make-") as temporary:
            makefile = Path(temporary) / "Makefile"
            makefile.write_text(".PHONY: test-hil\ntest-hil:\n\t@\"" + sys.executable + "\" -S \"" + str(ROOT / "scripts/assurance/hil_gate.py") + "\"\n")
            result = subprocess.run(["make", "-f", str(makefile), "test-hil"], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Error 3", result.stderr)
        self.assertIn("HIL refused", result.stderr)


class HilSyntheticSignatureTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        self.now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
        # A fixed, public, synthetic seed, not a deployable controller key.
        self.private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.key_id = "SYNTHETIC-TEST-ONLY-controller-key"
        public = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.trust = {"schema_version": "poseidon.hil-controller-keys.v1", "keys": {self.key_id: {
            "controller_id": "SYNTHETIC-TEST-ONLY-controller", "public_key_hex": public.hex(), "revoked": False}}}
        self.payload = {"schema_version": "poseidon.hil-authorization.v1", "authorization_id": "00000000-0000-4000-8000-000000000001",
                        "controller_id": "SYNTHETIC-TEST-ONLY-controller", "scope": gate.SCOPE,
                        "issued_at": "2026-09-08T11:59:00Z", "expires_at": "2026-09-08T12:01:00Z", "digital_only": True}
        self.envelope = self.sign(self.payload)
        self.temporary = tempfile.TemporaryDirectory(prefix="poseidon-synthetic-hil-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def sign(self, payload):
        return {"payload": copy.deepcopy(payload), "signature": {"algorithm": "Ed25519", "key_id": self.key_id,
                "canonicalization": "poseidon-json-v1", "value": base64.b64encode(self.private.sign(signing_bytes(payload, self.key_id))).decode("ascii")}}

    def validate(self, envelope=None, trust=None, now=None):
        return gate.validate(self.envelope if envelope is None else envelope, self.trust if trust is None else trust, now=self.now if now is None else now)

    def test_real_synthetic_signature_only_validates_no_operation_is_dispatched(self):
        with patch("subprocess.Popen", side_effect=AssertionError("no operation may be spawned")), patch("os.system", side_effect=AssertionError("no shell")):
            result = self.validate()
        self.assertTrue(result["authorization_validated"])
        for key in ("hil_executed", "physical_operations_supported", "release_authorized"):
            self.assertIs(result[key], False)
        self.assertIn("no HIL implementation or device path ran", result["explanation"])

    def test_tampered_signed_payload_refuses(self):
        changed = copy.deepcopy(self.envelope)
        changed["payload"]["authorization_id"] = "00000000-0000-4000-8000-000000000002"
        with self.assertRaisesRegex(gate.Refused, "signature is invalid"):
            self.validate(changed)

    def test_wrong_untrusted_key_refuses_even_with_same_identifier(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        other = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
        trust = copy.deepcopy(self.trust)
        trust["keys"][self.key_id]["public_key_hex"] = other.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        with self.assertRaisesRegex(gate.Refused, "signature is invalid"):
            self.validate(trust=trust)

    def test_unknown_revoked_wrong_controller_refuse(self):
        for mutation in ("unknown", "revoked", "controller"):
            trust = copy.deepcopy(self.trust)
            if mutation == "unknown":
                trust["keys"]["SYNTHETIC-other-key"] = trust["keys"].pop(self.key_id)
            elif mutation == "revoked":
                trust["keys"][self.key_id]["revoked"] = True
            else:
                trust["keys"][self.key_id]["controller_id"] = "SYNTHETIC-other-controller"
            with self.subTest(mutation=mutation), self.assertRaises(gate.Refused):
                self.validate(trust=trust)

    def test_signed_wrong_scope_or_physical_intent_refuses(self):
        for change in ({"scope": "hardware-run"}, {"digital_only": False}, {"operation": "open-device"}, {"schema_version": "unknown"}):
            with self.subTest(change=change), self.assertRaises(gate.Refused):
                self.validate(self.sign(self.payload | change))

    def test_expired_future_and_lifetime_refuse(self):
        for now in (self.now + timedelta(minutes=1), self.now - timedelta(minutes=2)):
            with self.subTest(now=now), self.assertRaises(gate.Refused):
                self.validate(now=now)
        for change in ({"expires_at": "2026-09-08T12:59:00Z"}, {"expires_at": self.payload["issued_at"]},
                       {"issued_at": "invalid"}, {"expires_at": "2026-02-30T12:00:00Z"}):
            with self.subTest(change=change), self.assertRaises(gate.Refused):
                self.validate(self.sign(self.payload | change))

    def test_malformed_payload_and_clock_refuse(self):
        for change in ({"authorization_id": "not-a-uuid"}, {"authorization_id": True}, {"controller_id": "bad/controller"}, {"digital_only": 1}):
            with self.subTest(change=change), self.assertRaises(gate.Refused):
                self.validate(self.sign(self.payload | change))
        with self.assertRaises(gate.Refused):
            self.validate(now=datetime(2026, 9, 8))

    def test_embedded_keys_cannot_establish_trust(self):
        for value in (self.envelope | {"public_key_hex": self.trust["keys"][self.key_id]["public_key_hex"]},
                      self.envelope | {"trusted_keys": self.trust}):
            with self.assertRaises(gate.Refused):
                self.validate(value)

    def test_malformed_signature_refuses(self):
        for change in ({"algorithm": "none"}, {"canonicalization": "json"}, {"value": "not base64"}, {"value": "AA=="},
                       {"value": self.envelope["signature"]["value"] + "="}, {"value": None}, {"key_id": "../key"}):
            changed = copy.deepcopy(self.envelope)
            changed["signature"].update(change)
            with self.subTest(change=change), self.assertRaises(gate.Refused):
                self.validate(changed)

    def test_malformed_trusted_registry_refuses(self):
        for change in ({"revoked": "false"}, {"public_key_hex": "ff"}, {"controller_id": "bad/id"}):
            trust = copy.deepcopy(self.trust)
            trust["keys"][self.key_id].update(change)
            with self.subTest(change=change), self.assertRaises(gate.Refused):
                self.validate(trust=trust)
        with self.assertRaises(gate.Refused):
            self.validate(trust={"schema_version": "poseidon.hil-controller-keys.v1", "keys": {}})

    def test_bounded_regular_strict_json_only(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'\xff', b'x' * (gate.MAX_BYTES + 1)):
            path = self.root / "SYNTHETIC-bad.json"
            path.write_bytes(raw)
            with self.subTest(raw=raw[:30]), synthetic_metadata_pin(), self.assertRaises((ValueError, OSError)):
                gate.load_object(path)
        source = self.root / "SYNTHETIC-valid.json"
        source.write_text(json.dumps(self.envelope))
        link = self.root / "SYNTHETIC-link.json"
        link.symlink_to(source)
        with self.assertRaises(gate.Refused):
            gate.load_object(link)
        fifo = self.root / "SYNTHETIC-fifo"
        os.mkfifo(fifo)
        with self.assertRaises(gate.Refused):
            gate.load_object(fifo)

    def test_platform_cli_real_io_and_signature_without_skips(self):
        # On Linux this exercises real O_PATH and Ed25519, not the FD mock above.
        # Darwin must refuse; that branch is not reported as Linux validation.
        current = datetime.now(timezone.utc).replace(microsecond=0)
        stamp = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = self.payload | {"issued_at": stamp(current - timedelta(seconds=10)), "expires_at": stamp(current + timedelta(seconds=60))}
        auth = self.root / "SYNTHETIC-live-clock-authorization.json"
        trust = self.root / "SYNTHETIC-live-clock-trusted-keys.json"
        auth.write_text(json.dumps(self.sign(payload)))
        trust.write_text(json.dumps(self.trust))
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ROOT / "libs/proto-py/src")}
        result = subprocess.run([sys.executable, str(ROOT / "scripts/assurance/hil_gate.py"), "--authorization", str(auth), "--trusted-controller-keys", str(trust)], env=environment, capture_output=True, text=True, timeout=10)
        if hasattr(os, "O_PATH"):
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertTrue(value["authorization_validated"])
            self.assertFalse(value["hil_executed"])
        else:
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn("Linux O_PATH", result.stderr)

    def test_positive_cli_reports_validation_only_and_rejects_same_file_trust(self):
        auth = self.root / "SYNTHETIC-authorization.json"
        trust = self.root / "SYNTHETIC-trusted-keys.json"
        auth.write_text(json.dumps(self.envelope))
        trust.write_text(json.dumps(self.trust))
        real_validate = gate.validate
        with synthetic_metadata_pin(), patch("sys.stdout", new_callable=io.StringIO) as output:
            with patch.object(gate, "validate", wraps=lambda a, k: real_validate(a, k, now=self.now)):
                self.assertEqual(gate.main(["--authorization", str(auth), "--trusted-controller-keys", str(trust)]), 0)
        self.assertFalse(json.loads(output.getvalue())["hil_executed"])
        with patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(gate.main(["--authorization", str(auth), "--trusted-controller-keys", str(auth)]), 3)


if __name__ == "__main__":
    unittest.main()
