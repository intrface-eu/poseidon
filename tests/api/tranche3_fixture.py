"""Owned synthetic browser/API fixture. Never used by the normal app factory.

Runner atomically writes a mode-0600 control file OUTSIDE the owned workspace:
{"schema_version":"poseidon.digital-watchdog-fixture.v1",
 "live_journal_heartbeat":true,"faults":[]}

faults: hung-heartbeat, network-loss, full-disk, full-inodes, sensor-disconnect,
clock-regression, journal-corruption, unrecoverable-job-failure. This is simulated
journal liveness, not a capture session, native binding or field heartbeat.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat

from poseidon_api.app import create_app
from poseidon_trident import Hub
from poseidon_trident.operating import FAULTS

ALLOWED = FAULTS | {"hung-heartbeat", "network-loss", "full-inodes", "sensor-disconnect"}


def make_fixture_app(workspace: Path, control_path: Path):
    workspace, control_path = workspace.absolute(), control_path.absolute()
    if control_path.is_relative_to(workspace):
        raise ValueError("fixture control must not be placed in evidence workspace")

    class SyntheticFixtureHub(Hub):
        def _fixture_input(self):
            info = control_path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096:
                raise ValueError("fixture control must be a private bounded regular file")
            value = json.loads(control_path.read_text())
            if (type(value) is not dict or set(value) != {"schema_version", "live_journal_heartbeat", "faults"}
                    or value["schema_version"] != "poseidon.digital-watchdog-fixture.v1"
                    or type(value["live_journal_heartbeat"]) is not bool or type(value["faults"]) is not list
                    or any(type(f) is not str or f not in ALLOWED for f in value["faults"])):
                raise ValueError("invalid synthetic fixture input")
            for fault in ALLOWED:
                self._watchdogs.inject(fault, fault in value["faults"])
            if value["live_journal_heartbeat"]:
                self._watchdogs.heartbeat("live_journal")

        def _watchdog_tick(self):
            self._fixture_input()
            return super()._watchdog_tick()

    return create_app(workspace, _hub_factory=SyntheticFixtureHub)


def main():
    parser = argparse.ArgumentParser(description="Tranche3 loopback synthetic QA API; no physical devices")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024..65535")
    import uvicorn
    uvicorn.run(make_fixture_app(args.workspace, args.control), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
