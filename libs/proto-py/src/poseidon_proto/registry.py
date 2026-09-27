"""The whole published contracts/v1 set: the frozen platform seven plus tranche 3.

poseidon_proto.platform is frozen at the seven original contracts, so this
module is the single place that knows the full published set. It restates no
domain rule. The seven original names go to platform.validate_contract
unchanged. Each tranche 3 name is checked against its published schema file and
then handed to the parser that already owns its semantics: command and
command-ack to poseidon_proto.command, calibration-record to
poseidon_proto.calibration. poseidon_proto.companion publishes transport
constants rather than a read-DTO parser, so companion-read is checked against
those exported constants and nothing else. Signatures are never verified here;
the schema and the owning parsers bound shape and encoding only.
"""
from __future__ import annotations

from functools import lru_cache
import json
from typing import Any

from poseidon_proto import platform as _platform
from poseidon_proto.calibration import parse_calibration
from poseidon_proto.command import parse_command, parse_command_ack
from poseidon_proto.companion import COMPANION_SCHEMA_VERSION, DOCUMENT_ROLES, PART_LIMITS
from poseidon_proto.models import ModelValidationError

#: Contracts published after platform.py was frozen.
ADDITIONAL = frozenset({"calibration-record", "command", "command-ack", "companion-read"})
CONTRACTS = frozenset(_platform.CONTRACTS | ADDITIONAL)
SCHEMA_DIR = _platform.SCHEMA_DIR

# Keywords platform._shape applies to the node itself, not to its children.
_LEAF = ("const", "enum", "type", "required", "additionalProperties", "minItems",
         "maxItems", "minLength", "maxLength", "pattern", "format",
         "minimum", "maximum", "exclusiveMinimum")
_KIND = {dict: "object", list: "array", str: "string", bool: "boolean",
         int: "number", float: "number", type(None): "null"}


def _fail(path: str, detail: str) -> None:
    raise ModelValidationError(f"{path}: {detail}")


@lru_cache(maxsize=16)
def _schema(name: str) -> dict:
    if name not in CONTRACTS:
        raise ModelValidationError("unknown contract")
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())


def _resolve(root: dict, ref: str) -> dict:
    """Resolve only local pointers; no contract may fetch a remote schema."""
    if type(ref) is not str or not ref.startswith("#/"):
        raise ModelValidationError("only local schema references are supported")
    node: Any = root
    for part in ref[2:].split("/"):
        if type(node) is not dict or part not in node:
            raise ModelValidationError("unresolvable schema reference")
        node = node[part]
    if type(node) is not dict:
        raise ModelValidationError("unresolvable schema reference")
    return node


def _local(schema: dict, value: Any, path: str) -> None:
    """Apply this node's own keywords with the frozen platform shape checker."""
    local = {key: schema[key] for key in _LEAF if key in schema}
    if "type" not in local and type(value) in (int, float, str) and type(value) is not bool:
        # Bounds and patterns composed through allOf/$ref carry no repeated type.
        local["type"] = _KIND[type(value)]
    if local.get("type") == "object":
        local["properties"] = {key: {} for key in schema.get("properties", {})}
    elif local.get("type") == "array":
        local["items"] = {}
    _platform._shape(local, value, path)


def _structural(schema: Any, value: Any, path: str, root: dict) -> None:
    if schema is True or schema == {}:
        return
    if schema is False:
        _fail(path, "no value is permitted here")
    if "$ref" in schema:
        _structural(_resolve(root, schema["$ref"]), value, path, root)
    for branch in schema.get("allOf", ()):
        _structural(branch, value, path, root)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            matches = 0
            for branch in schema[key]:
                try:
                    _structural(branch, value, path, root)
                except ModelValidationError:
                    pass
                else:
                    matches += 1
            if matches == 0 or (key == "oneOf" and matches != 1):
                _fail(path, "does not match the contract alternatives")
    _local(schema, value, path)
    if type(value) is dict:
        properties = schema.get("properties", {})
        for key, child in value.items():
            if key in properties:
                _structural(properties[key], child, f"{path}.{key}", root)
    elif type(value) is list:
        prefix = schema.get("prefixItems", ())
        items = schema.get("items")
        for index, item in enumerate(value):
            if index < len(prefix):
                _structural(prefix[index], item, f"{path}.{index}", root)
            elif items is not None:
                _structural(items, item, f"{path}.{index}", root)


def _companion_read(value: dict) -> None:
    """Check only what poseidon_proto.companion publishes; no second reader."""
    if value.get("schema_version") != COMPANION_SCHEMA_VERSION:
        _fail("schema_version", "unknown companion read version")
    if value.get("state") == "absent":
        return
    documents = value["documents"]
    if tuple(document["role"] for document in documents) != tuple(DOCUMENT_ROLES):
        _fail("documents", "retained documents must be the five JSON roles in order")
    for document in documents:
        if document["bytes"] > PART_LIMITS[document["role"]]:
            _fail("documents", "document exceeds its ratified role limit")


_SEMANTIC = {
    "command": parse_command,
    "command-ack": parse_command_ack,
    "calibration-record": parse_calibration,
    "companion-read": _companion_read,
}


def validate_contract(name: str, value: Any) -> dict:
    """Validate without coercion; return a detached, JSON-safe copy."""
    if name in _platform.CONTRACTS:
        return _platform.validate_contract(name, value)
    schema = _schema(name)
    _structural(schema, value, "input", schema)
    _SEMANTIC[name](value)
    return json.loads(json.dumps(value, allow_nan=False))
