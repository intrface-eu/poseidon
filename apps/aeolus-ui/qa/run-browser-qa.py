from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ["bun", str(ROOT / "qa" / "browser-qa.ts")]
TIMEOUT_SECONDS = 180

process = subprocess.Popen(COMMAND, cwd=ROOT, env=os.environ.copy(), start_new_session=True)
try:
    result = process.wait(timeout=TIMEOUT_SECONDS)
except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    print(f"browser QA exceeded {TIMEOUT_SECONDS} seconds", file=sys.stderr)
    raise SystemExit(124)

raise SystemExit(result)
