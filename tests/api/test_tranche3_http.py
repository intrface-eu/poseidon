from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import httpx
import pytest

from poseidon_proto.command import payload_bytes


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts/v1/fixtures"
FIXTURE_SERVER = ROOT / "tests/api/tranche3_fixture.py"

_spec = importlib.util.spec_from_file_location(
    "tranche3_http_companion_fixtures", ROOT / "tests/trident/_companion_support.py"
)
_companion_fixtures = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_companion_fixtures)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _utc(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class LiveFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.workspace = root / "workspace"
        self.control = root / "watchdog-control.json"
        self.log = root / "fixture.log"
        self.port = _free_port()
        self.process: subprocess.Popen | None = None
        self.client: httpx.Client | None = None
        self.write_control()

    def write_control(self, *faults: str, live_journal_heartbeat: bool = True) -> None:
        value = {
            "schema_version": "poseidon.digital-watchdog-fixture.v1",
            "live_journal_heartbeat": live_journal_heartbeat,
            "faults": list(faults),
        }
        temporary = self.root / f"watchdog-control-{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.control)
        finally:
            if temporary.exists():
                temporary.unlink()
        assert self.control.stat().st_mode & 0o777 == 0o600

    def start(self) -> None:
        assert self.process is None
        output = self.log.open("ab")
        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    str(FIXTURE_SERVER),
                    "--workspace",
                    str(self.workspace),
                    "--control",
                    str(self.control),
                    "--port",
                    str(self.port),
                ],
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            output.close()
        self.client = httpx.Client(
            base_url=f"http://127.0.0.1:{self.port}", timeout=5.0, trust_env=False
        )
        deadline = time.monotonic() + 12
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                pytest.fail(
                    f"fixture exited {self.process.returncode}: "
                    + self.log.read_text(encoding="utf-8", errors="replace")
                )
            try:
                response = self.client.get("/healthz")
                if response.status_code == 200:
                    return
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(0.05)
        self.stop()
        pytest.fail(f"fixture did not become ready: {last_error}")

    def _end(self, sig: signal.Signals) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            os.killpg(process.pid, sig)
            try:
                process.wait(timeout=8 if sig == signal.SIGTERM else 3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
        else:
            process.wait(timeout=1)
        self.process = None

    def stop(self) -> None:
        self._end(signal.SIGTERM)

    def crash(self) -> None:
        self._end(signal.SIGKILL)

    def auth(self, token: str | None = None) -> dict[str, str]:
        if token is None:
            token = (self.workspace / "access.token").read_text(encoding="ascii").strip()
        return {"Authorization": f"Bearer {token}"}

    def request(self, method: str, path: str, token: str | None = None, **kwargs) -> httpx.Response:
        assert self.client is not None
        headers = dict(kwargs.pop("headers", {}))
        headers.update(self.auth(token))
        return self.client.request(method, path, headers=headers, **kwargs)

    def wait(self, path: str, predicate, token: str | None = None, timeout: float = 8.0) -> dict:
        deadline = time.monotonic() + timeout
        last: dict | None = None
        while time.monotonic() < deadline:
            response = self.request("GET", path, token)
            if response.status_code == 200:
                last = response.json()
                if predicate(last):
                    return last
            time.sleep(0.05)
        pytest.fail(f"condition not reached for {path}: {last}")


@pytest.fixture
def live(tmp_path: Path):
    server = LiveFixture(tmp_path)
    server.start()
    try:
        yield server
    finally:
        server.stop()
        assert server.process is None


def _device(device_id: str, *, site_id: str = "site-1", kind: str = "hub") -> dict:
    return {
        "id": device_id,
        "site_id": site_id,
        "label": "Owned synthetic HTTP test device",
        "kind": kind,
        "hardware_revision": "synthetic-r1",
        "source_kind": "synthetic",
    }


def _profile(zone_id: str = "zone-1", *, stale: int = 30, offline: int = 120) -> dict:
    return {
        "schema_version": "poseidon.device-health-profile.v1",
        "zone_id": zone_id,
        "stale_after_s": stale,
        "offline_after_s": offline,
    }


def _principal(
    live: LiveFixture,
    subject: str,
    role: str,
    *,
    sites: list[str] | None = None,
    device_id: str | None = None,
) -> tuple[str, dict]:
    response = live.request(
        "POST",
        "/api/v1/principals",
        json={
            "subject": subject,
            "role": role,
            "site_ids": sites or ["site-1"],
            "device_id": device_id,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["token"], body["principal"]


def _setup_control(live: LiveFixture) -> tuple[str, dict, Ed25519PrivateKey]:
    response = live.request("POST", "/api/v1/devices", json=_device("hub-1"))
    assert response.status_code == 201, response.text
    assert live.request(
        "PUT", "/api/v1/devices/hub-1/health-profile", json=_profile()
    ).status_code == 200
    assert live.request("PUT", "/api/v1/hub-binding", json={"device_id": "hub-1"}).json() == {
        "device_id": "hub-1",
        "site_id": "site-1",
        "zone_id": "zone-1",
    }
    token, principal = _principal(live, "operator-1", "operator")
    key = Ed25519PrivateKey.generate()
    enrolled = live.request(
        "POST",
        "/api/v1/command-keys",
        token,
        json={
            "key_id": "operator-key-1",
            "principal_id": principal["id"],
            "public_key_hex": key.public_key()
            .public_bytes(Encoding.Raw, PublicFormat.Raw)
            .hex(),
        },
    )
    assert enrolled.status_code == 201, enrolled.text
    live.wait(
        "/api/v1/hub-state",
        lambda body: body["watchdogs"] and all(row["healthy"] for row in body["watchdogs"]),
        token,
    )
    return token, principal, key


def _command(
    principal: dict,
    key: Ed25519PrivateKey,
    sequence: int,
    kind: str,
    *,
    params: dict | None = None,
) -> dict:
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    body = {
        "schema_version": "poseidon.command.v1",
        "command_id": str(uuid.uuid4()),
        "site_id": "site-1",
        "zone_id": "zone-1",
        "device_id": "hub-1",
        "principal_id": principal["id"],
        "key_id": "operator-key-1",
        "sequence": str(sequence),
        "issued_at": _utc(now),
        "expires_at": _utc(now + timedelta(minutes=5)),
        "kind": kind,
        "params": params or {},
    }
    body["signature"] = {
        "algorithm": "Ed25519",
        "canonicalization": "poseidon-json-v1",
        "value": base64.b64encode(key.sign(payload_bytes(body))).decode("ascii"),
    }
    return body


def _wire(body: dict, *, pretty: bool = False) -> bytes:
    return json.dumps(
        body,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    ).encode("utf-8")


def _send_command(
    live: LiveFixture,
    token: str,
    body: dict,
    *,
    retained: bool = False,
    pretty: bool = False,
) -> httpx.Response:
    headers = {
        "Content-Type": "application/json",
        "X-Poseidon-Retained": "true" if retained else "false",
    }
    return live.request(
        "POST", "/api/v1/commands", token, headers=headers, content=_wire(body, pretty=pretty)
    )


def test_real_http_keys_scopes_retained_retry_uint64_and_command_transitions(live: LiveFixture) -> None:
    operator_token, principal, key = _setup_control(live)
    first = _command(principal, key, 1, "rearm")

    retained = _send_command(live, operator_token, first, retained=True)
    assert retained.status_code == 200
    assert retained.json() | {} == retained.json()
    assert (retained.json()["outcome"], retained.json()["reason"]) == (
        "rejected",
        "retained_delivery",
    )
    assert live.request(
        "GET", "/api/v1/command-sequence/hub-1", operator_token
    ).json()["sequence_seen"] == "0"
    before = live.request("GET", "/api/v1/hub-state", operator_token).json()
    assert before["state"] == "observe"
    assert live.request("GET", "/api/v1/commands", operator_token).json()["total"] == 0

    executed = _send_command(live, operator_token, first)
    assert executed.status_code == 200
    assert (executed.json()["outcome"], executed.json()["state_after"]) == (
        "executed",
        "armed",
    )
    transition_count = len(
        live.request("GET", "/api/v1/hub-state", operator_token).json()["last_transitions"]
    )
    duplicate = _send_command(live, operator_token, first)
    assert duplicate.json()["outcome"] == "duplicate"
    assert len(
        live.request("GET", "/api/v1/hub-state", operator_token).json()["last_transitions"]
    ) == transition_count
    changed_wire = _send_command(live, operator_token, first, pretty=True)
    assert (changed_wire.json()["outcome"], changed_wire.json()["reason"]) == (
        "rejected",
        "command_id_conflict",
    )

    for sequence, kind, expected in (
        (2, "inhibit", "inhibited"),
        (3, "resume", "observe"),
        (4, "rearm", "armed"),
    ):
        ack = _send_command(live, operator_token, _command(principal, key, sequence, kind))
        assert (ack.json()["outcome"], ack.json()["state_after"]) == ("executed", expected)

    maximum = _command(principal, key, 2**64 - 1, "health-request")
    assert _send_command(live, operator_token, maximum).json()["sequence_seen"] == str(2**64 - 1)
    assert _send_command(live, operator_token, maximum).json()["outcome"] == "duplicate"
    context = live.request("GET", "/api/v1/command-context/hub-1", operator_token).json()
    assert context["sequence_seen"] == str(2**64 - 1)
    assert context["allowed_kinds"] == [
        "inhibit",
        "resume",
        "rearm",
        "clear-fault",
        "wiper-run",
        "health-request",
        "config-apply",
    ]
    rendered = json.dumps(context)
    assert "private" not in rendered.lower()
    assert operator_token not in rendered

    assert live.request(
        "POST",
        "/api/v1/commands",
        headers={"Content-Type": "application/json"},
        content=_wire(maximum),
    ).status_code == 403
    assert live.request("POST", "/api/v1/devices", json=_device("site-2-hub", site_id="site-2")).status_code == 201
    assert live.request(
        "PUT",
        "/api/v1/devices/site-2-hub/health-profile",
        json=_profile("site-2-zone"),
    ).status_code == 200
    assert live.request(
        "GET", "/api/v1/command-context/site-2-hub", operator_token
    ).status_code == 404
    site_two_token, _ = _principal(live, "site-2-admin", "admin", sites=["site-2"])
    assert live.request("GET", "/api/v1/commands", site_two_token).json()["total"] == 0
    assert live.request("GET", "/api/v1/command-keys", site_two_token).json() == {"items": []}

    revoked = live.request(
        "POST", "/api/v1/command-keys/operator-key-1/revoke", operator_token, content=b""
    )
    assert revoked.status_code == 200
    rejected = _send_command(live, operator_token, maximum)
    assert (rejected.json()["outcome"], rejected.json()["reason"]) == (
        "rejected",
        "revoked_key",
    )
    assert rejected.json()["sequence_seen"] == str(2**64 - 1)


def test_real_http_file_watchdogs_health_alarms_and_restart_never_armed(live: LiveFixture) -> None:
    operator_token, principal, key = _setup_control(live)
    assert live.request("POST", "/api/v1/devices", json=_device("reef-1", kind="reef")).status_code == 201
    assert live.request(
        "PUT",
        "/api/v1/devices/reef-1/health-profile",
        json=_profile(stale=1, offline=3),
    ).status_code == 200
    device_token, _ = _principal(live, "reef-1-device", "device", device_id="reef-1")
    telemetry = _fixture("telemetry-envelope.valid") | {
        "device_id": "reef-1",
        "site_id": "site-1",
    }
    accepted = live.request("POST", "/api/v1/telemetry", device_token, json=telemetry)
    assert accepted.status_code == 200, accepted.text
    online = live.request("GET", "/api/v1/device-health", operator_token).json()
    assert next(row for row in online["items"] if row["device_id"] == "reef-1")["health"] == "online"
    time.sleep(1.15)
    stale = live.request("GET", "/api/v1/device-health", operator_token).json()
    assert next(row for row in stale["items"] if row["device_id"] == "reef-1")["health"] == "stale"
    time.sleep(2.0)
    offline = live.request("GET", "/api/v1/device-health", operator_token).json()
    assert next(row for row in offline["items"] if row["device_id"] == "reef-1")["health"] == "offline"
    device_alarm = next(
        row
        for row in live.request("GET", "/api/v1/alarms", operator_token).json()["items"]
        if row["source"] == "device" and row["device_id"] == "reef-1"
    )
    acknowledged = live.request(
        "POST", f"/api/v1/alarms/{device_alarm['id']}/acknowledge", operator_token, content=b""
    )
    assert acknowledged.json()["acknowledged_by"] == "operator-1"
    assert live.request("POST", "/api/v1/devices/reef-1/revoke", content=b"").status_code == 200
    revoked = live.request("GET", "/api/v1/device-health", operator_token).json()
    assert next(row for row in revoked["items"] if row["device_id"] == "reef-1")["health"] == "revoked"

    assert _send_command(live, operator_token, _command(principal, key, 1, "rearm")).json()[
        "state_after"
    ] == "armed"
    live.write_control("network-loss")
    inhibited = live.wait(
        "/api/v1/hub-state", lambda body: body["state"] == "inhibited", operator_token
    )
    assert inhibited["last_transitions"][0]["cause_id"] == "watchdog.api"
    live.write_control()
    live.wait(
        "/api/v1/hub-state",
        lambda body: all(row["healthy"] for row in body["watchdogs"]),
        operator_token,
    )
    assert _send_command(live, operator_token, _command(principal, key, 2, "resume")).json()[
        "state_after"
    ] == "observe"
    assert _send_command(live, operator_token, _command(principal, key, 3, "rearm")).json()[
        "state_after"
    ] == "armed"

    live.write_control("journal-corruption")
    faulted = live.wait("/api/v1/hub-state", lambda body: body["state"] == "fault", operator_token)
    assert faulted["last_transitions"][0]["cause_id"] == "journal-corruption"
    refused = _send_command(live, operator_token, _command(principal, key, 4, "clear-fault"))
    assert (refused.json()["outcome"], refused.json()["reason"]) == (
        "failed",
        "fault_unacknowledged",
    )
    alarms = live.request("GET", "/api/v1/alarms?limit=200", operator_token).json()["items"]
    for alarm in alarms:
        if alarm["source"] == "hub" and alarm["severity"] == "critical" and alarm["acknowledged_by"] is None:
            result = live.request(
                "POST", f"/api/v1/alarms/{alarm['id']}/acknowledge", operator_token, content=b""
            )
            assert result.status_code == 200
    live.write_control()
    live.wait(
        "/api/v1/hub-state",
        lambda body: all(row["healthy"] for row in body["watchdogs"]),
        operator_token,
    )
    assert _send_command(live, operator_token, _command(principal, key, 5, "clear-fault")).json()[
        "state_after"
    ] == "inhibited"
    assert _send_command(live, operator_token, _command(principal, key, 6, "resume")).json()[
        "state_after"
    ] == "observe"
    assert _send_command(live, operator_token, _command(principal, key, 7, "rearm")).json()[
        "state_after"
    ] == "armed"

    live.crash()
    live.start()
    after_crash = live.request("GET", "/api/v1/hub-state", operator_token).json()
    assert after_crash["state"] == "inhibited"
    assert after_crash["last_transitions"][0]["cause_id"] == "restart"
    live.stop()
    live.start()
    after_clean = live.request("GET", "/api/v1/hub-state", operator_token).json()
    assert after_clean["state"] == "observe"
    assert after_clean["last_transitions"][0]["cause_id"] == "restart"


def _calibration(principal: dict, key: Ed25519PrivateKey, record_id: str, supersedes_id=None) -> dict:
    now = datetime.now(timezone.utc)
    body = _fixture("calibration-record.valid") | {
        "record_id": record_id,
        "supersedes_id": supersedes_id,
        "instrument_id": "hub-1",
        "operator_id": principal["id"],
        "key_id": "operator-key-1",
        "valid_from": _utc(now - timedelta(days=1)),
        "valid_until": _utc(now + timedelta(days=1)),
    }
    body["signature"] = {
        "algorithm": "Ed25519",
        "canonicalization": "poseidon-json-v1",
        "value": base64.b64encode(key.sign(payload_bytes(body))).decode("ascii"),
    }
    return body


def test_real_http_config_migration_and_immutable_digital_calibration(live: LiveFixture) -> None:
    operator_token, principal, key = _setup_control(live)
    for sequence, name in enumerate(("digital-config.v1", "digital-config.v2"), start=1):
        response = _send_command(
            live,
            operator_token,
            _command(principal, key, sequence, "config-apply", params={"config": _fixture(name)}),
        )
        assert response.status_code == 200
        assert response.json()["outcome"] == "executed"
        assert "no physical dispatch" in response.json()["reason"]
    unknown = _send_command(
        live,
        operator_token,
        _command(
            principal,
            key,
            3,
            "config-apply",
            params={"config": {"schema_version": "poseidon.digital-config.v99"}},
        ),
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "invalid_request"
    assert live.request(
        "GET", "/api/v1/command-sequence/hub-1", operator_token
    ).json()["sequence_seen"] == "2"

    first = _calibration(principal, key, "http-calibration-1")
    created = live.request("POST", "/api/v1/calibrations", operator_token, json=first)
    assert created.status_code == 201, created.text
    assert created.json()["record"]["digital_only"] is True
    assert created.json()["validity"] == "current"
    assert live.request(
        "GET", "/api/v1/calibrations/http-calibration-1", operator_token
    ).json() == created.json()
    assert live.request("POST", "/api/v1/calibrations", operator_token, json=first).status_code == 409

    second = _calibration(principal, key, "http-calibration-2", "http-calibration-1")
    assert live.request("POST", "/api/v1/calibrations", operator_token, json=second).status_code == 201
    page = live.request("GET", "/api/v1/calibrations", operator_token).json()
    assert page["total"] == 2
    assert live.request(
        "GET", "/api/v1/calibrations/http-calibration-1", operator_token
    ).json()["validity"] == "superseded"
    invalid = dict(first)
    invalid["record_id"] = "not-digital"
    invalid["digital_only"] = False
    assert live.request("POST", "/api/v1/calibrations", operator_token, json=invalid).status_code == 400
    assert live.request("POST", "/api/v1/calibrations", json=second).status_code == 403


def _session() -> dict:
    return {
        "schema_version": "poseidon.acquisition-session.v1",
        "id": "platform-context",
        "site_id": "synthetic-site",
        "device_id": "synthetic-device",
        "started_at": None,
        "ended_at": None,
        "clock_quality": {
            "status": "unknown",
            "method": "unknown",
            "uncertainty_ms": None,
            "offset_ms": None,
            "reference": None,
        },
        "provenance": {"source_kind": "synthetic", "source_id": "audio", "transport": "import"},
        "operator": "Owned synthetic HTTP fixture",
        "notes": "Digital retention integration only.",
    }


def _multipart(bundle: dict) -> dict:
    return {
        role: (
            bundle["names"][role],
            bundle["bytes"][role],
            "audio/wav" if role == "wav" else "application/json",
        )
        for role in bundle["bytes"]
    }


def _wait_job(live: LiveFixture, job_id: str) -> dict:
    return live.wait(
        f"/api/v1/jobs/{job_id}",
        lambda body: body["status"] in {"succeeded", "failed"},
        timeout=12,
    )


def test_real_http_opt_in_retention_deletes_new_media_and_companions_not_prepolicy(
    live: LiveFixture, tmp_path: Path
) -> None:
    old, eligible = _companion_fixtures.make_exports(tmp_path / "owned-exports")
    assert live.request(
        "POST",
        "/api/v1/devices",
        json=_device("synthetic-device", site_id="synthetic-site", kind="hub"),
    ).status_code == 201
    assert live.request("POST", "/api/v1/acquisition-sessions", json=_session()).status_code == 201

    imported_old = live.request(
        "POST",
        "/api/v1/acquisition-sessions/platform-context/recordings",
        files=_multipart(old),
    )
    assert imported_old.status_code == 202, imported_old.text
    assert _wait_job(live, imported_old.json()["id"])["status"] == "succeeded"

    policy_body = {
        "schema_version": "poseidon.retention-policy.v1",
        "media": {"enabled": True, "max_age_s": 1},
        "companions": {"enabled": True, "max_age_s": 1},
    }
    policy = live.request("PUT", "/api/v1/retention-policy", json=policy_body)
    assert policy.status_code == 200
    assert all(policy.json()["eligible_after"][name] is not None for name in ("media", "companions"))

    imported_new = live.request(
        "POST",
        "/api/v1/acquisition-sessions/platform-context/recordings",
        files=_multipart(eligible),
    )
    assert imported_new.status_code == 202, imported_new.text
    assert _wait_job(live, imported_new.json()["id"])["status"] == "succeeded"
    source = live.workspace / "recordings/synthetic-later/source.wav"
    manifest = live.workspace / "recordings/synthetic-later/manifest.json"
    manifest_before = manifest.read_bytes()
    assert source.exists()
    time.sleep(1.1)
    assert source.exists(), "opt-in retention must not delete without an approved plan"

    old_preview = live.request(
        "POST",
        "/api/v1/retention/preview",
        json={"recording_ids": ["synthetic-first"], "data_classes": ["media", "companions"]},
    )
    assert old_preview.status_code == 409
    assert old_preview.json()["error"]["code"] == "retention_ineligible"
    plan_response = live.request(
        "POST",
        "/api/v1/retention/preview",
        json={"recording_ids": ["synthetic-later"], "data_classes": ["media", "companions"]},
    )
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    assert plan["state"] == "preview"
    approved = live.request(
        "POST",
        f"/api/v1/retention/plans/{plan['plan_id']}/approve",
        json={"sha256": plan["sha256"]},
    )
    assert approved.json()["state"] == "approved"
    executed = live.request(
        "POST",
        f"/api/v1/retention/plans/{plan['plan_id']}/execute",
        json={"sha256": plan["sha256"]},
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["state"] == "executed"
    assert not source.exists()
    assert manifest.read_bytes() == manifest_before

    tombstones = live.request(
        "GET", "/api/v1/retention/tombstones/synthetic-later"
    ).json()["items"]
    assert {row["data_class"] for row in tombstones} == {"media", "companions"}
    assert all(row["state"] == "expired" and row["complete_evidence"] is False for row in tombstones)
    for path in (
        "/api/v1/recordings/synthetic-later",
        "/api/v1/recordings/synthetic-later/waveform",
        "/api/v1/recordings/synthetic-later/video",
        "/api/v1/recordings/synthetic-later/acquisition-companion",
        "/api/v1/recordings/synthetic-later/acquisition-companion/documents/binding",
    ):
        response = live.request("GET", path)
        assert response.status_code == 410, (path, response.text)
        assert response.json()["error"]["code"] == "evidence_expired"
    recordings = live.request("GET", "/api/v1/recordings").json()
    assert recordings["total"] == 1
    assert recordings["items"][0]["recording_id"] == "synthetic-first"
    audit = live.request("GET", "/api/v1/audit?limit=200").json()["items"]
    deletes = [row for row in audit if row["action"] == "retention.delete"]
    assert len(deletes) == 2
    assert {row["details"]["data_class"] for row in deletes} == {"media", "companions"}
    with sqlite3.connect(live.workspace / "hub.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM recording_companion_documents WHERE recording_id='synthetic-later'"
        ).fetchone()[0] == 0
        projection = connection.execute(
            "SELECT projection_bytes FROM recording_companion_imports WHERE recording_id='synthetic-later'"
        ).fetchone()[0]
        assert bytes(projection) == b""
