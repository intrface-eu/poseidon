"""Bounded synthetic sine generation and whole-buffer attenuation, files only.

All numeric limits are software test envelopes, not biological/acoustic limits.
Normalized peak/RMS values have no underwater SPL interpretation.
"""

from dataclasses import dataclass, field
import math
from pathlib import Path
import struct
from typing import Iterable
import wave

MAX_SAMPLE_RATE_HZ = 96_000
MAX_SAMPLES = 960_000
MAX_DURATION_SECONDS = 10
PROVENANCE = "synthetic sine; software test only; uncalibrated normalized samples"


def _number(value: object, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and in [{low}, {high}]")
    return float(value)


def _sample_rate(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SAMPLE_RATE_HZ:
        raise ValueError("invalid sample_rate_hz")
    return value


@dataclass(frozen=True)
class SignalSpec:
    sample_rate_hz: int = 8_000
    sample_count: int = 2_000
    frequency_hz: float = 440.0
    amplitude: float = 0.2

    def __post_init__(self) -> None:
        _sample_rate(self.sample_rate_hz)
        if type(self.sample_count) is not int or not 1 <= self.sample_count <= MAX_SAMPLES:
            raise ValueError("invalid sample_count")
        if self.sample_count > self.sample_rate_hz * MAX_DURATION_SECONDS:
            raise ValueError("duration exceeds software test envelope")
        frequency = _number(self.frequency_hz, "frequency_hz", 0, self.sample_rate_hz / 2)
        if not 0 < frequency < self.sample_rate_hz / 2:
            raise ValueError("frequency must be positive and below Nyquist")
        _number(self.amplitude, "amplitude", 0, 1)

    @property
    def reserved_duration_ms(self) -> int:
        """Round up, never reserve less time than the WAV contains."""
        return (self.sample_count * 1_000 + self.sample_rate_hz - 1) // self.sample_rate_hz


def sine_samples(spec: SignalSpec) -> tuple[float, ...]:
    spec.__post_init__()
    return tuple(
        spec.amplitude * math.sin(2 * math.pi * spec.frequency_hz * i / spec.sample_rate_hz)
        for i in range(spec.sample_count)
    )


def _bounded_samples(samples: Iterable[float]) -> tuple[float, ...]:
    result = []
    for sample in samples:
        if len(result) >= MAX_SAMPLES:
            raise ValueError("too many samples")
        result.append(_number(sample, "sample", -1, 1))
    if not result:
        raise ValueError("empty samples")
    return tuple(result)


def _levels(samples: tuple[float, ...]) -> tuple[float, float]:
    return max(abs(x) for x in samples), math.sqrt(math.fsum(x * x for x in samples) / len(samples))


@dataclass(frozen=True)
class LimitedSignal:
    samples: tuple[float, ...]
    peak_limit: float
    rms_limit: float
    gain: float
    simulation_only: bool = field(default=True, init=False)
    physical_output_enabled: bool = field(default=False, init=False)

    @property
    def peak(self) -> float:
        return _levels(self.samples)[0]

    @property
    def rms(self) -> float:
        return _levels(self.samples)[1]


def limit_samples(samples: Iterable[float], *, peak_limit: float = 0.25, rms_limit: float = 0.15) -> LimitedSignal:
    """Apply one non-amplifying gain to the entire buffer; not a live limiter."""
    peak_limit = _number(peak_limit, "peak_limit", 0, 1)
    rms_limit = _number(rms_limit, "rms_limit", 0, peak_limit)
    values = _bounded_samples(samples)
    peak, rms = _levels(values)
    gain = min(1.0, peak_limit / peak if peak else 1.0, rms_limit / rms if rms else 1.0)
    # One ULP inward avoids a rounding overshoot at a nonzero limiting boundary.
    if 0 < gain < 1:
        gain = math.nextafter(gain, 0.0)
    return LimitedSignal(tuple(x * gain for x in values), peak_limit, rms_limit, gain)


def export_wav(path: str | Path, signal: LimitedSignal, *, sample_rate_hz: int) -> dict:
    """Create a new mono PCM16 file, never open an existing file/device for output.

    PCM conversion truncates toward zero, so quantization cannot raise peak/RMS.
    A partial file may remain on disk failure; no report is returned on failure.
    """
    _sample_rate(sample_rate_hz)
    values = _bounded_samples(signal.samples)
    if len(values) > sample_rate_hz * MAX_DURATION_SECONDS:
        raise ValueError("duration exceeds software test envelope")
    peak_limit = _number(signal.peak_limit, "peak_limit", 0, 1)
    rms_limit = _number(signal.rms_limit, "rms_limit", 0, peak_limit)
    _number(signal.gain, "gain", 0, 1)
    peak, rms = _levels(values)
    if peak > peak_limit or rms > rms_limit:
        raise ValueError("signal exceeds its declared digital limits")
    # Exclusive creation refuses existing regular files, symlinks, and devices.
    with Path(path).open("xb") as output:
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate_hz)
            wav.writeframes(b"".join(struct.pack("<h", int(x * 32767)) for x in values))
    return {
        "simulation_only": True,
        "physical_output_enabled": False,
        "provenance": "synthetic/offline normalized samples; not a field recording",
        "calibration_status": "uncalibrated; digital amplitude is not underwater SPL",
        "sample_rate_hz": sample_rate_hz,
        "sample_count": len(values),
        "duration_seconds": len(values) / sample_rate_hz,
        "normalized_peak": peak,
        "normalized_rms": rms,
        "peak_limit": peak_limit,
        "rms_limit": rms_limit,
        "gain": signal.gain,
        "pcm_scale": 32767,
    }
