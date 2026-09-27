"""Approved platform-manifest adapter for the host boot model, not ESP trust.

Select this verifier explicitly. The complete original signed envelope stays in
BootStore's image row; state summaries never replace cryptographic verification.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from poseidon_proto.models import ModelValidationError
from poseidon_proto.platform import canonical_json, parse_utc, validate_contract
from poseidon_proto.signing import signing_bytes

from .model import ImageVerifier, Rejected, _integer, _object

REFERENCE_SLOT_BYTES = 0x1F0000  # firmware/reference/partitions-reference.csv
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True)
class PlatformCandidate:
    schema: str
    board: str
    version: str
    security_version: int
    command_id: int
    expires_at: str
    image_size: int
    image_sha256: str
    key_id: str


class PlatformImageVerifier(ImageVerifier):
    profile = "poseidon.signed-manifest.v1"

    def __init__(self, board: str, keys: Mapping[str, bytes], max_image_bytes: int = REFERENCE_SLOT_BYTES):
        if type(board) is not str or not _ID.fullmatch(board):
            raise Rejected("invalid board identity")
        if not 1 <= len(keys) <= 32 or any(type(key) is not str or not _ID.fullmatch(key) for key in keys):
            raise Rejected("invalid trust mapping")
        super().__init__(board, keys, max_image_bytes)

    @staticmethod
    def validate_version(value: object) -> None:
        if type(value) is not str or not _ID.fullmatch(value):
            raise Rejected("invalid platform release version")

    @staticmethod
    def validate_digest(value: object) -> None:
        if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise Rejected("installed image digest required")

    @staticmethod
    def newer_version(candidate: PlatformCandidate, current_version: str) -> bool:
        # Release names are opaque, never semver/lexically ordered. Verification
        # enforces the signed monotonic sequence and security floor instead.
        return True

    @classmethod
    def candidate_from_state(cls, value: dict) -> PlatformCandidate:
        if type(value) is not dict or set(value) != set(PlatformCandidate.__dataclass_fields__):
            raise Rejected("corrupt platform candidate")
        candidate = PlatformCandidate(**value)
        if candidate.schema != "poseidon.reef.platform-candidate.v1":
            raise Rejected("wrong candidate profile")
        for item in (candidate.board, candidate.version, candidate.key_id):
            cls.validate_version(item)
        cls.validate_digest(candidate.image_sha256)
        _integer(candidate.command_id, 1, 0xFFFFFFFF, "candidate sequence")
        _integer(candidate.security_version, 0, 0xFFFFFFFF, "candidate security version")
        _integer(candidate.image_size, 1, 268435456, "candidate image size")
        try:
            parse_utc(candidate.expires_at)
        except (ModelValidationError, TypeError, ValueError) as exc:
            raise Rejected("candidate expiry") from exc
        return candidate

    @staticmethod
    def parse(raw: bytes) -> dict:
        if type(raw) is not bytes or not 1 <= len(raw) <= 8192:
            raise Rejected("platform manifest size")
        try:
            envelope = json.loads(raw, object_pairs_hook=_object)
            envelope = validate_contract("signed-manifest", envelope)
            if canonical_json(envelope) != raw:
                raise Rejected("noncanonical platform envelope")
            return envelope
        except Rejected:
            raise
        except (UnicodeError, RecursionError, ValueError, TypeError, OverflowError) as exc:
            raise Rejected("platform manifest rejected") from exc

    def verify(self, raw: bytes, signature: bytes, image: bytes, *, now: int | None,
               security_floor: int, current_version: str, last_command_id: int,
               current_digest: str | None = None) -> PlatformCandidate:
        # Signature is inside the approved envelope; never accept a detached
        # private-profile signature or silently choose between signing formats.
        if signature != b"" or type(signature) is not bytes:
            raise Rejected("platform signature must be inside envelope")
        if now is None:
            raise Rejected("trusted UTC required for image expiry")
        _integer(now, 0, 253402300799, "trusted UTC seconds")
        self.validate_version(current_version)
        self.validate_digest(current_digest)
        envelope = self.parse(raw)
        payload, signed = envelope["payload"], envelope["signature"]
        key = self.keys.get(signed["key_id"])
        if key is None:
            raise Rejected("untrusted platform key")
        try:
            detached = base64.b64decode(signed["value"], validate=True)
            if len(detached) != 64 or base64.b64encode(detached).decode("ascii") != signed["value"]:
                raise Rejected("noncanonical signature encoding")
            key.verify(detached, signing_bytes(payload, signed["key_id"]))
        except (InvalidSignature, binascii.Error, ValueError) as exc:
            raise Rejected("platform signature invalid") from exc
        if payload["kind"] != "update" or payload["target_kind"] != "reef" or payload["hardware_revision"] != self.board:
            raise Rejected("incompatible platform update")
        instant = datetime.fromtimestamp(now, timezone.utc)
        if not parse_utc(payload["issued_at"]) <= instant < parse_utc(payload["expires_at"]):
            raise Rejected("platform authorization not currently valid")
        if payload["security_version"] < security_floor:
            raise Rejected("platform security downgrade")
        if payload["sequence"] <= last_command_id:
            raise Rejected("platform sequence replay")
        if payload["previous_sha256"] != current_digest:
            raise Rejected("previous image digest mismatch")
        if type(image) is not bytes or not 1 <= len(image) <= self.max_image_bytes or len(image) != payload["artifact_size_bytes"]:
            raise Rejected("platform image size")
        if hashlib.sha256(image).hexdigest() != payload["artifact_sha256"]:
            raise Rejected("platform image digest mismatch")
        # Config in this signed update is validated and retained but not applied:
        # queue/sample policy changes need their own acknowledged configuration path.
        return PlatformCandidate(schema="poseidon.reef.platform-candidate.v1", board=self.board,
            version=payload["version"], security_version=payload["security_version"],
            command_id=payload["sequence"], expires_at=payload["expires_at"],
            image_size=payload["artifact_size_bytes"], image_sha256=payload["artifact_sha256"],
            key_id=signed["key_id"])
