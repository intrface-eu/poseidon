"""Synthetic host tests for the ADR-0002 update plan stubs.

Every key is generated in memory for the test process. Every image is
non-executable synthetic bytes. Nothing here fetches, writes, flashes, selects a
boot slot or reboots anything, and the stubs under test refuse to.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firmware/update/src"))
sys.path.insert(0, str(ROOT / "libs/proto-py/src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from poseidon_proto.platform import canonical_json
from poseidon_proto.signing import signing_bytes
from reef_update import ImageVerifier, Rejected
from reef_update.esp_transport_plan import (PRECONDITIONS as ESP_PRECONDITIONS,
                                            EspPullPlanner, PhysicalActionRefused,
                                            approved_endpoint)
from reef_update.esp_transport_plan import PLAN_SCHEMA as ESP_PLAN_SCHEMA
from reef_update.hub_bundle_plan import (DESCRIPTOR_SCHEMA, HubBundlePlanner, MissingPrecondition)
from reef_update.hub_bundle_plan import PLAN_SCHEMA as HUB_PLAN_SCHEMA
from reef_update.hub_bundle_plan import PhysicalActionRefused as HubPhysicalActionRefused
from reef_update.platform_manifest import PlatformImageVerifier

ENDPOINT = "https://hub.maintenance.invalid/reef/images/synthetic-1.bin"
ALLOWLIST = ("https://hub.maintenance.invalid/reef/images/",)


class Interrupted(RuntimeError):
    """Stands in for a power cut at a named boundary. Not a measurement."""


def owned_tempdir(prefix: str) -> tempfile.TemporaryDirectory:
    root = os.environ.get("REEF_TEST_TMPDIR")
    if root:
        Path(root).mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=root or None)


class EspPullPlanTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.image = b"SYNTHETIC-REEF-IMAGE-NOT-EXECUTABLE" * 7
        self.digest = hashlib.sha256(self.image).hexdigest()
        self.previous = hashlib.sha256(b"SYNTHETIC-KNOWN-GOOD-NOT-EXECUTABLE").hexdigest()
        self.now = int(datetime(2026, 9, 8, 12, tzinfo=timezone.utc).timestamp())
        self.verifier = PlatformImageVerifier("synthetic-esp32-ref", {"synthetic-key": self.public})
        self.planner = EspPullPlanner(self.verifier, ALLOWLIST, "ota_0")

    def envelope(self, **changes) -> dict:
        fixture = json.loads((ROOT / "contracts/v1/fixtures/signed-manifest.valid.json").read_text())
        payload = fixture["payload"]
        payload.update(id="synthetic-reef-pull-1", kind="update", target_kind="reef",
                       hardware_revision="synthetic-esp32-ref", version="release-b", sequence=4,
                       security_version=3, artifact_sha256=self.digest,
                       artifact_size_bytes=len(self.image), previous_sha256=self.previous)
        payload.update(changes)
        signature = self.key.sign(signing_bytes(payload, "synthetic-key"))
        fixture["signature"].update(key_id="synthetic-key",
                                    value=base64.b64encode(signature).decode("ascii"))
        return fixture

    def plan(self, envelope=None, image=None, *, planner=None, security_floor=1, **kwargs):
        envelope = self.envelope() if envelope is None else envelope
        raw = envelope if isinstance(envelope, bytes) else canonical_json(envelope)
        planner = planner or self.planner
        return planner.plan(kwargs.pop("endpoint", ENDPOINT), raw,
                            self.image if image is None else image, now=self.now,
                            security_floor=security_floor, current_version="release-a",
                            last_command_id=3, current_digest=self.previous, **kwargs)

    def test_plan_targets_the_inactive_slot_and_refuses_execution(self):
        plan = self.plan()
        self.assertEqual(plan.schema, ESP_PLAN_SCHEMA)
        self.assertEqual(plan.transport, "https-local-maintenance-pull")
        self.assertEqual((plan.active_slot, plan.target_slot), ("ota_0", "ota_1"))
        self.assertEqual((plan.version, plan.image_sha256, plan.image_size),
                         ("release-b", self.digest, len(self.image)))
        self.assertEqual(plan.key_id, "synthetic-key")
        self.assertFalse(plan.executable)
        self.assertIn("not implemented", plan.refusal_reason)
        self.assertTrue(plan.rollback_on_failed_trial)
        self.assertEqual(EspPullPlanner(self.verifier, ALLOWLIST, "ota_1").inactive_slot(), "ota_0")

    def test_security_floor_advances_only_to_the_confirmed_candidate(self):
        self.assertEqual(self.plan(security_floor=1).security_floor_after_confirmation, 3)
        self.assertEqual(self.plan(security_floor=3).security_floor_after_confirmation, 3)
        with self.assertRaises(Rejected):
            self.plan(security_floor=4)

    def test_plan_document_is_json_serialisable_for_evidence(self):
        with owned_tempdir("reef-tranche3-plan-") as directory:
            path = Path(directory) / "esp-plan.json"
            path.write_bytes(canonical_json(self.plan().as_dict()))
            self.assertEqual(json.loads(path.read_text())["target_slot"], "ota_1")

    def test_endpoint_must_be_https_on_the_approved_allowlist(self):
        self.assertEqual(approved_endpoint(ENDPOINT, ALLOWLIST), ENDPOINT)
        for bad in ("http://hub.maintenance.invalid/reef/images/x.bin",
                    "https://elsewhere.invalid/reef/images/x.bin",
                    "https://user:pw@hub.maintenance.invalid/reef/images/x.bin",
                    "https://hub.maintenance.invalid/reef/images/x.bin?token=1",
                    "https://hub.maintenance.invalid/reef/images/../../x.bin",
                    "ftp://hub.maintenance.invalid/reef/images/x.bin", "", 7):
            with self.subTest(endpoint=bad), self.assertRaises(Rejected):
                approved_endpoint(bad, ALLOWLIST)
        with self.assertRaises(Rejected):
            self.plan(endpoint="https://elsewhere.invalid/reef/images/x.bin")

    def test_wrong_reef_target_is_refused(self):
        for change in ({"target_kind": "hub"}, {"hardware_revision": "synthetic-esp32-other"}):
            with self.subTest(**change), self.assertRaises(Rejected):
                self.plan(self.envelope(**change))

    def test_mutated_or_unsigned_envelope_is_refused(self):
        envelope = self.envelope()
        mutated = copy.deepcopy(envelope)
        mutated["payload"]["version"] = "release-c"  # signed bytes no longer match
        with self.assertRaises(Rejected):
            self.plan(mutated)
        unsigned = copy.deepcopy(envelope)
        unsigned["signature"]["value"] = base64.b64encode(bytes(64)).decode("ascii")
        with self.assertRaises(Rejected):
            self.plan(unsigned)
        raw = bytearray(canonical_json(envelope))
        raw[raw.index(b"release-b")] = ord("R")  # a single flipped byte
        with self.assertRaises(Rejected):
            self.plan(bytes(raw))

    def test_image_bytes_must_match_the_signed_digest_and_slot(self):
        with self.assertRaises(Rejected):
            self.plan(image=self.image + b"\x00")
        narrow = EspPullPlanner(self.verifier, ALLOWLIST, "ota_0",
                                slot_capacity_bytes=len(self.image) - 1)
        with self.assertRaises(Rejected):
            self.plan(planner=narrow)

    def test_planner_requires_the_approved_platform_verifier(self):
        legacy = ImageVerifier("synthetic-esp32-ref", {"synthetic-key": self.public})
        with self.assertRaises(Rejected):
            EspPullPlanner(legacy, ALLOWLIST, "ota_0")
        for bad in (("http://hub.invalid/",), ("https://hub.invalid",), ()):
            with self.subTest(allowlist=bad), self.assertRaises(Rejected):
                EspPullPlanner(self.verifier, bad, "ota_0")
        with self.assertRaises(Rejected):
            EspPullPlanner(self.verifier, ALLOWLIST, "factory")

    def test_fault_injection_at_every_named_boundary_yields_no_plan(self):
        for stage in ("before_verify", "after_verify", "before_slot_selection", "before_plan_emit"):
            with self.subTest(stage=stage):
                def fault(name, stage=stage):
                    if name == stage:
                        raise Interrupted(stage)
                planner = EspPullPlanner(self.verifier, ALLOWLIST, "ota_0", fault=fault)
                with self.assertRaises(Interrupted):
                    self.plan(planner=planner)

    def test_every_physical_method_refuses_before_any_effect(self):
        for name in ("fetch", "write_slot", "set_boot_partition", "reboot"):
            with self.subTest(method=name), self.assertRaises(PhysicalActionRefused):
                getattr(self.planner, name)(ENDPOINT, "ota_1")
        self.assertTrue(issubclass(PhysicalActionRefused, Rejected))
        self.assertGreaterEqual(len(self.planner.unmet_preconditions()), len(ESP_PRECONDITIONS))


class HubBundlePlanTests(unittest.TestCase):
    def setUp(self):
        self.bundle = b"SYNTHETIC-HUB-BUNDLE-NOT-A-RAUC-BUNDLE" * 3
        self.planner = HubBundlePlanner("poseidon-hub-arm64", "rootfs.0", security_floor=2)

    def descriptor(self, **changes) -> dict:
        value = dict(schema=DESCRIPTOR_SCHEMA, target_kind="hub", compatible="poseidon-hub-arm64",
                     version="hub-release-b", security_version=3,
                     bundle_sha256=hashlib.sha256(self.bundle).hexdigest(),
                     bundle_size=len(self.bundle))
        value.update(changes)
        return value

    def test_plan_targets_the_inactive_rootfs_slot_and_keeps_data(self):
        plan = self.planner.plan(self.descriptor())
        self.assertEqual(plan.schema, HUB_PLAN_SCHEMA)
        self.assertEqual(plan.mechanism, "rauc-ab-full-rootfs")
        self.assertEqual((plan.active_slot, plan.target_slot), ("rootfs.0", "rootfs.1"))
        self.assertTrue(plan.persistent_data_preserved)
        self.assertFalse(plan.executable)
        self.assertEqual(plan.security_floor_after_confirmation, 3)
        self.assertEqual(plan.trial_boot_limit, 3)
        self.assertEqual(HubBundlePlanner("poseidon-hub-arm64", "rootfs.1",
                                          security_floor=0).inactive_slot(), "rootfs.0")

    def test_wrong_hub_target_and_downgrade_are_refused(self):
        for change in ({"target_kind": "reef"}, {"compatible": "poseidon-hub-other"},
                       {"security_version": 1}, {"schema": "poseidon.something-else.v1"},
                       {"bundle_sha256": "not-a-digest"}, {"bundle_size": 0},
                       {"version": "hub release b"}):
            with self.subTest(**change), self.assertRaises(Rejected):
                self.planner.plan(self.descriptor(**change))

    def test_descriptor_field_set_is_exact(self):
        extra = self.descriptor()
        extra["signature"] = "x"
        with self.assertRaises(Rejected):
            self.planner.plan(extra)
        short = self.descriptor()
        del short["version"]
        with self.assertRaises(Rejected):
            self.planner.plan(short)
        with self.assertRaises(Rejected):
            self.planner.plan([("schema", DESCRIPTOR_SCHEMA)])

    def test_there_is_no_stand_in_rauc_verifier(self):
        with self.assertRaises(MissingPrecondition) as caught:
            self.planner.verify_bundle(self.bundle)
        self.assertIn("must not be used as a substitute", str(caught.exception))
        self.assertTrue(issubclass(MissingPrecondition, Rejected))
        self.assertTrue(all(isinstance(item, str) for item in self.planner.unmet_preconditions()))

    def test_every_physical_method_refuses_before_any_effect(self):
        for name in ("download", "write_slot", "activate_slot", "reboot"):
            with self.subTest(method=name), self.assertRaises(HubPhysicalActionRefused):
                getattr(self.planner, name)(self.bundle, "rootfs.1")

    def test_fault_injection_at_every_named_boundary_yields_no_plan(self):
        for stage in ("before_verify", "after_verify", "before_slot_selection", "before_plan_emit"):
            with self.subTest(stage=stage):
                def fault(name, stage=stage):
                    if name == stage:
                        raise Interrupted(stage)
                planner = HubBundlePlanner("poseidon-hub-arm64", "rootfs.0",
                                           security_floor=2, fault=fault)
                with self.assertRaises(Interrupted):
                    planner.plan(self.descriptor())

    def test_planner_construction_validates_its_own_identity(self):
        for args, kwargs in ((("poseidon hub", "rootfs.0"), {"security_floor": 1}),
                             (("poseidon-hub-arm64", "rootfs.9"), {"security_floor": 1}),
                             (("poseidon-hub-arm64", "rootfs.0"), {"security_floor": -1}),
                             (("poseidon-hub-arm64", "rootfs.0"),
                              {"security_floor": 1, "trial_boot_limit": 0})):
            with self.subTest(args=args, kwargs=kwargs), self.assertRaises(Rejected):
                HubBundlePlanner(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()
