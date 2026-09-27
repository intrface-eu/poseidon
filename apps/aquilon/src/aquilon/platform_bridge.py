"""Optional wave-1 platform bridge. Requires libs/proto-py/src on PYTHONPATH.

Network transport stays numeric-loopback-only. Registry/credential snapshots are
trusted local provisioning inputs, never fields copied from an uplink sender.
"""
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import math
import re
import threading
import time
from types import MappingProxyType, SimpleNamespace
from urllib.parse import urlsplit

from poseidon_proto import reef
from poseidon_proto.platform import canonical_json, parse_utc, validate_contract

from .adapter import LocalRegistry, bounded_json
from .runtime import AquilonRuntime
from .transport import LoopbackJSONTransport, SinkFailure
from .wire import Rejected

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_IDENTITY = re.compile(r"reef-draft-v1:([0-9a-f]{16}):([1-9][0-9]{0,19}):([0-9]{1,10})\Z")
_KINDS = {1: "temperature", 2: "salinity", 3: "dissolved_oxygen"}
_MAX_AGE = 604800


def _identifier(value):
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError("invalid platform registry identifier")


@dataclass(frozen=True)
class CalibrationBinding:
    code: int
    sensor_kind: str
    calibration_id: str
    local_reference: str

    def __post_init__(self):
        _identifier(self.calibration_id)
        if (type(self.code) is not int or not 1 <= self.code <= 65535
                or self.sensor_kind not in _KINDS.values()
                or type(self.local_reference) is not str or not 1 <= len(self.local_reference) <= 256):
            raise ValueError("invalid calibration mapping")


@dataclass(frozen=True)
class DeviceBinding:
    dev_eui: str
    application_id: str
    device_id: str
    site_id: str
    source_kind: str
    source_id: str
    calibration_refs: tuple[CalibrationBinding, ...] = ()

    def __post_init__(self):
        for value in (self.device_id, self.site_id, self.source_id):
            _identifier(value)
        if (type(self.dev_eui) is not str or not re.fullmatch(r"[0-9a-f]{16}", self.dev_eui)
                or type(self.application_id) is not str or not 1 <= len(self.application_id) <= 128
                or self.source_kind not in ("synthetic", "bench", "field")
                or type(self.calibration_refs) is not tuple or len(self.calibration_refs) > 64
                or any(type(item) is not CalibrationBinding for item in self.calibration_refs)
                or len({item.code for item in self.calibration_refs}) != len(self.calibration_refs)):
            raise ValueError("invalid immutable device mapping")


class RegistrySnapshot:
    """Bounded immutable snapshot of approved device/site/source/calibration IDs."""
    def __init__(self, local_registry: LocalRegistry, devices: tuple[DeviceBinding, ...]):
        if type(devices) is not tuple or not 1 <= len(devices) <= 1024:
            raise ValueError("bounded registry tuple required")
        by_eui = {}
        device_ids = set()
        for device in devices:
            if type(device) is not DeviceBinding or device.dev_eui in by_eui or device.device_id in device_ids:
                raise ValueError("ambiguous device mapping")
            local_registry.device(device.dev_eui, device.application_id)
            for ref in device.calibration_refs:
                record = local_registry.calibrations.get((device.dev_eui, ref.code))
                if (record is None or not record.approved or _KINDS[record.sensor_kind] != ref.sensor_kind
                        or record.reference != ref.local_reference
                        or (record.synthetic and device.source_kind != "synthetic")):
                    raise ValueError("calibration mapping does not match immutable local reference")
            by_eui[device.dev_eui] = device
            device_ids.add(device.device_id)
        self._devices = MappingProxyType(by_eui)
        self._local_registry = local_registry

    @property
    def devices(self):
        return self._devices

    def resolve(self, eui, application):
        binding = self._devices.get(eui)
        if binding is None or binding.application_id != application:
            raise Rejected("platform_device_not_mapped")
        self._local_registry.device(eui, application)
        return binding

    def calibration(self, binding, fields):
        claimed_at = fields["observed_at_unix_s"]
        if claimed_at is None:
            raise Rejected("calibration_time_unknown")
        record = self._local_registry.calibration(binding.dev_eui,
            SimpleNamespace(calibration_id=fields["calibration_id"], sensor_kind=fields["sensor_kind"]),
            datetime.fromtimestamp(claimed_at, timezone.utc))
        for ref in binding.calibration_refs:
            if (ref.code == fields["calibration_id"] and ref.sensor_kind == _KINDS[fields["sensor_kind"]]
                    and ref.local_reference == record.reference):
                return ref.calibration_id
        raise Rejected("platform_calibration_not_mapped")


