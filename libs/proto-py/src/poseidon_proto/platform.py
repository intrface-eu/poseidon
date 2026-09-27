"""Strict, dependency-free validation of the additive repository contracts.

This implements only the JSON Schema keywords emitted by generate_contracts.py;
it is not a general JSON Schema engine. Domain checks below are additional to
shape validation and must be applied by adapters after decoding wire data.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from typing import Any

from .models import ModelValidationError

CONTRACTS = frozenset({"clock-quality", "clock-relation", "device", "telemetry-envelope", "acquisition-session", "independent-observation", "signed-manifest"})
SCHEMA_DIR = Path(__file__).resolve().parents[4] / "contracts" / "v1"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


@lru_cache(maxsize=16)
def _schema(name: str) -> dict:
    if name not in CONTRACTS:
        raise ModelValidationError("unknown platform contract")
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())


def _fail(path: str, detail: str) -> None:
    raise ModelValidationError(f"{path}: {detail}")


def _same(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _shape(schema: dict, value: Any, path: str = "input") -> None:
    for key in ("anyOf", "oneOf"):
        if key in schema:
            matches = 0
            for branch in schema[key]:
                try:
                    _shape(branch, value, path)
                except ModelValidationError:
                    pass
                else:
                    matches += 1
            if matches == 0 or (key == "oneOf" and matches != 1):
                _fail(path, "does not match the contract alternatives")
    if "const" in schema and not _same(value, schema["const"]):
        _fail(path, "must match its fixed contract value")
    if "enum" in schema and not any(_same(value, allowed) for allowed in schema["enum"]):
        _fail(path, "unsupported contract value")
    kind = schema.get("type")
    valid = {
        "object": type(value) is dict,
        "array": type(value) is list,
        "string": type(value) is str,
        "number": type(value) in (int, float),
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "null": value is None,
    }
    if kind is not None and not valid.get(kind, False):
        _fail(path, f"must be {kind}")
    if kind == "object":
        properties = schema["properties"]
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            _fail(path, "unknown fields")
        if set(schema.get("required", [])) - set(value):
            _fail(path, "missing required fields")
        for key, child in value.items():
            if key in properties:
                _shape(properties[key], child, f"{path}.{key}")
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 2**31):
            _fail(path, "array length outside contract bounds")
        for index, item in enumerate(value):
            _shape(schema["items"], item, f"{path}.{index}")
    elif kind == "string":
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 2**31):
            _fail(path, "text length outside contract bounds")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            _fail(path, "text does not match contract pattern")
        # JSON Schema '$' permits a trailing newline in Python's regular
        # expressions. Safe identifiers, digests and signatures do not.
        if "pattern" in schema and ("\n" in value or "\r" in value):
            _fail(path, "line breaks are not allowed")
        if schema.get("format") == "date-time":
            parse_utc(value)
        try:
            value.encode("utf-8")
        except UnicodeError:
            _fail(path, "invalid Unicode")
    elif kind in ("number", "integer"):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            _fail(path, "number must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            _fail(path, "number below contract minimum")
        if "maximum" in schema and value > schema["maximum"]:
            _fail(path, "number above contract maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            _fail(path, "number must exceed contract minimum")


def parse_utc(value: str) -> datetime:
    if type(value) is not str or not _DATE.fullmatch(value):
        raise ModelValidationError("timestamp must be UTC RFC3339 with Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelValidationError("timestamp is not a valid date") from exc


def _clock(value: dict) -> None:
    status, method = value["status"], value["method"]
    if status == "unknown":
        if method != "unknown" or any(value[key] is not None for key in ("uncertainty_ms", "offset_ms", "reference")):
            _fail("clock_quality", "unknown clock cannot assert synchronization evidence")
    elif status == "operator_declared":
        if method != "operator_offset" or value["offset_ms"] is None:
            _fail("clock_quality", "operator alignment needs its declared offset")
    elif method in ("unknown", "operator_offset") or value["uncertainty_ms"] is None or value["reference"] is None:
        _fail("clock_quality", "synchronization claims need method, uncertainty and reference")


def validate_contract(name: str, value: Any) -> dict:
    """Validate without coercion; return a detached, JSON-safe copy."""
    _shape(_schema(name), value)
    if name == "clock-quality":
        _clock(value)
    if name in ("telemetry-envelope", "acquisition-session"):
        _clock(value["clock_quality"])
    if name == "telemetry-envelope":
        if int(value["boot_id"]) > 2**64 - 1:
            _fail("boot_id", "boot counter exceeds uint64")
        if value["provenance"]["transport"] == "aquilon" and "radio" not in value:
            _fail("radio", "AQUILON telemetry requires radio provenance")
        radio = value.get("radio")
        if radio and ((radio["clock_claim"] == "unsynchronized") != (radio["observed_at_unix_s"] is None)):
            _fail("radio", "unsynchronized radio time is null; RTC/network claims need their stated time")
        if value["clock_quality"]["status"] == "unknown" and value["observed_at"] is not None:
            _fail("observed_at", "unknown clocks cannot supply a UTC observation time")
        seen = set()
        for item in value["measurements"]:
            if item["name"] in seen:
                _fail("measurements", "measurement names must be unique within an envelope")
            seen.add(item["name"])
            if (item["quality"] == "invalid") != (item["value"] is None):
                _fail("measurements", "invalid measurements must be null, valid measurements numeric")
            if item["quality"] == "calibrated" and item["calibration_id"] is None:
                _fail("measurements", "calibrated claim requires a calibration reference")
            if item["name"].endswith("_raw") and (item["quality"] == "calibrated" or item["calibration_id"] is not None):
                _fail("measurements", "raw instrument counts cannot claim calibration or physical units")
    elif name == "acquisition-session":
        start, end = value["started_at"], value["ended_at"]
        if end is not None and (start is None or parse_utc(end) < parse_utc(start)):
            _fail("ended_at", "session end precedes or lacks its start")
        if not value["operator"].strip():
            _fail("operator", "operator cannot be blank")
    elif name == "independent-observation":
        if value["end_s"] <= value["start_s"]:
            _fail("end_s", "observation interval must have positive duration")
        if not value["observer"].strip():
            _fail("observer", "observer cannot be blank")
        if value["label"] == "feeding_observed" and not value["notes"].strip():
            _fail("notes", "feeding observations require notes")
    elif name == "device" and not value["label"].strip():
        _fail("label", "device label cannot be blank")
    elif name == "signed-manifest":
        payload = value["payload"]
        if parse_utc(payload["expires_at"]) <= parse_utc(payload["issued_at"]):
            _fail("expires_at", "manifest must expire after issuance")
    relation = value if name == "clock-relation" else value.get("clock_relation")
    if relation is not None:
        if relation["source_domain"] == relation["reference_domain"]:
            _fail("clock_relation", "source and reference clock domains must be explicit and distinct")
        if relation["method"] != "operator_declared" and relation["evidence_ref"] is None:
            _fail("clock_relation", "measured/shared-clock relation needs an evidence reference")
    return json.loads(json.dumps(value, allow_nan=False))


def map_clock(relation: dict, source_s: float) -> tuple[float, float]:
    """Map source seconds into the named reference domain, never implicit UTC."""
    relation = validate_contract("clock-relation", relation)
    if type(source_s) not in (float, int) or not math.isfinite(source_s):
        raise ModelValidationError("source_s must be finite seconds")
    delta = source_s - relation["source_anchor_s"]
    reference = relation["reference_anchor_s"] + delta * (1 + relation["drift_ppm"] / 1e6)
    uncertainty = relation["anchor_uncertainty_s"] + abs(delta) * relation["drift_uncertainty_ppm"] / 1e6
    if not math.isfinite(reference) or not math.isfinite(uncertainty):
        raise ModelValidationError("clock relation overflow")
    return reference, uncertainty


def canonical_json(value: Any) -> bytes:
    """Poseidon JSON v1: ASCII escapes, sorted keys, no insignificant whitespace.

    This is not RFC 8785. Signed manifests have integer-only numeric fields.
    Unicode is not normalized; sign precisely the validated payload bytes.
    """
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
