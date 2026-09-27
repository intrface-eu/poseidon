"""Deterministic silent synthetic input for local passive replay."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
import wave

from poseidon_proto import RecordingManifest

from .detector import DetectorConfig, DetectionResult
from .errors import DemoError
from .replay import replay_to_store
from .store import SaveOutcome


DEMO_SAMPLE_RATE_HZ = 8_000
DEMO_WINDOW_FRAMES = 160
DEMO_ARTIFACT_NAMES = (
    "synthetic.wav",
    "recording-manifest.json",
    "evidence.sqlite3",
    "events.ndjson",
)


@dataclass(frozen=True, slots=True)
class DemoResult:
    output_dir: Path
    detection: DetectionResult
    save: SaveOutcome


def _prepare_output_dir(output_dir: Path) -> None:
    if output_dir.is_symlink():
        raise DemoError(f"demo output directory must not be a symbolic link: {output_dir}")
    if output_dir.exists():
        if not output_dir.is_dir():
            raise DemoError(f"demo output path is not a directory: {output_dir}")
        try:
            if any(output_dir.iterdir()):
                raise DemoError(f"demo output directory is not empty: {output_dir}")
        except OSError as exc:
            raise DemoError(f"cannot inspect demo output directory {output_dir}: {exc}") from exc
        return
    parent = output_dir.parent
    if not parent.exists() or not parent.is_dir():
        raise DemoError(f"demo output parent directory does not exist: {parent}")
    try:
        output_dir.mkdir()
    except OSError as exc:
        raise DemoError(f"cannot create demo output directory {output_dir}: {exc}") from exc


def _demo_samples() -> array:
    samples = array("h")
    # Ten 20 ms windows: quiet, burst, quiet gap, burst, quiet.
    sections = (
        (2, 0),
        (2, 20_000),
        (2, 0),
        (2, 20_000),
        (2, 0),
    )
    phase = 1
    for window_count, amplitude in sections:
        for _ in range(window_count * DEMO_WINDOW_FRAMES):
            samples.append(amplitude * phase if amplitude else 0)
            phase *= -1
    return samples


def _write_demo_wav(path: Path) -> None:
    samples = _demo_samples()
    if sys.byteorder != "little":
        samples.byteswap()
    try:
        with path.open("xb") as stream:
            with wave.open(stream, "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(DEMO_SAMPLE_RATE_HZ)
                writer.writeframes(samples.tobytes())
    except (OSError, wave.Error) as exc:
        raise DemoError(f"cannot write synthetic WAV {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1_048_576)
                if not chunk:
                    return digest.hexdigest()
                digest.update(chunk)
    except OSError as exc:
        raise DemoError(f"cannot hash synthetic WAV {path}: {exc}") from exc


def run_demo(output_dir: Path | str) -> DemoResult:
    """Create a marked synthetic WAV, manifest, evidence database, and JSONL export."""

    directory = Path(output_dir)
    _prepare_output_dir(directory)
    wav_path = directory / DEMO_ARTIFACT_NAMES[0]
    manifest_path = directory / DEMO_ARTIFACT_NAMES[1]
    database_path = directory / DEMO_ARTIFACT_NAMES[2]
    events_path = directory / DEMO_ARTIFACT_NAMES[3]

    _write_demo_wav(wav_path)
    manifest = RecordingManifest(
        schema_version=1,
        recording_id="synthetic-demo-recording-v1",
        site_id="synthetic-demo-site",
        zone_id="synthetic-demo-zone",
        device_id="synthetic-demo-device",
        started_at="2026-01-01T00:00:00Z",
        provenance="synthetic",
        wav_sha256=_sha256(wav_path),
        calibration_status="uncalibrated",
    )
    try:
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(manifest.to_json())
            stream.write("\n")
    except OSError as exc:
        raise DemoError(f"cannot write demo manifest {manifest_path}: {exc}") from exc

    detection, save = replay_to_store(
        wav_path,
        manifest_path,
        database_path,
        DetectorConfig(),
    )
    try:
        with events_path.open("x", encoding="utf-8", newline="\n") as stream:
            for event in detection.events:
                stream.write(event.to_json())
                stream.write("\n")
    except OSError as exc:
        raise DemoError(f"cannot write demo event export {events_path}: {exc}") from exc
    return DemoResult(directory, detection, save)
