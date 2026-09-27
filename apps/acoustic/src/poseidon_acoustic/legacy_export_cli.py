"""Local finalized-segment export CLI and deterministic synthetic replay example."""
from __future__ import annotations

import argparse
from pathlib import Path
import struct
import sys

from .errors import AcousticError
from .legacy_export import (
    DEFAULT_MAX_BYTES, EpochDeclaration, ExportError, FileOriginDeclaration,
    SegmentMapping, _new_output, export_segments,
)
from .replay import replay_to_store
from .session import Channel, ClockMap, Session, Source, canonical, pcm16_wav, publish
from .store import list_event_json


def run_demo(output_directory: Path | str) -> dict:
    """Create two synthetic segments: two candidate bursts, then zero candidates.

    The known inter-segment gap is not filled. This fixed UTC epoch is a fixture
    convention, not a sensor timestamp. No services, devices or audio playback.
    """
    output = _new_output(output_directory)
    output.mkdir(mode=0o700, exist_ok=False)
    source = Source(
        "synthetic-export-audio", "pcm16-wav", "synthetic",
        (Channel("pcm-0", "synthetic uncalibrated PCM"),),
        ClockMap("reference_seconds", "synthetic-export-start", reference_anchor_s=0.25,
                 drift_ppm=20, anchor_uncertainty_s=0.01, drift_uncertainty_ppm=2),
        sample_rate_hz=8000, origin="integer PCM16 alternating bursts and silence; not animal audio",
    )
    session = Session.create(output / "session", "synthetic-legacy-export-demo", (source,))
    samples = [amplitude * (1 if frame % 2 == 0 else -1)
               for windows, amplitude in ((2, 0), (2, 20000), (2, 0), (2, 20000), (2, 0))
               for frame in range(windows * 160)]
    pcm = struct.pack("<" + "h" * len(samples), *samples)
    session.append(source.source_id, pcm16_wav(pcm, 8000, 1), unit_start=0, units=1600,
                   source_start_s=0, source_end_s=0.2)
    session.append(source.source_id, pcm16_wav(b"\0\0" * 1600, 8000, 1),
                   unit_start=2400, units=1600, source_start_s=0.3, source_end_s=0.5,
                   dropped_units=800, gap_reason="synthetic fixture deliberately omits 800 frames")
    session.finalize()
    epoch = EpochDeclaration(source.source_id, "reference_seconds", "synthetic-export-start",
                             "2026-01-01T00:00:00Z", 0.005, "synthetic-fixture-generator",
                             "integer-fixture-epoch-convention-v1")
    mappings = tuple(SegmentMapping(index, f"synthetic-export-{index}", "synthetic-site",
                                    "synthetic-zone", "synthetic-device") for index in range(2))
    exported = export_segments(session.directory, output / "export", source_id=source.source_id,
                               mappings=mappings, epoch=epoch)
    replay = []
    for item in exported["exports"]:
        result, saved = replay_to_store(output / "export" / item["wav"]["path"],
                                        output / "export" / item["manifest"]["path"],
                                        output / "evidence.sqlite3")
        replay.append({"recording_id": item["recording_id"], "candidate_count": len(result.events),
                       "candidate_ids": [event.event_id for event in result.events],
                       "run_id": saved.run_id, "provenance": "synthetic"})
    events = list_event_json(output / "evidence.sqlite3")
    publish(output, "events.ndjson", ("\n".join(events) + ("\n" if events else "")).encode())
    report = {"schema": "poseidon.legacy-export-demo.provisional.v1", "synthetic": True,
              "hardware_verified": False, "authorization_verified": False,
              "calibration_status": "uncalibrated", "replay": replay,
              "candidate_count": sum(item["candidate_count"] for item in replay),
              "export_receipt": "export/export.receipt.json"}
    publish(output, "demo-result.json", canonical(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy finalized PCM16 segments to v1 replay; retain companion bindings")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="local deterministic synthetic session/export/replay; no device I/O")
    demo.add_argument("--output-dir", type=Path, required=True)
    export = commands.add_parser("export", help="abnormal final states and unresolved file provenance are refused")
    export.add_argument("--session", type=Path, required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    for name in ("source-id", "site-id", "zone-id", "device-id", "reference-domain", "reference-epoch",
                 "epoch-utc", "epoch-declared-by", "epoch-evidence-ref"):
        export.add_argument("--" + name, required=True)
    export.add_argument("--segment", action="append", required=True, metavar="INDEX=RECORDING_ID")
    export.add_argument("--epoch-uncertainty-s", type=float, required=True)
    export.add_argument("--file-origin", choices=("field", "bench"))
    export.add_argument("--original-input-sha256")
    export.add_argument("--origin-declared-by")
    export.add_argument("--origin-evidence-ref")
    export.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    export.add_argument("--max-segments", type=int, default=128)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            result = run_demo(args.output_dir)
        else:
            mappings = []
            for text in args.segment:
                index, separator, recording = text.partition("=")
                if not separator or not index.isascii() or not index.isdigit() or len(index) > 4:
                    raise ExportError("--segment must be INDEX=RECORDING_ID")
                mappings.append(SegmentMapping(int(index), recording, args.site_id, args.zone_id, args.device_id))
            origin_fields = (args.file_origin, args.original_input_sha256, args.origin_declared_by, args.origin_evidence_ref)
            origin = None
            if any(value is not None for value in origin_fields):
                if any(value is None for value in origin_fields):
                    raise ExportError("file origin requires all four origin declaration flags")
                origin = FileOriginDeclaration(args.source_id, args.original_input_sha256, args.file_origin,
                                               args.origin_declared_by, args.origin_evidence_ref)
            epoch = EpochDeclaration(args.source_id, args.reference_domain, args.reference_epoch, args.epoch_utc,
                                     args.epoch_uncertainty_s, args.epoch_declared_by, args.epoch_evidence_ref)
            result = export_segments(args.session, args.output_dir, source_id=args.source_id,
                                     mappings=tuple(mappings), epoch=epoch, file_origin=origin,
                                     max_bytes=args.max_bytes, max_segments=args.max_segments)
        print(canonical(result).decode(), end="")
        return 0
    except (OSError, ValueError, AcousticError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
