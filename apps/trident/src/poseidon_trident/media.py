"""Bounded, streaming validation for stored monitor evidence."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
from typing import BinaryIO
import wave

from poseidon_acoustic.demo import DEMO_SAMPLE_RATE_HZ, _demo_samples
from poseidon_proto import ModelValidationError, RecordingManifest

from .errors import HubError


MAX_WAV_BYTES = 64 * 1024 * 1024
MAX_VIDEO_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024
MAX_WAV_DURATION_S = 1800.0
MAX_CHANNELS = 8
MAX_SAMPLE_RATE_HZ = 384_000
STREAM_CHUNK_BYTES = 1024 * 1024
WAVEFORM_MIN_POINTS = 16
WAVEFORM_MAX_POINTS = 2048
PCM16_SCALE = 32_768.0


@dataclass(frozen=True, slots=True)
class WavInfo:
    byte_count: int
    sha256: str
    duration_s: float
    sample_rate_hz: int
    channel_count: int
    frame_count: int


def parse_manifest(manifest_bytes: bytes) -> RecordingManifest:
    if type(manifest_bytes) is not bytes:
        raise HubError("invalid_manifest", "manifest must be bytes", 400)
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise HubError(
            "manifest_too_large",
            f"manifest exceeds the {MAX_MANIFEST_BYTES}-byte limit",
            413,
        )
    try:
        text = manifest_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise HubError("invalid_manifest", "manifest must be UTF-8 JSON", 400) from exc
    try:
        return RecordingManifest.from_json(text)
    except ModelValidationError as exc:
        raise HubError("invalid_manifest", f"invalid recording manifest: {exc}", 400) from exc


def create_import_package(
    staging_dir: Path,
    wav_stream: BinaryIO,
    manifest_bytes: bytes,
    *,
    _owned_package_name: str | None = None,
    _ownership_checkpoint=None,
) -> tuple[Path, RecordingManifest, WavInfo]:
    """Write and validate one source package without publishing it."""

    manifest = parse_manifest(manifest_bytes)
    if not callable(getattr(wav_stream, "read", None)):
        raise HubError("invalid_wav", "WAV input must be a readable binary stream", 400)
    try:
        if _owned_package_name is None:
            package = Path(tempfile.mkdtemp(prefix="import-", dir=staging_dir))
        else:
            # Only the internal companion path supplies a pre-reserved name.
            # Never accept a client filename or reuse an existing directory.
            suffix = _owned_package_name.removeprefix("companion-")
            if (not _owned_package_name.startswith("companion-") or len(suffix) != 32
                    or any(char not in "0123456789abcdef" for char in suffix)):
                raise HubError("unsafe_workspace", "invalid owned staging identity", 500)
            package = staging_dir / _owned_package_name
            package.mkdir(mode=0o700)
            if _ownership_checkpoint is not None:
                _ownership_checkpoint("directory", package, package.lstat())
    except OSError as exc:
        raise HubError("workspace_unavailable", "cannot stage the recording", 500) from exc
    wav_path = package / "source.wav"
    manifest_path = package / "manifest.json"
    try:
        byte_count, digest = _copy_bounded(
            wav_stream,
            wav_path,
            limit=MAX_WAV_BYTES,
            too_large_code="wav_too_large",
            label="WAV",
            _ownership_checkpoint=_ownership_checkpoint,
        )
        _write_manifest(manifest_path, manifest_bytes, _ownership_checkpoint=_ownership_checkpoint)
        if digest != manifest.wav_sha256:
            raise HubError(
                "wav_hash_mismatch", "WAV SHA-256 does not match the manifest", 400
            )
        header = inspect_wav(wav_path)
        info = WavInfo(
            byte_count=byte_count,
            sha256=digest,
            duration_s=header.duration_s,
            sample_rate_hz=header.sample_rate_hz,
            channel_count=header.channel_count,
            frame_count=header.frame_count,
        )
        os.chmod(wav_path, 0o400)
        os.chmod(manifest_path, 0o400)
        os.chmod(package, 0o700)
        return package, manifest, info
    except Exception:
        if _owned_package_name is None:
            remove_owned_package(package)
        # Registered companion intents use stricter inode/hash-aware cleanup.
        raise


def _copy_bounded(
    source: BinaryIO,
    target: Path,
    *,
    limit: int,
    too_large_code: str,
    label: str,
    _ownership_checkpoint=None,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    try:
        with target.open("xb") as output:
            if _ownership_checkpoint is not None:
                _ownership_checkpoint("file_opened", target, os.fstat(output.fileno()))
            while True:
                try:
                    chunk = source.read(STREAM_CHUNK_BYTES)
                except Exception as exc:
                    raise HubError(
                        f"invalid_{label.lower()}", f"cannot read {label} input", 400
                    ) from exc
                if chunk in (b"", None):
                    if chunk is None:
                        raise HubError(
                            f"invalid_{label.lower()}",
                            f"{label} stream returned no bytes before EOF",
                            400,
                        )
                    break
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise HubError(
                        f"invalid_{label.lower()}",
                        f"{label} stream must return bytes",
                        400,
                    )
                raw = bytes(chunk)
                total += len(raw)
                if total > limit:
                    raise HubError(
                        too_large_code,
                        f"{label} exceeds the {limit}-byte limit",
                        413,
                    )
                output.write(raw)
                digest.update(raw)
            output.flush()
            os.fsync(output.fileno())
            if _ownership_checkpoint is not None:
                _ownership_checkpoint("file_completed", target, os.fstat(output.fileno()))
    except HubError:
        raise
    except OSError as exc:
        raise HubError("workspace_unavailable", f"cannot stage {label} input", 500) from exc
    return total, digest.hexdigest()


def _write_manifest(path: Path, data: bytes, *, _ownership_checkpoint=None) -> None:
    try:
        with path.open("xb") as stream:
            if _ownership_checkpoint is not None:
                _ownership_checkpoint("file_opened", path, os.fstat(stream.fileno()))
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            if _ownership_checkpoint is not None:
                _ownership_checkpoint("file_completed", path, os.fstat(stream.fileno()))
    except OSError as exc:
        raise HubError("workspace_unavailable", "cannot stage the manifest", 500) from exc


def inspect_wav(path: Path) -> WavInfo:
    """Validate the full uncompressed PCM16 data chunk without retaining samples."""

    try:
        byte_count = path.stat().st_size
        reader_context = wave.open(str(path), "rb")
    except (OSError, EOFError, wave.Error) as exc:
        raise HubError("invalid_wav", "WAV header is malformed or unsupported", 400) from exc
    try:
        with reader_context as reader:
            try:
                channel_count = reader.getnchannels()
                sample_width = reader.getsampwidth()
                sample_rate_hz = reader.getframerate()
                frame_count = reader.getnframes()
                compression_type = reader.getcomptype()
            except (EOFError, wave.Error) as exc:
                raise HubError("invalid_wav", "WAV header is malformed", 400) from exc
            if compression_type != "NONE":
                raise HubError("unsupported_wav", "WAV must contain uncompressed PCM audio", 400)
            if sample_width != 2:
                raise HubError("unsupported_wav", "WAV sample width must be 16-bit PCM", 400)
            if type(channel_count) is not int or not 1 <= channel_count <= MAX_CHANNELS:
                raise HubError(
                    "unsupported_wav",
                    f"WAV channel count must be from 1 through {MAX_CHANNELS}",
                    400,
                )
            if type(sample_rate_hz) is not int or not 1 <= sample_rate_hz <= MAX_SAMPLE_RATE_HZ:
                raise HubError(
                    "unsupported_wav",
                    f"WAV sample rate must be from 1 through {MAX_SAMPLE_RATE_HZ} Hz",
                    400,
                )
            if type(frame_count) is not int or frame_count < 0:
                raise HubError("invalid_wav", "WAV declares an invalid frame count", 400)
            duration_s = frame_count / sample_rate_hz
            if duration_s > MAX_WAV_DURATION_S:
                raise HubError(
                    "wav_too_long",
                    f"WAV duration exceeds the {MAX_WAV_DURATION_S:g}-second limit",
                    413,
                )
            block_align = channel_count * sample_width
            remaining = frame_count
            frames_read = 0
            while remaining:
                requested = min(4096, remaining)
                try:
                    raw = reader.readframes(requested)
                except (EOFError, wave.Error) as exc:
                    raise HubError("invalid_wav", "WAV PCM data is malformed", 400) from exc
                if len(raw) % block_align:
                    raise HubError("invalid_wav", "WAV ends with an incomplete PCM frame", 400)
                actual = len(raw) // block_align
                if actual != requested:
                    raise HubError(
                        "invalid_wav",
                        f"WAV PCM data is truncated at frame {frames_read + actual}",
                        400,
                    )
                frames_read += actual
                remaining -= actual
            try:
                extra = reader.readframes(1)
            except (EOFError, wave.Error) as exc:
                raise HubError("invalid_wav", "WAV PCM data is malformed", 400) from exc
            if extra:
                raise HubError(
                    "invalid_wav", "WAV data chunk is not aligned to complete PCM frames", 400
                )
    except OSError as exc:
        raise HubError("invalid_wav", "cannot read WAV data", 400) from exc
    return WavInfo(
        byte_count=byte_count,
        sha256="",
        duration_s=duration_s,
        sample_rate_hz=sample_rate_hz,
        channel_count=channel_count,
        frame_count=frame_count,
    )


def waveform_envelope(path: Path, points: int, expected: WavInfo) -> list[dict]:
    """Stream a min/max PCM16 envelope using frame-aligned buckets."""

    if type(points) is not int or not WAVEFORM_MIN_POINTS <= points <= WAVEFORM_MAX_POINTS:
        raise HubError(
            "invalid_points",
            f"points must be an integer from {WAVEFORM_MIN_POINTS} through {WAVEFORM_MAX_POINTS}",
            400,
        )
    try:
        reader_context = wave.open(str(path), "rb")
    except (OSError, EOFError, wave.Error) as exc:
        raise HubError("stored_wav_invalid", "stored WAV is unavailable or invalid", 500) from exc
    try:
        with reader_context as reader:
            try:
                channels = reader.getnchannels()
                width = reader.getsampwidth()
                rate = reader.getframerate()
                frame_count = reader.getnframes()
                compression = reader.getcomptype()
            except (EOFError, wave.Error) as exc:
                raise HubError("stored_wav_invalid", "stored WAV header is invalid", 500) from exc
            if (
                channels != expected.channel_count
                or rate != expected.sample_rate_hz
                or frame_count != expected.frame_count
                or width != 2
                or compression != "NONE"
            ):
                raise HubError(
                    "stored_wav_invalid", "stored WAV no longer matches its catalog metadata", 500
                )
            if frame_count == 0:
                return []
            bucket_count = min(points, frame_count)
            minima = [32767] * bucket_count
            maxima = [-32768] * bucket_count
            frames_read = 0
            bucket = 0
            while frames_read < frame_count:
                requested = min(4096, frame_count - frames_read)
                try:
                    raw = reader.readframes(requested)
                except (EOFError, wave.Error) as exc:
                    raise HubError("stored_wav_invalid", "stored WAV data is invalid", 500) from exc
                if len(raw) != requested * channels * 2:
                    raise HubError("stored_wav_invalid", "stored WAV data is truncated", 500)
                samples = array("h")
                samples.frombytes(raw)
                if sys.byteorder != "little":
                    samples.byteswap()
                sample_index = 0
                for local_frame in range(requested):
                    absolute_frame = frames_read + local_frame
                    bucket = min(bucket_count - 1, bucket)
                    while (
                        bucket < bucket_count - 1
                        and absolute_frame >= (bucket + 1) * frame_count // bucket_count
                    ):
                        bucket += 1
                    for _ in range(channels):
                        sample = samples[sample_index]
                        sample_index += 1
                        if sample < minima[bucket]:
                            minima[bucket] = sample
                        if sample > maxima[bucket]:
                            maxima[bucket] = sample
                frames_read += requested
            try:
                if reader.readframes(1):
                    raise HubError(
                        "stored_wav_invalid", "stored WAV has unexpected PCM data", 500
                    )
            except (EOFError, wave.Error) as exc:
                raise HubError("stored_wav_invalid", "stored WAV data is invalid", 500) from exc
    except OSError as exc:
        raise HubError("stored_wav_invalid", "cannot read stored WAV", 500) from exc

    buckets: list[dict] = []
    for index in range(bucket_count):
        start_frame = index * frame_count // bucket_count
        end_frame = (index + 1) * frame_count // bucket_count
        buckets.append(
            {
                "start_s": start_frame / expected.sample_rate_hz,
                "end_s": end_frame / expected.sample_rate_hz,
                "min": minima[index] / PCM16_SCALE,
                "max": maxima[index] / PCM16_SCALE,
            }
        )
    return buckets


def stage_video(staging_dir: Path, video_stream: BinaryIO) -> tuple[Path, int, str]:
    if not callable(getattr(video_stream, "read", None)):
        raise HubError("invalid_video", "video input must be a readable binary stream", 400)
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix="video-", suffix=".mp4", dir=staging_dir)
        os.close(descriptor)
        path = Path(raw_path)
        path.unlink()
    except OSError as exc:
        raise HubError("workspace_unavailable", "cannot stage video evidence", 500) from exc
    try:
        byte_count, digest = _copy_bounded(
            video_stream,
            path,
            limit=MAX_VIDEO_BYTES,
            too_large_code="video_too_large",
            label="video",
        )
        _validate_mp4(path, byte_count)
        os.chmod(path, 0o400)
        return path, byte_count, digest
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _validate_mp4(path: Path, byte_count: int) -> None:
    if byte_count < 16:
        raise HubError("invalid_video", "video is not an MP4 container", 400)
    try:
        with path.open("rb") as stream:
            prefix = stream.read(32)
    except OSError as exc:
        raise HubError("invalid_video", "cannot inspect video evidence", 400) from exc
    if len(prefix) < 16:
        raise HubError("invalid_video", "video is not an MP4 container", 400)
    size32, box_type = struct.unpack(">I4s", prefix[:8])
    header_size = 8
    if size32 == 1:
        if len(prefix) < 24:
            raise HubError("invalid_video", "video has a malformed MP4 header", 400)
        box_size = struct.unpack(">Q", prefix[8:16])[0]
        header_size = 16
    elif size32 == 0:
        box_size = byte_count
    else:
        box_size = size32
    if box_type != b"ftyp" or box_size < header_size + 8 or box_size > byte_count:
        raise HubError("invalid_video", "video is not an MP4 container", 400)
    brand_start = header_size
    brand = prefix[brand_start : brand_start + 4]
    if len(brand) != 4 or any(value < 0x20 or value > 0x7E for value in brand):
        raise HubError("invalid_video", "video has an invalid MP4 file type", 400)


def demo_inputs() -> tuple[io.BytesIO, bytes]:
    """Build the existing deterministic marked synthetic demo as import inputs."""

    output = io.BytesIO()
    samples = _demo_samples()
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(DEMO_SAMPLE_RATE_HZ)
        writer.writeframes(samples.tobytes())
    wav_bytes = output.getvalue()
    digest = hashlib.sha256(wav_bytes).hexdigest()
    manifest = RecordingManifest(
        schema_version=1,
        recording_id="synthetic-demo-recording-v1",
        site_id="synthetic-demo-site",
        zone_id="synthetic-demo-zone",
        device_id="synthetic-demo-device",
        started_at="2026-01-01T00:00:00Z",
        provenance="synthetic",
        wav_sha256=digest,
        calibration_status="uncalibrated",
    )
    return io.BytesIO(wav_bytes), (manifest.to_json() + "\n").encode("utf-8")


def remove_owned_package(package: Path) -> None:
    """Remove only the two fixed files in a staging package created by this module."""

    try:
        info = package.lstat()
    except FileNotFoundError:
        return
    except OSError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return
    try:
        entries = {entry.name: entry for entry in package.iterdir()}
    except OSError:
        return
    if set(entries) - {"source.wav", "manifest.json"}:
        return
    for name in ("source.wav", "manifest.json"):
        path = entries.get(name)
        if path is None:
            continue
        try:
            item = path.lstat()
            if stat.S_ISREG(item.st_mode) and not stat.S_ISLNK(item.st_mode):
                path.unlink()
        except OSError:
            return
    try:
        package.rmdir()
    except OSError:
        pass
