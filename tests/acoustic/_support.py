from __future__ import annotations

from array import array
import hashlib
from pathlib import Path
import sys
import wave

from poseidon_proto import RecordingManifest


def write_pcm16_wav(
    path: Path,
    frames: list[tuple[int, ...]],
    *,
    sample_rate: int = 1_000,
    channels: int | None = None,
) -> None:
    channel_count = channels if channels is not None else (len(frames[0]) if frames else 1)
    samples = array("h", (sample for frame in frames for sample in frame))
    if sys.byteorder != "little":
        samples.byteswap()
    with path.open("xb") as stream:
        with wave.open(stream, "wb") as writer:
            writer.setnchannels(channel_count)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes(samples.tobytes())


def write_pcm8_wav(path: Path, samples: bytes, *, sample_rate: int = 1_000) -> None:
    with path.open("xb") as stream:
        with wave.open(stream, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(1)
            writer.setframerate(sample_rate)
            writer.writeframes(samples)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_for(
    wav_path: Path,
    *,
    recording_id: str = "recording-1",
    site_id: str = "site-1",
    zone_id: str = "zone-1",
    device_id: str = "device-1",
    provenance: str = "synthetic",
) -> RecordingManifest:
    return RecordingManifest(
        schema_version=1,
        recording_id=recording_id,
        site_id=site_id,
        zone_id=zone_id,
        device_id=device_id,
        started_at="2026-01-02T03:04:05Z",
        provenance=provenance,
        wav_sha256=file_sha256(wav_path),
        calibration_status="uncalibrated",
    )


def write_manifest(path: Path, manifest: RecordingManifest) -> None:
    path.write_text(manifest.to_json() + "\n", encoding="utf-8")


def mono_windows(*amplitudes: int, frames_per_window: int = 20) -> list[tuple[int, ...]]:
    return [
        (amplitude,)
        for amplitude in amplitudes
        for _ in range(frames_per_window)
    ]
