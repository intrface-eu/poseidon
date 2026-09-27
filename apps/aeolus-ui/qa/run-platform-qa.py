"""Run bounded browser QA with owned loopback services and process-group cleanup.

No installs, runtime fallbacks, persistent services, or existing workspace key reads.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import Iterator, Sequence
import urllib.request

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]
TERM_GRACE_SECONDS = 20.0
KILL_WAIT_SECONDS = 2.0
GROUP_POLL_SECONDS = 0.05
QA_TIMEOUT_SECONDS = 330


class Interrupted(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"interrupted by signal {signum}")


class CleanupError(RuntimeError):
    pass


class Interrupts:
    """Defer cancellation during ownership registration and all-group cleanup.

    This uses the Python handler rather than a blocked POSIX signal mask, so a
    newly spawned child does not inherit blocked SIGINT/SIGTERM signals.
    """

    def __init__(self) -> None:
        self.pending: int | None = None
        self.depth = 0

    def handle(self, signum: int, _frame: object) -> None:
        if self.pending is not None:
            return  # Repeated signals must not interrupt the first unwind.
        self.pending = signum
        if self.depth == 0:
            raise Interrupted(signum)

    @contextmanager
    def deferred(self) -> Iterator[None]:
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1
            if self.depth == 0 and self.pending is not None:
                raise Interrupted(self.pending)


@contextmanager
def interrupt_handlers() -> Iterator[Interrupts]:
    interrupts = Interrupts()
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for sig in previous:
            signal.signal(sig, interrupts.handle)
        yield interrupts
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def loopback_ports() -> tuple[int, int]:
    api_port = free_port()
    for _ in range(16):
        ui_port = free_port()
        if ui_port != api_port:
            return api_port, ui_port
    raise RuntimeError("Could not select distinct checked-free loopback ports")


def start_owned(
    owned: list[subprocess.Popen],
    command: Sequence[str],
    interrupts: Interrupts,
    **options: object,
) -> subprocess.Popen:
    # Cancellation cannot land between a spawn and recording its owned group.
    with interrupts.deferred():
        process = subprocess.Popen(command, start_new_session=True, **options)
        owned.append(process)
    return process


def group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # A permissions failure is not evidence of an empty group.


def signal_owned_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except ProcessLookupError:
        pass


def wait_group_gone(process: subprocess.Popen, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        process.poll()  # Reap the leader, independently of descendant liveness.
        if not group_exists(process.pid):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(GROUP_POLL_SECONDS, remaining))


def stop(process: subprocess.Popen | None) -> None:
    """Stop only a group created with start_new_session, even if its leader exited."""
    if process is None:
        return
    if process.pid <= 1 or process.pid == os.getpgrp():
        raise CleanupError("refusing a non-owned/current process group")
    errors: list[str] = []
    gone = False
    try:
        signal_owned_group(process.pid, signal.SIGTERM)
    except BaseException as exc:
        errors.append(f"TERM: {type(exc).__name__}")
    try:
        gone = wait_group_gone(process, TERM_GRACE_SECONDS)
    except BaseException as exc:
        errors.append(f"grace wait: {type(exc).__name__}")
    if not gone:
        # Leader exit never suppresses escalation for surviving descendants.
        try:
            signal_owned_group(process.pid, signal.SIGKILL)
        except BaseException as exc:
            errors.append(f"KILL: {type(exc).__name__}")
        try:
            gone = wait_group_gone(process, KILL_WAIT_SECONDS)
        except BaseException as exc:
            errors.append(f"kill wait: {type(exc).__name__}")
    try:
        process.wait(timeout=0)
    except BaseException as exc:
        errors.append(f"leader reap: {type(exc).__name__}")
    if not gone:
        errors.append("group still present after bounded escalation")
    if errors:
        raise CleanupError(f"owned group {process.pid}: {', '.join(errors)}")


def cleanup_all(owned: Sequence[subprocess.Popen], interrupts: Interrupts | None = None) -> None:
    failures: list[str] = []
    guard = interrupts.deferred() if interrupts is not None else nullcontext()
    with guard:
        for process in owned:
            try:
                stop(process)
            except BaseException as exc:
                failure = f"owned group {process.pid}: {type(exc).__name__}"
                failures.append(failure)
                print(f"Cleanup failed for {failure}", file=sys.stderr)
        # Do not turn a passed browser script into a passed runner after cleanup fails.
        if failures:
            raise CleanupError("; ".join(failures))


def wait_ready(url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Owned service exited with code {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError):
            pass
        time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    raise RuntimeError("Owned loopback service missed its readiness deadline")


def executable(env: dict[str, str], name: str, default: str) -> str:
    value = env.get(name, default)
    if not value or "\x00" in value:
        raise ValueError(f"{name} must name one executable, not shell arguments")
    return value


def commands(env: dict[str, str], workspace: Path, api_port: int, ui_port: int) -> tuple[list[str], list[str], list[str]]:
    bun = executable(env, "PLATFORM_QA_BUN", "bun")
    if "PLATFORM_QA_API_PYTHON" in env:
        api = [executable(env, "PLATFORM_QA_API_PYTHON", "python")]
    else:
        api = [executable(env, "PLATFORM_QA_UV", "uv"), "run", "--project", str(REPO / "apps/aeolus-api"), "--frozen", "python"]
    tranche3 = env.get("PLATFORM_QA_TRANCHE3_ONLY") == "1"
    if tranche3 and any(env.get(mode) == "1" for mode in ("PLATFORM_QA_COMPANION_ONLY", "PLATFORM_QA_LEGACY_ONLY", "PLATFORM_QA_AUTH_ONLY")):
        raise ValueError("Tranche 3 QA cannot combine with another QA mode")
    if tranche3 and "PLATFORM_QA_API_PYTHON" not in env:
        raise ValueError("Tranche 3 QA requires the controller-selected existing Python environment")
    if tranche3:
        api += [str(REPO / "tests/api/tranche3_fixture.py"), "--workspace", str(workspace),
                "--control", str(workspace.parent / "digital-watchdog-control.json"), "--port", str(api_port)]
    else:
        api += ["-m", "poseidon_api", "--data-dir", str(workspace), "--host", "127.0.0.1", "--port", str(api_port)]
    script = "tranche3-browser-qa.ts" if tranche3 else "companion-browser-qa.ts" if env.get("PLATFORM_QA_COMPANION_ONLY") == "1" else "platform-browser-qa.ts"
    return api, [bun, "run", "start", "--port", str(ui_port)], [bun, str(APP / "qa" / script)]


def run_session(artifacts: Path, interrupts: Interrupts) -> int:
    owned: list[subprocess.Popen] = []
    with tempfile.TemporaryDirectory(prefix="poseidon-platform-ui-qa-") as temporary:
        workspace = Path(temporary) / "workspace"
        api_port, ui_port = loopback_ports()
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = ":".join(str(REPO / path) for path in ("libs/proto-py/src", "apps/acoustic/src", "apps/nereid/src", "apps/trident/src", "apps/aeolus-api/src"))
        env["POSEIDON_API_URL"] = f"http://127.0.0.1:{api_port}"
        env["UI_BASE_URL"] = f"http://127.0.0.1:{ui_port}"
        env["PLATFORM_QA_OWNED_WORKSPACE"] = "1"
        env["PLATFORM_QA_ARTIFACTS"] = str(artifacts)
        if env.get("PLATFORM_QA_TRANCHE3_ONLY") == "1":
            control = Path(temporary) / "digital-watchdog-control.json"
            descriptor = os.open(control, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                json.dump({"schema_version": "poseidon.digital-watchdog-fixture.v1", "live_journal_heartbeat": True, "faults": []}, output)
            env["PLATFORM_QA_WATCHDOG_CONTROL"] = str(control)
            env["PLATFORM_QA_WORKSPACE"] = str(workspace)
        api_command, ui_command, qa_command = commands(env, workspace, api_port, ui_port)
        with (artifacts / "api.log").open("w") as api_log, (artifacts / "ui.log").open("w") as ui_log:
            try:
                if env.get("PLATFORM_QA_COMPANION_ONLY") == "1":
                    fixture_root = env.get("PLATFORM_QA_COMPANION_FIXTURES")
                    if not fixture_root:
                        raise ValueError("Companion QA requires the Acquisition reader fixture directory")
                    fixture_output = Path(temporary) / "companion-fixtures"
                    # Reuse the exact selected API Python environment; no install/fallback.
                    python_command = api_command[:api_command.index("-m")]
                    prepare_command = python_command + [str(APP / "qa/prepare-companion-fixtures.py"), fixture_root, str(fixture_output)]
                    preparation = start_owned(owned, prepare_command, interrupts, cwd=REPO, env=env, stdout=api_log, stderr=subprocess.STDOUT)
                    try:
                        preparation_code = preparation.wait(timeout=60)
                    except subprocess.TimeoutExpired as exc:
                        raise RuntimeError("Companion fixture preparation exceeded 60 seconds") from exc
                    if preparation_code != 0:
                        raise RuntimeError(f"Actual-reader companion fixture preparation exited {preparation_code}")
                    env["PLATFORM_QA_COMPANION_CATALOG"] = str(fixture_output / "browser-fixtures.json")
                    (artifacts / "platform-tranche2-ui-fixture-catalog.json").write_bytes((fixture_output / "browser-fixtures.json").read_bytes())
                api_process = start_owned(owned, api_command, interrupts, cwd=REPO, env=env, stdout=api_log, stderr=subprocess.STDOUT)
                wait_ready(f"{env['POSEIDON_API_URL']}/healthz", api_process)
                # Only this runner's newly created workspace key; never an existing workspace.
                env["POSEIDON_ACCESS_TOKEN"] = (workspace / "access.token").read_text().strip()
                ui_process = start_owned(owned, ui_command, interrupts, cwd=APP, env=env, stdout=ui_log, stderr=subprocess.STDOUT)
                wait_ready(env["UI_BASE_URL"], ui_process)
                qa_process = start_owned(owned, qa_command, interrupts, cwd=APP, env=env)
                try:
                    code = qa_process.wait(timeout=QA_TIMEOUT_SECONDS)
                    return code if code >= 0 else 128 - code
                except subprocess.TimeoutExpired:
                    print(f"Platform browser QA exceeded the {QA_TIMEOUT_SECONDS}-second hard timeout", file=sys.stderr)
                    return 124
            finally:
                try:
                    cleanup_all(tuple(reversed(owned)), interrupts)
                finally:
                    if env.get("PLATFORM_QA_COMPANION_ONLY") == "1" or env.get("PLATFORM_QA_TRANCHE3_ONLY") == "1":
                        tranche = "tranche3" if env.get("PLATFORM_QA_TRANCHE3_ONLY") == "1" else "tranche2"
                        cleanup = {"ownedGroups": [{"pgid": process.pid, "present": group_exists(process.pid)} for process in owned],
                                   "apiPort": api_port, "uiPort": ui_port, "workspace": str(workspace),
                                   "temporaryRoot": temporary, "allOwnedGroupsGone": all(not group_exists(process.pid) for process in owned)}
                        if tranche == "tranche3":
                            cleanup.update(apiCommand=api_command, uiCommand=ui_command, browserCommand=qa_command,
                                           termGraceSeconds=TERM_GRACE_SECONDS, browserHardTimeoutSeconds=QA_TIMEOUT_SECONDS)
                        pending = artifacts / f"platform-{tranche}-ui-cleanup.json.tmp"
                        pending.write_text(json.dumps(cleanup, indent=2) + "\n")
                        pending.replace(artifacts / f"platform-{tranche}-ui-cleanup.json")


def main() -> int:
    try:
        with interrupt_handlers() as interrupts:
            if os.name != "posix":
                raise ValueError("Owned process-group QA requires POSIX")
            location = os.environ.get("PLATFORM_QA_ARTIFACTS")
            if not location:
                raise ValueError("Set PLATFORM_QA_ARTIFACTS to an owned artifact directory")
            artifacts = Path(location).resolve()
            artifacts.mkdir(parents=True, exist_ok=True)
            if any(os.environ.get(mode) == "1" for mode in ("PLATFORM_QA_COMPANION_ONLY", "PLATFORM_QA_TRANCHE3_ONLY")) and any(artifacts.iterdir()):
                raise ValueError("Companion/tranche 3 QA requires a new empty artifact directory; prior evidence is immutable")
            return run_session(artifacts, interrupts)
    except Interrupted as exc:
        print(str(exc), file=sys.stderr)
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130
    except (CleanupError, RuntimeError, ValueError, OSError) as exc:
        print(f"Platform QA runner failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
