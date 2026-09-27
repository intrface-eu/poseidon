"""Wave2: actual repository Hub/FastAPI over owned loopback Uvicorn sockets.

Separate discovery root; no __init__.py and no fallback to API-shaped mocks.
Generated credentials belong only to newly created temporary workspaces.
"""
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import http.client
from http.server import HTTPServer
from importlib.metadata import version
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import uvicorn
from poseidon_api import create_app
from poseidon_proto.platform import canonical_json, validate_contract
from poseidon_trident import Hub

from aquilon.adapter import Calibration, ChirpStackAdapter, Device, LocalRegistry, stamp
from aquilon.platform_bridge import (CalibrationBinding, CredentialResolver, DeviceBinding,
    DeviceCredential, MonotonicAdmissions, PlatformAPIClient, PlatformBridgeRuntime,
    PlatformBridgeSink, PlatformNormalizer, RegistrySnapshot)
from aquilon.spool import SQLiteSpool
from aquilon.transport import HTTPIntegrationConfig, SinkFailure, make_webhook_handler
from aquilon.wire import Telemetry, encode_payload

ROOT = Path(__file__).resolve().parents[3]
EUI = "00000000000000a1"
APP = "00000000-0000-4000-8000-000000000001"
DEVICE = "synthetic-wave2-reef-a1"
SITE = "synthetic-wave2-site-not-a-farm"
SOURCE = "synthetic-wave2-radio-source-a1"
CALIBRATION = "synthetic-wave2-calibration-not-a-certificate"
WEBHOOK_SECRET = "SYNTHETIC-WAVE2-NOT-DEPLOYED-WEBHOOK-SECRET"


def uplink(received, *, sequence=0, boot=1, clock_quality=0, calibrated=False):
    frame = Telemetry(1, boot, sequence, 42, clock_quality,
        int(received.timestamp()) if clock_quality else None, 3700, 5000, 0,
        1, 2150 if calibrated else 1234, 1 if calibrated else 0, 7 if calibrated else None)
    return canonical_json({"time": stamp(received), "deviceInfo": {
        "devEui": EUI, "applicationId": APP, "deviceName": "SYNTHETIC-WAVE2-NOT-DEPLOYED"},
        "fPort": 10, "data": base64.b64encode(encode_payload(frame)).decode("ascii"),
        "fCnt": sequence, "confirmed": False})


def compose(spool, credential, received, monotonic):
    local = LocalRegistry((Device(EUI, APP),), (Calibration(EUI, 7, 1, CALIBRATION,
        received - timedelta(days=1), received + timedelta(days=1), approved=True, synthetic=True),))
    mappings = RegistrySnapshot(local, (DeviceBinding(EUI, APP, DEVICE, SITE, "synthetic", SOURCE,
        (CalibrationBinding(7, "temperature", CALIBRATION, CALIBRATION),)),))
    admissions = MonotonicAdmissions(capacity=spool.max_rows, monotonic=monotonic)
    runtime = PlatformBridgeRuntime(ChirpStackAdapter(local), spool, admissions)
    normalizer = PlatformNormalizer(mappings)
    credentials = CredentialResolver((DeviceCredential(DEVICE, SITE, credential),))
    return runtime, normalizer, admissions, credentials


def request(address, method, path, *, token=None, body=None, timeout=2):
    """Real finite HTTP request, no redirects/proxies and no credential logging."""
    connection = http.client.HTTPConnection(address[0], address[1], timeout=timeout)
    try:
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            headers["Content-Type"] = "application/json"
            if type(body) is not bytes:
                body = canonical_json(body)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read(65537)
        if len(data) > 65536:
            raise AssertionError("owned API response exceeded test bound")
        return response.status, json.loads(data) if data else None
    finally:
        connection.close()