@dataclass(frozen=True)
class DeviceCredential:
    device_id: str
    site_id: str
    token: str = field(repr=False)
    enabled: bool = True

    def __post_init__(self):
        _identifier(self.device_id)
        _identifier(self.site_id)
        if (type(self.token) is not str or not 24 <= len(self.token) <= 512
                or not re.fullmatch(r"[A-Za-z0-9._~-]+", self.token)
                or type(self.enabled) is not bool):
            raise ValueError("invalid scoped credential")


class CredentialResolver:
    """Local injected secrets only; no remote lookup, logging, or fleet token."""
    def __init__(self, credentials: tuple[DeviceCredential, ...]):
        if type(credentials) is not tuple or len(credentials) > 1024:
            raise ValueError("bounded credentials tuple required")
        records = {}
        token_hashes = set()
        for credential in credentials:
            if type(credential) is not DeviceCredential or credential.device_id in records:
                raise ValueError("duplicate credential device")
            digest = hashlib.sha256(credential.token.encode("ascii")).digest()
            if digest in token_hashes:
                raise ValueError("one credential cannot span devices")
            token_hashes.add(digest)
            records[credential.device_id] = credential
        self._records = MappingProxyType(records)

    def resolve(self, device_id, site_id):
        credential = self._records.get(device_id)
        if credential is None or not credential.enabled or credential.site_id != site_id:
            raise SinkFailure("device_credential_unavailable")
        return credential.token


class PlatformNormalizer:
    def __init__(self, registry: RegistrySnapshot):
        self.registry = registry

    def normalize(self, identity: str, body: bytes, *, delivery_age_s: int):
        """Decode with the approved shared codec; never promote wire clock claims."""
        match = _IDENTITY.fullmatch(identity)
        if match is None:
            raise Rejected("platform_identity_invalid")
        eui, boot, sequence = match.groups()
        document = bounded_json(body)
        try:
            source, device = document["source"], document["device"]
            binding = self.registry.resolve(eui, device["application_id"])
            if (document["identity"] != identity or device["dev_eui"] != eui
                    or document["boot_id"] != boot or str(document["sequence"]) != sequence
                    or source["f_port"] != 10 or source["event"] != "up"):
                raise Rejected("platform_identity_mismatch")
            encoded = source["payload_base64"]
            if type(encoded) is not str or not 1 <= len(encoded) <= 88:
                raise Rejected("platform_frame_bound")
            payload = base64.b64decode(encoded, validate=True)
            if base64.b64encode(payload).decode("ascii") != encoded:
                raise Rejected("platform_frame_encoding")
            fields = reef.json_fields(reef.decode_frame(payload))
            digest = hashlib.sha256(payload).hexdigest()
            if (fields["boot_id"] != boot or str(fields["sequence"]) != sequence
                    or source["payload_sha256"] != digest):
                raise Rejected("platform_frame_identity_mismatch")
            network_time = document["network_event_at"]
            parse_utc(network_time)
        except (KeyError, TypeError, ValueError) as exc:
            raise Rejected("platform_source_invalid") from None

        def measurement(name, value, unit, quality, calibration_id=None):
            return {"name": name, "value": value, "unit": unit,
                    "quality": quality, "calibration_id": calibration_id}

        measurements = []
        for wire_name, name in (("battery_mv", "battery_voltage"), ("solar_mv", "solar_voltage")):
            value = fields[wire_name]
            measurements.append(measurement(name, value / 1000 if value is not None else None,
                                            "V", "uncalibrated" if value is not None else "invalid"))
        kind, quality = fields["sensor_kind"], fields["sensor_quality"]
        if kind:
            name, value = _KINDS[kind], fields["sensor_value"]
            if quality == 0:
                measurements.append(measurement(name + "_raw", value, "count", "uncalibrated"))
            elif quality == 1:
                calibration_id = self.registry.calibration(binding, fields)
                divisor, unit = {1: (100, "Cel"), 2: (1000, "1"), 3: (1, "ug/L")}[kind]
                measurements.append(measurement(name, value / divisor, unit, "calibrated", calibration_id))
            else:
                measurements.append(measurement(name, None, {1: "Cel", 2: "1", 3: "ug/L"}[kind], "invalid"))
        envelope = {
            "schema_version": "poseidon.telemetry.v1", "device_id": binding.device_id,
            "site_id": binding.site_id, "boot_id": fields["boot_id"], "sequence": fields["sequence"],
            "observed_at": None, "delivery_age_s": delivery_age_s,
            "clock_quality": {"status": "unknown", "method": "unknown", "uncertainty_ms": None,
                              "offset_ms": None, "reference": None},
            "provenance": {"source_kind": binding.source_kind, "source_id": binding.source_id,
                           "transport": "aquilon"},
            "measurements": measurements,
            "radio": {"dev_eui": binding.dev_eui, "uptime_s": fields["uptime_s"],
                      "power_mode": ("normal", "conserve", "critical")[fields["power_mode"]],
                      "clock_claim": ("unsynchronized", "rtc", "network")[fields["clock_quality"]],
                      "observed_at_unix_s": fields["observed_at_unix_s"],
                      "network_received_at": network_time, "frame_sha256": digest,
                      "calibration_code": fields["calibration_id"]},
        }
        return validate_contract("telemetry-envelope", envelope)


