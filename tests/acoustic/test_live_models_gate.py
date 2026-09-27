from dataclasses import replace
import contextlib
import io
import os
from pathlib import Path
import sys
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

from poseidon_acoustic.live_capture_cli import main, synthetic_demo_plan
from poseidon_acoustic.live_gate import (DeviceAccessDenied, WorkerAdmissionV1, acknowledgment_text,
    authorize_device_access, consume_device_access, validate_worker_admission)
from poseidon_acoustic.live_models import (CapturePlanV1, CapturedBlockV1, LiveValidationError, canonical,
    parse_canonical)
from poseidon_acoustic.live_supervisor import LiveCaptureSupervisor, SyntheticBackendFactory


def physical_plan():
    fake = synthetic_demo_plan()
    source = replace(fake.sources[0], backend="linux_alsa", device_node="/dev/snd/pcmC12D3c",
                     expected_identity_json=canonical({"pcm_id": "operator-declared-identity"}),
                     subdevice=0, period_frames=16, period_frames_max=32,
                     buffer_frames=64, buffer_frames_max=128, provenance="bench")
    return replace(fake, capture_id="physical-" + uuid.uuid4().hex, sources=(source,))


class GateModelsTests(unittest.TestCase):
    def test_roundtrip_immutable_plan(self):
        plan = synthetic_demo_plan()
        self.assertEqual(CapturePlanV1.from_bytes(plan.canonical_bytes), plan)
        self.assertEqual(len(plan.sha256), 64)
        with self.assertRaises(Exception):
            plan.sources[0].provenance = "field"

    def test_exact_identity_format_and_no_physical_defaults(self):
        source = physical_plan().sources[0]
        for change in ({"device_node": "default"}, {"device_node": "/dev/snd/../pcmC1D1c"},
                       {"sample_rate_hz": None}, {"subdevice": None}, {"expected_identity_json": canonical({})},
                       {"channels": ["a"]}, {"sample_rate_hz": True}):
            with self.subTest(change=change), self.assertRaises(LiveValidationError):
                replace(source, **change)
        value = parse_canonical(physical_plan().canonical_bytes)
        value["sources"][0]["format"] = "FLOAT_LE"
        with self.assertRaises(LiveValidationError):
            CapturePlanV1.from_bytes(canonical(value))

    def test_duplicate_nonfinite_and_noncanonical_json(self):
        for raw in (b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b'{ "x":1}\n', b'[]\n'):
            with self.subTest(raw=raw), self.assertRaises(LiveValidationError):
                parse_canonical(raw)

    def test_synthetic_cannot_promote_or_mutate_payload(self):
        source = synthetic_demo_plan().sources[0]
        for label in ("bench", "field"):
            with self.assertRaises(LiveValidationError):
                replace(source, provenance=label)
        with self.assertRaises(LiveValidationError):
            CapturedBlockV1(bytearray(b"00"), 1, canonical({}))
        scratch = bytearray(b"01")
        block = CapturedBlockV1(bytes(scratch), 1, canonical({"accuracy": None}))
        scratch[0] = 9
        self.assertEqual(block.payload, b"01")
        with self.assertRaises(LiveValidationError):
            SyntheticBackendFactory((), synthetic=False)

    def test_limits_source_count_and_return_bounds(self):
        plan = synthetic_demo_plan()
        for update in ({"queue_bytes": 1}, {"reserve_bytes": 1}, {"duration_s": float("inf")},
                       {"max_chunk_bytes": 8 * 1024 * 1024 + 1}, {"chunk_frames": True}):
            with self.subTest(update=update), self.assertRaises(LiveValidationError):
                replace(plan.limits, **update)
        with self.assertRaises(LiveValidationError):
            replace(plan, sources=(plan.sources[0], plan.sources[0]))

    def test_huge_numeric_budget_is_friendly_refusal_before_startup(self):
        with mock.patch("os.open") as opening, mock.patch("ctypes.CDLL") as loading:
            for name in ("duration_s", "poll_timeout_s", "shutdown_timeout_s"):
                with self.subTest(name=name), self.assertRaises(LiveValidationError):
                    replace(synthetic_demo_plan().limits, **{name: 10**10000})
            opening.assert_not_called()
            loading.assert_not_called()

    def test_denial_has_zero_native_or_device_calls(self):
        plan = physical_plan()
        factory = mock.Mock(synthetic=False)
        with mock.patch("ctypes.CDLL", side_effect=AssertionError("native load")), \
             mock.patch("os.stat", side_effect=AssertionError("stat")), \
             mock.patch("os.open", side_effect=AssertionError("open")), \
             mock.patch("os.scandir", side_effect=AssertionError("enumeration")), \
             mock.patch("os.readlink", side_effect=AssertionError("resolution")):
            with self.assertRaises(DeviceAccessDenied):
                LiveCaptureSupervisor().run(plan, factory, "/never-created")
            for ack in (None, "yes", acknowledgment_text(synthetic_demo_plan())):
                with self.assertRaises(DeviceAccessDenied):
                    authorize_device_access(plan, ack, "capture-only")
        factory.open.assert_not_called()

    def test_environment_cannot_enable(self):
        plan = physical_plan()
        with mock.patch.dict(os.environ, {"POSEIDON_DEVICE_ACCESS": "true", "POSEIDON_CAPTURE_ACK": acknowledgment_text(plan)}):
            with self.assertRaises(DeviceAccessDenied):
                authorize_device_access(plan, None, "capture-only")

    def test_grant_exact_plan_once_and_worker_once(self):
        plan = physical_plan()
        with mock.patch("poseidon_acoustic.live_gate.sys.platform", "linux"):
            grant = authorize_device_access(plan, acknowledgment_text(plan), "capture-only")
            admissions = consume_device_access(plan, grant)
            validate_worker_admission(admissions[0], plan, plan.sources[0])
            with self.assertRaises(DeviceAccessDenied):
                validate_worker_admission(admissions[0], plan, plan.sources[0])
            with self.assertRaises(DeviceAccessDenied):
                consume_device_access(plan, grant)
            with self.assertRaises(DeviceAccessDenied):
                authorize_device_access(plan, acknowledgment_text(plan), "capture-only")

    def test_constructed_worker_ticket_is_not_an_issued_grant(self):
        plan = physical_plan()
        ticket = WorkerAdmissionV1(plan.sha256, plan.sources[0].sha256, float("inf"), "unissued")
        with mock.patch("poseidon_acoustic.live_gate.sys.platform", "linux"):
            with self.assertRaises(DeviceAccessDenied):
                validate_worker_admission(ticket, plan, plan.sources[0])

    def test_acknowledgment_challenge_is_fresh_local_and_single_use(self):
        plan = physical_plan()
        with mock.patch("poseidon_acoustic.live_gate.sys.platform", "linux"), \
             mock.patch("poseidon_acoustic.live_gate.time.monotonic", return_value=100.0):
            acknowledgment = acknowledgment_text(plan)
        with mock.patch("poseidon_acoustic.live_gate.sys.platform", "linux"), \
             mock.patch("poseidon_acoustic.live_gate.time.monotonic", return_value=161.0):
            with self.assertRaises(DeviceAccessDenied):
                authorize_device_access(plan, acknowledgment, "capture-only")
            fresh = acknowledgment_text(plan)
            self.assertNotEqual(fresh, acknowledgment)
            with self.assertRaises(DeviceAccessDenied):
                authorize_device_access(plan, acknowledgment, "capture-only")
            with self.assertRaises(DeviceAccessDenied):
                authorize_device_access(plan, fresh, "capture-only")

    def test_cross_plan_and_stale_grants_burn_attempt(self):
        for stale in (False, True):
            plan = physical_plan()
            with mock.patch("poseidon_acoustic.live_gate.sys.platform", "linux"):
                grant = authorize_device_access(plan, acknowledgment_text(plan), "capture-only")
                with mock.patch("poseidon_acoustic.live_gate.time.monotonic", return_value=grant.expires_monotonic + 1 if stale else grant.issued_monotonic):
                    with self.assertRaises(DeviceAccessDenied):
                        consume_device_access(plan if stale else replace(plan, actor="other"), grant)
                with self.assertRaises(DeviceAccessDenied):
                    consume_device_access(plan, grant)

    def test_nonlinux_and_noncapture_refused(self):
        plan = physical_plan()
        with mock.patch("poseidon_acoustic.live_gate.sys.platform", "darwin"):
            with self.assertRaises(DeviceAccessDenied):
                authorize_device_access(plan, acknowledgment_text(plan), "capture-only")
        with self.assertRaises(DeviceAccessDenied):
            authorize_device_access(plan, acknowledgment_text(plan), "playback")

    def test_cli_nonregular_plan_refused_before_open_or_native_load(self):
        for command in ("validate", "capture"):
            for mode in (stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFLNK):
                with self.subTest(command=command, mode=mode), \
                     mock.patch("poseidon_acoustic.live_journal.os.lstat", return_value=SimpleNamespace(st_mode=mode, st_size=0)), \
                     mock.patch("os.open") as opening, mock.patch.object(Path, "open") as path_opening, \
                     mock.patch("ctypes.CDLL") as loading, \
                     mock.patch.object(LiveCaptureSupervisor, "run") as startup, \
                     contextlib.redirect_stderr(io.StringIO()):
                    args = [command, "--plan", "/host-fake/selected-plan"]
                    if command == "capture":
                        args.extend(["--output-dir", "/never-created"])
                    self.assertEqual(main(args), 2)
                    opening.assert_not_called()
                    path_opening.assert_not_called()
                    loading.assert_not_called()
                    startup.assert_not_called()

    def test_help_validate_and_denied_cli_do_not_import_native(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "plan.json"
            path.write_bytes(physical_plan().canonical_bytes)
            with mock.patch("ctypes.CDLL", side_effect=AssertionError("native")), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as end:
                    main(["--help"])
                self.assertEqual(end.exception.code, 0)
                self.assertEqual(main(["validate", "--plan", str(path)]), 0)
                self.assertEqual(main(["capture", "--plan", str(path), "--output-dir", str(Path(root) / "denied")]), 2)
                self.assertFalse((Path(root) / "denied").exists())


if __name__ == "__main__":
    unittest.main()
