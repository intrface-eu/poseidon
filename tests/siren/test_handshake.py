"""K4 bounded integer-time simulator checks, not output-chain evidence."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from poseidon_siren import EnableToken, Scheduler, SimulatorBackend, SirenDenied, SirenFault
from poseidon_siren import scheduler as implementation
from poseidon_siren.simulator import SimulatorFault


class HandshakeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.count = 0

    def initialize(self, backend=None, **kwargs):
        self.count += 1
        scheduler = Scheduler.initialize(self.root / str(self.count), backend=backend, **kwargs)
        self.addCleanup(scheduler.close)
        return scheduler

    def rearm(self, scheduler, now=0):
        return scheduler.rearm_simulation(now, acknowledge_simulation_only=True)

    def assert_inhibited_fault(self, scheduler, reason, *, durable=True):
        self.assertTrue(scheduler.status["inhibited"])
        self.assertEqual(scheduler.status["fault"], reason)
        self.assertIsNone(scheduler.handshake_status["token"])
        self.assertIsNone(scheduler.handshake_status["pending"])
        self.assertEqual(scheduler.handshake_status["audit_persisted"], durable)
        self.assertTrue(any(e["action"] == "fault" and e["reason"] == reason
                            for e in scheduler.status["audit"]))
        if durable:
            disk = json.loads((scheduler.directory / "state.json").read_bytes())["payload"]
            self.assertEqual(disk, scheduler.status)
        self.assertFalse(scheduler.status["physical_output_enabled"])
        self.assertTrue(all(not e["physical_output_enabled"] for e in scheduler.status["audit"]))

    def test_startup_never_requests_an_enable_and_default_is_compatible(self):
        backend = SimulatorBackend()
        with patch.object(backend, "begin_enable", wraps=backend.begin_enable) as begin:
            scheduler = self.initialize(backend)
            self.assertEqual(begin.call_count, 0)
            self.assertTrue(scheduler.status["inhibited"])
            self.assertIsNone(scheduler.handshake_status["token"])
            with self.assertRaisesRegex(SirenDenied, "inhibited"):
                scheduler.request(0, 1)
            self.assertEqual(begin.call_count, 0)
            token = self.rearm(scheduler)
            self.assertIsInstance(token, EnableToken)
            self.assertEqual(begin.call_count, 1)
        self.assertTrue(token.simulation_only)
        self.assertFalse(token.physical_output_enabled)
        with self.assertRaises(FrozenInstanceError):
            token.token_id = "changed"
        self.assertEqual(scheduler.request(0, 500).end_ms, 500)
        self.assertTrue(scheduler.handshake_status["audit_persisted"])
        snapshot = scheduler.handshake_status
        snapshot["token"]["expires_at_ms"] = 10**20
        self.assertEqual(scheduler.handshake_status["token"]["expires_at_ms"], 60_000)
        stored = (scheduler.directory / "state.json").read_text()
        self.assertNotIn(token.token_id, stored)
        self.assertNotIn(token.session_id, stored)
        self.assertIn(token.request_id, stored)

    def test_delayed_ack_remains_inhibited_until_observed_within_bound(self):
        backend = SimulatorBackend(ack_delay_ms=30)
        scheduler = self.initialize(backend, ack_timeout_ms=100)
        self.assertIsNone(self.rearm(scheduler, 10))
        pending = scheduler.handshake_status["pending"]
        self.assertEqual(pending["deadline_ms"], 110)
        with self.assertRaisesRegex(SirenDenied, "inhibited"):
            scheduler.request(10, 1)
        with self.assertRaisesRegex(SirenDenied, "poll_required"):
            self.rearm(scheduler, 20)
        self.assertEqual(scheduler.handshake_status["pending"], pending)
        self.assertIsNone(scheduler.poll_simulation(39))
        self.assertTrue(scheduler.status["inhibited"])
        token = scheduler.poll_simulation(40)
        self.assertEqual(token.acknowledged_at_ms, 40)
        self.assertEqual(token.request_id, pending["request_id"])
        self.assertFalse(scheduler.status["inhibited"])
        self.assertEqual(scheduler.request(40, 1).end_ms, 41)

    def test_exact_ack_deadline_is_inclusive_but_missed_poll_is_not(self):
        scheduler = self.initialize(SimulatorBackend(ack_delay_ms=100), ack_timeout_ms=100)
        self.assertIsNone(self.rearm(scheduler))
        self.assertIsNone(scheduler.poll_simulation(99))
        self.assertIsInstance(scheduler.poll_simulation(100), EnableToken)
        # Even an ack ready earlier is late if the scheduler missed observation.
        for delay in (10, 100, 101):
            with self.subTest(delay=delay):
                late = self.initialize(SimulatorBackend(ack_delay_ms=delay), ack_timeout_ms=100)
                self.assertIsNone(self.rearm(late))
                with self.assertRaisesRegex(SirenFault, "enable_ack_deadline"):
                    late.poll_simulation(101)
                self.assert_inhibited_fault(late, "enable_ack_deadline")

    def test_delay_beyond_bound_drop_and_missing_ack_fault_at_deadline(self):
        for backend in (SimulatorBackend(ack_delay_ms=101), SimulatorBackend(drop_ack=True)):
            with self.subTest(backend=backend):
                scheduler = self.initialize(backend, ack_timeout_ms=100)
                self.assertIsNone(self.rearm(scheduler))
                self.assertIsNone(scheduler.poll_simulation(99))
                with self.assertRaisesRegex(SirenFault, "enable_ack_deadline"):
                    scheduler.poll_simulation(100)
                self.assert_inhibited_fault(scheduler, "enable_ack_deadline")
                with self.assertRaises(SirenFault):
                    self.rearm(scheduler, 100)
                with self.assertRaises(SirenFault):
                    scheduler.request(100, 1)
        backend = SimulatorBackend()
        scheduler = self.initialize(backend, ack_timeout_ms=1)
        with patch.object(backend, "poll_ack", return_value=None):
            self.assertIsNone(self.rearm(scheduler))
            with self.assertRaisesRegex(SirenFault, "enable_ack_deadline"):
                scheduler.poll_simulation(1)
        self.assert_inhibited_fault(scheduler, "enable_ack_deadline")

    def test_late_old_rearm_or_request_cannot_restart_pending_deadline(self):
        for operation in (self.rearm, lambda s, now: s.request(now, 1), lambda s, now: s.stop(now)):
            for now in (5, 6):
                scheduler = self.initialize(SimulatorBackend(drop_ack=True), ack_timeout_ms=5)
                self.assertIsNone(self.rearm(scheduler))
                with self.assertRaisesRegex(SirenFault, "enable_ack_deadline"):
                    operation(scheduler, now)
                self.assert_inhibited_fault(scheduler, "enable_ack_deadline")

    def test_wrong_malformed_and_forged_acknowledgments_are_not_enable_tokens(self):
        mutations = [
            lambda t: {}, lambda t: "ack", lambda t: replace(t, session_id="wrong"),
            lambda t: replace(t, request_id="wrong"), lambda t: replace(t, token_id=""),
            lambda t: replace(t, token_id="x" * 32), lambda t: replace(t, token_id="0" * 32),
            lambda t: replace(t, acknowledged_at_ms=True),
            lambda t: replace(t, acknowledged_at_ms=-1),
            lambda t: replace(t, acknowledged_at_ms=1),
            lambda t: replace(t, expires_at_ms=True), lambda t: replace(t, expires_at_ms=0),
            lambda t: replace(t, expires_at_ms=86_400_001),
        ]
        for mutate in mutations:
            backend = SimulatorBackend()
            scheduler = self.initialize(backend)
            original = backend.poll_ack
            with self.subTest(mutate=mutate), patch.object(backend, "poll_ack", side_effect=lambda n: mutate(original(n))):
                with self.assertRaises(SirenFault):
                    self.rearm(scheduler)
            self.assertIn(scheduler.status["fault"], ("invalid_enable_ack", "backend_token_mismatch"))
            self.assert_inhibited_fault(scheduler, scheduler.status["fault"])
            self.assertEqual(scheduler.status["reservations"], [])

    def test_stopped_token_cannot_acknowledge_a_new_request(self):
        backend = SimulatorBackend()
        scheduler = self.initialize(backend)
        old = self.rearm(scheduler)
        scheduler.request(0, 500)
        scheduler.stop(0)
        self.assertIsNone(scheduler.handshake_status["token"])
        with self.assertRaises(SimulatorFault):
            backend.check_token(old, 0)
        with patch.object(backend, "poll_ack", return_value=old):
            with self.assertRaisesRegex(SirenFault, "invalid_enable_ack"):
                self.rearm(scheduler)
        self.assert_inhibited_fault(scheduler, "invalid_enable_ack")
        self.assertEqual(scheduler.status["reservations"], [[0, 500]])

    def test_stop_cancel_and_rearm_issue_a_new_token_without_refund(self):
        scheduler = self.initialize()
        old = self.rearm(scheduler)
        with self.assertRaisesRegex(SirenDenied, "stop_required"):
            self.rearm(scheduler)
        scheduler.request(0, 500)
        scheduler.stop(1)
        fresh = self.rearm(scheduler, 1)
        self.assertNotEqual(old.request_id, fresh.request_id)
        self.assertNotEqual(old.token_id, fresh.token_id)
        with self.assertRaisesRegex(SirenDenied, "overlap"):
            scheduler.request(1, 1)
        pending = self.initialize(SimulatorBackend(ack_delay_ms=10))
        self.assertIsNone(self.rearm(pending))
        old_request = pending.handshake_status["pending"]["request_id"]
        pending.stop(1)
        with self.assertRaisesRegex(SirenDenied, "inhibited"):
            pending.poll_simulation(10)
        self.assertIsNone(self.rearm(pending, 10))
        token = pending.poll_simulation(20)
        self.assertNotEqual(token.request_id, old_request)

    def test_restart_drops_token_and_rejects_old_session_ack(self):
        backend = SimulatorBackend()
        scheduler = self.initialize(backend)
        old = self.rearm(scheduler)
        scheduler.request(0, 500)
        scheduler.close()
        with Scheduler(scheduler.directory, backend=backend) as recovered:
            self.assertTrue(recovered.status["inhibited"])
            self.assertIsNone(recovered.handshake_status["token"])
            self.assertNotEqual(recovered.handshake_status["session_id"], old.session_id)
            self.assertEqual(recovered.status["reservations"], [[0, 500]])
            with self.assertRaisesRegex(SirenDenied, "inhibited"):
                recovered.request(0, 1)
            with patch.object(backend, "poll_ack", return_value=old):
                with self.assertRaisesRegex(SirenFault, "invalid_enable_ack"):
                    self.rearm(recovered)
            self.assert_inhibited_fault(recovered, "invalid_enable_ack")
        with Scheduler(scheduler.directory) as recovered:
            with self.assertRaisesRegex(SirenFault, "invalid_enable_ack"):
                self.rearm(recovered)

    def test_token_must_cover_full_half_open_reservation_and_expiry_is_exclusive(self):
        scheduler = self.initialize(SimulatorBackend(token_ttl_ms=500))
        token = self.rearm(scheduler)
        self.assertEqual(scheduler.request(0, 500).end_ms, token.expires_at_ms)
        self.assertEqual(scheduler.poll_simulation(499), token)
        with self.assertRaisesRegex(SirenFault, "enable_token_expired"):
            scheduler.poll_simulation(500)
        self.assert_inhibited_fault(scheduler, "enable_token_expired")
        self.assertEqual(scheduler.status["reservations"], [[0, 500]])
        short = self.initialize(SimulatorBackend(token_ttl_ms=499))
        self.rearm(short)
        with self.assertRaisesRegex(SirenFault, "enable_token_expired"):
            short.request(0, 500)
        self.assert_inhibited_fault(short, "enable_token_expired")
        self.assertEqual(short.status["reservations"], [])

    def test_expiry_cannot_be_bypassed_by_old_rearm_request_or_stop(self):
        for operation in (self.rearm, lambda s, now: s.request(now, 1), lambda s, now: s.stop(now)):
            scheduler = self.initialize(SimulatorBackend(token_ttl_ms=1))
            self.rearm(scheduler)
            with self.assertRaisesRegex(SirenFault, "enable_token_expired"):
                operation(scheduler, 1)
            self.assert_inhibited_fault(scheduler, "enable_token_expired")

    def test_ack_expired_before_observation_is_refused(self):
        scheduler = self.initialize(SimulatorBackend(ack_delay_ms=1, token_ttl_ms=1))
        self.assertIsNone(self.rearm(scheduler))
        with self.assertRaisesRegex(SirenFault, "enable_token_expired"):
            scheduler.poll_simulation(2)
        self.assert_inhibited_fault(scheduler, "enable_token_expired")

    def test_disconnect_and_underrun_during_ack_and_enable_latch_audit(self):
        for kind in ("disconnect", "underrun"):
            for phase in ("check", "poll", "enable"):
                with self.subTest(kind=kind, phase=phase):
                    backend = SimulatorBackend()
                    backend.inject_fault(kind, on=phase)
                    scheduler = self.initialize(backend)
                    self.assertTrue(scheduler.status["inhibited"])
                    self.assertIsNone(scheduler.status["fault"])
                    with self.assertRaisesRegex(SirenFault, f"backend_{kind}"):
                        self.rearm(scheduler)
                    self.assert_inhibited_fault(scheduler, f"backend_{kind}")
                    self.assertEqual(scheduler.status["reservations"], [])
                    with self.assertRaises(SirenFault):
                        self.rearm(scheduler)

    def test_disconnect_and_underrun_while_pending_and_while_enabled(self):
        for kind in ("disconnect", "underrun"):
            for pending in (True, False):
                backend = SimulatorBackend(ack_delay_ms=10 if pending else 0)
                scheduler = self.initialize(backend)
                self.rearm(scheduler)
                backend.inject_fault(kind)
                with self.assertRaisesRegex(SirenFault, f"backend_{kind}"):
                    scheduler.poll_simulation(1)
                self.assert_inhibited_fault(scheduler, f"backend_{kind}")

    def test_pending_backend_fault_cannot_be_hidden_by_old_rearm_or_request(self):
        for kind in ("disconnect", "underrun"):
            for operation in (self.rearm, lambda s, now: s.request(now, 1)):
                backend = SimulatorBackend(drop_ack=True)
                scheduler = self.initialize(backend)
                self.assertIsNone(self.rearm(scheduler))
                backend.inject_fault(kind)
                with self.assertRaisesRegex(SirenFault, f"backend_{kind}"):
                    operation(scheduler, 1)
                self.assert_inhibited_fault(scheduler, f"backend_{kind}")

    def test_backend_failure_before_reservation_never_charges_a_grant(self):
        for kind in ("disconnect", "underrun"):
            backend = SimulatorBackend()
            scheduler = self.initialize(backend)
            self.rearm(scheduler)
            backend.inject_fault(kind)
            with self.assertRaisesRegex(SirenFault, f"backend_{kind}"):
                scheduler.request(0, 500)
            self.assert_inhibited_fault(scheduler, f"backend_{kind}")
            self.assertEqual(scheduler.status["reservations"], [])

    def test_backend_failure_after_reservation_keeps_full_durable_charge(self):
        for kind in ("disconnect", "underrun"):
            backend = SimulatorBackend()
            scheduler = self.initialize(backend)
            self.rearm(scheduler)
            backend.inject_fault(kind, on="reserve")
            with self.assertRaisesRegex(SirenFault, f"backend_{kind}"):
                scheduler.request(0, 500)
            self.assert_inhibited_fault(scheduler, f"backend_{kind}")
            self.assertEqual(scheduler.status["reservations"], [[0, 500]])
            scheduler.close()
            with Scheduler(scheduler.directory) as recovered:
                self.assertEqual(recovered.status["reservations"], [[0, 500]])
                with self.assertRaisesRegex(SirenFault, f"backend_{kind}"):
                    self.rearm(recovered)

    def test_lost_backend_token_is_detected_by_old_request_api(self):
        backend = SimulatorBackend()
        scheduler = self.initialize(backend)
        self.rearm(scheduler)
        backend.inhibit()
        with self.assertRaisesRegex(SirenFault, "backend_token_mismatch"):
            scheduler.request(0, 1)
        self.assert_inhibited_fault(scheduler, "backend_token_mismatch")

    def test_enable_audit_write_failure_revokes_and_reports_unconfirmed_durability(self):
        backend = SimulatorBackend()
        scheduler = self.initialize(backend)
        write = implementation._atomic_write

        def fail_enable(directory, state):
            if state["audit"][-1]["action"] == "simulation_rearm":
                raise OSError("synthetic audit disk full")
            return write(directory, state)

        with patch.object(implementation, "_atomic_write", side_effect=fail_enable):
            with self.assertRaisesRegex(SirenFault, "audit durability unconfirmed"):
                self.rearm(scheduler)
        self.assert_inhibited_fault(scheduler, "persistence_failure", durable=False)
        disk = json.loads((scheduler.directory / "state.json").read_bytes())["payload"]
        self.assertTrue(disk["inhibited"])
        self.assertIsNone(disk["fault"])
        self.assertNotEqual(disk["audit"], scheduler.status["audit"])
        scheduler.close()
        self.assertTrue(scheduler.handshake_status["audit_persisted"])

    def test_post_reservation_fault_audit_failure_never_claims_durable_fault(self):
        backend = SimulatorBackend()
        scheduler = self.initialize(backend)
        self.rearm(scheduler)
        backend.inject_fault("disconnect", on="reserve")
        write = implementation._atomic_write

        def fail_fault(directory, state):
            if state["audit"][-1]["action"] == "fault":
                raise OSError("synthetic fault audit write failure")
            return write(directory, state)

        with patch.object(implementation, "_atomic_write", side_effect=fail_fault):
            with self.assertRaisesRegex(SirenFault, "audit durability unconfirmed"):
                scheduler.request(0, 500)
        self.assert_inhibited_fault(scheduler, "backend_disconnect", durable=False)
        disk = json.loads((scheduler.directory / "state.json").read_bytes())["payload"]
        self.assertEqual(disk["reservations"], [[0, 500]])
        self.assertIsNone(disk["fault"])
        scheduler.close()
        with Scheduler(scheduler.directory) as recovered:
            self.assertEqual(recovered.status["reservations"], [[0, 500]])
            self.assert_inhibited_fault(recovered, "backend_disconnect")

    def test_pending_poll_and_enable_audit_capacity_are_bounded_and_revoke(self):
        for backend in (SimulatorBackend(drop_ack=True), SimulatorBackend()):
            scheduler = self.initialize(backend)
            with patch.object(implementation, "MAX_AUDIT", 4):
                with self.assertRaisesRegex(SirenFault, "audit_capacity"):
                    self.rearm(scheduler)
                self.assertEqual(len(scheduler.status["audit"]), 4)
                self.assert_inhibited_fault(scheduler, "audit_capacity")
        scheduler = self.initialize(SimulatorBackend(drop_ack=True))
        self.rearm(scheduler)
        with patch.object(implementation, "MAX_AUDIT", 8):
            with self.assertRaisesRegex(SirenFault, "audit_capacity"):
                for _ in range(10):
                    scheduler.poll_simulation(0)
            self.assertEqual(len(scheduler.status["audit"]), 8)
            self.assert_inhibited_fault(scheduler, "audit_capacity")

    def test_bounded_settings_and_simulator_only_boundary(self):
        for value in (0, -1, True, 0.5, float("nan"), float("inf"), 10_001):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                self.initialize(ack_timeout_ms=value)
        for kwargs in ({"ack_delay_ms": -1}, {"ack_delay_ms": True}, {"ack_delay_ms": 86_400_001},
                       {"drop_ack": 1}, {"token_ttl_ms": 0}, {"token_ttl_ms": True},
                       {"token_ttl_ms": 86_400_001}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SimulatorBackend(**kwargs)
        class OtherBackend(SimulatorBackend):
            pass
        for backend in (object(), OtherBackend()):
            with self.assertRaisesRegex(ValueError, "in-process SimulatorBackend"):
                self.initialize(backend)
        backend = SimulatorBackend()
        with self.assertRaises(ValueError):
            backend.inject_fault("other")
        with self.assertRaises(ValueError):
            backend.inject_fault("disconnect", on="other")
        scheduler = self.initialize(backend)
        token = self.rearm(scheduler)
        with self.assertRaisesRegex(SirenFault, "already belongs"):
            self.initialize(backend)
        self.assertEqual(scheduler.poll_simulation(0), token)


if __name__ == "__main__":
    unittest.main()
