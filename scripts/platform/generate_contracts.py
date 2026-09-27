"""Emit the platform v1 JSON Schemas and unmistakably synthetic golden inputs."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "contracts" / "v1"
ID = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", "maxLength": 128}
TEXT = {"type": "string", "maxLength": 2000}
UTC = {"type": "string", "format": "date-time", "pattern": r"Z$"}
HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
UINT = {"type": "integer", "minimum": 0, "maximum": 2**32 - 1}
SOURCE = {"enum": ["synthetic", "bench", "field"]}
BOOT_ID = {"type": "string", "pattern": r"^[1-9][0-9]{0,19}$", "maxLength": 20}


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def obj(properties, required=None):
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": list(properties) if required is None else required}


def document(name, properties, defs=None):
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://poseidon.invalid/contracts/v1/{name}.schema.json",
            "title": f"Poseidon {name} v1", **obj(properties), **({"$defs": defs} if defs else {})}


CLOCK = obj({
    "status": {"enum": ["unknown", "operator_declared", "synchronized", "holdover"]},
    "method": {"enum": ["unknown", "operator_offset", "ntp", "gnss", "shared_clock", "measured_reference"]},
    "uncertainty_ms": nullable({"type": "number", "minimum": 0, "maximum": 604800000}),
    "offset_ms": nullable({"type": "number", "minimum": -604800000, "maximum": 604800000}),
    "reference": nullable({"type": "string", "minLength": 1, "maxLength": 256}),
})
PROVENANCE = obj({"source_kind": SOURCE, "source_id": ID,
                  "transport": {"enum": ["local", "aquilon", "import"]}})
MEASUREMENTS = {
    "temperature": "Cel", "voltage": "V", "current": "A", "relative_humidity": "%RH",
    "pressure": "Pa", "conductivity": "S/m", "battery_soc": "%", "digital_rms": "normalized_pcm16_full_scale",
    "battery_voltage": "V", "solar_voltage": "V", "salinity": "1", "dissolved_oxygen": "ug/L",
    "temperature_raw": "count", "salinity_raw": "count", "dissolved_oxygen_raw": "count",
}
MEASUREMENT = {"oneOf": [obj({
    "name": {"const": name}, "value": nullable({"type": "number"}), "unit": {"const": unit},
    "quality": {"enum": ["uncalibrated", "calibrated", "invalid"]}, "calibration_id": nullable(ID),
}) for name, unit in MEASUREMENTS.items()]}


def build():
    schemas = {
        "clock-quality": {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://poseidon.invalid/contracts/v1/clock-quality.schema.json", **CLOCK},
        "device": document("device", {
            "id": ID, "site_id": ID, "label": {"type": "string", "minLength": 1, "maxLength": 160},
            "kind": {"enum": ["reef", "aquilon", "hub"]}, "hardware_revision": ID, "source_kind": SOURCE,
        }),
        "telemetry-envelope": document("telemetry-envelope", {
            "schema_version": {"const": "poseidon.telemetry.v1"}, "device_id": ID, "site_id": ID,
            "boot_id": BOOT_ID, "sequence": UINT, "observed_at": nullable(UTC),
            "delivery_age_s": {"type": "integer", "minimum": 0, "maximum": 604800},
            "clock_quality": CLOCK, "provenance": PROVENANCE,
            "measurements": {"type": "array", "minItems": 1, "maxItems": 32, "items": MEASUREMENT},
        }),
        "acquisition-session": document("acquisition-session", {
            "schema_version": {"const": "poseidon.acquisition-session.v1"}, "id": ID, "site_id": ID,
            "device_id": nullable(ID), "started_at": nullable(UTC), "ended_at": nullable(UTC),
            "clock_quality": CLOCK, "provenance": PROVENANCE,
            "operator": {"type": "string", "minLength": 1, "maxLength": 80},
            "notes": TEXT,
        }),
        "independent-observation": document("independent-observation", {
            "id": ID, "start_s": {"type": "number", "minimum": 0},
            "end_s": {"type": "number", "exclusiveMinimum": 0},
            "label": {"enum": ["feeding_observed", "no_feeding_observed", "uncertain", "not_visible"]},
            "notes": TEXT, "observer": {"type": "string", "minLength": 1, "maxLength": 80},
            "expected_revision": {"type": "integer", "minimum": 0, "maximum": 2**31 - 1},
        }),
    }
    relation = obj({
        "source_domain": ID, "reference_domain": ID,
        "source_anchor_s": {"type": "number"}, "reference_anchor_s": {"type": "number"},
        "drift_ppm": {"type": "number", "exclusiveMinimum": -1000000},
        "anchor_uncertainty_s": {"type": "number", "minimum": 0},
        "drift_uncertainty_ppm": {"type": "number", "minimum": 0},
        "method": {"enum": ["operator_declared", "measured_reference", "shared_clock"]},
        "evidence_ref": nullable(ID),
    })
    context = obj({
        "protocol_id": nullable(ID), "evidence_refs": {"type": "array", "maxItems": 32, "items": ID},
        "visibility": {"enum": ["clear", "limited", "not_visible", "unknown"]},
        "sync_uncertainty_s": nullable({"type": "number", "minimum": 0}),
        "reviewed_coverage": {"type": "boolean"},
    })
    radio = obj({
        "dev_eui": {"type": "string", "pattern": "^[a-f0-9]{16}$"},
        "uptime_s": UINT, "power_mode": {"enum": ["normal", "conserve", "critical"]},
        "clock_claim": {"enum": ["unsynchronized", "rtc", "network"]},
        "observed_at_unix_s": nullable(UINT), "network_received_at": nullable(UTC),
        "frame_sha256": HASH, "calibration_code": nullable({"type": "integer", "minimum": 1, "maximum": 65535}),
    })
    schemas["clock-relation"] = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://poseidon.invalid/contracts/v1/clock-relation.schema.json", **relation}
    schemas["acquisition-session"]["properties"]["clock_relation"] = nullable(relation)
    schemas["independent-observation"]["properties"]["review_context"] = context
    schemas["telemetry-envelope"]["properties"]["radio"] = radio
    payload = obj({
        "schema_version": {"const": "poseidon.signed-manifest.v1"},
        "id": ID, "kind": {"enum": ["config", "release", "update"]},
        "target_kind": {"enum": ["hub", "reef"]}, "hardware_revision": ID,
        "version": ID, "sequence": UINT, "security_version": UINT,
        "issued_at": UTC, "expires_at": UTC,
        "artifact_sha256": HASH, "artifact_size_bytes": {"type": "integer", "minimum": 1, "maximum": 268435456},
        "previous_sha256": nullable(HASH),
        "config": obj({"monitor_only": {"const": True}, "telemetry_interval_s": {"type": "integer", "minimum": 1, "maximum": 86400}, "offline_queue_limit": {"type": "integer", "minimum": 1, "maximum": 4096}}),
    })
    schemas["signed-manifest"] = document("signed-manifest", {
        "payload": payload, "signature": obj({"algorithm": {"const": "Ed25519"}, "key_id": ID,
        "canonicalization": {"const": "poseidon-json-v1"}, "value": {"type": "string", "pattern": "^[A-Za-z0-9+/]{86}==$", "maxLength": 88}}),
    })
    unknown_clock = {"status": "unknown", "method": "unknown", "uncertainty_ms": None, "offset_ms": None, "reference": None}
    provenance = {"source_kind": "synthetic", "source_id": "synthetic-golden-v1", "transport": "local"}
    fixtures = {
        "clock-quality": unknown_clock,
        "clock-relation": {"source_domain": "synthetic-audio-monotonic", "reference_domain": "synthetic-video-monotonic", "source_anchor_s": 0, "reference_anchor_s": 0.12, "drift_ppm": 10, "anchor_uncertainty_s": 0.02, "drift_uncertainty_ppm": 5, "method": "operator_declared", "evidence_ref": None},
        "device": {"id": "synthetic-reef-001", "site_id": "synthetic-site", "label": "Synthetic contract fixture; not connected", "kind": "reef", "hardware_revision": "simulation-v1", "source_kind": "synthetic"},
        "telemetry-envelope": {"schema_version": "poseidon.telemetry.v1", "device_id": "synthetic-reef-001", "site_id": "synthetic-site", "boot_id": "1", "sequence": 1, "observed_at": None, "delivery_age_s": 0, "clock_quality": unknown_clock, "provenance": provenance, "measurements": [{"name": "temperature", "value": 21.5, "unit": "Cel", "quality": "uncalibrated", "calibration_id": None}]},
        "acquisition-session": {"schema_version": "poseidon.acquisition-session.v1", "id": "synthetic-session-001", "site_id": "synthetic-site", "device_id": None, "started_at": None, "ended_at": None, "clock_quality": unknown_clock, "provenance": provenance, "operator": "Synthetic test operator", "notes": "Software fixture only; no field capture or verified synchronization."},
        "independent-observation": {"id": "synthetic-observation-001", "start_s": 0.0, "end_s": 0.1, "label": "uncertain", "notes": "Synthetic interval fixture; no biological evidence.", "observer": "Synthetic test operator", "expected_revision": 0},
        "signed-manifest": {"payload": {"schema_version": "poseidon.signed-manifest.v1", "id": "synthetic-update-001", "kind": "update", "target_kind": "reef", "hardware_revision": "simulation-v1", "version": "synthetic-1", "sequence": 1, "security_version": 1, "issued_at": "2026-09-08T00:00:00Z", "expires_at": "2026-09-09T00:00:00Z", "artifact_sha256": "0" * 64, "artifact_size_bytes": 1, "previous_sha256": None, "config": {"monitor_only": True, "telemetry_interval_s": 60, "offline_queue_limit": 128}}, "signature": {"algorithm": "Ed25519", "key_id": "synthetic-test-key", "canonicalization": "poseidon-json-v1", "value": "A" * 86 + "=="}},
    }
    for name, schema in schemas.items():
        (OUT / "fixtures").mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n")
        (OUT / "fixtures" / f"{name}.valid.json").write_text(json.dumps(fixtures[name], indent=2) + "\n")
    negatives = [
        {"contract": "telemetry-envelope", "mutation": "measurements.0.unit", "value": "dB", "reason": "temperature is Cel, not acoustic dB"},
        {"contract": "telemetry-envelope", "mutation": "sequence", "value": True, "reason": "boolean is not a counter"},
        {"contract": "telemetry-envelope", "mutation": "delivery_age_s", "value": 604801, "reason": "bounded offline delivery"},
        {"contract": "telemetry-envelope", "mutation": "provenance.source_kind", "value": "real", "reason": "unrecognized source kind"},
        {"contract": "independent-observation", "mutation": "end_s", "value": 0, "reason": "empty interval"},
        {"contract": "signed-manifest", "mutation": "payload.config.monitor_only", "value": False, "reason": "no active-output configuration"},
        {"contract": "acquisition-session", "mutation": "unexpected", "value": "no", "reason": "unknown field"},
    ]
    (OUT / "fixtures" / "negative-cases.json").write_text(json.dumps(negatives, indent=2) + "\n")
    print(f"Emitted {len(schemas)} schemas, {len(fixtures)} shape fixtures, {len(negatives)} negative cases")


if __name__ == "__main__":
    build()
