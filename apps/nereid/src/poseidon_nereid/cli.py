"""Portable offline NEREID CLI: timestamped PGM8, never live video."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from poseidon_acoustic.session import LinuxPiCaptureAdapter, Session, SessionError, canonical, publish
from .video import Observation, ROI, _separate_output, build_index, capture_frames, export_excerpt, file_frames, write_fixture
from .wiper import SimulatedActuator, Wiper


def _review_args(parser):
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--occluded-frame", type=int, action="append", default=[])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NEREID PGM8 offline reference; no biological classifier or live device")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--output-dir", type=Path, required=True)
    fixture = commands.add_parser("fixture")
    fixture.add_argument("--output-dir", type=Path, required=True)
    fixture.add_argument("--count", type=int, default=8)
    capture = commands.add_parser("capture")
    capture.add_argument("--frames-manifest", type=Path, required=True)
    capture.add_argument("--output-dir", type=Path, required=True)
    capture.add_argument("--session-id", required=True)
    capture.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    capture.add_argument("--max-chunks", type=int, default=256)
    index = commands.add_parser("index")
    _review_args(index)
    excerpt = commands.add_parser("excerpt")
    _review_args(excerpt)
    excerpt.add_argument("--observation-id", required=True)
    excerpt.add_argument("--reference-domain", required=True)
    excerpt.add_argument("--reference-epoch", required=True)
    excerpt.add_argument("--start-s", type=float, required=True)
    excerpt.add_argument("--end-s", type=float, required=True)
    excerpt.add_argument("--uncertainty-s", type=float, required=True)
    excerpt.add_argument("--label", choices=("observed_event", "hard_negative", "unknown", "unusable"), required=True)
    excerpt.add_argument("--observer", required=True)
    excerpt.add_argument("--padding-s", type=float, default=0.0)
    excerpt.add_argument("--max-frames", type=int, default=128)
    excerpt.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    commands.add_parser("live", help="always refuses device access")
    args = parser.parse_args(argv)
    try:
        if args.command == "live":
            LinuxPiCaptureAdapter().open()
        elif args.command == "fixture":
            print(write_fixture(args.output_dir, count=args.count))
        elif args.command == "capture":
            source, frames = file_frames(args.frames_manifest)
            session = Session.create(args.output_dir, args.session_id, (source,), max_bytes=args.max_bytes,
                                     max_chunks=args.max_chunks)
            capture_frames(session, source.source_id, frames)
            print(canonical(session.finalize()).decode(), end="")
        elif args.command == "demo":
            args.output_dir.mkdir(parents=True, exist_ok=False)
            source, frames = file_frames(write_fixture(args.output_dir / "input"))
            session = Session.create(args.output_dir / "session", "synthetic-video-demo", (source,))
            capture_frames(session, source.source_id, frames)
            session.finalize()
            index = build_index(session, source.source_id, roi=ROI(2, 2, 8, 6), operator_occluded_frames=(3,))
            publish(args.output_dir, "index.nereid-v1.json", canonical(index))
            observation = Observation("synthetic-independent-interval", source.clock.reference_domain,
                                      source.clock.reference_epoch, 0.6, 1.2, 0.03, "unknown", "synthetic-fixture-generator")
            excerpt = export_excerpt(session, source.source_id, observation, args.output_dir / "excerpt",
                                     roi=ROI(2, 2, 8, 6), operator_occluded_frames=(3,))
            actuator = SimulatedActuator()
            wiper = Wiper(actuator)
            wiper.arm(0.0, operator_enable=True, inhibit_released=True)
            wiper.request(0.0, inhibit_released=True)
            for time_s in (0.25, 0.5, 0.75, 1.0):
                wiper.tick(time_s, inhibit_released=True)
            wiper.stop()
            publish(args.output_dir, "wiper.simulation-v1.json", canonical({"hardware_verified": False,
                    "simulation_only": True, "state": wiper.state, "energized": actuator.energized, "audit": wiper.audit}))
            print(canonical({"frames": len(index["frames"]), "excerpt_frames": len(excerpt["frames"]),
                             "provenance": "synthetic", "hardware_verified": False,
                             "wiper_energized": actuator.energized, "codec": "canonical PGM8 only"}).decode(), end="")
        else:
            session = Session(args.session)
            roi = ROI(*args.roi) if args.roi else None
            options = {"roi": roi, "operator_occluded_frames": tuple(args.occluded_frame)}
            if args.command == "index":
                _separate_output(session.directory, args.output_dir)
                result = build_index(session, args.source_id, **options)
                args.output_dir.mkdir(parents=True, exist_ok=False)
                publish(args.output_dir, "index.nereid-v1.json", canonical(result))
            else:
                observation = Observation(args.observation_id, args.reference_domain, args.reference_epoch,
                                          args.start_s, args.end_s, args.uncertainty_s, args.label, args.observer)
                result = export_excerpt(session, args.source_id, observation, args.output_dir,
                                        padding_s=args.padding_s, max_frames=args.max_frames,
                                        max_bytes=args.max_bytes, **options)
            print(canonical(result).decode(), end="")
        return 0
    except (OSError, SessionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