class PlatformAPIClient:
    """Approved POST /api/v1/telemetry shape; owned loopback/mock endpoints only."""
    def __init__(self, endpoint: str, credentials: CredentialResolver, *, timeout_seconds=2):
        if urlsplit(endpoint).path != "/api/v1/telemetry":
            raise ValueError("approved telemetry route required")
        self._transport = LoopbackJSONTransport(endpoint, timeout_seconds=timeout_seconds)
        self._credentials = credentials

    def send(self, envelope: dict):
        self.send_frozen(canonical_json(validate_contract("telemetry-envelope", envelope)))

    def send_frozen(self, body: bytes):
        """Validate stored bytes, but transmit those exact bytes without rebuilding."""
        envelope = validate_contract("telemetry-envelope", bounded_json(body))
        if canonical_json(envelope) != body:
            raise SinkFailure("platform_frozen_not_canonical")
        token = self._credentials.resolve(envelope["device_id"], envelope["site_id"])
        response = self._transport.post(body, {"Authorization": "Bearer " + token}, max_response_bytes=16384)
        try:
            if (set(response) != {"id", "envelope", "received_at", "actor_subject", "duplicate"}
                    or type(response["duplicate"]) is not bool
                    or type(response["id"]) is not str or not 1 <= len(response["id"]) <= 128
                    or type(response["actor_subject"]) is not str or not 1 <= len(response["actor_subject"]) <= 256):
                raise SinkFailure("platform_ack_invalid")
            acknowledged = validate_contract("telemetry-envelope", response["envelope"])
            if canonical_json(acknowledged) != body:
                raise SinkFailure("platform_ack_mismatch")
            parse_utc(response["received_at"])
        except (KeyError, TypeError, ValueError):
            raise SinkFailure("platform_ack_invalid") from None


@dataclass
class _Admission:
    started_at: float
    body_digest: str | None = None