class OwnedAPI:
    """Actual create_app/Hub in an owned Uvicorn child, never an API substitute."""
    def __init__(self, workspace):
        self.workspace = workspace
        self.process = None
        self.address = None
        self._stderr = None
        self.log_path = workspace.parent / "owned-api.stderr"

    def __enter__(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Port-zero bind atomically selects and reserves a free numeric
            # loopback port. Only this descriptor is inherited by our child.
            listener.bind(("127.0.0.1", 0))
            listener.listen(32)
            self.address = listener.getsockname()
            self._stderr = self.log_path.open("xb")
            self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                "--serve-api", str(self.workspace), str(listener.fileno())],
                pass_fds=(listener.fileno(),), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=self._stderr, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        except BaseException:
            self.close()
            raise
        finally:
            listener.close()
        try:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise AssertionError("owned actual API exited during startup; inspect owned stderr")
                try:
                    status, body = request(self.address, "GET", "/healthz", timeout=0.2)
                    if status == 200 and body == {"status": "ok"}:
                        return self
                except (OSError, http.client.HTTPException):
                    pass
                threading.Event().wait(0.02)
            raise AssertionError("owned actual API startup exceeded 12 seconds")
        except BaseException:
            self.close()
            raise

    def close(self):
        forced = False
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()  # Precise owned PID; Uvicorn handles SIGTERM.
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    forced = True
                    self.process.kill()
                    self.process.wait(timeout=2)
            if self.process is not None and self.process.poll() is None:
                raise AssertionError("owned API process was not reaped")
        finally:
            if self._stderr is not None:
                self._stderr.close()
        if forced:
            raise AssertionError("owned API exceeded graceful shutdown deadline; owned child was killed/reaped")

    def __exit__(self, *_):
        self.close()
        # Reacquiring the real Hub's exclusive workspace checks lock release.
        with Hub(self.workspace):
            pass


