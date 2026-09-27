"""Owned local MP4/H264 fixture, decode, index and independent excerpt CLI."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import sys

from poseidon_acoustic.session import SessionError, canonical, publish
from .codec import DecodeLimits, build_codec_index, decode_file, export_codec_excerpt, synthetic_fixture
from .video import Observation, _separate_output


def _limits(parser):
    defaults = asdict(DecodeLimits())
    for name in ("max_input_bytes", "max_streams", "max_frames", "max_dimension", "max_pixels",
                 "max_duration_s", "max_storage_bytes", "timeout_s", "max_rss_bytes"):
        parser.add_argument("--" + name.replace("_", "-"), type=float if name == "timeout_s" else int,
                            default=defaults[name])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local recorded MP4/avc1 H264 only. Software evidence, no live devices or biological classifier.")
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixture", help="real libx264 encoder; six explicitly SYNTHETIC VFR/B frames")
    fixture.add_argument("--output-dir", type=Path, required=True)
    _limits(fixture)
    decode = commands.add_parser("decode")
    decode.add_argument("--input", type=Path, required=True)
    decode.add_argument("--declaration", type=Path, required=True)
    decode.add_argument("--output-dir", type=Path, required=True)
    decode.add_argument("--session-id", required=True)
    _limits(decode)
    index = commands.add_parser("index")
    index.add_argument("--bundle", type=Path, required=True)
    index.add_argument("--output-dir", type=Path, required=True)
    excerpt = commands.add_parser("excerpt")
    excerpt.add_argument("--bundle", type=Path, required=True)
    excerpt.add_argument("--output-dir", type=Path, required=True)
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
    args = parser.parse_args(argv)
    try:
        if args.command in {"fixture", "decode"}:
            limits = DecodeLimits(**{name: getattr(args, name) for name in asdict(DecodeLimits())})
            if args.command == "fixture":
                result = synthetic_fixture(args.output_dir, limits=limits)
            else:
                result = decode_file(args.input, args.declaration, args.output_dir, session_id=args.session_id, limits=limits)
        elif args.command == "index":
            _separate_output(args.bundle, args.output_dir)
            result = build_codec_index(args.bundle)
            args.output_dir.mkdir(parents=True, exist_ok=False)
            publish(args.output_dir, "index.codec-v1.json", canonical(result))
        else:
            observation = Observation(args.observation_id, args.reference_domain, args.reference_epoch,
                                      args.start_s, args.end_s, args.uncertainty_s, args.label, args.observer)
            result = export_codec_excerpt(args.bundle, observation, args.output_dir, max_frames=args.max_frames,
                                          max_bytes=args.max_bytes, padding_s=args.padding_s)
        print(canonical(result).decode(), end="")
        return 0
    except (OSError, SessionError, TypeError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
