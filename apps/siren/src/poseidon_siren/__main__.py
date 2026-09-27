"""File-only synthetic demo. No playback, hardware adapter, or enable switch."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from poseidon_dsp import SignalSpec, export_wav, limit_samples, sine_samples
from .scheduler import Scheduler, SirenDenied, SirenFault


def demo(output: Path) -> dict:
    output.mkdir(parents=False, exist_ok=False)
    spec = SignalSpec(amplitude=0.8)
    signal = limit_samples(sine_samples(spec))
    with Scheduler.initialize(output / "scheduler") as scheduler:
        try:
            scheduler.request(0, spec.reserved_duration_ms)
        except SirenDenied as error:
            startup_denial = str(error)
        scheduler.rearm_simulation(0, acknowledge_simulation_only=True)
        reservation = scheduler.request(0, spec.reserved_duration_ms)
        try:
            scheduler.request(0, 1)
        except SirenDenied as error:
            overlap_denial = str(error)
        # File export has no real-time side effects and cannot control an output.
        wav = export_wav(output / "synthetic-sine.wav", signal, sample_rate_hz=spec.sample_rate_hz)
        scheduler.stop(0)
    report = {
        "simulation_only": True, "physical_output_enabled": False,
        "provenance": "generated synthetic sine and integer simulation clock; no sensor data",
        "limits_status": "software test envelopes ONLY; no biological safety or efficacy claim",
        "startup_denial": startup_denial, "overlap_denial": overlap_denial,
        "signal_spec": asdict(spec), "reservation": asdict(reservation), "wav": wav,
        "scheduler": scheduler.status,
    }
    with (output / "synthetic-report.json").open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2, allow_nan=False)
        target.write("\n")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo_parser = commands.add_parser("demo", help="create a NEW synthetic file-only demo directory")
    demo_parser.add_argument("--output", required=True, type=Path)
    status_parser = commands.add_parser("status", help="open existing state with startup inhibit and print its audit")
    status_parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            result = demo(args.output)
        else:
            with Scheduler(args.state) as scheduler:
                pass
            result = scheduler.status
    except (OSError, ValueError, SirenFault, SirenDenied) as error:
        print(json.dumps({"simulation_only": True, "physical_output_enabled": False,
                          "error": str(error), "inhibited": True}))
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
