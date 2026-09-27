"""Synthetic local protocol/storage evidence only. No live ChirpStack or radio."""
import base64
from contextlib import closing, contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import random
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from aquilon.adapter import (MAX_JSON_BYTES, Calibration, ChirpStackAdapter, ClockPolicy,
                             Device, LocalRegistry, bounded_json, stamp)
from aquilon.runtime import AquilonRuntime
from aquilon.spool import RetryPolicy, SQLiteSpool, SpoolFull
from aquilon.transport import HTTPIntegrationConfig, LocalHTTPSink, SinkFailure, make_webhook_handler
from aquilon.wire import Rejected, Telemetry, decode_payload, encode_payload

ROOT = Path(__file__).resolve().parents[2]
EUI = "00000000000000a1"
APP = "00000000-0000-4000-8000-000000000001"
SECRET = "SYNTHETIC-NOT-A-DEPLOYED-SECRET-000001"
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
SAMPLE = Telemetry(1, 1, 0, 42, 0, None, 3700, 5000, 0, 1, 1234, 0, None)


def registry(*, enabled=True, calibrations=()):
    return LocalRegistry([Device(EUI, APP, enabled=enabled)], calibrations)


def calibration(**changes):
    record = Calibration(EUI, 7, 1, "SYNTHETIC-REFERENCE-NOT-A-CERTIFICATE",
                         NOW - timedelta(days=1), NOW + timedelta(days=1), approved=True)
    return replace(record, **changes)


def uplink(telemetry=SAMPLE, **changes):
    value = {"deduplicationId": "00000000-0000-4000-8000-000000000002", "time": stamp(NOW),
             "deviceInfo": {"tenantId": "synthetic-tenant", "applicationId": APP,
                            "devEui": EUI, "deviceName": "SYNTHETIC-REEF-NOT-DEPLOYED"},
             "fPort": 10, "fCnt": 1, "confirmed": False,
             "data": base64.b64encode(encode_payload(telemetry)).decode("ascii"),
             "rxInfo": [{"gatewayId": "0000000000000000", "rssi": -80, "snr": 7.5}],
             "txInfo": {"frequency": 868100000, "modulation": {"lora": {"spreadingFactor": 7}}}}
    value.update(changes)
    return json.dumps(value).encode()


def accepted(telemetry=SAMPLE, **kwargs):
    return ChirpStackAdapter(registry()).parse(uplink(telemetry), event="up", received_at=NOW, **kwargs)


@contextmanager
def owned_server(handler):
    # Atomic port-zero bind obtains a checked-free numeric loopback port and
    # reserves it without a check-then-bind race. No existing listener is touched.
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise AssertionError("owned HTTP server did not stop")


class MemorySink:
    def __init__(self, fail=0, lose_response=False):
        self.fail, self.lose_response = fail, lose_response
        self.calls = 0
        self.records = {}

    def send(self, identity, body):
        self.calls += 1
        if self.fail:
            self.fail -= 1
            raise OSError("SYNTHETIC delivery failure")
        previous = self.records.setdefault(identity, body)
        if previous != body:
            raise ValueError("idempotency conflict")
        if self.lose_response:
            self.lose_response = False
            raise OSError("SYNTHETIC accepted but acknowledgement lost")


