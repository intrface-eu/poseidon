"""Command-line interface for local passive WAV replay."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence, TextIO

from .demo import run_demo
from .detector import DetectorConfig
from .errors import AcousticError
from .replay import replay_to_store
from .store import list_event_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m poseidon_acoustic",
        description="Replay PCM16 WAV files through an uncalibrated normalized-amplitude detector.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay = subparsers.add_parser("replay", help="validate and store one WAV replay")
    replay.add_argument("--wav", type=Path, required=True, help="PCM16 WAV input")
    replay.add_argument("--manifest", type=Path, required=True, help="recording manifest JSON")
    replay.add_argument("--database", type=Path, required=True, help="local SQLite evidence path")
    replay.add_argument("--threshold", type=float, default=0.2, help="normalized RMS threshold")
    replay.add_argument("--window-ms", type=float, default=20.0, help="analysis window in milliseconds")

    events = subparsers.add_parser("events", help="emit stored events as deterministic JSONL")
    events.add_argument("--database", type=Path, required=True, help="existing SQLite evidence path")

    demo = subparsers.add_parser("demo", help="create and replay a marked synthetic WAV")
    demo.add_argument("--output-dir", type=Path, required=True, help="new or empty output directory")
    return parser


def _write_lines(lines: Sequence[str], output: TextIO) -> None:
    for line in lines:
        output.write(line)
        output.write("\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = sys.stdout if stdout is None else stdout
    diagnostics = sys.stderr if stderr is None else stderr
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "replay":
            config = DetectorConfig(arguments.threshold, arguments.window_ms)
            result, outcome = replay_to_store(
                arguments.wav,
                arguments.manifest,
                arguments.database,
                config,
            )
            _write_lines(tuple(event.to_json() for event in result.events), output)
            diagnostics.write(
                f"stored replay {outcome.run_id}: {outcome.event_count} event(s); "
                f"already_present={str(outcome.already_present).lower()}\n"
            )
            return 0
        if arguments.command == "events":
            _write_lines(list_event_json(arguments.database), output)
            return 0
        if arguments.command == "demo":
            demo_result = run_demo(arguments.output_dir)
            _write_lines(tuple(event.to_json() for event in demo_result.detection.events), output)
            diagnostics.write(f"synthetic demo output: {demo_result.output_dir}\n")
            return 0
        parser.error(f"unsupported command: {arguments.command}")
    except AcousticError as exc:
        diagnostics.write(f"error: {exc}\n")
        return 2
    except BrokenPipeError:
        return 0
    return 2
