"""Immutable digital calibration declarations, not measured calibration evidence."""
from __future__ import annotations

from decimal import Decimal
import json

from .command import ID, UTC, SIGNATURE, obj, decode_wire, signed_json, signature, reject
from .platform import _shape, canonical_json, parse_utc

DECIMAL = {"type": "string", "maxLength": 80, "pattern": r"^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$"}
SUPPORTED_UCUM = ("1", "%", "Cel", "K", "Pa", "kPa", "m", "s", "Hz", "V", "mV", "A", "W", "mg/L", "g/L", "m/s", "dB", "[pH]")
CALIBRATION_SCHEMA = obj({
    "schema_version": {"const": "poseidon.calibration-record.v1"}, "record_id": ID,
    "supersedes_id": {"anyOf": [ID, {"type": "null"}]},
    **{key: ID for key in ("instrument_id", "quantity", "method", "reference_id", "operator_id", "key_id")},
    "unit": {"type": "string", "enum": list(SUPPORTED_UCUM)},
    "value": DECIMAL, "uncertainty": obj({"value": DECIMAL, "coverage_factor": DECIMAL}),
    "valid_from": UTC, "valid_until": UTC,
    "source_documents": {"type": "array", "minItems": 1, "maxItems": 32,
                         "items": {"type": "string", "pattern": r"^[a-f0-9]{64}$"}},
    "digital_only": {"const": True}, "signature": SIGNATURE,
})


def parse_calibration(value: dict | bytes | str) -> dict:
    value = decode_wire(value) if isinstance(value, (str, bytes)) else value
    _shape(CALIBRATION_SCHEMA, value)
    signed_json(value)
    signature(value["signature"])
    for quantity in (value["value"], value["uncertainty"]["value"], value["uncertainty"]["coverage_factor"]):
        if quantity == "-0":
            reject("negative zero is not canonical decimal text")
    if Decimal(value["uncertainty"]["value"]) < 0 or Decimal(value["uncertainty"]["coverage_factor"]) <= 0:
        reject("uncertainty must be nonnegative and coverage factor positive")
    if parse_utc(value["valid_until"]) <= parse_utc(value["valid_from"]):
        reject("calibration validity must have positive duration")
    if value["record_id"] == value["supersedes_id"]:
        reject("calibration cannot supersede itself")
    if len(set(value["source_documents"])) != len(value["source_documents"]):
        reject("source document hashes must be unique")
    return json.loads(canonical_json(value))