class MonotonicAdmissions:
    """Process-local bounded residence evidence. Restart never becomes age zero."""
    def __init__(self, *, capacity: int, monotonic=time.monotonic):
        if type(capacity) is not int or not 1 <= capacity <= 1000000:
            raise ValueError("admission capacity bound")
        self.capacity, self._clock = capacity, monotonic
        self._records = {}
        self._last = None
        self._lost = False
        self.lock = threading.RLock()

    def _now(self):
        if self._lost:
            raise SinkFailure("residence_time_basis_lost")
        value = self._clock()
        if (type(value) not in (int, float) or not math.isfinite(value) or value < 0
                or (self._last is not None and value < self._last)):
            self._lost = True
            raise SinkFailure("residence_time_basis_lost")
        self._last = value
        return value

    def begin(self):
        with self.lock:
            return self._now()

    def admit_new(self, identity, started_at):
        with self.lock:
            now = self._now()
            if started_at > now or identity in self._records:
                raise SinkFailure("admission_cannot_reset")
            if len(self._records) >= self.capacity:
                raise SinkFailure("admission_capacity")
            self._records[identity] = _Admission(started_at)

    def check_residence(self, identity, body):
        with self.lock:
            now = self._now()
            record = self._records.get(identity)
            if record is None:
                raise SinkFailure("residence_evidence_missing")
            age = math.ceil(now - record.started_at)
            if not 0 <= age <= _MAX_AGE:
                raise SinkFailure("delivery_residence_expired")
            digest = hashlib.sha256(body).hexdigest()
            if record.body_digest is not None and record.body_digest != digest:
                raise SinkFailure("admitted_body_changed")
            record.body_digest = digest
            return age

    def prepare(self, identity, body, normalizer):
        """Preview only; sending requires SQLiteSpool.freeze_forwarding."""
        age = self.check_residence(identity, body)
        return normalizer.normalize(identity, body, delivery_age_s=age)

    def acknowledged(self, identity):
        with self.lock:
            self._records.pop(identity, None)

    def health(self):
        with self.lock:
            return {"tracked": len(self._records), "capacity": self.capacity,
                    "time_basis": "lost" if self._lost else "process-local-monotonic",
                    "restart_recovery": "external-time-evidence-required"}


class PlatformBridgeSink:
    def __init__(self, normalizer: PlatformNormalizer, client: PlatformAPIClient,
                 admissions: MonotonicAdmissions, spool):
        if admissions.capacity != spool.max_rows:
            raise ValueError("admission capacity must equal spool row capacity")
        self.normalizer, self.client, self.admissions = normalizer, client, admissions
        self.spool = spool

    def send(self, identity, body):
        age = self.admissions.check_residence(identity, body)
        frozen = self.spool.freeze_forwarding(identity, body, lambda: canonical_json(
            self.normalizer.normalize(identity, body, delivery_age_s=age)))
        # Check again after the durable commit; slow/full storage cannot extend
        # the local freshness allowance. Already frozen fields never rebuild.
        self.admissions.check_residence(identity, body)
        self.client.send_frozen(frozen)

    def local_committed(self, identity):
        """SQLiteSpool calls this only after its successful local delete COMMIT."""
        self.admissions.acknowledged(identity)


class PlatformBridgeRuntime(AquilonRuntime):
    """Admission wrapper; duplicates/recovered spool rows never gain a new clock."""
    def __init__(self, adapter, spool, admissions: MonotonicAdmissions):
        super().__init__(adapter, spool)
        if admissions.capacity != spool.max_rows:
            raise ValueError("admission capacity must equal spool row capacity")
        self.admissions = admissions
        self._ingest_lock = threading.Lock()

    def ingest(self, body, **kwargs):
        with self._ingest_lock:
            started = self.admissions.begin()
            result = super().ingest(body, **kwargs)
            if result["status"] == "accepted":
                self.admissions.admit_new(result["identity"], started)
            return result

    def health(self):
        result = super().health()
        residence = self.admissions.health()
        residence["held_without_process_time_evidence"] = (
            result["spool"]["rows"] if residence["time_basis"] == "lost"
            else max(0, result["spool"]["rows"] - residence["tracked"]))
        result.update(platform_ingest="approved-v1-loopback-client-reference",
                      registry="immutable-local-platform-mapping-snapshot", residence=residence)
        return result
