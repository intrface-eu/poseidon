"""Bounded ChirpStack v4 JSON HTTP-integration uplink adapter; private draft."""
import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from types import MappingProxyType

from .wire import MAX_PAYLOAD_BYTES, Rejected, decode_payload

MAX_JSON_BYTES = 16384
_EUI = re.compile(r"[0-9a-fA-F]{16}\Z")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})\Z")


def bounded_json(body: bytes):
    if type(body) is not bytes or not 1 <= len(body) <= MAX_JSON_BYTES:
        raise Rejected("json_size")
    try:
        text = body.decode("utf-8", errors="strict")
        # Bound nesting before the recursive stdlib decoder sees it.
        depth, quoted, escape = 0, False, False
        for char in text:
            if quoted:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                if depth > 12:
                    raise Rejected("json_depth")
            elif char in "]}":
                depth -= 1

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise Rejected("json_duplicate_key")
                result[key] = value
            return result

        def integer(value):
            if len(value) > 21:
                raise Rejected("json_integer_size")
            return int(value)

        def floating(value):
            result = float(value)
            if not math.isfinite(result):
                raise Rejected("json_nonfinite")
            return result

        def constant(_):
            raise Rejected("json_nonfinite")

        result = json.loads(text, object_pairs_hook=pairs, parse_int=integer,
                            parse_float=floating, parse_constant=constant)
        pending, count = [result], 0
        while pending:
            value = pending.pop()
            count += 1
            if count > 2048:
                raise Rejected("json_nodes")
            if isinstance(value, dict):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str):
                if len(value) > 4096:
                    raise Rejected("json_string_size")
                value.encode("utf-8", errors="strict")
        if type(result) is not dict:
            raise Rejected("json_object")
        return result
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as exc:
        raise Rejected("json_invalid") from exc


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise Rejected("clock_not_aware")
    return value.astimezone(timezone.utc)


def stamp(value: datetime) -> str:
    return utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value) -> datetime:
    if type(value) is not str or not _TIME.fullmatch(value):
        raise Rejected("network_time_format")
    try:
        return utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise Rejected("network_time_format") from exc


@dataclass(frozen=True)
class ClockPolicy:
    """Local acceptance limits, not sensor/field operating limits."""
    future_seconds: int = 60
    max_event_age_seconds: int = 86400
    max_observed_age_seconds: int = 86400

    def __post_init__(self):
        for value in (self.future_seconds, self.max_event_age_seconds,
                      self.max_observed_age_seconds):
            if type(value) is not int or not 0 <= value <= 31536000:
                raise ValueError("clock policy must be bounded nonnegative seconds")


@dataclass(frozen=True)
class Device:
    dev_eui: str
    application_id: str
    enabled: bool = True
    provenance: str = "synthetic-local-reference"

    def __post_init__(self):
        if not _EUI.fullmatch(self.dev_eui) or self.dev_eui != self.dev_eui.lower():
            raise ValueError("registry DevEUI must be lowercase hex")
        if (type(self.enabled) is not bool or not isinstance(self.application_id, str)
                or not 1 <= len(self.application_id) <= 128
                or not isinstance(self.provenance, str) or not 1 <= len(self.provenance) <= 256):
            raise ValueError("invalid local device record")


@dataclass(frozen=True)
class Calibration:
    dev_eui: str
    calibration_id: int
    sensor_kind: int
    reference: str
    valid_from: datetime
    valid_until: datetime
    approved: bool = False
    synthetic: bool = True

    def __post_init__(self):
        if (not _EUI.fullmatch(self.dev_eui) or self.dev_eui != self.dev_eui.lower()
                or type(self.calibration_id) is not int or not 1 <= self.calibration_id <= 65535
                or type(self.sensor_kind) is not int or self.sensor_kind not in (1, 2, 3)
                or not isinstance(self.reference, str) or not 1 <= len(self.reference) <= 256
                or type(self.approved) is not bool or type(self.synthetic) is not bool
                or utc(self.valid_from) >= utc(self.valid_until)):
            raise ValueError("invalid local calibration record")


class LocalRegistry:
    """Explicit local metadata only; no claim of platform registry integration."""
    def __init__(self, devices, calibrations=()):
        devices, calibrations = tuple(devices), tuple(calibrations)
        if len(devices) > 1024 or len(calibrations) > 4096:
            raise ValueError("registry bound")
        self.devices = MappingProxyType({device.dev_eui: device for device in devices})
        self.calibrations = MappingProxyType({(c.dev_eui, c.calibration_id): c for c in calibrations})
        if len(self.devices) != len(devices) or len(self.calibrations) != len(calibrations):
            raise ValueError("duplicate registry entry")

    def device(self, eui, application):
        device = self.devices.get(eui)
        if device is None or not device.enabled or device.application_id != application:
            raise Rejected("device_not_allowed")
        return device

    def calibration(self, eui, telemetry, reference_time):
        record = self.calibrations.get((eui, telemetry.calibration_id))
        if (record is None or not record.approved or record.sensor_kind != telemetry.sensor_kind
                or not utc(record.valid_from) <= reference_time < utc(record.valid_until)):
            raise Rejected("calibration_reference_invalid")
        return record


