"""Run with python -m poseidon_acoustic.session_cli; no device I/O."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .session import (
    Channel, ClockMap, LinuxPiCaptureAdapter, Session, SessionError, Source, canonical,
    capture_audio, capture_guard, file_sha256, synthetic_audio, wav_blocks,
)


def _clock_args(parser):
    parser.add_argument("--source-domain", required=True)
    parser.add_argument("--reference-domain", default="reference_seconds")
    parser.add_argument("--reference-epoch", required=True)
    parser.add_argument("--source-anchor-s", type=float, default=0.0)
    parser.add_argument("--reference-anchor-s", type=float, default=0.0)
    parser.add_argument("--drift-ppm", type=float, default=0.0,
                        help="source-to-reference mapping scale, not oscillator-fast sign")
    parser.add_argument("--anchor-uncertainty-s", type=float, required=True)
    parser.add_argument("--drift-uncertainty-ppm", type=float, required=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provisional file/synthetic acquisition; hardware-unverified")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--output-dir", type=Path, required=True)
    demo.add_argument("--frames", type=int, default=8000)
    demo.add_argument("--chunk-frames", type=int, default=2000)
    demo.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    capture = commands.add_parser("capture-wav")
    capture.add_argument("--wav", type=Path, required=True)
    capture.add_argument("--output-dir", type=Path, required=True)
    capture.add_argument("--session-id", required=True)
    capture.add_argument("--source-id", required=True)
    capture.add_argument("--provenance", choices=("file", "synthetic"), required=True)
    capture.add_argument("--sample-rate-hz", type=int, required=True)
    capture.add_argument("--channel", action="append", required=True, help="repeat stable channel IDs in WAV order")
    capture.add_argument("--chunk-frames", type=int, default=2000)
    capture.add_argument("--max-frames", type=int, default=100_000_000)
    capture.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    capture.add_argument("--max-chunks", type=int, default=256)
    _clock_args(capture)
    for name in ("recover", "finalize"):
        command = commands.add_parser(name)
        command.add_argument("--session", type=Path, required=True)
    commands.add_parser("live", help="always refuses device access")
    args = parser.parse_args(argv)
    try:
        if args.command == "live":
            LinuxPiCaptureAdapter().open()
        elif args.command == "recover":
            result = Session(args.session).recover()
            print(canonical(result).decode(), end="")
        elif args.command == "finalize":
            print(canonical(Session(args.session).finalize()).decode(), end="")
        elif args.command == "demo":
            source = Source("synthetic-audio", "pcm16-wav", "synthetic",
                            (Channel("pcm-0", "synthetic uncalibrated PCM"),),
                            ClockMap("reference_seconds", "synthetic-session-start", reference_anchor_s=0.25,
                                     drift_ppm=20.0, anchor_uncertainty_s=0.01, drift_uncertainty_ppm=2.0),
                            sample_rate_hz=8000, origin="LCG PCM16 fixture v1; seed=7; not animal audio")
            session = Session.create(args.output_dir, "synthetic-audio-demo", (source,), max_bytes=args.max_bytes)
            capture_audio(session, source.source_id, synthetic_audio(frames=args.frames, chunk_frames=args.chunk_frames))
            print(canonical(session.finalize()).decode(), end="")
        else:
            clock = ClockMap(args.reference_domain, args.reference_epoch, args.source_anchor_s,
                             args.reference_anchor_s, args.drift_ppm, args.anchor_uncertainty_s,
                             args.drift_uncertainty_ppm, source_domain=args.source_domain)
            checksum = file_sha256(args.wav)
            source = Source(args.source_id, "pcm16-wav", args.provenance,
                            tuple(Channel(channel, "operator-declared uncalibrated PCM channel") for channel in args.channel),
                            clock, args.sample_rate_hz, origin="operator-declared PCM16 WAV file", input_sha256=checksum)
            session = Session.create(args.output_dir, args.session_id, (source,),
                                     max_bytes=args.max_bytes, max_chunks=args.max_chunks)
            with capture_guard(session):
                capture_audio(session, source.source_id,
                              wav_blocks(args.wav, sample_rate_hz=args.sample_rate_hz, channels=len(args.channel),
                                         chunk_frames=args.chunk_frames, max_frames=args.max_frames))
                if file_sha256(args.wav) != checksum:
                    raise SessionError("WAV source checksum changed during capture")
            print(canonical(session.finalize()).decode(), end="")
        return 0
    except (OSError, SessionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