class TrackedWebhookServer(HTTPServer):
    def __init__(self, *args, **kwargs):
        self._owned_connections = set()
        self._connection_lock = threading.Lock()
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        with self._connection_lock:
            self._owned_connections.add(connection)
        return connection, address

    def close_request(self, connection):
        with self._connection_lock:
            self._owned_connections.discard(connection)
        super().close_request(connection)

    def interrupt_owned_connections(self):
        with self._connection_lock:
            connections = tuple(self._owned_connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()


@contextmanager
def owned_webhook(runtime, received):
    handler = make_webhook_handler(runtime, HTTPIntegrationConfig(WEBHOOK_SECRET, timeout_seconds=1),
                                   clock=lambda: received)
    server = TrackedWebhookServer(("127.0.0.1", 0), handler)
    ready = threading.Event()

    def run():
        ready.set()
        server.serve_forever(poll_interval=0.02)

    thread = threading.Thread(target=run, name="owned-aquilon-webhook", daemon=True)
    thread.start()
    try:
        if not ready.wait(1):
            raise AssertionError("owned webhook startup deadline")
        yield server.server_address
    finally:
        stop = threading.Thread(target=server.shutdown, name="owned-webhook-shutdown", daemon=True)
        stop.start()
        stop.join(timeout=2)
        if stop.is_alive():
            server.interrupt_owned_connections()
        server.server_close()
        stop.join(timeout=2)
        thread.join(timeout=2)
        if stop.is_alive() or thread.is_alive():
            raise AssertionError("owned webhook shutdown exceeded deadline")


def post_webhook(address, body):
    connection = http.client.HTTPConnection(*address, timeout=2)
    try:
        connection.request("POST", "/chirpstack?event=up", body=body,
            headers={"Content-Type": "application/json", "X-Aquilon-Integration-Key": WEBHOOK_SECRET})
        response = connection.getresponse()
        return response.status, json.loads(response.read(4096))
    finally:
        connection.close()


class AfterRealAcceptance:
    """Fault boundary: calls real transport first, never creates a success reply."""
    def __init__(self, transport, callback):
        self.transport, self.callback = transport, callback
        self.accepted_bytes = []
        self.replies = []

    def post(self, body, headers, **kwargs):
        response = self.transport.post(body, headers, **kwargs)
        if canonical_json(validate_contract("telemetry-envelope", response["envelope"])) != body:
            raise AssertionError("real API did not acknowledge the exact attempted envelope")
        self.accepted_bytes.append(body)
        self.replies.append(response)
        self.callback()
        return response


class RealAPIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aquilon-real-api-wave2-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "new-api-workspace"
        # Never read any existing service credential; create and close a new Hub
        # before create_app's actual lifespan takes exclusive workspace ownership.
        with Hub(self.workspace) as hub:
            self.admin = hub.access_token()
        self.api = OwnedAPI(self.workspace)
        self.api.__enter__()
        self.addCleanup(self.api.__exit__, None, None, None)
        self.received = datetime.now(timezone.utc)
        self.tick = 100.0
        self.register(DEVICE, SITE, EUI)
        self.issued = self.issue(DEVICE, SITE)
        self.token = self.issued["token"]
        self.spool = SQLiteSpool(self.root / "aquilon.sqlite3", max_rows=8)
        self.addCleanup(self.spool.close)
        self.runtime, self.normalizer, self.admissions, self.credentials = compose(
            self.spool, self.token, self.received, lambda: self.tick)
        self.client = PlatformAPIClient(self.endpoint, self.credentials, timeout_seconds=2)
        self.sink = PlatformBridgeSink(self.normalizer, self.client, self.admissions, self.spool)

    @property
    def endpoint(self):
        return f"http://{self.api.address[0]}:{self.api.address[1]}/api/v1/telemetry"

    def api_request(self, method, suffix, *, token=None, body=None):
        return request(self.api.address, method, "/api/v1" + suffix,
                       token=self.admin if token is None else token, body=body)

    def register(self, device, site, eui):
        status, result = self.api_request("POST", "/devices", body={"id": device, "site_id": site,
            "label": "Synthetic wave2 real API test, not deployed", "kind": "reef",
            "hardware_revision": "synthetic-wave2-reference", "source_kind": "synthetic"})
        self.assertEqual(status, 201)
        self.assertEqual((result["id"], result["site_id"], result["source_kind"]), (device, site, "synthetic"))
        mapping = {"dev_eui": eui, "calibration_refs": [{"code": 7, "sensor_kind": "temperature",
                                                       "calibration_id": CALIBRATION}]}
        status, result = self.api_request("PUT", f"/devices/{device}/aquilon-mapping", body=mapping)
        self.assertEqual(status, 200)
        self.assertEqual(result, mapping)

    def issue(self, device, site):
        status, issued = self.api_request("POST", "/principals", body={"subject": "synthetic-principal-" + device,
            "role": "device", "site_ids": [site], "device_id": device})
        self.assertEqual(status, 201)
        self.assertEqual(issued["principal"]["device_id"], device)
        return issued

    def enqueue_webhook(self, **fields):
        with owned_webhook(self.runtime, self.received) as address:
            status, result = post_webhook(address, uplink(self.received, **fields))
            self.assertEqual(status, 200)
            self.assertEqual(result["status"], "accepted")
            return result["identity"]

    def stored(self):
        # Read-only platform database query is independent of AQUILON state and
        # API return data. No direct fixture insertion or mutation of Hub tables.
        database = self.workspace / "hub.sqlite3"
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            rows = connection.execute("SELECT envelope_json,received_at,actor_subject FROM telemetry ORDER BY id").fetchall()
        return [{"envelope": json.loads(body), "received_at": received, "actor_subject": actor}
                for body, received, actor in rows]

    def frozen(self):
        row = self.spool.db.execute("SELECT envelope FROM forwarding").fetchone()
        return bytes(row[0]) if row else None

    def test_locked_api_runtime_versions(self):
        expected = {"fastapi": "0.141.1", "uvicorn": "0.52.4", "cryptography": "46.0.3",
                    "pydantic-core": "2.46.5", "httpx": "0.28.1", "pytest": "9.1.1"}
        self.assertEqual({package: version(package) for package in expected}, expected)

    def test_real_raw_uint64_and_clock_claims_roundtrip(self):
        for sequence, clock in ((0, 0), (1, 2)):
            self.enqueue_webhook(sequence=sequence, boot=2**64 - 1, clock_quality=clock)
            self.tick += 1.2
            self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp()), 1)
        rows = self.stored()
        self.assertEqual(len(rows), 2)
        rows.sort(key=lambda item: item["envelope"]["sequence"])
        for sequence, row in enumerate(rows):
            envelope = row["envelope"]
            self.assertEqual(envelope["boot_id"], "18446744073709551615")
            self.assertEqual((envelope["device_id"], envelope["site_id"]), (DEVICE, SITE))
            self.assertEqual(envelope["provenance"], {"source_kind": "synthetic", "source_id": SOURCE, "transport": "aquilon"})
            self.assertEqual(envelope["measurements"][-1], {"name": "temperature_raw", "value": 1234,
                "unit": "count", "quality": "uncalibrated", "calibration_id": None})
            self.assertIsNone(envelope["observed_at"])
            self.assertEqual(envelope["clock_quality"]["status"], "unknown")
            self.assertEqual(envelope["radio"]["clock_claim"], "unsynchronized" if sequence == 0 else "network")
            self.assertEqual(envelope["radio"]["observed_at_unix_s"], None if sequence == 0 else int(self.received.timestamp()))
            self.assertEqual(envelope["delivery_age_s"], 2)
            self.assertEqual(row["actor_subject"], self.issued["principal"]["subject"])
        status, page = self.api_request("GET", "/telemetry", token=self.token)
        self.assertEqual((status, page["total"]), (200, 2))
        self.assertEqual((self.spool.health()["rows"], self.spool.health()["frozen_rows"]), (0, 0))
        self.assertEqual(self.admissions.health()["tracked"], 0)

    def test_real_calibration_mapping_preserves_claim_and_units(self):
        self.enqueue_webhook(calibrated=True, clock_quality=1)
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp()), 1)
        envelope = self.stored()[0]["envelope"]
        self.assertEqual(envelope["measurements"][-1], {"name": "temperature", "value": 21.5,
            "unit": "Cel", "quality": "calibrated", "calibration_id": CALIBRATION})
        self.assertIsNone(envelope["observed_at"])
        self.assertEqual(envelope["radio"]["clock_claim"], "rtc")
        self.assertEqual(envelope["radio"]["calibration_code"], 7)
        status, mapping = self.api_request("GET", f"/devices/{DEVICE}/aquilon-mapping", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(mapping["calibration_refs"][0]["calibration_id"], CALIBRATION)

    def test_real_identical_retry_conflict_and_admin_ingest_denial(self):
        self.enqueue_webhook()
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp()), 1)
        envelope = self.stored()[0]["envelope"]
        status, duplicate = self.api_request("POST", "/telemetry", token=self.token, body=canonical_json(envelope))
        self.assertEqual(status, 200)
        self.assertTrue(duplicate["duplicate"])
        conflict = json.loads(canonical_json(envelope))
        conflict["measurements"][-1]["value"] += 1
        status, rejected = self.api_request("POST", "/telemetry", token=self.token, body=conflict)
        self.assertEqual((status, rejected["error"]["code"]), (409, "telemetry_conflict"))
        self.assertEqual(self.api_request("POST", "/telemetry", body=envelope)[0], 403)
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(self.spool.health()["rows"], 0)

    def test_wrong_device_and_site_scope_keeps_spool_until_correct_token(self):
        self.register("synthetic-wave2-reef-b2", "synthetic-wave2-other-site", "00000000000000b2")
        other = self.issue("synthetic-wave2-reef-b2", "synthetic-wave2-other-site")
        wrong = CredentialResolver((DeviceCredential(DEVICE, SITE, other["token"]),))
        self.sink.client = PlatformAPIClient(self.endpoint, wrong)
        self.enqueue_webhook()
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp()), 0)
        frozen = self.frozen()
        status, rejected = self.api_request("POST", "/telemetry", token=other["token"], body=frozen)
        # The actual Hub deliberately conceals out-of-site/device resources.
        self.assertEqual((status, rejected["error"]["code"]), (404, "not_found"))
        self.register("synthetic-wave2-reef-c3", SITE, "00000000000000c3")
        same_site_other_device = self.issue("synthetic-wave2-reef-c3", SITE)
        status, rejected = self.api_request("POST", "/telemetry", token=same_site_other_device["token"], body=frozen)
        self.assertEqual((status, rejected["error"]["code"]), (404, "not_found"))
        self.assertEqual(len(self.stored()), 0)
        self.assertEqual(self.spool.health()["rows"], 1)
        self.assertEqual(self.admissions.health()["tracked"], 1)
        self.sink.client = self.client
        self.tick += 3
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp() + 2), 1)
        self.assertEqual(canonical_json(self.stored()[0]["envelope"]), frozen)
        self.assertEqual(self.spool.health()["rows"], 0)

    def test_revoked_principal_rejects_real_delivery_without_dropping_source(self):
        self.enqueue_webhook()
        principal = self.issued["principal"]["id"]
        self.assertEqual(self.api_request("POST", f"/principals/{principal}/revoke")[0], 200)
        self.assertEqual(self.api_request("GET", "/identity", token=self.token)[0], 401)
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp()), 0)
        self.assertEqual(len(self.stored()), 0)
        self.assertEqual((self.spool.health()["rows"], self.spool.health()["frozen_rows"]), (1, 1))
        self.assertFalse(self.token.encode() in self.frozen(), "credential leaked into frozen envelope")

    def test_device_revocation_is_actual_disable_and_cascades_principal(self):
        self.enqueue_webhook()
        status, device = self.api_request("POST", f"/devices/{DEVICE}/revoke")
        self.assertEqual(status, 200)
        self.assertIsNotNone(device["revoked_at"])
        self.assertEqual(self.api_request("GET", "/identity", token=self.token)[0], 401)
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp()), 0)
        status, device = self.api_request("GET", f"/devices/{DEVICE}")
        self.assertEqual(status, 200)
        self.assertIsNotNone(device["revoked_at"])
        self.assertEqual(len(self.stored()), 0)
        self.assertEqual(self.spool.health()["rows"], 1)

    def test_real_credential_rotation_retries_frozen_bytes_with_new_token(self):
        self.enqueue_webhook()
        principal = self.issued["principal"]["id"]
        status, rotated = self.api_request("POST", f"/principals/{principal}/rotate")
        self.assertEqual(status, 200)
        replacement = rotated["token"]
        self.assertFalse(replacement == self.token, "rotation did not replace the credential")
        self.assertEqual(self.api_request("GET", "/identity", token=self.token)[0], 401)
        self.assertEqual(self.api_request("GET", "/identity", token=replacement)[0], 200)
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp()), 0)
        frozen = self.frozen()
        self.assertEqual(len(self.stored()), 0)
        credentials = CredentialResolver((DeviceCredential(DEVICE, SITE, replacement),))
        self.sink.client = PlatformAPIClient(self.endpoint, credentials)
        self.tick += 3
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp() + 2), 1)
        self.assertEqual(canonical_json(self.stored()[0]["envelope"]), frozen)
        self.assertFalse(self.token.encode() in frozen, "old credential leaked into frozen envelope")
        self.assertFalse(replacement.encode() in frozen, "rotated credential leaked into frozen envelope")
        self.assertEqual((self.spool.health()["rows"], self.admissions.health()["tracked"]), (0, 0))

    def test_real_acceptance_response_loss_then_exact_same_process_retry(self):
        self.enqueue_webhook()
        remaining = [1]

        def lose_once():
            if remaining[0]:
                remaining[0] = 0
                raise OSError("synthetic response loss after real API committed")

        fault = AfterRealAcceptance(self.client._transport, lose_once)
        self.client._transport = fault
        self.tick += 1.1
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp()), 0)
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(self.spool.health()["rows"], 1)
        frozen = self.frozen()
        self.assertEqual(frozen, fault.accepted_bytes[0])
        self.assertEqual(frozen, canonical_json(self.stored()[0]["envelope"]))
        self.tick += 20
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp() + 2), 1)
        self.assertEqual(fault.accepted_bytes, [frozen, frozen])
        self.assertFalse(fault.replies[0]["duplicate"])
        self.assertTrue(fault.replies[1]["duplicate"])
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual((self.spool.health()["rows"], self.spool.health()["frozen_rows"]), (0, 0))

    def local_completion_fault(self, mode):
        self.enqueue_webhook()
        transport = self.client._transport

        def arm_after_accept():
            if mode == "delete":
                self.spool.db.execute("""CREATE TEMP TRIGGER synthetic_delete_failure BEFORE DELETE ON spool
                    BEGIN SELECT RAISE(ABORT,'synthetic post-accept delete failure'); END""")
            else:
                self.spool.db.set_authorizer(lambda action, first, *_:
                    sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT"
                    else sqlite3.SQLITE_OK)

        fault = AfterRealAcceptance(transport, arm_after_accept)
        self.client._transport = fault
        try:
            with self.assertRaises(sqlite3.Error):
                self.spool.deliver_due(self.sink, now=self.received.timestamp())
        finally:
            self.spool.db.set_authorizer(None)
            self.spool.db.execute("DROP TRIGGER IF EXISTS synthetic_delete_failure")
            self.client._transport = transport
        self.assertEqual(len(self.stored()), 1)
        frozen = self.frozen()
        self.assertEqual(frozen, fault.accepted_bytes[0])
        self.assertEqual(self.spool.health()["rows"], 1)
        self.assertEqual(self.spool.health()["counters"]["delivered"], 0)
        self.assertEqual(self.admissions.health()["tracked"], 1)
        self.assertEqual(self.runtime.health()["residence"]["held_without_process_time_evidence"], 0)
        replay = AfterRealAcceptance(transport, lambda: None)
        self.client._transport = replay
        self.tick += 10
        self.assertEqual(self.spool.deliver_due(self.sink, now=self.received.timestamp() + 2), 1)
        self.assertEqual(replay.accepted_bytes, [frozen])
        self.assertTrue(replay.replies[0]["duplicate"])
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual((self.spool.health()["rows"], self.spool.health()["frozen_rows"]), (0, 0))
        self.assertEqual(self.spool.health()["counters"]["delivered"], 1)
        self.assertEqual(self.admissions.health()["tracked"], 0)

    def test_real_acceptance_then_local_delete_rollback_preserves_residence(self):
        self.local_completion_fault("delete")

    def test_real_acceptance_then_local_commit_rollback_preserves_residence(self):
        self.local_completion_fault("commit")

    def test_real_acceptance_lost_response_process_death_and_reopen_hold(self):
        child_spool = self.root / "abrupt-child-aquilon.sqlite3"
        packet_path = self.root / "owned-child-private-input.json"
        packet = {"spool": str(child_spool), "endpoint": self.endpoint, "token": self.token,
                  "received_at": stamp(self.received)}
        descriptor = os.open(packet_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical_json(packet))
        # No credentials in argv, environment, logs, reports, or golden fixtures.
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--crash-after-real-accept", str(packet_path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=15)
        self.assertEqual(result.returncode, 29, "owned crash worker failed before expected interruption")
        packet_path.unlink()
        rows = self.stored()
        self.assertEqual(len(rows), 1)
        with SQLiteSpool(child_spool, max_rows=8) as reopened:
            frozen = reopened.db.execute("SELECT identity,source_digest,envelope FROM forwarding").fetchone()
            self.assertIsNotNone(frozen)
            source = bytes(reopened.db.execute("SELECT body FROM spool").fetchone()[0])
            attempted = bytes(frozen["envelope"])
            self.assertEqual(attempted, canonical_json(rows[0]["envelope"]))
            self.assertEqual(frozen["source_digest"], hashlib.sha256(source).hexdigest())
            self.assertEqual(rows[0]["envelope"]["delivery_age_s"], 4)
            runtime, normalizer, admissions, credentials = compose(reopened, self.token, self.received, lambda: 9000.0)
            client = PlatformAPIClient(self.endpoint, credentials)
            observed = AfterRealAcceptance(client._transport, lambda: None)
            client._transport = observed
            sink = PlatformBridgeSink(normalizer, client, admissions, reopened)
            self.assertEqual(reopened.deliver_due(sink, now=self.received.timestamp() + 2), 0)
            self.assertEqual(observed.accepted_bytes, [])
            self.assertEqual(runtime.health()["residence"]["held_without_process_time_evidence"], 1)
            self.assertEqual((reopened.health()["rows"], reopened.health()["frozen_rows"]), (1, 1))
            self.assertEqual(bytes(reopened.db.execute("SELECT envelope FROM forwarding").fetchone()[0]), attempted)
        self.assertEqual(len(self.stored()), 1)


