"""REEF telemetry CBOR v1 reference codec, no radio or device I/O."""
from __future__ import annotations

from .models import ModelValidationError

FPORT = 10
MAX_BYTES = 64
FIELDS = ("version", "boot_id", "sequence", "uptime_s", "clock_quality", "observed_at_unix_s", "battery_mv", "solar_mv", "power_mode", "sensor_kind", "sensor_value", "sensor_quality", "calibration_id")


def validate_frame(fields: list) -> list:
    if type(fields) is not list or len(fields) != 13:
        raise ModelValidationError("REEF v1 requires exactly 13 fields")
    bounds = [(1, 1), (1, 2**64 - 1), (0, 2**32 - 1), (0, 2**32 - 1), (0, 2), (0, 2**32 - 1), (0, 65535), (0, 65535), (0, 2), (0, 3), (-2**31, 2**31 - 1), (0, 2), (1, 65535)]
    nullable = {5, 6, 7, 10, 12}
    for index, (value, (low, high)) in enumerate(zip(fields, bounds)):
        if index in nullable and value is None:
            continue
        if type(value) is not int or not low <= value <= high:
            raise ModelValidationError(f"invalid REEF {FIELDS[index]}")
    if (fields[4] == 0) != (fields[5] is None):
        raise ModelValidationError("unsynchronized REEF clock requires null UTC; clock claims require timestamp")
    sensor, value, quality, calibration = fields[9:13]
    if sensor == 0 and quality != 2:
        raise ModelValidationError("absent sensor requires invalid quality")
    if sensor == 0 or quality == 2:
        if value is not None or calibration is not None:
            raise ModelValidationError("absent/invalid sensor must have null value and calibration")
    elif value is None or (quality == 0 and calibration is not None) or (quality == 1 and calibration is None):
        raise ModelValidationError("raw counts have no calibration; calibrated readings need a reference")
    return list(fields)


def _integer(value: int) -> bytes:
    major = 0 if value >= 0 else 1
    n = value if value >= 0 else -1 - value
    if n < 24:
        return bytes([(major << 5) | n])
    for size, extra in ((1, 24), (2, 25), (4, 26), (8, 27)):
        if n < 1 << (size * 8):
            return bytes([(major << 5) | extra]) + n.to_bytes(size, "big")
    raise ModelValidationError("CBOR integer exceeds uint64")


def encode_frame(fields: list) -> bytes:
    fields = validate_frame(fields)
    data = b"\x8d" + b"".join(b"\xf6" if value is None else _integer(value) for value in fields)
    if len(data) > MAX_BYTES:
        raise ModelValidationError("REEF frame exceeds parser bound")
    return data


def decode_frame(data: bytes) -> list:
    if type(data) is not bytes or not 1 <= len(data) <= MAX_BYTES or data[0] != 0x8D:
        raise ModelValidationError("REEF requires a bounded definite 13-element CBOR array")
    fields = []
    position = 1
    for _ in FIELDS:
        if position >= len(data):
            raise ModelValidationError("truncated REEF frame")
        initial = data[position]
        position += 1
        if initial == 0xF6:
            fields.append(None)
            continue
        major, extra = initial >> 5, initial & 31
        if major not in (0, 1):
            raise ModelValidationError("REEF fields must be integers or null")
        if extra < 24:
            value = extra
        elif extra in (24, 25, 26, 27):
            size = {24: 1, 25: 2, 26: 4, 27: 8}[extra]
            if position + size > len(data):
                raise ModelValidationError("truncated REEF integer")
            value = int.from_bytes(data[position:position + size], "big")
            position += size
            if value < {24: 24, 25: 256, 26: 65536, 27: 2**32}[extra]:
                raise ModelValidationError("nonminimal CBOR integer")
        else:
            raise ModelValidationError("unsupported CBOR integer encoding")
        fields.append(value if major == 0 else -1 - value)
    if position != len(data):
        raise ModelValidationError("trailing REEF frame bytes")
    return validate_frame(fields)


def json_fields(fields: list) -> dict:
    """Export uint64 boot IDs as decimal text, safe in JavaScript and SQLite."""
    values = dict(zip(FIELDS, validate_frame(fields)))
    values["boot_id"] = str(values["boot_id"])
    return values
