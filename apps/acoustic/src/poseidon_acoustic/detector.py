"""Streaming normalized-amplitude detector for PCM16 WAV replay."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import sys
from typing import BinaryIO
import wave

from poseidon_proto import AcousticCandidateEvent, RecordingManifest, canonical_json

from .errors import InputError


DETECTOR_VERSION = "normalized-rms-v1"
MAX_CHANNELS = 8
MAX_SAMPLE_RATE_HZ = 384_000
MAX_WINDOW_MS = 10_000.0
READ_CHUNK_FRAMES = 4_096
PCM16_SCALE = 32_768.0


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    """Validated settings for fixed, non-overlapping analysis windows."""

    threshold: float = 0.2
    window_ms: float = 20.0

    def __post_init__(self) -> None:
        if type(self.threshold) not in (int, float):
            raise InputError("threshold must be a finite number")
        try:
            threshold = float(self.threshold)
        except OverflowError as exc:
            raise InputError("threshold must be a finite number") from exc
        if not math.isfinite(threshold):
            raise InputError("threshold must be a finite number")
        if not 0.0 < threshold <= 1.0:
            raise InputError("threshold must be greater than 0 and at most 1")
        if type(self.window_ms) not in (int, float):
            raise InputError("window-ms must be a finite number")
        try:
            window_ms = float(self.window_ms)
        except OverflowError as exc:
            raise InputError("window-ms must be a finite number") from exc
        if not math.isfinite(window_ms):
            raise InputError("window-ms must be a finite number")
        if not 0.0 < window_ms <= MAX_WINDOW_MS:
            raise InputError(f"window-ms must be greater than 0 and at most {MAX_WINDOW_MS:g}")
        object.__setattr__(self, "threshold", threshold)
        object.__setattr__(self, "window_ms", window_ms)

    def window_frames(self, sample_rate_hz: int) -> int:
        if type(sample_rate_hz) is not int or not 1 <= sample_rate_hz <= MAX_SAMPLE_RATE_HZ:
            raise InputError(
                f"sample rate must be an integer from 1 through {MAX_SAMPLE_RATE_HZ} Hz"
            )
        return max(1, int(round(sample_rate_hz * self.window_ms / 1_000.0)))

    def to_dict(self, sample_rate_hz: int) -> dict[str, object]:
        return {
            "detector_version": DETECTOR_VERSION,
            "threshold_normalized_rms": self.threshold,
            "window_ms": self.window_ms,
            "window_frames": self.window_frames(sample_rate_hz),
        }

    def config_id(self, sample_rate_hz: int) -> str:
        digest = hashlib.sha256(canonical_json(self.to_dict(sample_rate_hz)).encode("utf-8"))
        return f"cfg_{digest.hexdigest()}"


@dataclass(frozen=True, slots=True)
class DetectionResult:
    events: tuple[AcousticCandidateEvent, ...]
    run_id: str
    detector_config_id: str
    detector_config_json: str
    sample_rate_hz: int
    channel_count: int
    frame_count: int


@dataclass(slots=True)
class _WindowStats:
    sums_of_squares: list[int]
    peaks: list[int]
    frame_count: int = 0

    @classmethod
    def empty(cls, channels: int) -> _WindowStats:
        return cls([0] * channels, [0] * channels)


@dataclass(slots=True)
class _EventStats:
    start_frame: int
    end_frame: int
    sums_of_squares: list[int]
    peaks: list[int]
    frame_count: int

    @classmethod
    def from_window(
        cls, start_frame: int, end_frame: int, stats: _WindowStats
    ) -> _EventStats:
        return cls(
            start_frame=start_frame,
            end_frame=end_frame,
            sums_of_squares=stats.sums_of_squares.copy(),
            peaks=stats.peaks.copy(),
            frame_count=stats.frame_count,
        )

    def append_window(self, end_frame: int, stats: _WindowStats) -> None:
        self.end_frame = end_frame
        self.frame_count += stats.frame_count
        for channel, value in enumerate(stats.sums_of_squares):
            self.sums_of_squares[channel] += value
            self.peaks[channel] = max(self.peaks[channel], stats.peaks[channel])


def _event_from_stats(
    manifest: RecordingManifest,
    event_stats: _EventStats,
    *,
    sample_rate_hz: int,
    channel_count: int,
    config_id: str,
    run_id: str,
) -> AcousticCandidateEvent:
    normalized_peak = max(event_stats.peaks) / PCM16_SCALE
    normalized_rms = max(
        math.sqrt(value / event_stats.frame_count) / PCM16_SCALE
        for value in event_stats.sums_of_squares
    )
    identity = canonical_json(
        {
            "run_id": run_id,
            "start_frame": event_stats.start_frame,
            "end_frame": event_stats.end_frame,
        }
    )
    event_id = f"evt_{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
    return AcousticCandidateEvent(
        schema_version=1,
        event_id=event_id,
        recording_id=manifest.recording_id,
        site_id=manifest.site_id,
        zone_id=manifest.zone_id,
        device_id=manifest.device_id,
        event_type="acoustic_candidate",
        source="replay",
        provenance=manifest.provenance,
        start_frame=event_stats.start_frame,
        end_frame=event_stats.end_frame,
        start_time_s=event_stats.start_frame / sample_rate_hz,
        end_time_s=event_stats.end_frame / sample_rate_hz,
        sample_rate_hz=sample_rate_hz,
        channel_count=channel_count,
        normalized_peak_max=normalized_peak,
        normalized_rms_max=normalized_rms,
        amplitude_units="normalized_pcm16_full_scale",
        calibration_status="uncalibrated",
        detector_version=DETECTOR_VERSION,
        detector_config_id=config_id,
        run_id=run_id,
        emission_enabled=False,
    )


def detect_wav(
    wav_source: Path | str | BinaryIO,
    manifest: RecordingManifest,
    config: DetectorConfig,
) -> DetectionResult:
    """Analyze PCM frames from a path or an already-open seekable WAV stream."""

    if not isinstance(manifest, RecordingManifest):
        raise InputError("manifest must be a RecordingManifest")
    if not isinstance(config, DetectorConfig):
        raise InputError("config must be a DetectorConfig")
    if isinstance(wav_source, (str, Path)):
        source: str | BinaryIO = str(Path(wav_source))
        source_label = str(Path(wav_source))
    elif hasattr(wav_source, "read") and hasattr(wav_source, "seek"):
        source = wav_source
        source_label = str(getattr(wav_source, "name", "<open WAV stream>"))
    else:
        raise InputError("WAV source must be a path or seekable binary stream")
    try:
        reader_context = wave.open(source, "rb")
    except (OSError, EOFError, wave.Error) as exc:
        raise InputError(f"cannot open WAV {source_label}: {exc}") from exc

    try:
        with reader_context as reader:
            try:
                channel_count = reader.getnchannels()
                sample_width = reader.getsampwidth()
                sample_rate_hz = reader.getframerate()
                declared_frames = reader.getnframes()
                compression_type = reader.getcomptype()
            except (EOFError, wave.Error) as exc:
                raise InputError(f"malformed WAV header in {source_label}: {exc}") from exc

            if compression_type != "NONE":
                raise InputError("WAV must contain uncompressed PCM audio")
            if sample_width != 2:
                raise InputError("WAV sample width must be 16-bit PCM")
            if type(channel_count) is not int or not 1 <= channel_count <= MAX_CHANNELS:
                raise InputError(f"WAV channel count must be from 1 through {MAX_CHANNELS}")
            if type(sample_rate_hz) is not int or not 1 <= sample_rate_hz <= MAX_SAMPLE_RATE_HZ:
                raise InputError(
                    f"WAV sample rate must be from 1 through {MAX_SAMPLE_RATE_HZ} Hz"
                )
            if type(declared_frames) is not int or declared_frames < 0:
                raise InputError("WAV declares an invalid PCM frame count")

            window_frames = config.window_frames(sample_rate_hz)
            config_json = canonical_json(config.to_dict(sample_rate_hz))
            config_id = config.config_id(sample_rate_hz)
            run_identity = canonical_json(
                {
                    "recording_manifest_fingerprint": manifest.fingerprint(),
                    "detector_config_id": config_id,
                }
            )
            run_id = f"run_{hashlib.sha256(run_identity.encode('utf-8')).hexdigest()}"

            events: list[AcousticCandidateEvent] = []
            window = _WindowStats.empty(channel_count)
            active_event: _EventStats | None = None
            window_start = 0
            frames_read = 0

            def finish_window(window_end: int) -> None:
                nonlocal active_event, window, window_start
                if window.frame_count == 0:
                    return
                rms_max = max(
                    math.sqrt(value / window.frame_count) / PCM16_SCALE
                    for value in window.sums_of_squares
                )
                if rms_max >= config.threshold:
                    if active_event is None:
                        active_event = _EventStats.from_window(window_start, window_end, window)
                    else:
                        active_event.append_window(window_end, window)
                elif active_event is not None:
                    events.append(
                        _event_from_stats(
                            manifest,
                            active_event,
                            sample_rate_hz=sample_rate_hz,
                            channel_count=channel_count,
                            config_id=config_id,
                            run_id=run_id,
                        )
                    )
                    active_event = None
                window = _WindowStats.empty(channel_count)
                window_start = window_end

            remaining = declared_frames
            while remaining:
                requested = min(READ_CHUNK_FRAMES, remaining)
                try:
                    raw = reader.readframes(requested)
                except (EOFError, wave.Error) as exc:
                    raise InputError(f"malformed PCM data in {source_label}: {exc}") from exc
                block_align = channel_count * sample_width
                if len(raw) % block_align != 0:
                    raise InputError("WAV ends with an incomplete PCM frame")
                chunk_frames = len(raw) // block_align
                if chunk_frames != requested:
                    raise InputError(
                        f"WAV PCM data is truncated: expected {declared_frames} frames, "
                        f"read {frames_read + chunk_frames}"
                    )
                samples = array("h")
                samples.frombytes(raw)
                if sys.byteorder != "little":
                    samples.byteswap()

                sample_index = 0
                for _ in range(chunk_frames):
                    for channel in range(channel_count):
                        sample = samples[sample_index]
                        sample_index += 1
                        window.sums_of_squares[channel] += sample * sample
                        window.peaks[channel] = max(window.peaks[channel], abs(sample))
                    window.frame_count += 1
                    frames_read += 1
                    if window.frame_count == window_frames:
                        finish_window(frames_read)
                remaining -= chunk_frames

            try:
                extra = reader.readframes(1)
            except (EOFError, wave.Error) as exc:
                raise InputError(f"malformed PCM data in {source_label}: {exc}") from exc
            if extra:
                raise InputError("WAV data chunk is not aligned to complete PCM frames")
            if window.frame_count:
                finish_window(frames_read)
            if active_event is not None:
                events.append(
                    _event_from_stats(
                        manifest,
                        active_event,
                        sample_rate_hz=sample_rate_hz,
                        channel_count=channel_count,
                        config_id=config_id,
                        run_id=run_id,
                    )
                )

            return DetectionResult(
                events=tuple(events),
                run_id=run_id,
                detector_config_id=config_id,
                detector_config_json=config_json,
                sample_rate_hz=sample_rate_hz,
                channel_count=channel_count,
                frame_count=frames_read,
            )
    except OSError as exc:
        raise InputError(f"cannot read WAV {source_label}: {exc}") from exc
