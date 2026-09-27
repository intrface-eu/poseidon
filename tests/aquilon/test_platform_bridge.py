"""Approved domain validation and route-shaped loopback mock, not live AEOLUS."""
from dataclasses import replace
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aquilon.adapter import ChirpStackAdapter
from aquilon.spool import SQLiteSpool
from aquilon.transport import SinkFailure, make_webhook_handler, HTTPIntegrationConfig
from aquilon.wire import Rejected
from test_aquilon import (APP, EUI, NOW, ROOT, SAMPLE, SECRET, accepted, calibration, owned_server,
                          registry, stamp, uplink)

try:
    from poseidon_proto.platform import canonical_json, validate_contract
    from aquilon.platform_bridge import (CalibrationBinding, CredentialResolver, DeviceBinding,
        DeviceCredential, MonotonicAdmissions, PlatformAPIClient, PlatformBridgeRuntime,
        PlatformBridgeSink, PlatformNormalizer, RegistrySnapshot)
except ModuleNotFoundError as error:
    if error.name != "poseidon_proto":
        raise
    SHARED_AVAILABLE = False
else:
    SHARED_AVAILABLE = True

DEVICE = "synthetic-reef-a1"
SITE = "synthetic-site-not-a-farm"
TOKEN = "SYNTHETIC-DEVICE-A1-NOT-DEPLOYED-TOKEN-0001"
TOKEN_B = "SYNTHETIC-DEVICE-B2-NOT-DEPLOYED-TOKEN-0002"


def binding(**changes):
    return replace(DeviceBinding(EUI, APP, DEVICE, SITE, "synthetic", "synthetic-reef-source-a1"), **changes)