def serve_api(workspace, descriptor):
    listener = socket.socket(fileno=int(descriptor))
    try:
        app = create_app(Path(workspace), start_worker=False)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, loop="asyncio", http="h11",
            ws="none", lifespan="on", access_log=False, log_level="critical", log_config=None,
            timeout_keep_alive=1, timeout_graceful_shutdown=2, limit_concurrency=16))
        server.run(sockets=[listener])
    finally:
        listener.close()


def crash_after_real_accept(packet_path):
    with Path(packet_path).open("rb") as source:
        raw = source.read(8193)
    if len(raw) > 8192:
        raise ValueError("owned child input bound")
    packet = json.loads(raw)
    received = datetime.fromisoformat(packet["received_at"].replace("Z", "+00:00"))
    spool = SQLiteSpool(packet["spool"], max_rows=8)
    tick = [100.0]
    runtime, normalizer, admissions, credentials = compose(spool, packet["token"], received, lambda: tick[0])
    client = PlatformAPIClient(packet["endpoint"], credentials)

    def drop_real_ack():
        raise OSError("synthetic response loss after actual platform acceptance")

    client._transport = AfterRealAcceptance(client._transport, drop_real_ack)
    sink = PlatformBridgeSink(normalizer, client, admissions, spool)
    with owned_webhook(runtime, received) as address:
        status, _ = post_webhook(address, uplink(received, boot=2**64 - 1, clock_quality=2))
        if status != 200:
            os._exit(91)
        tick[0] += 3.5
        if spool.deliver_due(sink, now=received.timestamp()) != 0 or len(client._transport.accepted_bytes) != 1:
            os._exit(92)
        os._exit(29)  # Required interruption, no Python finally; OS closes owned child descriptors.


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve-api":
        serve_api(sys.argv[2], sys.argv[3])
    elif len(sys.argv) > 1 and sys.argv[1] == "--crash-after-real-accept":
        crash_after_real_accept(sys.argv[2])
    else:
        unittest.main()
