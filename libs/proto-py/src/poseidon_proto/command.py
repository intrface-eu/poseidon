"""Strict digital command/ack wire parsing; no keys, dispatch or package reexports."""
from __future__ import annotations

import base64
import json
import re
from typing import Any

from .models import ModelValidationError
from .platform import canonical_json, parse_utc, _shape
from .signing import signing_bytes

KINDS = ("inhibit", "resume", "rearm", "clear-fault", "wiper-run", "health-request", "config-apply")
STATES = ("observe", "armed", "inhibited", "fault", "emit")
OUTCOMES = ("accepted", "rejected", "expired", "duplicate", "executed", "failed")
ID = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"}
UINT64 = {"type": "string", "pattern": r"^(0|[1-9][0-9]{0,19})$"}
UTC = {"type": "string", "format": "date-time", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?Z$"}
UUID4 = {"type": "string", "pattern": r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"}


def obj(properties: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


SIGNATURE = obj({"algorithm": {"const": "Ed25519"}, "canonicalization": {"const": "poseidon-json-v1"},
                 "value": {"type": "string", "pattern": r"^[A-Za-z0-9+/]{86}==$"}})
COMMAND_SCHEMA = obj({"schema_version": {"const": "poseidon.command.v1"}, "command_id": UUID4,
                      **{key: ID for key in ("site_id", "zone_id", "device_id", "principal_id", "key_id")},
                      "sequence": UINT64, "issued_at": UTC, "expires_at": UTC, "kind": {"enum": list(KINDS)},
                      "params": {"type": "object", "properties": {}}, "signature": SIGNATURE})
ACK_SCHEMA = obj({"schema_version": {"const": "poseidon.command-ack.v1"}, "command_id": UUID4,
                  "device_id": ID, "received_at": UTC, "outcome": {"enum": list(OUTCOMES)},
                  "reason": {"type": "string", "minLength": 1, "maxLength": 256},
                  "state_after": {"enum": list(STATES)}, "sequence_seen": UINT64})


def reject(message: str):
    raise ModelValidationError(message)


def uint64(value: Any) -> str:
    _shape(UINT64, value)
    if int(value) > 2**64 - 1:
        reject("counter exceeds uint64")
    return value


def signed_json(value: Any, depth: int = 0) -> None:
    """Limit the shared canonicalization domain to interoperable integer JSON."""
    if depth > 16:
        reject("JSON nesting exceeds 16")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if abs(value) > 2**53 - 1:
            reject("JSON number must be a safe integer; use decimal text")
    elif type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeError:
            reject("invalid Unicode")
    elif type(value) is list:
        for item in value:
            signed_json(item, depth + 1)
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                reject("JSON object keys must be strings")
            signed_json(key, depth + 1)
            signed_json(item, depth + 1)
    else:
        reject("signed JSON supports only safe integers, not floating point")


def signature(value: Any) -> None:
    _shape(SIGNATURE, value)
    try:
        raw = base64.b64decode(value["value"], validate=True)
    except ValueError:
        reject("invalid signature encoding")
    if len(raw) != 64 or base64.b64encode(raw).decode() != value["value"]:
        reject("signature must be canonical base64 of 64 bytes")


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            reject("duplicate JSON key")
        value[key] = item
    return value


def decode_wire(raw: bytes | str, maximum: int = 16384) -> dict:
    if not isinstance(raw, (bytes, str)):
        reject("wire input must be bytes or text")
    try:
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(data) > maximum:
            reject("wire document exceeds byte limit")
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: reject("nonfinite JSON"))
        if type(value) is not dict:
            reject("wire document must be an object")
        signed_json(value)
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ModelValidationError("invalid JSON wire document") from exc


def parse_command(value: dict | bytes | str) -> dict:
    value = decode_wire(value) if isinstance(value, (str, bytes)) else value
    _shape(COMMAND_SCHEMA, value)
    signed_json(value)
    uint64(value["sequence"])
    signature(value["signature"])
    duration = (parse_utc(value["expires_at"]) - parse_utc(value["issued_at"])).total_seconds()
    if not 0 < duration <= 600:
        reject("command lifetime must be positive and at most 600 seconds")
    if len(canonical_json(value["params"])) > 4096:
        reject("params exceed 4096 canonical bytes")
    if value["kind"] == "config-apply":
        if set(value["params"]) != {"config"}:
            reject("config-apply requires only config")
        from .config_migrations import migrate_config
        migrate_config(value["params"]["config"])
    elif value["params"] != {}:
        reject("this command requires empty params")
    return json.loads(canonical_json(value))


def parse_command_ack(value: dict | bytes | str, *, retained: bool = False) -> dict:
    if type(retained) is not bool or retained:
        reject("retained acknowledgement rejected")
    value = decode_wire(value) if isinstance(value, (str, bytes)) else value
    _shape(ACK_SCHEMA, value)
    signed_json(value)
    uint64(value["sequence_seen"])
    # emit is representable in the shared state enum, never a valid digital ack.
    if value["state_after"] == "emit":
        reject("emit is reserved and unreachable")
    return json.loads(canonical_json(value))


def payload_bytes(document: dict) -> bytes:
    """Use the existing frozen domain-separated signing helper unchanged."""
    return signing_bytes({key: value for key, value in document.items() if key != "signature"}, document["key_id"])
