"""Command-line entry point for the loopback monitor API."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import uvicorn

from .app import create_app


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _loopback_host(value: str) -> str:
    if value.casefold() not in _LOOPBACK_HOSTS:
        raise argparse.ArgumentTypeError("host must be localhost, 127.0.0.1 or ::1")
    return value


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be from 1 through 65535")
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Poseidon monitor API.")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1", type=_loopback_host)
    parser.add_argument("--port", default=8080, type=_port)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token_path = args.data_dir.expanduser().resolve() / "access.token"
    print(f"Workspace token file: {token_path}")
    print("Read that private file and use its value as the Bearer token. The token is not printed here.")
    uvicorn.run(
        create_app(data_dir=args.data_dir, start_worker=True),
        host=args.host,
        port=args.port,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=30,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
