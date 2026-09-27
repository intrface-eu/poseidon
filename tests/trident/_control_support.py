"""Shared synthetic in-memory signing helpers for digital-only control tests."""
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from poseidon_proto.command import payload_bytes

FIXTURES = Path(__file__).resolve().parents[2] / "contracts/v1/fixtures"
PROFILE = {"schema_version": "poseidon.device-health-profile.v1", "zone_id": "zone-1", "stale_after_s": 30, "offline_after_s": 120}


def utc(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def device(hub, device_id="hub-1", site="site-1", kind="hub", profile=True, source="synthetic"):
    hub.create_device({"id": device_id, "site_id": site, "kind": kind, "label": "Synthetic digital test", "hardware_revision": "synthetic-r1", "source_kind": source})
    if profile:
        hub.put_health_profile(device_id, PROFILE)


def setup(hub):
    device(hub)
    hub.bind_hub({"device_id": "hub-1"})
    issued = hub.create_principal({"subject": "operator-1", "role": "operator", "site_ids": ["site-1"], "device_id": None})
    op = hub.for_principal(hub.authenticate(issued["token"]))
    key = Ed25519PrivateKey.generate()
    op.enroll_command_key({"key_id": "test-key", "principal_id": issued["principal"]["id"], "public_key_hex": key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()})
    healthy(hub)
    return op, issued, key


def healthy(hub):
    for source in ("host", "api", "live_journal"):
        hub._watchdogs.heartbeat(source)


def signed(body, key):
    body = dict(body)
    body["signature"] = {"algorithm": "Ed25519", "canonicalization": "poseidon-json-v1", "value": base64.b64encode(key.sign(payload_bytes(body))).decode()}
    return body


def command(issued, key, sequence=1, kind="health-request", **changes):
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    body = {"schema_version": "poseidon.command.v1", "command_id": str(uuid.uuid4()), "site_id": "site-1", "zone_id": "zone-1", "device_id": "hub-1",
            "principal_id": issued["principal"]["id"], "key_id": "test-key", "sequence": str(sequence), "issued_at": utc(now), "expires_at": utc(now + timedelta(seconds=300)), "kind": kind, "params": {}}
    return signed(body | changes, key)


def calibration(issued, key, **changes):
    body = json.loads((FIXTURES / "calibration-record.valid.json").read_text())
    now = datetime.now(timezone.utc)
    body |= {"instrument_id": "hub-1", "operator_id": issued["principal"]["id"], "key_id": "test-key", "valid_from": utc(now - timedelta(days=1)), "valid_until": utc(now + timedelta(days=1))}
    return signed(body | changes, key)
