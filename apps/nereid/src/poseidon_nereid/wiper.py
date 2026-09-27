"""Simulation-only fail-safe wiper logic. No GPIO, servo library or live port."""
from __future__ import annotations

from dataclasses import dataclass, field

from poseidon_acoustic.session import SessionError, finite, positive_int


@dataclass(frozen=True)
class WiperPolicy:
    wipe_s: float = 1.0
    cooldown_s: float = 10.0
    watchdog_s: float = 0.5
    max_cycles: int = 3

    def __post_init__(self):
        for name in ("wipe_s", "cooldown_s", "watchdog_s"):
            if finite(getattr(self, name), name) <= 0:
                raise SessionError("simulation durations must be finite and positive")
        positive_int(self.max_cycles, "cycle budget", maximum=1000)


@dataclass
class SimulatedActuator:
    energized: bool = False
    fail_on_start: bool = False
    commands: list[bool] = field(default_factory=list)

    def set(self, enabled: bool):
        if type(enabled) is not bool:
            raise SessionError("boolean simulated command required")
        if enabled and self.fail_on_start:
            raise SessionError("injected simulated actuator failure")
        if len(self.commands) >= 4096:
            self.energized = False
            if enabled:
                raise SessionError("simulated command log capacity reached")
            return
        self.energized = enabled
        self.commands.append(enabled)


class Wiper:
    """Each tick supplies a simulated independent inhibit input.

    A tick watchdog is a software test, not an independent hardware watchdog.
    Real actuator power removal, travel limits and jam detection remain unbuilt.
    """

    hardware_verified = False

    def __init__(self, actuator: SimulatedActuator, policy: WiperPolicy | None = None):
        if type(actuator) is not SimulatedActuator:
            raise SessionError("only the in-memory simulated actuator is allowed")
        self.policy = WiperPolicy() if policy is None else policy
        if not isinstance(self.policy, WiperPolicy):
            raise SessionError("wiper policy required")
        self.actuator = actuator
        self.state = "inhibited"
        self.fault_reason = None
        self.last_s = None
        self.deadline_s = None
        self.next_allowed_s = 0.0
        self.cycles = 0
        self.audit = []
        self.actuator.set(False)

    def _record(self, event: str):
        # Bounded audit: refuse new actions rather than discard the oldest record.
        if len(self.audit) >= 4096:
            self.actuator.set(False)
            self.state = "fault"
            self.fault_reason = "audit_capacity"
            raise SessionError("wiper audit capacity reached")
        self.audit.append({"event": event, "state": self.state, "simulation_time_s": self.last_s,
                           "cycles": self.cycles, "energized": self.actuator.energized,
                           "fault_reason": self.fault_reason, "hardware_verified": False})

    def _fault(self, reason: str):
        self.actuator.set(False)
        self.state = "fault"
        self.fault_reason = reason
        self._record("fault")

    def tick(self, now_s: float, *, inhibit_released: bool = False, jam_declared: bool = False) -> str:
        try:
            finite(now_s, "simulation clock", nonnegative=True)
        except SessionError:
            self._fault("invalid_clock")
            return self.state
        if type(inhibit_released) is not bool or type(jam_declared) is not bool:
            self._fault("invalid_inhibit_or_jam_input")
            return self.state
        if jam_declared:
            self._fault("operator_declared_simulated_jam")
            return self.state
        if self.last_s is not None and now_s < self.last_s:
            self._fault("clock_reversed")
            return self.state
        if self.last_s is not None and self.state in {"armed", "wiping"} and now_s - self.last_s > self.policy.watchdog_s:
            self.last_s = now_s
            self._fault("watchdog_expired")
            return self.state
        self.last_s = now_s
        if self.state == "fault":
            self.actuator.set(False)
            return self.state
        if not inhibit_released:
            self.actuator.set(False)
            self.state = "inhibited"
            self._record("independent_inhibit")
            return self.state
        if self.state == "wiping" and now_s >= self.deadline_s:
            self.actuator.set(False)
            self.state = "cooldown"
            try:
                self.deadline_s = finite(now_s + self.policy.cooldown_s, "cooldown deadline")
                if self.deadline_s <= now_s:
                    raise SessionError("cooldown lost duration to numeric precision")
            except SessionError:
                self._fault("invalid_cooldown_deadline")
                return self.state
            self.next_allowed_s = self.deadline_s
            self._record("wipe_finished")
        elif self.state == "cooldown" and now_s >= self.deadline_s:
            self.state = "armed"
            self._record("cooldown_finished")
        return self.state

    def arm(self, now_s: float, *, operator_enable: bool = False, inhibit_released: bool = False) -> str:
        self.tick(now_s, inhibit_released=inhibit_released)
        if type(operator_enable) is not bool:
            self._fault("invalid_operator_enable")
        elif operator_enable and inhibit_released and self.state == "inhibited":
            self.state = "armed"
            self._record("operator_armed")
        return self.state

    def request(self, now_s: float, *, inhibit_released: bool = False) -> bool:
        self.tick(now_s, inhibit_released=inhibit_released)
        if self.state != "armed" or now_s < self.next_allowed_s:
            return False
        if self.cycles >= self.policy.max_cycles:
            self._fault("cycle_capacity")
            return False
        try:
            deadline = finite(now_s + self.policy.wipe_s, "wipe deadline")
            next_allowed = finite(deadline + self.policy.cooldown_s, "cooldown deadline")
            if deadline <= now_s or next_allowed <= deadline:
                raise SessionError("wiper deadline lost duration to numeric precision")
            self.actuator.set(True)
        except SessionError:
            self._fault("simulated_actuator_or_deadline_fault")
            return False
        self.cycles += 1
        self.deadline_s = deadline
        self.next_allowed_s = next_allowed
        self.state = "wiping"
        self._record("wipe_started")
        return True

    def stop(self) -> str:
        self.actuator.set(False)
        if self.state != "fault":
            self.state = "inhibited"
        self._record("operator_stop")
        return self.state
