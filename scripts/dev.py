#!/usr/bin/env python3
"""Run the local monitor API and operator UI, or print a workspace access token."""

from __future__ import annotations

import argparse
import math
import os
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence, TextIO


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
API_DIRECTORY = REPOSITORY_ROOT / "apps" / "aeolus-api"
UI_DIRECTORY = REPOSITORY_ROOT / "apps" / "aeolus-ui"
DEFAULT_DATA_DIRECTORY = REPOSITORY_ROOT / ".local" / "monitor"
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8080
DEFAULT_UI_PORT = 3000
DEFAULT_READINESS_TIMEOUT = 30.0
TOKEN_FILENAME = "access.token"
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "libs" / "proto-py" / "src",
    REPOSITORY_ROOT / "apps" / "acoustic" / "src",
    REPOSITORY_ROOT / "apps" / "trident" / "src",
    REPOSITORY_ROOT / "apps" / "aeolus-api" / "src",
)


class DevError(Exception):
    """An expected local development startup error."""


@dataclass(frozen=True)
class LaunchSpec:
    name: str
    command: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]


@dataclass(frozen=True)
class ManagedProcess:
    name: str
    process: subprocess.Popen[object]


def valid_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer from 1 through 65535") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("must be an integer from 1 through 65535")
    return port


def positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive number") from error
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return seconds


def data_directory(value: str) -> Path:
    return Path(value).expanduser().absolute()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("start", "token"),
        default="start",
        help="start the API and UI (default), or print the workspace access token",
    )
    parser.add_argument(
        "--data-dir",
        type=data_directory,
        default=DEFAULT_DATA_DIRECTORY,
        metavar="PATH",
        help=f"workspace directory (default: {DEFAULT_DATA_DIRECTORY})",
    )
    parser.add_argument(
        "--api-port",
        type=valid_port,
        default=DEFAULT_API_PORT,
        help=f"loopback API port (default: {DEFAULT_API_PORT})",
    )
    parser.add_argument(
        "--ui-port",
        type=valid_port,
        default=DEFAULT_UI_PORT,
        help=f"loopback UI port (default: {DEFAULT_UI_PORT})",
    )
    parser.add_argument(
        "--readiness-timeout",
        type=positive_seconds,
        default=DEFAULT_READINESS_TIMEOUT,
        metavar="SECONDS",
        help=f"maximum wait for both services (default: {DEFAULT_READINESS_TIMEOUT:g})",
    )
    parser.add_argument(
        "--ui-mode",
        choices=("dev", "production"),
        default="dev",
        help="run the Next development server or serve its built bundle (default: dev)",
    )
    return parser.parse_args(argv)


def source_pythonpath(existing: str | None = None) -> str:
    roots = [str(path) for path in SOURCE_ROOTS]
    if existing:
        roots.append(existing)
    return os.pathsep.join(roots)


def service_specs(options: argparse.Namespace) -> tuple[LaunchSpec, LaunchSpec]:
    environment = os.environ.copy()
    environment["NEXT_TELEMETRY_DISABLED"] = "1"
    environment["PYTHONPATH"] = source_pythonpath(environment.get("PYTHONPATH"))
    uv = environment.get("UV", "uv")
    bun = environment.get("BUN", "bun")
    api_url = f"http://{LOOPBACK_HOST}:{options.api_port}"
    api = LaunchSpec(
        name="API",
        command=(
            uv,
            "run",
            "--project",
            str(API_DIRECTORY),
            "--frozen",
            "python",
            "-m",
            "poseidon_api",
            "--data-dir",
            str(options.data_dir),
            "--host",
            LOOPBACK_HOST,
            "--port",
            str(options.api_port),
        ),
        cwd=REPOSITORY_ROOT,
        environment=environment,
    )
    ui_environment = environment.copy()
    ui_environment["POSEIDON_API_URL"] = api_url
    ui_script = "dev" if options.ui_mode == "dev" else "start"
    ui = LaunchSpec(
        name="UI",
        command=(
            bun,
            "run",
            ui_script,
            "--hostname",
            LOOPBACK_HOST,
            "--port",
            str(options.ui_port),
        ),
        cwd=UI_DIRECTORY,
        environment=ui_environment,
    )
    return api, ui


def port_is_available(host: str, port: int) -> bool:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        listener.close()


