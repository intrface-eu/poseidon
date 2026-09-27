from __future__ import annotations

from array import array
import hashlib
import io
import sys
import wave

from poseidon_proto import RecordingManifest


def wav_bytes(
    frames: list[tuple[int, ...]],
    *,
    sample_rate: int = 1_000,
    channels: int | None = None,
) -> bytes:
    channel_count = channels if channels is not None else (len(frames[0]) if frames else 1)
    samples = array("h", (sample for frame in frames for sample in frame))
    if sys.byteorder != "little":
        samples.byteswap()
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channel_count)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(samples.tobytes())
    return output.getvalue()


def manifest_bytes(
    wav: bytes,
    *,
    recording_id: str = "recording-1",
    site_id: str = "site-1",
    zone_id: str = "zone-1",
    device_id: str = "device-1",
    provenance: str = "synthetic",
    started_at: str = "2026-01-02T03:04:05Z",
) -> bytes:
    manifest = RecordingManifest(
        schema_version=1,
        recording_id=recording_id,
        site_id=site_id,
        zone_id=zone_id,
        device_id=device_id,
        started_at=started_at,
        provenance=provenance,
        wav_sha256=hashlib.sha256(wav).hexdigest(),
        calibration_status="uncalibrated",
    )
    return (manifest.to_json() + "\n").encode("utf-8")


def active_wav(*, sample_rate: int = 1_000) -> bytes:
    frames = [(0,)] * 20 + [(20_000,)] * 20 + [(0,)] * 20
    return wav_bytes(frames, sample_rate=sample_rate)


def mp4_bytes(payload: bytes = b"monitor-evidence") -> bytes:
    # One valid ISO BMFF file-type box followed by opaque test bytes.
    ftyp = (
        (24).to_bytes(4, "big")
        + b"ftyp"
        + b"isom"
        + (0).to_bytes(4, "big")
        + b"isom"
        + b"mp42"
    )
    return ftyp + payload
