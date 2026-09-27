"""Bound a tranche 3 check and publish new command evidence, without installs."""
from __future__ import annotations

import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("owned_qa", APP / "qa/run-platform-qa.py")
assert spec and spec.loader
owned_qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned_qa)


def atomic(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def main() -> int:
    stage, seconds, report_dir, log_path, *command = sys.argv[1:]
    if not command or not stage.replace("-", "").isalnum():
        raise ValueError("Name one bounded check and exact argv")
    reports = Path(report_dir).resolve()
    result = reports / f"platform-tranche3-ui-{stage}-command.json"
    if result.exists():
        raise ValueError("Prior command evidence is immutable; choose a new stage name")
    record = {"stage": stage, "state": "running", "cwd": str(APP), "command": command,
              "hardTimeoutSeconds": int(seconds), "termGraceSeconds": owned_qa.TERM_GRACE_SECONDS,
              "log": log_path, "startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    progress = reports / "platform-tranche3-ui-progress.json"
    processes = []
    code = 2
    atomic(progress, record)
    try:
        with owned_qa.interrupt_handlers() as interrupts:
            try:
                with Path(log_path).open("x") as output:
                    process = owned_qa.start_owned(processes, command, interrupts, cwd=APP,
                        stdout=output, stderr=subprocess.STDOUT,
                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                    record["ownedPgid"] = process.pid
                    atomic(progress, record)
                    try:
                        code = process.wait(timeout=int(seconds))
                    except subprocess.TimeoutExpired:
                        record["timedOut"] = True
                        code = 124
            finally:
                owned_qa.cleanup_all(tuple(reversed(processes)), interrupts)
    except owned_qa.Interrupted as exc:
        code = 128 + exc.signum
    except BaseException as exc:
        record["runnerError"] = type(exc).__name__
        code = 2
    finally:
        record.update(state="passed" if code == 0 else "failed", exit=code,
                      finishedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      ownedGroups=[{"pgid": process.pid, "present": owned_qa.group_exists(process.pid)} for process in processes])
        atomic(progress, record)
        atomic(result, record)
        print(json.dumps(record))
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    raise SystemExit(main())