def verify_ports(options: argparse.Namespace, probe: Callable[[str, int], bool] = port_is_available) -> None:
    if options.api_port == options.ui_port:
        raise DevError("API and UI ports must differ")
    busy = [
        f"{name} port {port}"
        for name, port in (("API", options.api_port), ("UI", options.ui_port))
        if not probe(LOOPBACK_HOST, port)
    ]
    if busy:
        raise DevError("already in use: " + ", ".join(busy) + "; stop the owning process or choose another port")


def prepare_data_directory(data_dir: Path) -> None:
    """Create missing workspace directories without changing existing user paths."""
    missing: list[Path] = []
    current = data_dir
    while True:
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            missing.append(current)
            parent = current.parent
            if parent == current:
                raise DevError(f"cannot find an existing parent for workspace {data_dir}")
            current = parent
            continue
        except NotADirectoryError as error:
            parent = current.parent
            while True:
                try:
                    parent_mode = parent.lstat().st_mode
                except (FileNotFoundError, NotADirectoryError):
                    if parent == parent.parent:
                        raise DevError(f"cannot inspect workspace path {current}: {error}") from error
                    parent = parent.parent
                    continue
                except OSError as parent_error:
                    raise DevError(f"cannot inspect workspace path {parent}: {parent_error}") from parent_error
                if not stat.S_ISDIR(parent_mode):
                    raise DevError(f"workspace parent is not a directory: {parent}")
                raise DevError(f"cannot inspect workspace path {current}: {error}") from error
        except OSError as error:
            raise DevError(f"cannot inspect workspace path {current}: {error}") from error
        if stat.S_ISLNK(mode):
            raise DevError(f"refusing symlinked workspace path {current}")
        if not stat.S_ISDIR(mode):
            if current == data_dir:
                raise DevError(f"workspace path is not a directory: {data_dir}")
            raise DevError(f"workspace parent is not a directory: {current}")
        break

    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as error:
            raise DevError(f"cannot create workspace directory {directory}: {error}") from error
        try:
            mode = directory.lstat().st_mode
        except OSError as error:
            raise DevError(f"cannot inspect workspace path {directory}: {error}") from error
        if stat.S_ISLNK(mode):
            raise DevError(f"refusing symlinked workspace path {directory}")
        if not stat.S_ISDIR(mode):
            raise DevError(f"workspace path is not a directory: {directory}")


def start_process(spec: LaunchSpec, popen_factory: Callable[..., subprocess.Popen[object]]) -> ManagedProcess:
    options: dict[str, object] = {
        "cwd": str(spec.cwd),
        "env": spec.environment,
    }
    if os.name == "posix":
        options["start_new_session"] = True
    try:
        process = popen_factory(spec.command, **options)
    except OSError as error:
        raise DevError(f"could not start {spec.name}: {error}") from error
    return ManagedProcess(name=spec.name, process=process)


def signal_process_group(managed: ManagedProcess, signum: int) -> None:
    """Signal the process group created for one service, even after its leader exits."""
    process = managed.process
    try:
        if os.name == "posix":
            os.killpg(process.pid, signum)
        elif process.poll() is None:
            process.send_signal(signum)
    except ProcessLookupError:
        return


