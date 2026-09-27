"""Private draft REEF scalar CBOR profile. Not a published platform contract."""
from dataclasses import asdict, dataclass

MAX_PAYLOAD_BYTES = 64


class Rejected(ValueError):
    """A bounded, non-secret reason suitable for a local health counter."""


@dataclass(frozen=True)
class Telemetry:
    version: int
    boot_id: int
    sequence: int
    uptime_s: int
    clock_quality: int
    observed_at_unix_s: int | None
    battery_mv: int | None
    solar_mv: int | None
    power_mode: int
    sensor_kind: int
    sensor_value: int | None
    sensor_quality: int
    calibration_id: int | None

    def validate(self):
        def integer(value, low, high):
            if type(value) is not int or not low <= value <= high:
                raise Rejected("wire_field_range")

        integer(self.version, 1, 1)
        integer(self.boot_id, 1, 2**64 - 1)
        for value in (self.sequence, self.uptime_s):
            integer(value, 0, 2**32 - 1)
        integer(self.clock_quality, 0, 2)
        if self.clock_quality == 0:
            if self.observed_at_unix_s is not None:
                raise Rejected("unsynchronized_observed_time")
        else:
            integer(self.observed_at_unix_s, 0, 2**32 - 1)
        for value in (self.battery_mv, self.solar_mv):
            if value is not None:
                integer(value, 0, 65535)
        integer(self.power_mode, 0, 2)
        integer(self.sensor_kind, 0, 3)
        integer(self.sensor_quality, 0, 2)
        if self.sensor_value is not None:
            integer(self.sensor_value, -(2**31), 2**31 - 1)
        if self.calibration_id is not None:
            integer(self.calibration_id, 1, 65535)
        if self.sensor_kind == 0 and self.sensor_quality != 2:
            raise Rejected("none_sensor_quality")
        if self.sensor_kind == 0 or self.sensor_quality == 2:
            if self.sensor_value is not None or self.calibration_id is not None:
                raise Rejected("invalid_sensor_fields")
        elif self.sensor_quality == 0:
            if self.sensor_value is None or self.calibration_id is not None:
                raise Rejected("raw_sensor_fields")
        elif self.sensor_value is None or self.calibration_id is None:
            raise Rejected("calibrated_sensor_fields")
        return self


def decode_payload(data: bytes) -> Telemetry:
    if type(data) is not bytes or not 1 <= len(data) <= MAX_PAYLOAD_BYTES:
        raise Rejected("wire_size")
    if data[0] != 0x8D:
        raise Rejected("wire_array")
    offset = 1
    values = []
    for _ in range(13):
        if offset >= len(data):
            raise Rejected("wire_truncated")
        initial = data[offset]
        offset += 1
        if initial == 0xF6:
            values.append(None)
            continue
        major, info = initial >> 5, initial & 31
        if major not in (0, 1) or info > 27:
            raise Rejected("wire_scalar")
        if info < 24:
            value = info
        else:
            width = 1 << (info - 24)
            if offset + width > len(data):
                raise Rejected("wire_truncated")
            value = int.from_bytes(data[offset:offset + width], "big")
            offset += width
            if value < {1: 24, 2: 256, 4: 65536, 8: 2**32}[width]:
                raise Rejected("wire_noncanonical")
        values.append(value if major == 0 else -1 - value)
    if offset != len(data):
        raise Rejected("wire_trailing")
    return Telemetry(*values).validate()


def encode_payload(telemetry: Telemetry) -> bytes:
    telemetry.validate()
    data = bytearray([0x8D])
    for value in asdict(telemetry).values():
        if value is None:
            data.append(0xF6)
            continue
        major = 0 if value >= 0 else 0x20
        number = value if value >= 0 else -1 - value
        if number < 24:
            data.append(major | number)
        else:
            for width, info in ((1, 24), (2, 25), (4, 26), (8, 27)):
                if number < 1 << (width * 8):
                    data.append(major | info)
                    data.extend(number.to_bytes(width, "big"))
                    break
    if len(data) > MAX_PAYLOAD_BYTES:
        raise Rejected("wire_size")
    return bytes(data)
