from __future__ import annotations

import unittest

from poseidon_acoustic.session import SessionError, canonical
from poseidon_nereid.wiper import SimulatedActuator, Wiper, WiperPolicy


class WiperTests(unittest.TestCase):
    def start(self, **changes):
        actuator = SimulatedActuator()
        wiper = Wiper(actuator, WiperPolicy(**changes))
        self.assertEqual(wiper.arm(0, operator_enable=True, inhibit_released=True), "armed")
        self.assertTrue(wiper.request(0, inhibit_released=True))
        return wiper, actuator

    def test_default_inhibit_and_explicit_operator_enable(self):
        actuator = SimulatedActuator()
        wiper = Wiper(actuator)
        self.assertFalse(wiper.request(0))
        self.assertEqual(wiper.arm(0, inhibit_released=True), "inhibited")
        self.assertEqual(wiper.arm(0, operator_enable=True), "inhibited")
        self.assertFalse(actuator.energized)
        self.assertFalse(wiper.hardware_verified)
        self.assertNotIn(True, actuator.commands)

    def test_wipe_cooldown_and_second_cycle(self):
        wiper, actuator = self.start()
        self.assertTrue(actuator.energized)
        for time_s in (0.25, 0.5, 0.75):
            self.assertEqual(wiper.tick(time_s, inhibit_released=True), "wiping")
        self.assertEqual(wiper.tick(1, inhibit_released=True), "cooldown")
        self.assertFalse(actuator.energized)
        self.assertFalse(wiper.request(5, inhibit_released=True))
        self.assertTrue(wiper.request(11, inhibit_released=True))
        self.assertEqual(wiper.cycles, 2)
        self.assertEqual(wiper.stop(), "inhibited")
        self.assertFalse(actuator.energized)

    def test_independent_inhibit_stops_and_cannot_bypass_cooldown_by_rearming(self):
        wiper, actuator = self.start()
        self.assertEqual(wiper.tick(0.25), "inhibited")
        self.assertFalse(actuator.energized)
        wiper.arm(0.25, operator_enable=True, inhibit_released=True)
        self.assertFalse(wiper.request(0.25, inhibit_released=True))
        self.assertEqual(wiper.cycles, 1)

    def test_watchdog_and_backwards_clock_latch_fault_off(self):
        for time_s, reason in ((0.6, "watchdog_expired"), (-0.1, "invalid_clock")):
            wiper, actuator = self.start()
            self.assertEqual(wiper.tick(time_s, inhibit_released=True), "fault")
            self.assertEqual(wiper.fault_reason, reason)
            self.assertFalse(actuator.energized)
            self.assertEqual(wiper.arm(1, operator_enable=True, inhibit_released=True), "fault")
            self.assertFalse(wiper.request(1, inhibit_released=True))
        wiper, actuator = self.start()
        wiper.tick(0.4, inhibit_released=True)
        wiper.tick(0.3, inhibit_released=True)
        self.assertEqual(wiper.fault_reason, "clock_reversed")
        self.assertFalse(actuator.energized)

    def test_nonfinite_and_bad_boolean_inputs_fault_without_nonfinite_audit(self):
        for value in (float("nan"), float("inf"), "0", True):
            wiper, actuator = self.start()
            self.assertEqual(wiper.tick(value, inhibit_released=True), "fault")
            self.assertFalse(actuator.energized)
            canonical(wiper.audit)
        wiper, actuator = self.start()
        self.assertEqual(wiper.tick(0.1, inhibit_released="yes"), "fault")
        self.assertFalse(actuator.energized)

    def test_declared_jam_and_injected_actuator_failure_stop(self):
        wiper, actuator = self.start()
        self.assertEqual(wiper.tick(0.2, inhibit_released=True, jam_declared=True), "fault")
        self.assertFalse(actuator.energized)
        actuator = SimulatedActuator(fail_on_start=True)
        wiper = Wiper(actuator)
        wiper.arm(0, operator_enable=True, inhibit_released=True)
        self.assertFalse(wiper.request(0, inhibit_released=True))
        self.assertEqual(wiper.state, "fault")
        self.assertFalse(actuator.energized)

    def test_cycle_capacity_latches_fault(self):
        wiper, actuator = self.start(max_cycles=1)
        for time_s in (0.25, 0.5, 0.75, 1):
            wiper.tick(time_s, inhibit_released=True)
        self.assertFalse(wiper.request(11, inhibit_released=True))
        self.assertEqual(wiper.fault_reason, "cycle_capacity")
        self.assertFalse(actuator.energized)

    def test_invalid_policy_and_overflow_deadline_never_energize(self):
        for change in ({"wipe_s": 0}, {"cooldown_s": -1}, {"watchdog_s": float("nan")},
                       {"max_cycles": 0}, {"max_cycles": True}):
            with self.assertRaises(SessionError):
                WiperPolicy(**change)
        actuator = SimulatedActuator()
        wiper = Wiper(actuator, WiperPolicy(wipe_s=1e308, cooldown_s=1e308))
        wiper.arm(1e308, operator_enable=True, inhibit_released=True)
        self.assertFalse(wiper.request(1e308, inhibit_released=True))
        self.assertEqual(wiper.state, "fault")
        self.assertFalse(actuator.energized)
        self.assertNotIn(True, actuator.commands)

    def test_large_finite_clock_cannot_round_wipe_duration_to_zero(self):
        actuator = SimulatedActuator()
        wiper = Wiper(actuator)
        wiper.arm(1e30, operator_enable=True, inhibit_released=True)
        self.assertFalse(wiper.request(1e30, inhibit_released=True))
        self.assertEqual(wiper.state, "fault")
        self.assertFalse(actuator.energized)
        self.assertNotIn(True, actuator.commands)

    def test_audit_capacity_halts_without_deleting_evidence(self):
        actuator = SimulatedActuator()
        wiper = Wiper(actuator)
        for index in range(4096):
            wiper.tick(index)
        first = dict(wiper.audit[0])
        with self.assertRaises(SessionError):
            wiper.tick(4096)
        self.assertEqual(len(wiper.audit), 4096)
        self.assertEqual(wiper.audit[0], first)
        self.assertEqual(wiper.state, "fault")
        self.assertFalse(actuator.energized)

    def test_reboot_starts_inhibited_and_foreign_drivers_are_refused(self):
        wiper, actuator = self.start()
        restarted = Wiper(actuator)
        self.assertEqual(restarted.state, "inhibited")
        self.assertFalse(actuator.energized)
        with self.assertRaises(SessionError):
            Wiper(object())
        class NotAnAuthorizedDriver(SimulatedActuator):
            pass
        with self.assertRaises(SessionError):
            Wiper(NotAnAuthorizedDriver())


if __name__ == "__main__":
    unittest.main()
