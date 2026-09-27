"""Run one digital verification command with a bounded owned process group.

This wrapper grants no equipment, field, network-service or release authorization.
The caller supplies a reviewed command; shell interpolation is never used.
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import signal
import subprocess
import sys


class Interrupted(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"interrupted by signal {signum}")


def stop_owned_group(process: subprocess.Popen, term_grace: float = 3) -> None:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=term_grace)
        except (subprocess.TimeoutExpired, Interrupted, KeyboardInterrupt):
            pass
        finally:
            # A departed leader does not prove its descendants have stopped.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
    finally:
        # Pending cancellation is delivered only after escalation and reaping.
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def run(command: list[str], timeout: float, cwd: Path | None = None, term_grace: float = 3) -> int:
    if not command or not all(isinstance(arg, str) and arg and "\x00" not in arg for arg in command):
        raise ValueError("a nonempty command argument list is required")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and greater than zero")
    if not math.isfinite(term_grace) or term_grace <= 0:
        raise ValueError("termination grace must be finite and greater than zero")
    if os.name != "posix":
        raise ValueError("owned process-group verification requires POSIX")
    process = None
    registering = True
    cleaning = False
    pending: int | None = None
    timed_out = False

    def interrupt(signum: int, _frame: object) -> None:
        nonlocal pending
        if pending is None:
            pending = signum
        if not registering and not cleaning:
            raise Interrupted(pending)

    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        try:
            # Defer Python cancellation until ownership is recorded, without
            # making the child inherit a blocked SIGINT/SIGTERM mask.
            process = subprocess.Popen(command, cwd=cwd, start_new_session=True)
            registering = False
            if pending is not None:
                raise Interrupted(pending)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                code = 124
        finally:
            registering = False
            if process is not None:
                cleaning = True
                stop_owned_group(process, term_grace)
        if pending is not None:
            raise Interrupted(pending)
        if timed_out:
            print(f"Digital check timed out after {timeout:g}s; owned process group stopped", file=sys.stderr)
        return code if code >= 0 else 128 - code
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--term-grace", type=float, default=3)
    parser.add_argument("--cwd", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command

    def interrupt(signum: int, _frame: object) -> None:
        raise Interrupted(signum)

    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        return run(command, args.timeout, args.cwd, args.term_grace)
    except Interrupted as exc:
        print(str(exc), file=sys.stderr)
        return 128 + exc.signum
    except (ValueError, OSError) as exc:
        print(f"Cannot run digital check: {exc}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