class WireTests(unittest.TestCase):
    def test_roundtrip_and_uint64_boot(self):
        for sample in (SAMPLE, replace(SAMPLE, boot_id=2**64 - 1, sequence=2**32 - 1),
                       replace(SAMPLE, sensor_value=-(2**31)),
                       replace(SAMPLE, sensor_kind=0, sensor_value=None, sensor_quality=2)):
            with self.subTest(sample=sample):
                self.assertEqual(sample, decode_payload(encode_payload(sample)))
                self.assertLessEqual(len(encode_payload(sample)), 64)

    def test_reject_noncanonical_cbor_and_types(self):
        data = encode_payload(SAMPLE)
        bad = [b"", data + b"\x00", b"\x9f" + data[1:] + b"\xff",
               b"\x98\x0d" + data[1:], data[:1] + b"\x18\x01" + data[2:],
               data[:1] + b"\x19\x00\x01" + data[2:],
               data[:1] + b"\xfa\x3f\x80\x00\x00" + data[2:],
               data[:1] + b"\xf5" + data[2:], data[:1] + b"\xc0\x01" + data[2:],
               b"\xa0", b"\x80", b"\x8d" + b"\x00" * 64]
        bad.extend(data[:i] for i in range(1, len(data)))
        for candidate in bad:
            with self.subTest(hex=candidate.hex()):
                with self.assertRaises(Rejected):
                    decode_payload(candidate)

    def test_wire_field_and_sensor_rules(self):
        bad = [{"boot_id": 0}, {"boot_id": 2**64}, {"sequence": 2**32}, {"sequence": -1},
               {"sequence": True}, {"version": 2}, {"clock_quality": 3},
               {"clock_quality": 0, "observed_at_unix_s": int(NOW.timestamp())},
               {"clock_quality": 1}, {"battery_mv": 65536}, {"solar_mv": -1},
               {"power_mode": 3}, {"sensor_kind": 4}, {"sensor_quality": 3},
               {"sensor_value": 2**31}, {"sensor_value": None}, {"calibration_id": 7},
               {"sensor_quality": 1}, {"sensor_quality": 1, "calibration_id": 0},
               {"sensor_quality": 2}, {"sensor_kind": 0},
               {"sensor_kind": 0, "sensor_value": None, "sensor_quality": 0}]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(Rejected):
                encode_payload(replace(SAMPLE, **changes))

    def test_bounded_random_bytes_only_decode_or_reject(self):
        rng = random.Random(741)
        for _ in range(1000):
            candidate = bytes(rng.randrange(256) for _ in range(rng.randrange(70)))
            try:
                decoded = decode_payload(candidate)
            except Rejected:
                continue
            self.assertEqual(encode_payload(decoded), candidate)

    def test_cpp_golden_fixtures(self):
        path = ROOT / "libs/proto-cpp/fixtures/reef-telemetry-v1.json"
        if not path.exists():
            self.skipTest("C++ child fixtures not yet available; parity gate remains open")
        fixtures = json.loads(path.read_text())
        self.assertGreater(len(fixtures["valid"]), 0)
        self.assertGreater(len(fixtures["invalid"]), 0)
        for case in fixtures["valid"]:
            with self.subTest(valid=case["name"]):
                decoded = decode_payload(bytes.fromhex(case["hex"]))
                normalized = list(asdict(decoded).values())
                normalized[1] = str(normalized[1])
                self.assertEqual(normalized, case["fields"])
                wire_fields = list(case["fields"])
                self.assertIsInstance(wire_fields[1], str)
                self.assertEqual(str(int(wire_fields[1])), wire_fields[1])
                wire_fields[1] = int(wire_fields[1])
                self.assertEqual(encode_payload(Telemetry(*wire_fields)).hex(), case["hex"])
        for case in fixtures["invalid"]:
            with self.subTest(invalid=case["name"]), self.assertRaises(Rejected):
                decode_payload(bytes.fromhex(case["hex"]))


    def test_platform_review_candidate_wire_fixtures(self):
        path = ROOT / "contracts/v1/fixtures/reef-cbor-vectors.json"
        self.assertTrue(path.is_file(), "review-candidate parity vectors missing")
        fixtures = json.loads(path.read_text())
        for case in fixtures["valid"]:
            with self.subTest(valid=case["name"]):
                decoded = decode_payload(bytes.fromhex(case["hex"]))
                fields = asdict(decoded)
                fields["boot_id"] = str(fields["boot_id"])
                self.assertEqual(fields, case["fields"])
                wire_fields = dict(case["fields"], boot_id=int(case["fields"]["boot_id"]))
                self.assertEqual(encode_payload(Telemetry(**wire_fields)).hex(), case["hex"])
        for case in fixtures["invalid"]:
            with self.subTest(invalid=case["name"]), self.assertRaises(Rejected):
                decode_payload(bytes.fromhex(case["hex"]))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = ChirpStackAdapter(registry())

    def parse(self, body=None, **kwargs):
        return self.adapter.parse(body or uplink(), event="up", received_at=NOW, **kwargs)

    def test_raw_counts_never_become_calibrated_units(self):
        result = self.parse().document
        self.assertEqual(result["sensor"]["raw_counts"], 1234)
        self.assertIsNone(result["sensor"]["value"])
        self.assertIsNone(result["sensor"]["unit"])
        self.assertIsNone(result["sensor"]["calibration"])
        self.assertIsNone(result["observed_at"])
        self.assertEqual(result["uptime_s"], 42)
        self.assertEqual(result["source"]["transport"], "fixture-replay")
        self.assertEqual(result["contract_status"], "draft-unapproved")

    def test_uint64_boot_is_canonical_decimal_string_in_json(self):
        result = self.parse(uplink(replace(SAMPLE, boot_id=2**64 - 1))).document
        self.assertEqual(result["boot_id"], "18446744073709551615")
        self.assertIsInstance(json.loads(json.dumps(result))["boot_id"], str)

    def test_calibrated_units_and_immutable_metadata(self):
        for kind, value, expected, unit in ((1, -123, -1.23, "degC"),
                (2, 35456, 35.456, "practical_salinity_dimensionless"), (3, 8123, 8123, "ug/L")):
            with self.subTest(kind=kind):
                reg = registry(calibrations=[calibration(sensor_kind=kind)])
                adapter = ChirpStackAdapter(reg)
                data = uplink(replace(SAMPLE, sensor_kind=kind, sensor_quality=1,
                                      sensor_value=value, calibration_id=7, clock_quality=2,
                                      observed_at_unix_s=int(NOW.timestamp())))
                result = adapter.parse(data, event="up", received_at=NOW).document["sensor"]
                self.assertEqual(result["value"], expected)
                self.assertEqual(result["wire_value"], value)
                self.assertEqual(result["unit"], unit)
                self.assertIsNone(result["raw_counts"])
                self.assertTrue(result["calibration"]["synthetic"])
                self.assertEqual(result["calibration"]["validity_time_basis"], "claimed_observed_at")
                with self.assertRaises(TypeError):
                    reg.calibrations[(EUI, 7)] = calibration()

    def test_missing_wrong_expired_unapproved_calibration_rejected(self):
        records = [(), (calibration(sensor_kind=2),), (calibration(approved=False),),
                   (calibration(valid_until=NOW),),
                   (calibration(dev_eui="00000000000000b2"),)]
        data = uplink(replace(SAMPLE, sensor_quality=1, calibration_id=7, clock_quality=2,
                              observed_at_unix_s=int(NOW.timestamp())))
        for refs in records:
            with self.subTest(refs=refs), self.assertRaisesRegex(Rejected, "calibration_reference_invalid"):
                ChirpStackAdapter(registry(calibrations=refs)).parse(data, event="up", received_at=NOW)

    def test_calibrated_unsynchronized_observation_rejected(self):
        adapter = ChirpStackAdapter(registry(calibrations=[calibration()]))
        with self.assertRaisesRegex(Rejected, "calibration_time_unknown"):
            adapter.parse(uplink(replace(SAMPLE, sensor_quality=1, calibration_id=7)),
                          event="up", received_at=NOW)

    def test_calibration_validity_uses_observed_time_when_known(self):
        observed = NOW - timedelta(seconds=120)
        record = calibration(valid_until=NOW - timedelta(seconds=60))
        data = uplink(replace(SAMPLE, sensor_quality=1, calibration_id=7, clock_quality=2,
                              observed_at_unix_s=int(observed.timestamp())))
        result = ChirpStackAdapter(registry(calibrations=[record])).parse(data, event="up", received_at=NOW)
        self.assertEqual(result.document["sensor"]["calibration"]["validity_time_basis"], "claimed_observed_at")

    def test_three_timestamps_remain_distinct(self):
        observed = NOW - timedelta(seconds=30)
        event = NOW - timedelta(seconds=5)
        result = self.parse(uplink(replace(SAMPLE, clock_quality=2,
                observed_at_unix_s=int(observed.timestamp())), time=stamp(event))).document
        self.assertIsNone(result["observed_at"])
        self.assertEqual(result["clock_quality"], "unknown")
        self.assertEqual(result["clock_claim"], "network")
        self.assertEqual(result["claimed_observed_at"], stamp(observed))
        self.assertEqual(result["network_event_at"], stamp(event))
        self.assertEqual(result["received_at"], stamp(NOW))

    def test_nanosecond_network_timestamp_preserved_as_source(self):
        value = "2026-09-08T12:00:00.123456789Z"
        result = self.parse(uplink(time=value)).document
        self.assertEqual(result["source"]["network_event_time_original"], value)
        self.assertEqual(result["network_event_at"], "2026-09-08T12:00:00.123456Z")

    def test_unknown_disabled_and_wrong_application_rejected(self):
        for info in ({"devEui": "00000000000000b2", "applicationId": APP},
                     {"devEui": EUI, "applicationId": "synthetic-wrong-app"},
                     {"devEui": "not-an-eui", "applicationId": APP},
                     {"devEui": EUI}, None):
            with self.subTest(info=info), self.assertRaises(Rejected):
                self.parse(uplink(deviceInfo=info))
        with self.assertRaises(Rejected):
            ChirpStackAdapter(registry(enabled=False)).parse(uplink(), event="up", received_at=NOW)

    def test_fport_event_and_json_schema_rejected(self):
        for changes in ({"fPort": 11}, {"fPort": "10"}, {"fPort": True},
                        {"data": None}, {"time": "2026-09-08"}, {"time": "2026-02-31T00:00:00Z"}):
            with self.subTest(changes=changes), self.assertRaises(Rejected):
                self.parse(uplink(**changes))
        for event in ("ack", "join", "", None):
            with self.subTest(event=event), self.assertRaises(Rejected):
                self.adapter.parse(uplink(), event=event, received_at=NOW)
        with self.assertRaises(Rejected):
            self.adapter.parse(uplink(), event="up", received_at=NOW.replace(tzinfo=None))

    def test_base64_bounds_alphabet_padding_and_pad_bits(self):
        encoded = json.loads(uplink())["data"]
        # The canonical 0xff payload encoding /w== has aliases /x== etc.; reject
        # the alias before wire decode even though stdlib accepts its pad bits.
        for value in (encoded + "=", encoded + "\n", "!bad!", "AA", "A" * 100, "/x==", ""):
            with self.subTest(value=value), self.assertRaises(Rejected):
                self.parse(uplink(data=value))

    def test_json_limits_duplicates_unicode_and_nonfinite(self):
        for body in (b"[]", b"null", b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}',
                     b'{"x":1234567890123456789012}', b'"\xff"', b'{"x":"\\ud800"}',
                     b'{"x":' + b"[" * 13 + b"0" + b"]" * 13 + b"}",
                     b'{"x":"' + b"a" * 4097 + b'"}', b" " * (MAX_JSON_BYTES + 1),
                     b'{"x":[' + b"0," * 2048 + b"0]}"):
            with self.subTest(body=body[:60]), self.assertRaises(Rejected):
                bounded_json(body)

    def test_clock_policy_future_stale_observed_and_boundary(self):
        for offset in (-86401, 61):
            with self.subTest(event_offset=offset), self.assertRaises(Rejected):
                self.parse(uplink(time=stamp(NOW + timedelta(seconds=offset))))
            with self.subTest(observed_offset=offset), self.assertRaises(Rejected):
                self.parse(uplink(replace(SAMPLE, clock_quality=1,
                    observed_at_unix_s=int(NOW.timestamp()) + offset)))
        for offset in (-86400, 60):
            self.parse(uplink(time=stamp(NOW + timedelta(seconds=offset))))
        with self.assertRaises(Rejected):
            self.parse(uplink(replace(SAMPLE, clock_quality=1, observed_at_unix_s=int(NOW.timestamp())),
                              time=stamp(NOW - timedelta(seconds=61))))
        with self.assertRaises(ValueError):
            ClockPolicy(future_seconds=-1)


class SpoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aquilon-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "spool.sqlite3"

    def spool(self, **kwargs):
        spool = SQLiteSpool(self.path, **kwargs)
        self.addCleanup(spool.close)
        return spool

    def test_atomic_accept_dedupe_restart_and_delivered_receipt(self):
        first = SQLiteSpool(self.path)
        self.assertEqual(first.enqueue(accepted(), now=100), "accepted")
        first.close()
        spool = self.spool()
        self.assertEqual(spool.enqueue(accepted(), now=101), "duplicate")
        sink = MemorySink()
        self.assertEqual(spool.deliver_due(sink, now=101), 1)
        self.assertEqual(spool.enqueue(accepted(), now=102), "duplicate")
        self.assertEqual(spool.health()["rows"], 0)
        self.assertEqual(spool.health()["counters"]["accepted"], 1)
        self.assertEqual(spool.health()["counters"]["duplicate"], 2)

    def test_full_spool_does_not_advance_identity_or_highwater(self):
        spool = self.spool(max_rows=1)
        spool.enqueue(accepted(), now=0)
        newer = accepted(replace(SAMPLE, sequence=1))
        with self.assertRaises(SpoolFull):
            spool.enqueue(newer, now=0)
        self.assertEqual(spool.health()["receipts"], 1)
        self.assertEqual(spool.db.execute("SELECT sequence FROM highwater").fetchone()[0], 0)
        spool.deliver_due(MemorySink(), now=0)
        self.assertEqual(spool.enqueue(newer, now=1), "accepted")
        self.assertEqual(spool.health()["counters"]["spool_full"], 1)

    def test_byte_bound_is_transactional(self):
        spool = self.spool(max_bytes=1)
        with self.assertRaises(SpoolFull):
            spool.enqueue(accepted(), now=0)
        health = spool.health()
        self.assertEqual((health["rows"], health["devices"], health["receipts"]), (0, 0, 0))

    def test_identity_conflict_preserves_first_payload(self):
        spool = self.spool()
        spool.enqueue(accepted(), now=0)
        with self.assertRaisesRegex(Rejected, "identity_conflict"):
            spool.enqueue(accepted(replace(SAMPLE, sensor_value=999)), now=0)
        self.assertEqual(spool.health()["rows"], 1)
        self.assertEqual(spool.health()["counters"]["identity_conflict"], 1)

    def test_lower_boot_stale_sequence_and_sequence_wrap_reject(self):
        spool = self.spool()
        spool.enqueue(accepted(replace(SAMPLE, boot_id=2, sequence=2**32 - 1)), now=0)
        for changes in ({"boot_id": 1, "sequence": 2**32 - 1},
                        {"boot_id": 2, "sequence": 0}, {"boot_id": 2, "sequence": 2**32 - 2}):
            with self.subTest(changes=changes), self.assertRaisesRegex(Rejected, "stale_or_replayed"):
                spool.enqueue(accepted(replace(SAMPLE, **changes)), now=0)
        self.assertEqual(spool.enqueue(accepted(replace(SAMPLE, boot_id=3, sequence=0)), now=0), "accepted")

    def test_uint64_persists_as_text_without_sqlite_overflow(self):
        first = SQLiteSpool(self.path)
        first.enqueue(accepted(replace(SAMPLE, boot_id=2**64 - 1)), now=0)
        value = first.db.execute("SELECT boot,typeof(boot) FROM highwater").fetchone()
        self.assertEqual(tuple(value), ("18446744073709551615", "text"))
        first.close()
        spool = self.spool()
        with self.assertRaises(Rejected):
            spool.enqueue(accepted(replace(SAMPLE, boot_id=2**63, sequence=10)), now=0)

    def test_receipts_bounded_but_replay_floor_survives_pruning(self):
        spool = self.spool(max_receipts=2)
        for sequence in range(6):
            spool.enqueue(accepted(replace(SAMPLE, sequence=sequence)), now=0)
            spool.deliver_due(MemorySink(), now=0)
        self.assertEqual(spool.health()["receipts"], 2)
        with self.assertRaises(Rejected):
            spool.enqueue(accepted(), now=0)
        self.assertEqual(spool.health()["devices"], 1)

    def test_bounded_retry_schedule_restart_exhaustion_and_recovery(self):
        policy = RetryPolicy(max_attempts=4, base_seconds=2, max_seconds=3)
        spool = SQLiteSpool(self.path, retry_policy=policy)
        record = accepted()
        spool.enqueue(record, now=100)
        sink = MemorySink(fail=4)
        self.assertEqual(spool.deliver_due(sink, now=100), 0)
        self.assertEqual(spool.health()["next_at"], 102)
        spool.close()
        spool = self.spool(retry_policy=policy)
        self.assertEqual(spool.deliver_due(sink, now=101), 0)
        self.assertEqual(sink.calls, 1)
        spool.deliver_due(sink, now=102)
        self.assertEqual(spool.health()["next_at"], 105)
        spool.deliver_due(sink, now=105)
        self.assertEqual(spool.health()["next_at"], 108)
        spool.deliver_due(sink, now=108)
        self.assertEqual(spool.health()["exhausted"], 1)
        self.assertIsNone(spool.health()["next_at"])
        self.assertEqual(spool.deliver_due(sink, now=10000), 0)
        self.assertEqual(sink.calls, 4)
        self.assertTrue(spool.retry_exhausted(record.identity, now=10001))
        self.assertEqual(spool.deliver_due(sink, now=10001), 1)
        health = spool.health()
        self.assertEqual(health["rows"], 0)
        self.assertEqual(health["counters"]["delivery_failed"], 4)
        self.assertEqual(health["counters"]["retry_exhausted"], 1)
        self.assertFalse(spool.retry_exhausted(record.identity, now=10002))

    def test_response_loss_is_idempotent(self):
        spool = self.spool()
        spool.enqueue(accepted(), now=0)
        sink = MemorySink(lose_response=True)
        self.assertEqual(spool.deliver_due(sink, now=0), 0)
        self.assertEqual(spool.deliver_due(sink, now=2), 1)
        self.assertEqual(len(sink.records), 1)
        self.assertEqual(sink.calls, 2)

    def test_multiple_connections_serialize_atomic_accept(self):
        one, two = self.spool(), self.spool()
        outcomes, errors = [], []
        barrier = threading.Barrier(2)

        def run(spool):
            try:
                barrier.wait(timeout=2)
                outcomes.append(spool.enqueue(accepted(), now=0))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(spool,)) for spool in (one, two)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertCountEqual(outcomes, ["accepted", "duplicate"])
        self.assertEqual(one.health()["rows"], 1)

    def test_sqlite_disk_full_rolls_back_acceptance(self):
        spool = self.spool(max_disk_bytes=262144)
        failed = None
        for sequence in range(1000):
            try:
                spool.enqueue(accepted(replace(SAMPLE, sequence=sequence)), now=0)
            except SpoolFull:
                failed = sequence
                break
        self.assertIsNotNone(failed, "page bound did not stop writes")
        floor = spool.db.execute("SELECT sequence FROM highwater").fetchone()[0]
        self.assertEqual(floor, failed - 1)
        self.assertEqual(spool.health()["rows"], failed)
        self.assertLessEqual(self.path.stat().st_size, 262144)
        spool.deliver_due(MemorySink(), now=0, limit=1024)
        self.assertEqual(spool.enqueue(accepted(replace(SAMPLE, sequence=failed)), now=1), "accepted")

    def test_commit_survives_process_exit_without_close(self):
        body_path = Path(self.temp.name) / "synthetic-uplink.json"
        body_path.write_bytes(uplink())
        program = """
import os, sys
from pathlib import Path
from aquilon.adapter import ChirpStackAdapter, Device, LocalRegistry, parse_time
from aquilon.spool import SQLiteSpool
adapter = ChirpStackAdapter(LocalRegistry([Device(sys.argv[3], sys.argv[4])]))
record = adapter.parse(Path(sys.argv[2]).read_bytes(), event='up', received_at=parse_time(sys.argv[5]))
spool = SQLiteSpool(sys.argv[1])
spool.enqueue(record, now=0)
os._exit(0)
"""
        run = subprocess.run([sys.executable, "-c", program, str(self.path), str(body_path), EUI, APP, stamp(NOW)],
                             env=dict(os.environ, PYTHONPATH=str(ROOT / "apps/aquilon/src"),
                                      PYTHONDONTWRITEBYTECODE="1"), capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        spool = self.spool()
        self.assertEqual(spool.health()["rows"], 1)
        self.assertEqual(spool.enqueue(accepted(), now=1), "duplicate")

    def test_durable_first_attempt_freeze_and_atomic_cleanup(self):
        first = SQLiteSpool(self.path, retry_policy=RetryPolicy(max_attempts=1))
        record = accepted()
        first.enqueue(record, now=0)
        source = bytes(first.db.execute("SELECT body FROM spool").fetchone()[0])
        frozen = b'{"synthetic_first_attempt":true}'
        self.assertEqual(first.freeze_forwarding(record.identity, source, lambda: frozen), frozen)
        self.assertEqual(first.health()["bytes"], len(source) + len(frozen) + 64)
        first.deliver_due(MemorySink(fail=1), now=0)
        self.assertEqual(first.health()["exhausted"], 1)
        first.close()
        spool = self.spool(retry_policy=RetryPolicy(max_attempts=1))

        def must_not_rebuild():
            raise AssertionError("frozen first-attempt fields were recomputed")

        self.assertEqual(spool.freeze_forwarding(record.identity, source, must_not_rebuild), frozen)
        self.assertEqual(spool.health()["frozen_rows"], 1)
        self.assertEqual(spool.health()["frozen_bytes"], len(frozen) + 64)
        spool.retry_exhausted(record.identity, now=1)
        self.assertEqual(spool.deliver_due(MemorySink(), now=1), 1)
        self.assertEqual(spool.health()["frozen_rows"], 0)
        self.assertEqual(spool.health()["bytes"], 0)
        self.assertEqual(spool.health()["receipts"], 1)

    def test_freeze_budget_source_binding_and_new_enqueue_bound(self):
        spool = self.spool()
        record = accepted()
        spool.enqueue(record, now=0)
        source = bytes(spool.db.execute("SELECT body FROM spool").fetchone()[0])
        frozen = b'{"synthetic_first_attempt":true}'
        spool.max_bytes = len(source) + len(frozen) + 63
        with self.assertRaises(SpoolFull):
            spool.freeze_forwarding(record.identity, source, lambda: frozen)
        self.assertEqual(spool.health()["frozen_rows"], 0)
        self.assertEqual(spool.health()["bytes"], len(source))
        with self.assertRaisesRegex(Rejected, "source_mismatch"):
            spool.freeze_forwarding(record.identity, source + b" ", lambda: frozen)
        spool.max_bytes += 1
        spool.freeze_forwarding(record.identity, source, lambda: frozen)
        with self.assertRaises(SpoolFull):
            spool.enqueue(accepted(replace(SAMPLE, sequence=1)), now=0)
        self.assertEqual(spool.health()["rows"], 1)
        self.assertEqual(spool.db.execute("SELECT sequence FROM highwater").fetchone()[0], 0)

    def test_v1_spool_migrates_without_resetting_accepted_state(self):
        first = SQLiteSpool(self.path)
        first.enqueue(accepted(), now=0)
        # Recreate the exact pre-freeze v1 shape without changing its accepted data.
        first.db.execute("DROP TABLE forwarding")
        first.db.execute("PRAGMA user_version=1")
        first.close()
        spool = self.spool()
        self.assertEqual(spool.db.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(spool.health()["rows"], 1)
        self.assertEqual(spool.health()["frozen_rows"], 0)
        self.assertEqual(spool.enqueue(accepted(), now=1), "duplicate")

    def test_process_exit_immediately_before_and_after_freeze_commit(self):
        body_path = Path(self.temp.name) / "synthetic-freeze-uplink.json"
        body_path.write_bytes(uplink())
        program = """
import os, sys
from pathlib import Path
from aquilon.adapter import ChirpStackAdapter, Device, LocalRegistry, parse_time
from aquilon.spool import SQLiteSpool
adapter = ChirpStackAdapter(LocalRegistry([Device(sys.argv[3], sys.argv[4])]))
record = adapter.parse(Path(sys.argv[2]).read_bytes(), event='up', received_at=parse_time(sys.argv[5]))
spool = SQLiteSpool(sys.argv[1])
spool.enqueue(record, now=0)
source = bytes(spool.db.execute('SELECT body FROM spool').fetchone()[0])
if sys.argv[6] == 'before':
    def interrupt(statement):
        if statement == 'COMMIT':
            os._exit(23)
    spool.db.set_trace_callback(interrupt)
spool.freeze_forwarding(record.identity, source, lambda: b'{"synthetic_first_attempt":true}')
os._exit(24)
"""
        for mode, expected_exit, expected_frozen in (("before", 23, 0), ("after", 24, 1)):
            with self.subTest(mode=mode):
                path = Path(self.temp.name) / f"freeze-{mode}.sqlite3"
                run = subprocess.run([sys.executable, "-c", program, str(path), str(body_path), EUI, APP, stamp(NOW), mode],
                    env=dict(os.environ, PYTHONPATH=str(ROOT / "apps/aquilon/src"), PYTHONDONTWRITEBYTECODE="1"),
                    capture_output=True, timeout=10)
                self.assertEqual(run.returncode, expected_exit, run.stderr)
                with SQLiteSpool(path) as reopened:
                    self.assertEqual(reopened.health()["rows"], 1)
                    self.assertEqual(reopened.health()["frozen_rows"], expected_frozen)
                    self.assertEqual(reopened.enqueue(accepted(), now=1), "duplicate")
                    if expected_frozen:
                        self.assertEqual(bytes(reopened.db.execute("SELECT envelope FROM forwarding").fetchone()[0]),
                                         b'{"synthetic_first_attempt":true}')

    def test_unknown_database_and_invalid_limits_rejected(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE other_app (id INTEGER)")
        with self.assertRaises(ValueError):
            SQLiteSpool(self.path)
        for changes in ({"max_rows": 0}, {"max_bytes": -1}, {"max_receipts": True},
                        {"max_disk_bytes": 1024}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                SQLiteSpool(self.path, **changes)
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=33)

    def test_scheduler_and_counter_bounds(self):
        spool = self.spool()
        for now in (-1, float("nan"), float("inf"), True):
            with self.subTest(now=now), self.assertRaises(ValueError):
                spool.enqueue(accepted(), now=now)
        with self.assertRaises(ValueError):
            spool.deliver_due(MemorySink(), now=0, limit=1025)
        with self.assertRaises(ValueError):
            spool.count("attacker-controlled-counter")


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aquilon-http-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.spool = SQLiteSpool(Path(self.temp.name) / "spool.db")
        self.addCleanup(self.spool.close)
        self.runtime = AquilonRuntime(ChirpStackAdapter(registry()), self.spool)
        self.config = HTTPIntegrationConfig(SECRET, timeout_seconds=0.2)
        self.handler = make_webhook_handler(self.runtime, self.config, clock=lambda: NOW)

    def request(self, address, *, body=None, path="/chirpstack?event=up", headers=None, method="POST"):
        connection = http.client.HTTPConnection(*address, timeout=2)
        try:
            supplied = {self.config.auth_header: SECRET, "Content-Type": "application/json"}
            if headers:
                supplied.update(headers)
            connection.request(method, path, body=uplink() if body is None else body, headers=supplied)
            response = connection.getresponse()
            return response.status, response.read(4096)
        finally:
            connection.close()

    def test_authenticated_real_http_handler_and_duplicate(self):
        with owned_server(self.handler) as address:
            for expected in ("accepted", "duplicate"):
                status, body = self.request(address)
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["status"], expected)
        sink = MemorySink()
        self.spool.deliver_due(sink, now=NOW.timestamp())
        doc = json.loads(next(iter(sink.records.values())))
        self.assertEqual(doc["source"]["transport"], "authenticated-chirpstack-http-integration")
        self.assertEqual(self.runtime.health()["platform_ingest"], "not-integrated")

    def test_auth_failure_redacted_and_not_enqueued(self):
        with owned_server(self.handler) as address:
            status, body = self.request(address, headers={self.config.auth_header: "WRONG-SYNTHETIC-SECRET"})
            self.assertEqual(status, 401)
            self.assertNotIn(b"SECRET", body)
            self.assertEqual(self.spool.health()["rows"], 0)
            self.assertEqual(self.spool.health()["counters"]["auth_rejected"], 1)
        self.assertNotIn(SECRET, repr(self.config))

    def test_custom_auth_header_and_path(self):
        config = HTTPIntegrationConfig(SECRET, auth_header="X-Synthetic-Test-Key", path="/synthetic-hook")
        with owned_server(make_webhook_handler(self.runtime, config, clock=lambda: NOW)) as address:
            status, _ = self.request(address, path="/synthetic-hook?event=up",
                                     headers={"X-Synthetic-Test-Key": SECRET})
            self.assertEqual(status, 200)

    def test_transport_rejections(self):
        cases = [{"path": "/chirpstack?event=join"}, {"path": "/chirpstack"},
                 {"path": "/chirpstack?event=up&event=up"},
                 {"path": "/chirpstack?event=up&a=1&b=1&c=1&d=1"},
                 {"path": "/other?event=up"}, {"headers": {"Content-Type": "text/plain"}},
                 {"headers": {"Content-Encoding": "gzip"}},
                 {"headers": {"Transfer-Encoding": "chunked"}}, {"body": b""},
                 {"headers": {"Content-Length": str(MAX_JSON_BYTES + 1)}}]
        with owned_server(self.handler) as address:
            for case in cases:
                with self.subTest(case=case):
                    status, _ = self.request(address, **case)
                    self.assertIn(status, (400, 413))
        self.assertEqual(self.spool.health()["rows"], 0)

    def test_parser_rejection_is_422_and_counted(self):
        with owned_server(self.handler) as address:
            status, body = self.request(address, body=b'{"fPort":10}')
            self.assertEqual(status, 422)
            self.assertEqual(json.loads(body), {"error": "uplink_rejected"})
        self.assertEqual(self.spool.health()["counters"]["parser_rejected"], 1)

    def test_body_read_timeout_and_duplicate_auth_headers(self):
        with owned_server(self.handler) as address:
            with socket.create_connection(address, timeout=2) as client:
                client.sendall((f"POST /chirpstack?event=up HTTP/1.0\r\n"
                                f"{self.config.auth_header}: {SECRET}\r\n"
                                "Content-Type: application/json\r\nContent-Length: 100\r\n\r\n").encode())
                response = client.recv(4096)
                self.assertIn(b"408", response)
            with socket.create_connection(address, timeout=2) as client:
                client.sendall((f"POST /chirpstack?event=up HTTP/1.0\r\n"
                                f"{self.config.auth_header}: {SECRET}\r\n"
                                f"{self.config.auth_header}: {SECRET}\r\n"
                                "Content-Length: 0\r\n\r\n").encode())
                self.assertIn(b"401", client.recv(4096))
        self.assertEqual(self.spool.health()["rows"], 0)

    def test_spool_full_http_503_can_retry_after_drain(self):
        self.spool.max_rows = 1
        with owned_server(self.handler) as address:
            self.assertEqual(self.request(address)[0], 200)
            next_body = uplink(replace(SAMPLE, sequence=1))
            self.assertEqual(self.request(address, body=next_body)[0], 503)
            self.spool.deliver_due(MemorySink(), now=NOW.timestamp())
            self.assertEqual(self.request(address, body=next_body)[0], 200)

    def test_mock_http_sink_idempotence_after_lost_ack_and_retry(self):
        records, calls = {}, []

        class MockSinkHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.connection.settimeout(1)
                key = self.headers.get("Idempotency-Key")
                body = self.rfile.read(min(int(self.headers.get("Content-Length", "0")), MAX_JSON_BYTES))
                calls.append(key)
                if self.headers.get("X-Aquilon-Integration-Key") != SECRET:
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if key in records and records[key] != body:
                    self.send_response(409)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                records[key] = body
                if len(calls) == 1:
                    self.close_connection = True  # accepted durably in this mock; no ACK
                    return
                response = json.dumps({"accepted": True, "identity": key}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        self.spool.enqueue(accepted(), now=0)
        with owned_server(MockSinkHandler) as address:
            sink = LocalHTTPSink(f"http://{address[0]}:{address[1]}/synthetic-ingest", SECRET)
            self.assertEqual(self.spool.deliver_due(sink, now=0), 0)
            self.assertEqual(self.spool.deliver_due(sink, now=2), 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(len(calls), 2)

    def test_mock_sink_refuses_external_urls_and_weak_secret(self):
        for url in ("https://example.com/ingest", "http://localhost:8000/ingest",
                    "http://127.0.0.1:8000/ingest?secret=x", "http://u:p@127.0.0.1:8000/ingest"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                LocalHTTPSink(url, SECRET)
        with self.assertRaises(ValueError):
            HTTPIntegrationConfig("weak")

    def test_sink_total_deadline_stops_slow_trickled_headers(self):
        class TrickleSink(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                self.connection.settimeout(1)
                self.rfile.read(int(self.headers["Content-Length"]))
                try:
                    self.wfile.write(b"HTTP/1.0 200 OK\r\nX-Synthetic: ")
                    for _ in range(20):
                        threading.Event().wait(0.025)
                        self.wfile.write(b"a")
                except OSError:
                    pass

        with owned_server(TrickleSink) as address:
            sink = LocalHTTPSink(f"http://{address[0]}:{address[1]}/synthetic-ingest", SECRET, timeout_seconds=0.1)
            start = time.monotonic()
            with self.assertRaises(SinkFailure):
                sink.send(accepted().identity, b"{}")
            self.assertLess(time.monotonic() - start, 0.7)

    def test_sink_response_size_and_ack_are_bounded(self):
        for mode in ("oversized", "wrong-identity", "redirect", "auth-failure"):
            with self.subTest(mode=mode):
                class BadSink(BaseHTTPRequestHandler):
                    def log_message(self, *_):
                        pass

                    def do_POST(self):
                        self.connection.settimeout(1)
                        self.rfile.read(int(self.headers["Content-Length"]))
                        body = b'{"accepted":true,"identity":"WRONG"}'
                        self.send_response(302 if mode == "redirect" else 401 if mode == "auth-failure" else 200)
                        self.send_header("Content-Length", "5000" if mode == "oversized" else str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)

                with owned_server(BadSink) as address:
                    sink = LocalHTTPSink(f"http://{address[0]}:{address[1]}/synthetic-ingest", SECRET)
                    with self.assertRaises(SinkFailure) as error:
                        sink.send(accepted().identity, b"{}")
                    self.assertNotIn(SECRET, str(error.exception))


class CLITests(unittest.TestCase):
    def test_fixture_replay_new_spool_health_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="aquilon-cli-synthetic-") as directory:
            fixture, spool = Path(directory) / "synthetic.json", Path(directory) / "spool.db"
            fixture.write_bytes(uplink())
            env = dict(os.environ, PYTHONPATH=str(ROOT / "apps/aquilon/src"), PYTHONDONTWRITEBYTECODE="1")
            args = [sys.executable, "-m", "aquilon", "replay", str(fixture), "--spool", str(spool),
                    "--dev-eui", EUI, "--application-id", APP, "--received-at", stamp(NOW)]
            run = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["health"]["spool"]["rows"], 1)
            retry = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(retry.returncode, 2)
            health = subprocess.run([sys.executable, "-m", "aquilon", "health", "--spool", str(spool)],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(health.returncode, 0, health.stderr)
            self.assertEqual(json.loads(health.stdout)["rows"], 1)


if __name__ == "__main__":
    unittest.main()
