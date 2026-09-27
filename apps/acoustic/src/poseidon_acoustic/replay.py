"""Manifest-bound WAV replay orchestration."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO

from poseidon_proto import ModelValidationError, RecordingManifest

from .detector import DetectionResult, DetectorConfig, detect_wav
from .errors import InputError
from .store import SaveOutcome, save_replay


HASH_CHUNK_BYTES = 1_048_576


def load_manifest(manifest_path: Path | str) -> RecordingManifest:
    path = Path(manifest_path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InputError(f"cannot read manifest {path}: {exc}") from exc
    try:
        return RecordingManifest.from_json(text)
    except ModelValidationError as exc:
        raise InputError(f"invalid manifest {path}: {exc}") from exc


def _hash_open_file(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(HASH_CHUNK_BYTES)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def replay_to_store(
    wav_path: Path | str,
    manifest_path: Path | str,
    database_path: Path | str,
    config: DetectorConfig | None = None,
) -> tuple[DetectionResult, SaveOutcome]:
    """Validate all source bytes, detect candidates, then atomically store the run."""

    detector_config = DetectorConfig() if config is None else config
    if not isinstance(detector_config, DetectorConfig):
        raise InputError("config must be a DetectorConfig")
    manifest = load_manifest(manifest_path)
    path = Path(wav_path)
    try:
        with path.open("rb") as stream:
            before_stat = os.fstat(stream.fileno())
            first_hash = _hash_open_file(stream)
            if first_hash != manifest.wav_sha256:
                raise InputError(
                    f"WAV SHA-256 does not match manifest: expected {manifest.wav_sha256}, "
                    f"got {first_hash}"
                )
            stream.seek(0)
            result = detect_wav(stream, manifest, detector_config)
            stream.seek(0)
            second_hash = _hash_open_file(stream)
            after_stat = os.fstat(stream.fileno())
    except InputError:
        raise
    except (OSError, ValueError) as exc:
        raise InputError(f"cannot read WAV {path}: {exc}") from exc

    stable_identity = (
        before_stat.st_dev,
        before_stat.st_ino,
        before_stat.st_size,
        before_stat.st_mtime_ns,
    ) == (
        after_stat.st_dev,
        after_stat.st_ino,
        after_stat.st_size,
        after_stat.st_mtime_ns,
    )
    if not stable_identity or second_hash != first_hash:
        raise InputError(f"WAV changed while it was being replayed: {path}")
    outcome = save_replay(database_path, manifest, result)
    return result, outcome
