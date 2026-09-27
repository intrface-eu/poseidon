"""Bounded local fixture replay only; no listener or external network calls."""
import argparse
import json
from pathlib import Path
import sqlite3

from .adapter import MAX_JSON_BYTES, ChirpStackAdapter, Device, LocalRegistry, parse_time
from .runtime import AquilonRuntime
from .spool import SQLiteSpool
from .wire import Rejected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("replay", help="synthetic JSON fixture to a NEW isolated spool")
    replay.add_argument("fixture", type=Path)
    replay.add_argument("--spool", type=Path, required=True)
    replay.add_argument("--dev-eui", required=True)
    replay.add_argument("--application-id", required=True)
    replay.add_argument("--received-at", required=True, help="explicit aware RFC3339 replay clock")
    health = commands.add_parser("health", help="inspect an existing local draft spool")
    health.add_argument("--spool", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "replay":
            # Exclusive create avoids overwriting anyone's spool. On rejection the
            # empty initialized file remains inspectable, not silently removed.
            with args.spool.open("xb"):
                pass
            with args.fixture.open("rb") as source:
                body = source.read(MAX_JSON_BYTES + 1)
            registry = LocalRegistry([Device(args.dev_eui, args.application_id)])
            with SQLiteSpool(args.spool) as spool:
                runtime = AquilonRuntime(ChirpStackAdapter(registry), spool)
                result = runtime.ingest(body, event="up", received_at=parse_time(args.received_at))
                print(json.dumps({"synthetic_fixture_replay": True, "result": result,
                                  "health": runtime.health()}, sort_keys=True))
        else:
            if not args.spool.is_file():
                raise ValueError("spool missing")
            with SQLiteSpool(args.spool) as spool:
                print(json.dumps(spool.health(), sort_keys=True))
        return 0
    except (OSError, ValueError, Rejected, sqlite3.Error):
        # No raw payload, configuration values, or local exception paths.
        print(json.dumps({"error": "local_operation_rejected"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