class RouteMock:
    """Only the approved request/response shape and token scope, in local memory."""
    def __init__(self, *, lose_first_ack=False, corrupt_ack=False):
        self.records, self.requests = {}, []
        self.lose_first_ack, self.corrupt_ack = lose_first_ack, corrupt_ack

    def handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.connection.settimeout(1)
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 16384:
                    self.reply(413, {"error": {"code": "size", "message": "bounded request required"}})
                    return
                data = self.rfile.read(length)
                body = json.loads(data)
                owner.requests.append(body)
                token = self.headers.get("Authorization", "")
                if self.path != "/api/v1/telemetry":
                    self.reply(404, {})
                    return
                if token not in ("Bearer " + TOKEN, "Bearer " + TOKEN_B):
                    self.reply(401, {"error": {"code": "unauthorized", "message": "SYNTHETIC SECRET DO NOT RELAY"}})
                    return
                if (token == "Bearer " + TOKEN and body["device_id"] != DEVICE) or (
                        token == "Bearer " + TOKEN_B and body["device_id"] != "synthetic-reef-b2"):
                    self.reply(403, {"error": {"code": "scope", "message": "SYNTHETIC SECRET DO NOT RELAY"}})
                    return
                validate_contract("telemetry-envelope", body)
                key = (body["device_id"], body["boot_id"], body["sequence"])
                previous = owner.records.get(key)
                if previous is not None and previous != data:
                    self.reply(409, {"error": {"code": "telemetry_conflict", "message": "contents changed"}})
                    return
                owner.records[key] = data
                if owner.lose_first_ack:
                    owner.lose_first_ack = False
                    self.close_connection = True
                    return
                if owner.corrupt_ack:
                    body["site_id"] = "synthetic-wrong-site"
                self.reply(200, {"id": "telemetry_" + hashlib.sha256(data).hexdigest(),
                    "envelope": body, "received_at": stamp(NOW),
                    "actor_subject": "synthetic-device-principal", "duplicate": previous is not None})

            def reply(self, status, body):
                data = json.dumps(body, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return Handler


@unittest.skipUnless(SHARED_AVAILABLE, "optional bridge: add libs/proto-py/src to PYTHONPATH")
class PlatformBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aquilon-platform-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "spool.db"
        self.spool = SQLiteSpool(self.path, max_rows=4)
        self.addCleanup(self.spool.close)
        self.tick = 100.0
        self.admissions = MonotonicAdmissions(capacity=4, monotonic=lambda: self.tick)
        self.local_registry = registry()
        self.mapping = RegistrySnapshot(self.local_registry, (binding(),))
        self.normalizer = PlatformNormalizer(self.mapping)
        self.runtime = PlatformBridgeRuntime(ChirpStackAdapter(self.local_registry), self.spool, self.admissions)
        self.credentials = CredentialResolver((DeviceCredential(DEVICE, SITE, TOKEN),))

    def ingest(self, body=None):
        return self.runtime.ingest(body or uplink(), event="up", received_at=NOW)

    def client(self, address, credentials=None):
        return PlatformAPIClient(f"http://{address[0]}:{address[1]}/api/v1/telemetry",
                                 credentials or self.credentials)

    def test_exact_shared_envelope_and_raw_counts(self):
        row = accepted()
        envelope = self.normalizer.normalize(row.identity, canonical_json(row.document), delivery_age_s=2)
        self.assertEqual(validate_contract("telemetry-envelope", envelope), envelope)
        self.assertEqual(envelope["schema_version"], "poseidon.telemetry.v1")
        self.assertEqual(envelope["device_id"], DEVICE)
        self.assertEqual(envelope["site_id"], SITE)
        self.assertEqual(envelope["provenance"]["source_kind"], "synthetic")
        self.assertEqual(envelope["provenance"]["transport"], "aquilon")
        sensor = envelope["measurements"][-1]
        self.assertEqual(sensor, {"name": "temperature_raw", "value": 1234, "unit": "count",
                                  "quality": "uncalibrated", "calibration_id": None})
        self.assertEqual(envelope["measurements"][0]["value"], 3.7)
        self.assertEqual(envelope["measurements"][0]["quality"], "uncalibrated")
        self.assertIsNone(envelope["observed_at"])
        self.assertEqual(envelope["clock_quality"]["status"], "unknown")

    def test_sender_cannot_choose_site_source_device_or_measurement(self):
        row = accepted()
        row.document.update(site_id="forged-site", device_id="forged-device", source_kind="field",
                            measurements=[{"name": "forged", "value": 999}])
        row.document["sensor"]["value"] = 999
        row.document["source"].update(source_kind="field", source_id="forged")
        envelope = self.normalizer.normalize(row.identity, canonical_json(row.document), delivery_age_s=0)
        self.assertEqual(envelope["site_id"], SITE)
        self.assertEqual(envelope["device_id"], DEVICE)
        self.assertEqual(envelope["provenance"]["source_kind"], "synthetic")
        self.assertEqual(envelope["measurements"][-1]["value"], 1234)

    def test_uint64_and_clock_claim_preserved_without_utc_promotion(self):
        row = accepted(replace(SAMPLE, boot_id=2**64 - 1, clock_quality=2,
                               observed_at_unix_s=int(NOW.timestamp())))
        envelope = self.normalizer.normalize(row.identity, canonical_json(row.document), delivery_age_s=0)
        self.assertEqual(envelope["boot_id"], "18446744073709551615")
        self.assertIsNone(envelope["observed_at"])
        self.assertEqual(envelope["clock_quality"], {"status": "unknown", "method": "unknown",
                                                   "uncertainty_ms": None, "offset_ms": None, "reference": None})
        self.assertEqual(envelope["radio"]["clock_claim"], "network")
        self.assertEqual(envelope["radio"]["observed_at_unix_s"], int(NOW.timestamp()))

    def test_calibration_maps_immutable_reference_and_approved_units(self):
        for kind, value, expected, unit in ((1, 2150, 21.5, "Cel"), (2, 35125, 35.125, "1"),
                                           (3, 8123, 8123, "ug/L")):
            with self.subTest(kind=kind):
                record = calibration(sensor_kind=kind)
                local = registry(calibrations=(record,))
                name = {1: "temperature", 2: "salinity", 3: "dissolved_oxygen"}[kind]
                mapping = RegistrySnapshot(local, (binding(calibration_refs=(
                    CalibrationBinding(7, name, "synthetic-calibration-7", record.reference),)),))
                sample = replace(SAMPLE, sensor_kind=kind, sensor_quality=1, calibration_id=7,
                                 sensor_value=value, clock_quality=2, observed_at_unix_s=int(NOW.timestamp()))
                row = ChirpStackAdapter(local).parse(uplink(sample), event="up", received_at=NOW)
                envelope = PlatformNormalizer(mapping).normalize(row.identity, canonical_json(row.document), delivery_age_s=1)
                sensor = envelope["measurements"][-1]
                self.assertEqual((sensor["name"], sensor["value"], sensor["unit"]), (name, expected, unit))
                self.assertEqual(sensor["calibration_id"], "synthetic-calibration-7")
                self.assertEqual(envelope["radio"]["calibration_code"], 7)
                self.assertIsNone(envelope["observed_at"])
                with self.assertRaises(Rejected):
                    PlatformNormalizer(RegistrySnapshot(local, (binding(),))).normalize(
                        row.identity, canonical_json(row.document), delivery_age_s=1)

    def test_invalid_and_absent_sensor_do_not_fabricate_values(self):
        for kind in (0, 1, 2, 3):
            row = accepted(replace(SAMPLE, sensor_kind=kind, sensor_quality=2, sensor_value=None,
                                   battery_mv=None, solar_mv=None))
            envelope = self.normalizer.normalize(row.identity, canonical_json(row.document), delivery_age_s=0)
            self.assertTrue(all(item["value"] is None and item["quality"] == "invalid" for item in envelope["measurements"]))
            self.assertEqual(len(envelope["measurements"]), 2 if kind == 0 else 3)

    def test_ambiguous_mutable_and_wrong_calibration_mappings_reject(self):
        with self.assertRaises(ValueError):
            RegistrySnapshot(self.local_registry, (binding(), binding()))
        with self.assertRaises(ValueError):
            binding(calibration_refs=[])
        with self.assertRaises(TypeError):
            self.mapping.devices[EUI] = binding(site_id="wrong-site")
        with self.assertRaises(Rejected):
            RegistrySnapshot(self.local_registry, (binding(application_id="wrong-app"),))
        local = registry(calibrations=(calibration(),))
        for changes in ({"local_reference": "wrong-reference"}, {"sensor_kind": "salinity"}):
            ref = replace(CalibrationBinding(7, "temperature", "synthetic-cal-7", calibration().reference), **changes)
            with self.assertRaises(ValueError):
                RegistrySnapshot(local, (binding(calibration_refs=(ref,)),))
        with self.assertRaises(ValueError):
            RegistrySnapshot(local, (binding(source_kind="field", calibration_refs=(
                CalibrationBinding(7, "temperature", "synthetic-cal-7", calibration().reference),)),))

    def test_frame_identity_and_integrity_checked_with_shared_decoder(self):
        for mutation in ("identity", "boot", "digest", "frame", "application"):
            row = accepted()
            if mutation == "identity":
                row.document["identity"] += "1"
            elif mutation == "boot":
                row.document["boot_id"] = "01"
            elif mutation == "digest":
                row.document["source"]["payload_sha256"] = "0" * 64
            elif mutation == "frame":
                row.document["source"]["payload_base64"] = "oA=="
            else:
                row.document["device"]["application_id"] = "wrong-app"
            with self.subTest(mutation=mutation), self.assertRaises(Rejected):
                self.normalizer.normalize(row.identity, canonical_json(row.document), delivery_age_s=0)

    def test_authenticated_webhook_through_bridge_to_route_shaped_mock(self):
        mock = RouteMock()
        handler = make_webhook_handler(self.runtime, HTTPIntegrationConfig(SECRET), clock=lambda: NOW)
        with owned_server(handler) as hook_address, owned_server(mock.handler()) as api_address:
            connection = http.client.HTTPConnection(*hook_address, timeout=2)
            try:
                connection.request("POST", "/chirpstack?event=up", body=uplink(),
                    headers={"Content-Type": "application/json", "X-Aquilon-Integration-Key": SECRET})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read(4096)
            finally:
                connection.close()
            self.tick += 1.2
            sink = PlatformBridgeSink(self.normalizer, self.client(api_address), self.admissions, self.spool)
            self.assertEqual(self.spool.deliver_due(sink, now=NOW.timestamp()), 1)
        self.assertEqual(len(mock.records), 1)
        document = json.loads(next(iter(mock.records.values())))
        self.assertEqual(document["delivery_age_s"], 2)  # conservative ceil, not fabricated 0
        self.assertEqual(self.admissions.health()["tracked"], 0)
        self.assertEqual(self.runtime.health()["platform_ingest"], "approved-v1-loopback-client-reference")

    def test_first_dispatch_age_frozen_but_current_retry_age_rechecked(self):
        self.ingest()
        self.tick += 2.1
        mock = RouteMock(lose_first_ack=True)
        with owned_server(mock.handler()) as address:
            sink = PlatformBridgeSink(self.normalizer, self.client(address), self.admissions, self.spool)
            self.assertEqual(self.spool.deliver_due(sink, now=NOW.timestamp()), 0)
            self.assertEqual(self.admissions.health()["tracked"], 1)
            frozen = bytes(self.spool.db.execute("SELECT envelope FROM forwarding").fetchone()[0])
            self.assertEqual(frozen, next(iter(mock.records.values())))
            self.tick += 100
            with patch.object(self.normalizer, "normalize", side_effect=AssertionError("must not rebuild frozen fields")):
                self.assertEqual(self.spool.deliver_due(sink, now=NOW.timestamp() + 2), 1)
            self.assertEqual(self.spool.health()["frozen_rows"], 0)
        self.assertEqual(len(mock.records), 1)
        self.assertEqual(mock.requests[0], mock.requests[1])
        self.assertEqual(mock.requests[1]["delivery_age_s"], 3)

    def test_current_age_over_seven_days_blocks_even_with_frozen_envelope(self):
        self.ingest()
        mock = RouteMock(lose_first_ack=True)
        with owned_server(mock.handler()) as address:
            sink = PlatformBridgeSink(self.normalizer, self.client(address), self.admissions, self.spool)
            self.assertEqual(self.spool.deliver_due(sink, now=NOW.timestamp()), 0)
            frozen = bytes(self.spool.db.execute("SELECT envelope FROM forwarding").fetchone()[0])
            self.tick += 604801
            self.assertEqual(self.spool.deliver_due(sink, now=NOW.timestamp() + 2), 0)
            self.assertEqual(bytes(self.spool.db.execute("SELECT envelope FROM forwarding").fetchone()[0]), frozen)
        self.assertEqual(len(mock.requests), 1)
        self.assertEqual(self.spool.health()["rows"], 1)

    def test_recovered_rows_and_duplicates_cannot_get_new_age_zero(self):
        self.ingest()
        # New process-equivalent admission tracker starts empty, not from UTC.
        recovered = MonotonicAdmissions(capacity=4, monotonic=lambda: self.tick)
        runtime = PlatformBridgeRuntime(ChirpStackAdapter(self.local_registry), self.spool, recovered)
        self.assertEqual(runtime.ingest(uplink(), event="up", received_at=NOW)["status"], "duplicate")
        self.assertEqual(recovered.health()["tracked"], 0)
        self.assertEqual(runtime.health()["residence"]["held_without_process_time_evidence"], 1)
        mock = RouteMock()
        with owned_server(mock.handler()) as address:
            sink = PlatformBridgeSink(self.normalizer, self.client(address), recovered, self.spool)
            self.assertEqual(self.spool.deliver_due(sink, now=NOW.timestamp()), 0)
        self.assertEqual(len(mock.requests), 0)
        self.assertEqual(self.spool.health()["rows"], 1)

    def test_monotonic_regression_latches_lost_evidence(self):
        self.ingest()
        self.tick = 99
        row = accepted()
        with self.assertRaisesRegex(SinkFailure, "time_basis_lost"):
            self.admissions.prepare(row.identity, canonical_json(row.document), self.normalizer)
        self.tick = 200
        with self.assertRaisesRegex(SinkFailure, "time_basis_lost"):
            self.admissions.begin()
        self.assertEqual(self.admissions.health()["time_basis"], "lost")

    def test_admission_capacity_duplicate_age_and_full_spool(self):
        first = self.ingest()
        self.tick += 10
        self.assertEqual(self.ingest()["status"], "duplicate")
        row = accepted()
        envelope = self.admissions.prepare(row.identity, canonical_json(row.document), self.normalizer)
        self.assertEqual(envelope["delivery_age_s"], 10)
        for sequence in (1, 2, 3):
            self.ingest(uplink(replace(SAMPLE, sequence=sequence)))
        with self.assertRaises(Rejected):
            self.ingest(uplink(replace(SAMPLE, sequence=4)))
        self.assertEqual(self.admissions.health()["tracked"], 4)
        with self.assertRaisesRegex(SinkFailure, "cannot_reset"):
            self.admissions.admit_new(first["identity"], self.tick)
        with self.assertRaises(ValueError):
            PlatformBridgeRuntime(ChirpStackAdapter(self.local_registry), self.spool, MonotonicAdmissions(capacity=5))

    def test_missing_wrong_site_disabled_and_reused_credentials_fail_closed(self):
        for credentials in ((), (DeviceCredential(DEVICE, "wrong-site", TOKEN),),
                            (DeviceCredential(DEVICE, SITE, TOKEN, enabled=False),)):
            with self.subTest(credentials=credentials), self.assertRaises(SinkFailure):
                CredentialResolver(credentials).resolve(DEVICE, SITE)
        with self.assertRaises(ValueError):
            CredentialResolver((DeviceCredential(DEVICE, SITE, TOKEN), DeviceCredential("other-device", SITE, TOKEN)))
        self.assertNotIn(TOKEN, repr(DeviceCredential(DEVICE, SITE, TOKEN)))
        self.assertNotIn(TOKEN, repr(self.credentials))

    def test_mock401_and403_do_not_leak_credentials_or_drop_spool(self):
        self.ingest()
        for token in ("SYNTHETIC-UNKNOWN-CREDENTIAL-NOT-DEPLOYED", TOKEN_B):
            mock = RouteMock()
            credentials = CredentialResolver((DeviceCredential(DEVICE, SITE, token),))
            with owned_server(mock.handler()) as address:
                sink = PlatformBridgeSink(self.normalizer, self.client(address, credentials), self.admissions, self.spool)
                row = accepted()
                with self.assertRaises(SinkFailure) as error:
                    sink.send(row.identity, canonical_json(row.document))
                self.assertNotIn(token, str(error.exception))
                self.assertNotIn("SECRET", str(error.exception))
            self.assertEqual(len(mock.records), 0)
            self.assertEqual(self.admissions.health()["tracked"], 1)
        self.assertEqual(self.spool.health()["rows"], 1)

    def test_freeze_write_commit_or_budget_failure_prevents_network_send(self):
        self.ingest()
        row = accepted()
        source = bytes(self.spool.db.execute("SELECT body FROM spool").fetchone()[0])
        original_limit = self.spool.max_bytes
        original_bytes = self.spool.health()["bytes"]
        mock = RouteMock()
        with owned_server(mock.handler()) as address:
            sink = PlatformBridgeSink(self.normalizer, self.client(address), self.admissions, self.spool)
            for mode in ("insert", "commit", "budget"):
                with self.subTest(mode=mode):
                    if mode == "insert":
                        self.spool.db.execute("""CREATE TEMP TRIGGER synthetic_freeze_failure BEFORE INSERT ON forwarding
                            BEGIN SELECT RAISE(ABORT,'synthetic freeze write failure'); END""")
                    elif mode == "commit":
                        self.spool.db.set_authorizer(lambda action, first, *_:
                            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT"
                            else sqlite3.SQLITE_OK)
                    else:
                        self.spool.max_bytes = original_bytes
                    try:
                        with self.assertRaises((sqlite3.Error, Rejected)):
                            sink.send(row.identity, source)
                    finally:
                        self.spool.db.set_authorizer(None)
                        self.spool.db.execute("DROP TRIGGER IF EXISTS synthetic_freeze_failure")
                        self.spool.max_bytes = original_limit
                    self.assertEqual(mock.requests, [])
                    self.assertEqual(self.spool.health()["frozen_rows"], 0)
                    self.assertEqual(self.spool.health()["bytes"], original_bytes)
                    self.assertEqual(self.spool.health()["rows"], 1)

    def test_http_ack_loss_then_process_exit_preserves_freeze_and_recovery_hold(self):
        path = Path(self.temp.name) / "child-spool.sqlite3"
        fixture = Path(self.temp.name) / "synthetic-child-uplink.json"
        fixture.write_bytes(uplink())
        program = """
import os, sys
from pathlib import Path
from aquilon.adapter import ChirpStackAdapter, Device, LocalRegistry, parse_time
from aquilon.spool import SQLiteSpool
from aquilon.platform_bridge import (RegistrySnapshot, DeviceBinding, CredentialResolver,
    DeviceCredential, MonotonicAdmissions, PlatformNormalizer, PlatformAPIClient,
    PlatformBridgeRuntime, PlatformBridgeSink)
eui, app = '00000000000000a1', '00000000-0000-4000-8000-000000000001'
device, site = 'synthetic-reef-a1', 'synthetic-site-not-a-farm'
local = LocalRegistry([Device(eui, app)])
mapping = RegistrySnapshot(local, (DeviceBinding(eui, app, device, site, 'synthetic', 'synthetic-reef-source-a1'),))
credentials = CredentialResolver((DeviceCredential(device, site, 'SYNTHETIC-DEVICE-A1-NOT-DEPLOYED-TOKEN-0001'),))
spool = SQLiteSpool(sys.argv[1], max_rows=4)
tick = [100.0]
admissions = MonotonicAdmissions(capacity=4, monotonic=lambda: tick[0])
runtime = PlatformBridgeRuntime(ChirpStackAdapter(local), spool, admissions)
received = parse_time(sys.argv[4])
runtime.ingest(Path(sys.argv[2]).read_bytes(), event='up', received_at=received)
tick[0] += 3.5
sink = PlatformBridgeSink(PlatformNormalizer(mapping), PlatformAPIClient(sys.argv[3], credentials), admissions, spool)
if spool.deliver_due(sink, now=received.timestamp()) != 0:
    os._exit(99)
os._exit(17)  # Deliberate abrupt exit: no connection/spool finally or close.
"""
        mock = RouteMock(lose_first_ack=True)
        with owned_server(mock.handler()) as address:
            endpoint = f"http://{address[0]}:{address[1]}/api/v1/telemetry"
            result = subprocess.run([sys.executable, "-c", program, str(path), str(fixture), endpoint, stamp(NOW)],
                env=dict(os.environ, PYTHONPATH=f"{ROOT / 'apps/aquilon/src'}:{ROOT / 'libs/proto-py/src'}",
                         PYTHONDONTWRITEBYTECODE="1"), capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertEqual(len(mock.records), 1)
            attempted = next(iter(mock.records.values()))
            with SQLiteSpool(path, max_rows=4) as reopened:
                stored = reopened.db.execute("SELECT identity,source_digest,envelope FROM forwarding").fetchone()
                source = bytes(reopened.db.execute("SELECT body FROM spool").fetchone()[0])
                self.assertEqual(bytes(stored["envelope"]), attempted)
                self.assertEqual(stored["source_digest"], hashlib.sha256(source).hexdigest())
                self.assertEqual(json.loads(attempted)["delivery_age_s"], 4)
                recovered = MonotonicAdmissions(capacity=4, monotonic=lambda: 1000.0)
                runtime = PlatformBridgeRuntime(ChirpStackAdapter(self.local_registry), reopened, recovered)
                sink = PlatformBridgeSink(self.normalizer, self.client(address), recovered, reopened)
                self.assertEqual(reopened.deliver_due(sink, now=NOW.timestamp() + 2), 0)
                self.assertEqual(runtime.health()["residence"]["held_without_process_time_evidence"], 1)
                self.assertEqual(reopened.health()["frozen_rows"], 1)
                self.assertEqual(bytes(reopened.db.execute("SELECT envelope FROM forwarding").fetchone()[0]), attempted)
                with patch.object(self.normalizer, "normalize", side_effect=AssertionError("no rebuild after restart")):
                    self.assertEqual(reopened.freeze_forwarding(stored["identity"], source,
                        lambda: canonical_json(self.normalizer.normalize(stored["identity"], source, delivery_age_s=0))), attempted)
            self.assertEqual(len(mock.requests), 1)

    def test_api_client_rejects_mismatched_ack_and_nonlocal_route(self):
        self.ingest()
        mock = RouteMock(corrupt_ack=True)
        with owned_server(mock.handler()) as address:
            sink = PlatformBridgeSink(self.normalizer, self.client(address), self.admissions, self.spool)
            self.assertEqual(self.spool.deliver_due(sink, now=NOW.timestamp()), 0)
        self.assertEqual(self.admissions.health()["tracked"], 1)
        for endpoint in ("http://example.com:8080/api/v1/telemetry", "http://localhost:8080/api/v1/telemetry",
                         "http://127.0.0.1:8080/wrong-route"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                PlatformAPIClient(endpoint, self.credentials)


if __name__ == "__main__":
    unittest.main()
