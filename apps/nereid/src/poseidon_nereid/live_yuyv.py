"""Pure YUYV row validation. No device, decoder, clock mapping or capture imports."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

MAX_PIXELS = 1_048_576
MAX_BYTES = 8 * 1024 * 1024
UINT32_MAX = 2**32 - 1
TIMESTAMP_MASK = 0xE000
TIMESTAMP_UNKNOWN = 0
TIMESTAMP_MONOTONIC = 0x2000
TIMESTAMP_SOURCE_MASK = 0x70000
TIMESTAMP_EOF = 0
TIMESTAMP_SOE = 0x10000
BUFFER_ERROR = 0x40
FIELD_NONE = 1


class YUYVError(ValueError):
    pass


def _integer(value: int, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise YUYVError(f"{name} outside integer bounds")
    return value


@dataclass(frozen=True)
class YUYVLayout:
    width: int
    height: int
    bytesperline: int
    sizeimage: int
    mapped_length: int
    bytesused: int
    max_payload_bytes: int

    def __post_init__(self) -> None:
        _integer(self.width, "width", 2, MAX_PIXELS)
        _integer(self.height, "height", 1, MAX_PIXELS)
        if self.width % 2 or self.width * self.height > MAX_PIXELS:
            raise YUYVError("YUYV requires even width within pixel cap")
        _integer(self.max_payload_bytes, "payload cap", 1, MAX_BYTES)
        _integer(self.bytesperline, "stride", self.width * 2, MAX_BYTES)
        _integer(self.mapped_length, "mapped length", 1, MAX_BYTES)
        _integer(self.sizeimage, "sizeimage", self.required_bytes, self.mapped_length)
        _integer(self.bytesused, "bytesused", self.required_bytes, self.sizeimage)
        if self.payload_bytes > self.max_payload_bytes:
            raise YUYVError("active payload exceeds plan cap")

    @property
    def required_bytes(self) -> int:
        return (self.height - 1) * self.bytesperline + self.width * 2

    @property
    def payload_bytes(self) -> int:
        return self.width * self.height * 2

    @property
    def padding_removed(self) -> bool:
        return self.bytesused != self.payload_bytes or self.bytesperline != self.width * 2


@dataclass(frozen=True)
class PackedYUYV:
    payload: bytes
    payload_sha256: str
    layout: YUYVLayout
    operation: str = "active-yuyv-rows-chroma-unchanged"
    full_kernel_buffer_byte_identical: bool = False


def copy_active_rows(buffer: bytes | bytearray | memoryview, layout: YUYVLayout) -> PackedYUYV:
    """Copy before a caller requeues/reuses its buffer. Never return a view."""
    if type(layout) is not YUYVLayout:
        raise YUYVError("validated YUYVLayout required")
    if not isinstance(buffer, (bytes, bytearray, memoryview)):
        raise YUYVError("byte buffer required")
    view = memoryview(buffer)
    if not view.c_contiguous or view.itemsize != 1 or view.nbytes < layout.bytesused or view.nbytes > layout.mapped_length:
        raise YUYVError("buffer length/layout mismatch")
    view = view.cast("B")
    row = layout.width * 2
    payload = b"".join(bytes(view[y * layout.bytesperline:y * layout.bytesperline + row]) for y in range(layout.height))
    return PackedYUYV(payload, sha256(payload).hexdigest(), layout)


def sequence_step(previous: int | None, current: int) -> bool:
    """Return explicit uint32 wrap; gaps, repeats and resets stop the generation."""
    _integer(current, "sequence", 0, UINT32_MAX)
    if previous is None:
        return False
    _integer(previous, "previous sequence", 0, UINT32_MAX)
    if current != (previous + 1) & UINT32_MAX:
        raise YUYVError("driver sequence discontinuity; physical loss remains unknown")
    return previous == UINT32_MAX


def raw_timestamp(*, flags: int, field: int, seconds: int, microseconds: int,
                  valid: bool, previous_flags: int | None = None) -> dict:
    _integer(flags, "flags", 0, UINT32_MAX)
    if type(valid) is not bool or field != FIELD_NONE or type(field) is not int or flags & BUFFER_ERROR:
        raise YUYVError("invalid/error/interlaced frame")
    domain, source = flags & TIMESTAMP_MASK, flags & TIMESTAMP_SOURCE_MASK
    if domain not in (TIMESTAMP_UNKNOWN, TIMESTAMP_MONOTONIC) or source not in (TIMESTAMP_EOF, TIMESTAMP_SOE):
        raise YUYVError("unsupported timestamp domain/source")
    if previous_flags is not None:
        _integer(previous_flags, "previous flags", 0, UINT32_MAX)
        if flags & (TIMESTAMP_MASK | TIMESTAMP_SOURCE_MASK) != previous_flags & (TIMESTAMP_MASK | TIMESTAMP_SOURCE_MASK):
            raise YUYVError("timestamp domain/source changed")
    if valid:
        _integer(seconds, "timestamp seconds", 0, 2**63 - 1)
        _integer(microseconds, "timestamp microseconds", 0, 999999)
    return {"raw_flags": flags, "field": field, "timestamp_valid": valid,
            "timestamp_seconds": seconds if valid else None,
            "timestamp_microseconds": microseconds if valid else None,
            "timestamp_domain_flags": domain, "timestamp_source_flags": source,
            "timestamp_domain": "monotonic" if domain == TIMESTAMP_MONOTONIC else "unknown",
            "timestamp_source": "soe" if source == TIMESTAMP_SOE else "eof",
            "physical_exposure_start": None, "physical_exposure_end": None,
            "physical_uncertainty_s": None, "utc": None}