@dataclass(frozen=True)
class Accepted:
    dev_eui: str
    boot_id: int
    sequence: int
    payload_sha256: str
    document: dict

    @property
    def identity(self):
        return f"reef-draft-v1:{self.dev_eui}:{self.boot_id}:{self.sequence}"


class ChirpStackAdapter:
    def __init__(self, registry: LocalRegistry, clock_policy: ClockPolicy | None = None):
        self.registry = registry
        self.clock_policy = clock_policy or ClockPolicy()

    def parse(self, body: bytes, *, event: str, received_at: datetime,
              transport: str = "fixture-replay", integration_id: str = "synthetic-local") -> Accepted:
        if event != "up":
            raise Rejected("event_not_up")
        received_at = utc(received_at)
        envelope = bounded_json(body)
        if type(envelope.get("fPort")) is not int or envelope["fPort"] != 10:
            raise Rejected("fport_not_10")
        info = envelope.get("deviceInfo")
        if type(info) is not dict:
            raise Rejected("device_metadata_missing")
        eui, application = info.get("devEui"), info.get("applicationId")
        if (type(eui) is not str or not _EUI.fullmatch(eui)
                or type(application) is not str or not 1 <= len(application) <= 128):
            raise Rejected("device_metadata_invalid")
        eui = eui.lower()
        device = self.registry.device(eui, application)
        network_time = parse_time(envelope.get("time"))
        policy = self.clock_policy
        age = (received_at - network_time).total_seconds()
        if age < -policy.future_seconds or age > policy.max_event_age_seconds:
            raise Rejected("network_time_outside_policy")
        encoded = envelope.get("data")
        if type(encoded) is not str or not 1 <= len(encoded) <= 4 * ((MAX_PAYLOAD_BYTES + 2) // 3):
            raise Rejected("base64_size")
        try:
            payload = base64.b64decode(encoded, validate=True)
            if base64.b64encode(payload).decode("ascii") != encoded:
                raise Rejected("base64_noncanonical")
        except (ValueError, binascii.Error) as exc:
            raise Rejected("base64_invalid") from exc
        telemetry = decode_payload(payload)
        observed = None
        if telemetry.observed_at_unix_s is not None:
            observed = datetime.fromtimestamp(telemetry.observed_at_unix_s, timezone.utc)
            age = (received_at - observed).total_seconds()
            if (age < -policy.future_seconds or age > policy.max_observed_age_seconds
                    or (observed - network_time).total_seconds() > policy.future_seconds):
                raise Rejected("observed_time_outside_policy")
        kinds = ("none", "temperature", "salinity", "dissolved_oxygen")
        sensor = {"kind": kinds[telemetry.sensor_kind],
                  "quality": ("raw", "calibrated", "invalid")[telemetry.sensor_quality],
                  "wire_value": telemetry.sensor_value, "raw_counts": None,
                  "value": None, "unit": None, "calibration": None}
        if telemetry.sensor_kind and telemetry.sensor_quality == 0:
            sensor["raw_counts"] = telemetry.sensor_value
        elif telemetry.sensor_kind and telemetry.sensor_quality == 1:
            if observed is None:
                raise Rejected("calibration_time_unknown")
            reference_time = observed
            record = self.registry.calibration(eui, telemetry, reference_time)
            divisor, unit = {1: (100, "degC"), 2: (1000, "practical_salinity_dimensionless"),
                             3: (1, "ug/L")}[telemetry.sensor_kind]
            sensor.update(value=telemetry.sensor_value / divisor, unit=unit,
                          calibration={"id": record.calibration_id, "reference": record.reference,
                                       "synthetic": record.synthetic,
                                       "validity_checked_at": stamp(reference_time),
                                       "validity_time_basis": "claimed_observed_at",
                                       "validity_evidence": "claim-time-range-check-not-verified-observation"})
        digest = hashlib.sha256(payload).hexdigest()
        document = {
            "schema": "aquilon-normalized-v1-proposal", "contract_status": "draft-unapproved",
            "device": {"dev_eui": eui, "application_id": application},
            "boot_id": str(telemetry.boot_id), "sequence": telemetry.sequence,
            "uptime_s": telemetry.uptime_s,
            "clock_quality": "unknown",
            "clock_claim": ("unsynchronized", "rtc", "network")[telemetry.clock_quality],
            "received_at": stamp(received_at), "network_event_at": stamp(network_time),
            "observed_at": None,  # No independent clock evidence adapter exists yet.
            "claimed_observed_at": stamp(observed) if observed else None,
            "power": {"battery_mv": telemetry.battery_mv, "solar_mv": telemetry.solar_mv,
                      "mode": ("normal", "conserve", "critical")[telemetry.power_mode]},
            "sensor": sensor,
            "source": {"adapter": "chirpstack-v4-json", "transport": transport,
                       "integration_id": integration_id, "registry_provenance": device.provenance,
                       "network_event_time_original": envelope["time"],
                       "payload_sha256": digest, "payload_base64": encoded,
                       "f_port": 10, "event": "up"},
        }
        accepted = Accepted(eui, telemetry.boot_id, telemetry.sequence, digest, document)
        document["identity"] = accepted.identity
        return accepted
