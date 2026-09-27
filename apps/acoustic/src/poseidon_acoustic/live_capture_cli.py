"""Separate denied-by-default live entrypoint. Existing session_cli is unchanged."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from pathlib import Path
import sys

from .live_gate import acknowledgment_text, authorize_device_access
from .live_journal import LiveJournal, _read, verify_live_journal
from .live_models import (MAX_METADATA_BYTES, CaptureLimitsV1, CapturePlanV1,
                          CapturedBlockV1, SourcePlanV1, canonical)
from .live_supervisor import LiveCaptureSupervisor, SyntheticBackendFactory, SyntheticSourceScript


def synthetic_demo_plan() -> CapturePlanV1:
    """Named host fixture values, never defaults for a physical capture plan."""
    return CapturePlanV1(
        "synthetic-demo", (SourcePlanV1("fake-audio", "audio", "synthetic", None, canonical({}),
            ("fake-channel",), ("synthetic-fixture",), 8000, None, None, None, None,
            None, None, None, None, None, None, None, "synthetic"),),
        CaptureLimitsV1(5.0, 32, 64, 8, 512, 512, 1048576, 16, 16384, 0.02, 2.0),
        "synthetic-no-device-operation", "host-fake-demo")


def _plan(path):
    selected = Path(path)
    return CapturePlanV1.from_bytes(_read(selected.parent, selected.name, MAX_METADATA_BYTES))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Unqualified capture evidence; device access denied by default. "
                                     "Capture supervision requires the main thread for SIGTERM/SIGINT handling.")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="file-only canonical plan validation")
    validate.add_argument("--plan", required=True)
    capture = commands.add_parser("capture", help="one capture-only operation; acknowledgment is not a permit")
    capture.add_argument("--plan", required=True)
    capture.add_argument("--output-dir", required=True)
    ack_options = capture.add_mutually_exclusive_group()
    ack_options.add_argument("--ack", help="replayed/persisted text is refused; use --ack-prompt for a fresh local decision")
    ack_options.add_argument("--ack-prompt", action="store_true", help="request a fresh exact-plan one-use challenge on a local terminal")
    for name in ("artifact-path", "artifact-sha256", "build-sha256", "profile-sha256"):
        capture.add_argument("--" + name)
    demo = commands.add_parser("synthetic-demo", help="finite host-fake audio; no device access")
    demo.add_argument("--output-dir", required=True)
    for command in ("inspect", "recover"):
        sub = commands.add_parser(command, help="file-only live journal " + command)
        sub.add_argument("--journal", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            plan = _plan(args.plan)
            print(canonical({"plan_sha256": plan.sha256, "synthetic": plan.synthetic,
                             "device_access_occurred": False,
                             "required_local_ack": None if plan.synthetic else "fresh in-process challenge; capture --ack-prompt"}).decode(), end="")
            return 0
        if args.command in ("inspect", "recover"):
            view = verify_live_journal(args.journal) if args.command == "inspect" else LiveJournal.recover(args.journal)
            result = asdict(view)
            result["final_json"] = None if view.final_json is None else view.final_json.decode("ascii")
            print(canonical(result).decode(), end="")
            return 0 if view.integrity_error is None else 2
        if args.command == "synthetic-demo":
            plan = synthetic_demo_plan()
            blocks = tuple(CapturedBlockV1(bytes([index, 0]) * 16, 16,
                           canonical({"provider": "synthetic", "timestamp": None,
                                      "clock_domain": "synthetic-counter", "driver_accuracy_ns": None})) for index in range(3))
            factory = SyntheticBackendFactory((SyntheticSourceScript("fake-audio", blocks, 0.02),))
            grant = None
        else:
            plan = _plan(args.plan)
            acknowledgment = args.ack
            if args.ack_prompt:
                if sys.platform != "linux" or not sys.stdin.isatty():
                    raise ValueError("fresh acknowledgment requires Linux and a local terminal")
                challenge = acknowledgment_text(plan)
                print("Capture-only guard, not a permit. Opening may initialize hardware.\n"
                      + challenge + "\nType that exact line within 60 seconds:", file=sys.stderr)
                acknowledgment = input()
            grant = authorize_device_access(plan, acknowledgment, "capture-only")
            if any(getattr(args, name) is None for name in ("artifact_path", "artifact_sha256", "build_sha256", "profile_sha256")):
                raise ValueError("explicit native artifact and source/build/profile hashes required")
            # Import is deliberately after the local operation gate. The native
            # factory rechecks its source ticket before artifact stat/read/CDLL.
            from .linux_capture import LinuxBackendFactory
            factory = LinuxBackendFactory(plan, artifact_path=args.artifact_path,
                artifact_sha256=args.artifact_sha256, build_sha256=args.build_sha256,
                profile_sha256=args.profile_sha256)
        result = LiveCaptureSupervisor().run(plan, factory, args.output_dir, grant=grant)
        output = asdict(result)
        output["final_json"] = None if result.final_json is None else result.final_json.decode("ascii")
        print(canonical(output).decode(), end="")
        return 0 if (result.owned_workers_reaped and result.finalized and
                     result.reason in ("source-exhausted", "duration-deadline", "cancelled")) else 2
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"live capture refused/failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
