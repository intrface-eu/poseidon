"""Deterministic synthetic proposal vectors; no sensor or calibration evidence.

Run with Python stdlib only. This is fixture construction, not an ingest codec.
JSON boot IDs are decimal strings; CBOR boot IDs are unsigned integers.
"""
from __future__ import annotations

import json
from pathlib import Path

DESTINATION = Path(__file__).resolve().parents[1] / "fixtures/reef-telemetry-v1.json"


def scalar(value: int | None) -> bytes:
    if value is None:
        return b"\xf6"
    major = 0 if value >= 0 else 1
    argument = value if value >= 0 else -1 - value
    if argument < 24:
        return bytes([(major << 5) | argument])
    for size, info in ((1, 24), (2, 25), (4, 26), (8, 27)):
        if argument < 1 << (size * 8):
            return bytes([(major << 5) | info]) + argument.to_bytes(size, "big")
    raise ValueError("fixture integer outside CBOR uint64 argument")


def wire(fields: list[int | str | None]) -> bytes:
    return b"\x8d" + b"".join(scalar(int(value) if isinstance(value, str) else value) for value in fields)


def fixture_document() -> dict:
    base = [1, "1", 0, 0, 0, None, None, None, 0, 0, None, 2, None]
    valid = []
    invalid = []

    def good(name: str, fields: list) -> None:
        valid.append({"name": name, "fields": fields, "hex": wire(fields).hex()})

    def bad(name: str, payload: bytes) -> None:
        invalid.append({"name": name, "hex": payload.hex()})

    def changed(index: int, value: int | str | None, source: list | None = None) -> list:
        fields = list(base if source is None else source)
        fields[index] = value
        return fields

    good("unsynchronized_missing", base)
    good("rtc_raw_temperature", [1, "24", 23, 24, 1, 1700000000, 12800, 19000, 0, 1, 12345, 0, None])
    good("network_calibrated_temperature", [1, "256", 256, 65536, 2, 1700000060, 12300, 0, 1, 1, -125, 1, 7])
    good("calibrated_salinity", [1, "65536", 65536, 4294967295, 2, 4294967295, 11800, None, 2, 2, 35000, 1, 8])
    good("calibrated_dissolved_oxygen", [1, "4294967296", 1, 1, 1, 0, 0, 65535, 2, 3, 8500, 1, 65535])
    good("all_maximum_unsigned_and_signed", [1, "18446744073709551615", 4294967295, 4294967295, 2, 4294967295, 65535, 65535, 2, 3, 2147483647, 1, 65535])
    good("minimum_signed", [1, "18446744073709551615", 4294967295, 4294967295, 2, 4294967295, 65535, 65535, 2, 3, -2147483648, 1, 65535])
    for kind in (1, 2, 3):
        good(f"invalid_sensor_{kind}", changed(9, kind))
    for value in (0, 23, 24, 255, 256, 65535, 65536, -1, -24, -25, -256, -257, -65536, -65537):
        fields = list(base)
        fields[9:13] = [1, value, 0, None]
        good(f"raw_integer_{str(value).replace('-', 'minus_')}", fields)

    bad("empty", b"")
    bad("oversize_65", bytes(65))
    bad("trailing", wire(base) + b"\x00")
    bad("indefinite_array", b"\x9f" + wire(base)[1:] + b"\xff")
    bad("nonminimal_array_length", b"\x98\x0d" + wire(base)[1:])
    for prefix, name in ((b"\x8c", "short_array"), (b"\x8e", "long_array"), (b"\xa0", "map"), (b"\xc0", "tag")):
        bad(name, prefix + wire(base)[1:])
    for index, value, name in (
        (0, 2, "version"), (0, None, "null_version"), (1, "0", "zero_boot"),
        (1, -1, "negative_boot"), (1, None, "null_boot"),
        (2, -1, "negative_sequence"), (2, 4294967296, "sequence_overflow"),
        (3, -1, "negative_uptime"), (3, 4294967296, "uptime_overflow"),
        (4, 3, "clock_enum"), (4, 256, "clock_enum_narrowing"),
        (4, 1, "synced_null_time"), (5, 1, "unsynced_has_time"),
        (6, 65536, "battery_overflow"), (6, -1, "negative_battery"),
        (7, 65536, "solar_overflow"), (7, -1, "negative_solar"),
        (8, 3, "power_enum"), (8, 256, "power_enum_narrowing"),
        (9, 4, "sensor_enum"), (9, 256, "sensor_enum_narrowing"),
        (10, 0, "none_has_value"), (11, 0, "none_is_raw"),
        (11, 1, "none_is_calibrated"), (11, 3, "quality_enum"),
        (11, 256, "quality_enum_narrowing"), (12, 1, "none_has_calibration"),
        (12, 65536, "calibration_overflow"),
    ):
        bad(name, wire(changed(index, value)))
    calibrated = valid[2]["fields"]
    for index, value, name in (
        (5, 4294967296, "utc_overflow"), (5, -1, "negative_utc"),
        (10, 2147483648, "sensor_positive_overflow"), (10, -2147483649, "sensor_negative_overflow"),
        (10, None, "calibrated_null_value"), (12, None, "calibrated_null_id"),
        (12, 0, "calibrated_zero_id"), (12, -1, "negative_calibration"),
        (11, 0, "raw_has_calibration"), (11, 2, "invalid_has_value"),
    ):
        bad(name, wire(changed(index, value, calibrated)))
    raw = list(base)
    raw[9:13] = [1, None, 0, None]
    bad("raw_null_value", wire(raw))
    for token, name in ((b"\xf4", "boolean"), (b"\xf5", "true"), (b"\xf7", "undefined"),
                        (b"\xfa\x3f\x80\x00\x00", "float"), (b"\xc0\x01", "tagged_scalar"),
                        (b"\x61\x31", "text"), (b"\x41\x01", "bytes"), (b"\x80", "nested_array"),
                        (b"\x1c", "reserved_integer"), (b"\x1f", "indefinite_integer"),
                        (b"\x18\x01", "nonminimal_u8"), (b"\x19\x00\x01", "nonminimal_u16"),
                        (b"\x1a\x00\x00\x00\x01", "nonminimal_u32"),
                        (b"\x1b\x00\x00\x00\x00\x00\x00\x00\x01", "nonminimal_u64")):
        bad(name, b"\x8d" + token + wire(base)[2:])
    bad("nonminimal_negative", b"\x8d" + b"".join(scalar(x) for x in [1, 1, 0, 0, 0, None, None, None, 0, 1]) + b"\x38\x00\x00\xf6")
    return {
        "profile": "reef-telemetry-cbor-v1-proposal",
        "status": "implementation_input_pending_shared_contract_review",
        "synthetic": True,
        "boot_id_json": "canonical decimal string; CBOR uint64 on wire",
        "calibration_note": "Synthetic IDs are not a calibration registry or verified calibration evidence.",
        "max_payload_bytes": 64,
        "field_names": ["version", "boot_id", "sequence", "uptime_s", "clock_quality", "observed_at_unix_s", "battery_mv", "solar_mv", "power_mode", "sensor_kind", "sensor_value", "sensor_quality", "calibration_id"],
        "valid": valid,
        "invalid": invalid,
    }


if __name__ == "__main__":
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(json.dumps(fixture_document(), indent=2) + "\n", encoding="utf-8")
