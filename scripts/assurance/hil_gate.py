"""Validate controller authorization only. This module has no HIL execution path.

Trust comes from the caller's explicit --trusted-controller-keys file, never
from the authorization. No key store is discovered or provisioned. Exit 3 means
refusal; exit 0 means signature/scope validation only, not a hardware test.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

SCOPE = "hil-authorization-validation-only"
MAX_BYTES = 64 * 1024
KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class Refused(ValueError):
    """No authorization validation can be accepted."""


class RefusalParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise Refused(message)


def exact(value: object, fields: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise Refused(f"{label} has missing or unexpected fields")
    return value


def identifier(value: object, label: str) -> str:
    if type(value) is not str or not KEY_ID.fullmatch(value):
        raise Refused(f"invalid {label}")
    return value


def timestamp(value: object, label: str) -> datetime:
    if type(value) is not str or not STAMP.fullmatch(value):
        raise Refused(f"{label} must be an RFC3339 UTC second timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Refused(f"invalid {label}") from exc


def load_object(path: Path) -> dict:
    # O_NOFOLLOW alone does not prevent regular-file/device substitution. First
    # reject nonregular metadata, then pin the inode with Linux O_PATH, which
    # does not open a device for I/O. Reopen only that checked regular-file FD.
    # Platforms without O_PATH (including Darwin) refuse file validation rather
    # than fall back to a racy data open. validate(dict, trusted_dict) is portable.
    from poseidon_proto.models import parse_json_object

    absolute = path.absolute()
    before = absolute.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BYTES:
        raise Refused("authorization/key source must be a bounded regular file")
    if absolute.resolve() != absolute:
        raise Refused("authorization/key-source paths must not traverse symlinks")
    metadata_flag = getattr(os, "O_PATH", None)
    if metadata_flag is None:
        raise Refused("authorization-file validation requires Linux O_PATH metadata pinning; unavailable on this platform")
    metadata = os.open(absolute, metadata_flag | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        pinned = os.fstat(metadata)
        if not stat.S_ISREG(pinned.st_mode) or (pinned.st_dev, pinned.st_ino) != (before.st_dev, before.st_ino):
            raise Refused("authorization/key source changed before metadata pinning")
        descriptor = os.open(f"/proc/self/fd/{metadata}", os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (info.st_dev, info.st_ino) != (pinned.st_dev, pinned.st_ino) or not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
                raise Refused("authorization/key source changed before reading")
            raw = stream.read(MAX_BYTES + 1)
    finally:
        os.close(metadata)
    if len(raw) > MAX_BYTES:
        raise Refused("authorization/key source exceeds size limit")
    return parse_json_object(raw.decode("utf-8"))


def validate(authorization: dict, trusted_keys: dict, *, now: datetime | None = None) -> dict:
    """Authenticate a validation-only envelope against separately supplied trust.

    This function never imports a device/backend module or dispatches an action.
    The caller, not the untrusted envelope, selects the trusted key source.
    """
    from poseidon_proto.signing import signing_bytes

    envelope = exact(authorization, {"payload", "signature"}, "authorization envelope")
    payload = exact(envelope["payload"], {"schema_version", "authorization_id", "controller_id", "scope", "issued_at", "expires_at", "digital_only"}, "authorization payload")
    if payload["schema_version"] != "poseidon.hil-authorization.v1" or payload["scope"] != SCOPE or payload["digital_only"] is not True:
        raise Refused("only digital-only HIL authorization validation is supported; hardware execution is unavailable")
    controller = identifier(payload["controller_id"], "controller_id")
    try:
        identity = uuid.UUID(payload["authorization_id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise Refused("authorization_id must be a canonical UUID4") from exc
    if identity.version != 4 or str(identity) != payload["authorization_id"]:
        raise Refused("authorization_id must be a canonical UUID4")
    issued = timestamp(payload["issued_at"], "issued_at")
    expires = timestamp(payload["expires_at"], "expires_at")
    current = datetime.now(timezone.utc) if now is None else now
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise Refused("validation requires a timezone-aware clock")
    if not 0 < (expires - issued).total_seconds() <= 600:
        raise Refused("authorization lifetime must be positive and at most 600 seconds")
    if not issued <= current < expires:
        raise Refused("authorization is expired or not yet valid")

    signature = exact(envelope["signature"], {"algorithm", "key_id", "canonicalization", "value"}, "signature")
    key_id = identifier(signature["key_id"], "key_id")
    if signature["algorithm"] != "Ed25519" or signature["canonicalization"] != "poseidon-json-v1":
        raise Refused("unsupported signing scheme")
    registry = exact(trusted_keys, {"schema_version", "keys"}, "trusted controller key source")
    if registry["schema_version"] != "poseidon.hil-controller-keys.v1" or type(registry["keys"]) is not dict or not 1 <= len(registry["keys"]) <= 128:
        raise Refused("invalid trusted controller key source")
    for registered_id, entry in registry["keys"].items():
        identifier(registered_id, "trusted key_id")
        exact(entry, {"controller_id", "public_key_hex", "revoked"}, "trusted controller key")
        identifier(entry["controller_id"], "trusted controller_id")
        if type(entry["revoked"]) is not bool or type(entry["public_key_hex"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", entry["public_key_hex"]):
            raise Refused("malformed trusted controller key")
    key = registry["keys"].get(key_id)
    if key is None or key["revoked"] or key["controller_id"] != controller:
        raise Refused("controller key is unknown, revoked or belongs to another controller")
    try:
        # Existing locked API/update environments provide cryptography. There is
        # no install, pure-Python fallback, embedded key or alternate algorithm.
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise Refused("Ed25519 verification requires the existing locked API/update Python environment") from exc
    try:
        if type(signature["value"]) is not str:
            raise ValueError("signature must be text")
        decoded = base64.b64decode(signature["value"], validate=True)
        if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != signature["value"]:
            raise ValueError("noncanonical signature")
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"])).verify(decoded, signing_bytes(payload, key_id))
    except (ValueError, InvalidSignature) as exc:
        raise Refused("authorization signature is invalid") from exc
    return {"authorization_validated": True, "authorization_id": str(identity), "controller_id": controller,
            "scope": SCOPE, "hil_executed": False, "physical_operations_supported": False,
            "release_authorized": False,
            "explanation": "Authorization validated only; no HIL implementation or device path ran."}


def main(argv: list[str] | None = None) -> int:
    try:
        parser = RefusalParser(description=__doc__)
        parser.add_argument("--authorization")
        parser.add_argument("--trusted-controller-keys")
        args = parser.parse_args(argv)
        if not args.authorization:
            raise Refused("an explicit controller-signed authorization file is required; no hardware test ran")
        if not args.trusted_controller_keys:
            raise Refused("an explicit trusted controller key source is required; manifest-embedded keys are never trusted")
        authorization = Path(args.authorization)
        key_source = Path(args.trusted_controller_keys)
        if authorization.resolve() == key_source.resolve():
            raise Refused("trusted keys must be separate from the untrusted authorization")
        result = validate(load_object(authorization), load_object(key_source))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refused, OSError, ValueError, TypeError, ImportError, RecursionError) as exc:
        print(f"HIL refused: {exc}. No hardware operation is implemented or authorized by this gate.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
