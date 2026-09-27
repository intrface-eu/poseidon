"""Synthetic host tests for the K1 `config-apply` acknowledgement formatter.

Keys are generated in memory for the test process. No broker, no dispatch, no
retained delivery and no device is involved. Parsing a document here proves its
shape, never that anyone authenticated it.
"""
from __future__ import annotations

import base64
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firmware/reef/host"))
sys.path.insert(0, str(ROOT / "libs/proto-py/src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from poseidon_proto.command import parse_command_ack, payload_bytes
from poseidon_proto.models import ModelValidationError
from reef_config_ack import (ACK_SCHEMA_VERSION, AckContext, AckRefused,
                             ack_for_config_apply_command, bridge_legacy_configuration,
                             format_config_apply_ack)

COMMAND_ID = "6f1a2b3c-4d5e-4f60-8a1b-2c3d4e5f6071"
DEVICE_ID = "synthetic-reef-01"
CONFIG_V2 = {"schema_version": "poseidon.digital-config.v2", "simulation": True,
             "health_interval_s": 60}
CONFIG_V1 = {"schema_version": "poseidon.digital-config.v1", "health_interval_s": 60}


def context(**changes) -> AckContext:
    values = dict(command_id=COMMAND_ID, device_id=DEVICE_ID,
                  received_at="2026-09-08T12:00:00Z", outcome="executed",
                  reason="configuration applied", state_after="observe", sequence_seen="42")
    values.update(changes)
    return AckContext(**values)


class ConfigApplyAckTests(unittest.TestCase):
    def test_canonical_ack_is_the_only_output_shape(self):
        ack = format_config_apply_ack(context(), config=CONFIG_V2)
        self.assertEqual(ack, {"schema_version": ACK_SCHEMA_VERSION, "command_id": COMMAND_ID,
                               "device_id": DEVICE_ID, "received_at": "2026-09-08T12:00:00Z",
                               "outcome": "executed", "reason": "configuration applied",
                               "state_after": "observe", "sequence_seen": "42"})
        # The formatter's own output re-parses, and there is no second format.
        self.assertEqual(parse_command_ack(ack), ack)

    def test_every_context_field_is_required_and_checked(self):
        for change in ({"command_id": "not-a-uuid"},
                       {"command_id": "6f1a2b3c-4d5e-1f60-8a1b-2c3d4e5f6071"},  # not version 4
                       {"command_id": None}, {"device_id": ""}, {"device_id": "bad id"},
                       {"received_at": "2026-09-08T12:00:00+02:00"},
                       {"received_at": "2026-09-08 12:00:00Z"},
                       {"outcome": "acknowledged"}, {"outcome": 1},
                       {"reason": ""}, {"reason": "x" * 257}, {"reason": "line\nbreak"},
                       {"state_after": "unknown"}, {"sequence_seen": 42},
                       {"sequence_seen": "042"}, {"sequence_seen": "-1"}):
            with self.subTest(**change), self.assertRaises(AckRefused):
                context(**change)
        with self.assertRaises(TypeError):
            AckContext(command_id=COMMAND_ID, device_id=DEVICE_ID)

    def test_partial_context_object_is_refused(self):
        for bad in (None, {}, dict(command_id=COMMAND_ID), "executed"):
            with self.subTest(context=bad), self.assertRaises(AckRefused):
                format_config_apply_ack(bad, config=CONFIG_V2)

    def test_emit_can_never_appear_in_an_ack(self):
        with self.assertRaises(AckRefused):
            context(state_after="emit")
        forged = {"schema_version": ACK_SCHEMA_VERSION, "command_id": COMMAND_ID,
                  "device_id": DEVICE_ID, "received_at": "2026-09-08T12:00:00Z",
                  "outcome": "executed", "reason": "forged", "state_after": "emit",
                  "sequence_seen": "42"}
        with self.assertRaises(ModelValidationError):
            parse_command_ack(forged)

    def test_counter_overflow_is_refused(self):
        self.assertEqual(context(sequence_seen=str(2**64 - 1)).sequence_seen, "18446744073709551615")
        for value in (str(2**64), str(2**64 + 1), "9" * 21):
            with self.subTest(sequence_seen=value), self.assertRaises(AckRefused):
                context(sequence_seen=value)

    def test_retained_delivery_is_refused(self):
        with self.assertRaises(ModelValidationError):
            format_config_apply_ack(context(), config=CONFIG_V2, retained=True)
        with self.assertRaises(AckRefused):
            format_config_apply_ack(context(), config=CONFIG_V2, retained="false")

    def test_config_is_accepted_only_through_the_migration_registry(self):
        self.assertEqual(format_config_apply_ack(context(), config=CONFIG_V1)["outcome"], "executed")
        for bad in ({"schema_version": "poseidon.digital-config.v0", "health_interval_s": 60},
                    {"schema_version": "poseidon.digital-config.v2", "simulation": False,
                     "health_interval_s": 60},
                    {"schema_version": "poseidon.digital-config.v1", "health_interval_s": 0},
                    {"schema_version": "poseidon.digital-config.v1", "health_interval_s": 3601},
                    {"health_interval_s": 60}, []):
            with self.subTest(config=bad), self.assertRaises(ModelValidationError):
                format_config_apply_ack(context(), config=bad)

    def test_applied_outcomes_require_the_configuration_they_applied(self):
        for outcome in ("accepted", "executed"):
            with self.subTest(outcome=outcome), self.assertRaises(AckRefused):
                format_config_apply_ack(context(outcome=outcome), config=None)
        for outcome in ("rejected", "expired", "duplicate", "failed"):
            with self.subTest(outcome=outcome):
                ack = format_config_apply_ack(context(outcome=outcome, reason="refused"),
                                              config=None)
                self.assertEqual(ack["outcome"], outcome)
        # A refusal that does carry a configuration still migrates it.
        with self.assertRaises(ModelValidationError):
            format_config_apply_ack(context(outcome="rejected", reason="bad config"),
                                    config={"schema_version": "poseidon.digital-config.v9"})

    def test_legacy_device_config_interval_is_not_bridged(self):
        with self.assertRaises(AckRefused) as caught:
            bridge_legacy_configuration(interval_s=300)
        message = str(caught.exception)
        self.assertIn("60..86400", message)
        self.assertIn("1..3600", message)


class CommandDerivedAckTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()

    def command(self, *, sign_correctly=True, **changes) -> dict:
        document = {"schema_version": "poseidon.command.v1", "command_id": COMMAND_ID,
                    "site_id": "synthetic-site", "zone_id": "synthetic-zone",
                    "device_id": DEVICE_ID, "principal_id": "synthetic-operator",
                    "key_id": "synthetic-session-key", "sequence": "42",
                    "issued_at": "2026-09-08T11:59:30Z", "expires_at": "2026-09-08T12:00:30Z",
                    "kind": "config-apply", "params": {"config": dict(CONFIG_V2)},
                    "signature": {"algorithm": "Ed25519", "canonicalization": "poseidon-json-v1",
                                  "value": base64.b64encode(bytes(64)).decode("ascii")}}
        document.update(changes)
        if sign_correctly:
            signature = self.key.sign(payload_bytes(document))
            document["signature"]["value"] = base64.b64encode(signature).decode("ascii")
        return document

    def ack(self, command=None, **changes):
        values = dict(device_id=DEVICE_ID, received_at="2026-09-08T12:00:00Z",
                      outcome="executed", reason="configuration applied", state_after="observe")
        values.update(changes)
        return ack_for_config_apply_command(self.command() if command is None else command, **values)

    def test_identity_and_counter_are_copied_from_the_command(self):
        ack = self.ack()
        self.assertEqual(ack["command_id"], COMMAND_ID)
        self.assertEqual(ack["sequence_seen"], "42")
        self.assertEqual(ack["schema_version"], ACK_SCHEMA_VERSION)

    def test_schema_parsing_is_not_authentication(self):
        # A syntactically valid signature over nothing still parses. The ack this
        # produces asserts handling, never that the command was authenticated.
        ack = self.ack(self.command(sign_correctly=False))
        self.assertEqual(ack["command_id"], COMMAND_ID)

    def test_wrong_device_and_wrong_kind_are_refused(self):
        with self.assertRaises(AckRefused):
            self.ack(device_id="synthetic-reef-02")
        other = self.command(kind="inhibit", params={})
        with self.assertRaises(AckRefused):
            self.ack(other)

    def test_command_level_rejections_reach_the_caller(self):
        for change in ({"expires_at": "2026-09-08T12:20:00Z"},  # lifetime over 600 s
                       {"kind": "emit"}, {"sequence": 42},
                       {"params": {"config": {"schema_version": "poseidon.digital-config.v9"}}},
                       {"params": {"config": dict(CONFIG_V2), "extra": 1}}):
            with self.subTest(**change), self.assertRaises(ModelValidationError):
                self.ack(self.command(**change))

    def test_context_still_has_to_be_complete(self):
        for change in ({"received_at": "yesterday"}, {"reason": ""}, {"state_after": "emit"},
                       {"outcome": "done"}):
            with self.subTest(**change), self.assertRaises(AckRefused):
                self.ack(**change)

    def test_replace_on_a_context_revalidates(self):
        base = context()
        self.assertEqual(replace(base, outcome="failed").outcome, "failed")
        with self.assertRaises(AckRefused):
            replace(base, sequence_seen="ten")


if __name__ == "__main__":
    unittest.main()
