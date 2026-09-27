"""Pure migrations for the shipped digital control configuration documents."""
from __future__ import annotations

from copy import deepcopy

from .models import ModelValidationError

CURRENT_VERSION = "poseidon.digital-config.v2"


def _error():
    raise ModelValidationError("unknown or invalid digital config schema_version")


def _v1_v2(value):
    return {"schema_version": CURRENT_VERSION, "simulation": True, "health_interval_s": value["health_interval_s"]}


MIGRATIONS = {("poseidon.digital-config.v1", CURRENT_VERSION): _v1_v2}


def migrate_config(value: dict, target: str = CURRENT_VERSION) -> dict:
    """Return a detached validated document; never read clocks, storage or devices."""
    if type(value) is not dict or target != CURRENT_VERSION:
        _error()
    result = deepcopy(value)
    version = result.get("schema_version")
    if version not in {"poseidon.digital-config.v1", CURRENT_VERSION}:
        _error()
    expected = {"schema_version", "health_interval_s"} | ({"simulation"} if version == CURRENT_VERSION else set())
    if set(result) != expected or type(result.get("health_interval_s")) is not int or not 1 <= result["health_interval_s"] <= 3600:
        _error()
    if version == CURRENT_VERSION and result["simulation"] is not True:
        _error()
    if version != target:
        result = MIGRATIONS[(version, target)](result)
    return result