def wait_for_exit(
    processes: Sequence[ManagedProcess],
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[ManagedProcess]:
    remaining = [managed for managed in processes if managed.process.poll() is None]
    while remaining and clock() < deadline:
        sleep(min(0.1, max(0.0, deadline - clock())))
        remaining = [managed for managed in remaining if managed.process.poll() is None]
    return remaining


def shutdown_processes(
    processes: Sequence[ManagedProcess],
    *,
    grace_seconds: float = 5.0,
    kill_seconds: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    signal_group: Callable[[ManagedProcess, int], None] = signal_process_group,
) -> None:
    owned_groups = list(processes)
    for managed in owned_groups:
        signal_group(managed, signal.SIGTERM)
    wait_for_exit(owned_groups, clock() + grace_seconds, clock, sleep)
    # A service leader can exit while a descendant remains in its session. The
    # group ID remains owned by this launcher until its last descendant exits.
    for managed in owned_groups:
        signal_group(managed, signal.SIGKILL)
    wait_for_exit(owned_groups, clock() + kill_seconds, clock, sleep)
    for managed in processes:
        try:
            managed.process.wait(timeout=0)
        except (subprocess.TimeoutExpired, OSError):
            continue


def start_services(
    options: argparse.Namespace,
    popen_factory: Callable[..., subprocess.Popen[object]] = subprocess.Popen,
    cleanup: Callable[[Sequence[ManagedProcess]], None] = shutdown_processes,
) -> list[ManagedProcess]:
    started: list[ManagedProcess] = []
    try:
        for spec in service_specs(options):
            started.append(start_process(spec, popen_factory))
    except BaseException:
        cleanup(started)
        raise
    return started


def http_ready(url: str, timeout: float = 0.5) -> bool:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 400
    except (OSError, TimeoutError, urllib.error.URLError):
        return False


def child_failure(processes: Sequence[ManagedProcess]) -> str | None:
    for managed in processes:
        code = managed.process.poll()
        if code is not None:
            return f"{managed.name} exited before readiness (status {code})"
    return None


def wait_for_readiness(
    processes: Sequence[ManagedProcess],
    options: argparse.Namespace,
    *,
    probe: Callable[[str], bool] = http_ready,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    api_url = f"http://{LOOPBACK_HOST}:{options.api_port}/healthz"
    ui_url = f"http://{LOOPBACK_HOST}:{options.ui_port}/"
    deadline = clock() + options.readiness_timeout
    while True:
        failure = child_failure(processes)
        if failure:
            raise DevError(failure)
        if probe(api_url) and probe(ui_url):
            return
        if clock() >= deadline:
            raise DevError(f"services did not become ready within {options.readiness_timeout:g} seconds")
        sleep(min(0.1, max(0.0, deadline - clock())))


def monitor_processes(
    processes: Sequence[ManagedProcess],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    while True:
        failure = child_failure(processes)
        if failure:
            raise DevError(failure)
        sleep(0.25)


def run_dev(
    options: argparse.Namespace,
    *,
    port_probe: Callable[[str, int], bool] = port_is_available,
    popen_factory: Callable[..., subprocess.Popen[object]] = subprocess.Popen,
    readiness_probe: Callable[[str], bool] = http_ready,
    printer: Callable[[str], None] = print,
) -> int:
    processes: list[ManagedProcess] = []
    try:
        verify_ports(options, port_probe)
        prepare_data_directory(options.data_dir)
        processes = start_services(options, popen_factory)
        wait_for_readiness(processes, options, probe=readiness_probe)
        printer(f"Operator UI: http://{LOOPBACK_HOST}:{options.ui_port}")
        printer(f"API health: http://{LOOPBACK_HOST}:{options.api_port}/healthz")
        printer(f"API access token file: {options.data_dir / TOKEN_FILENAME}")
        monitor_processes(processes)
    except KeyboardInterrupt:
        printer("Stopping local monitor services.")
        return 130
    except DevError as error:
        printer(f"error: {error}")
        return 1
    finally:
        if processes:
            shutdown_processes(processes)
    return 0


def run_cli(options: argparse.Namespace) -> int:
    """Install a temporary SIGTERM handler for the CLI process only."""
    previous_handler = signal.getsignal(signal.SIGTERM)
    shutdown_requested = False

    def request_shutdown(_signum: int, _frame: object) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            return
        shutdown_requested = True
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_shutdown)
    try:
        return run_dev(options)
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


def print_token(data_dir_path: Path, output: TextIO = sys.stdout, errors: TextIO = sys.stderr) -> int:
    if data_dir_path.is_symlink():
        print(f"error: refusing symlinked data directory {data_dir_path}", file=errors)
        return 1
    token_path = data_dir_path / TOKEN_FILENAME
    try:
        mode = token_path.lstat().st_mode
    except FileNotFoundError:
        print(f"error: access token file is missing: {token_path}", file=errors)
        return 1
    except OSError as error:
        print(f"error: cannot inspect access token file {token_path}: {error}", file=errors)
        return 1
    if stat.S_ISLNK(mode):
        print(f"error: refusing symlinked access token file {token_path}", file=errors)
        return 1
    if not stat.S_ISREG(mode):
        print(f"error: access token path is not a regular file: {token_path}", file=errors)
        return 1
    if stat.S_IMODE(mode) & 0o077:
        print(f"error: access token file permissions must deny group and other access: {token_path}", file=errors)
        return 1
    try:
        token = token_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"error: cannot read access token file {token_path}: {error}", file=errors)
        return 1
    token = token.rstrip("\r\n")
    if not token:
        print(f"error: access token file is empty: {token_path}", file=errors)
        return 1
    print(token, file=output)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    if options.command == "token":
        return print_token(options.data_dir)
    return run_cli(options)


if __name__ == "__main__":
    raise SystemExit(main())
