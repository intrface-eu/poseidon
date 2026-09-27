"""In-process integer-time handshake fixture. No transport or output driver."""

from dataclasses import dataclass, field
from uuid import uuid4

MAX_ACK_TIMEOUT_MS = 10_000
MAX_TOKEN_TTL_MS = 86_400_000


def _bounded(value: object, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"invalid {name}")
    return value


@dataclass(frozen=True)
class EnableToken:
    """Ephemeral simulator acknowledgment, never physical authorization."""

    session_id: str
    request_id: str
    token_id: str
    acknowledged_at_ms: int
    expires_at_ms: int
    simulation_only: bool = field(default=True, init=False)
    physical_output_enabled: bool = field(default=False, init=False)


class SimulatorFault(RuntimeError):
    """A latched, injected backend fault or invalid simulator token."""


class SimulatorBackend:
    """One scheduler per instance. Every operation returns without waiting.

    Delay/drop apply to acknowledgments. Disconnect/underrun can be injected at
    the next poll, enable check, reservation check, or health check. Inhibit
    revokes pending acknowledgments and tokens, but never clears backend faults.
    """

    def __init__(self, *, ack_delay_ms: int = 0, drop_ack: bool = False,
                 token_ttl_ms: int = 60_000):
        self._ack_delay_ms = _bounded(ack_delay_ms, 0, MAX_TOKEN_TTL_MS, "ack_delay_ms")
        self._token_ttl_ms = _bounded(token_ttl_ms, 1, MAX_TOKEN_TTL_MS, "token_ttl_ms")
        if type(drop_ack) is not bool:
            raise ValueError("invalid drop_ack")
        self._drop_ack = drop_ack
        self._session_id = None
        self._pending = None
        self._token = None
        self._fault = None
        self._injections = {}

    def _attach(self, session_id: str) -> None:
        if self._session_id is not None:
            raise ValueError("simulator already belongs to an open scheduler")
        self.inhibit()
        self._session_id = session_id

    def _detach(self) -> None:
        self.inhibit()
        self._session_id = None

    def inhibit(self) -> None:
        self._pending = None
        self._token = None

    def inject_fault(self, kind: str, *, on: str = "check") -> None:
        if kind not in {"disconnect", "underrun"}:
            raise ValueError("invalid simulator fault")
        if on not in {"poll", "enable", "reserve", "check"}:
            raise ValueError("invalid simulator checkpoint")
        self._injections[on] = kind

    def _checkpoint(self, phase: str) -> None:
        fault = self._injections.pop(phase, None)
        self._fault = self._fault or fault
        if self._fault:
            self.inhibit()
            raise SimulatorFault(f"backend_{self._fault}")

    def check_health(self) -> None:
        self._checkpoint("check")

    def begin_enable(self, session_id: str, request_id: str, now_ms: int) -> None:
        self.inhibit()
        if session_id != self._session_id:
            raise SimulatorFault("backend_session_mismatch")
        self._checkpoint("check")
        self._pending = (session_id, request_id, now_ms + self._ack_delay_ms)

    def poll_ack(self, now_ms: int) -> EnableToken | None:
        self._checkpoint("check")
        self._checkpoint("poll")
        if self._pending is None or self._drop_ack or now_ms < self._pending[2]:
            return None
        session_id, request_id, due_ms = self._pending
        self._pending = None
        self._token = EnableToken(session_id, request_id, uuid4().hex,
                                  due_ms, due_ms + self._token_ttl_ms)
        return self._token

    def check_token(self, token: EnableToken, now_ms: int, *, phase: str = "check") -> None:
        self._checkpoint("check")
        if phase != "check":
            self._checkpoint(phase)
        if self._token is None or token != self._token or token.session_id != self._session_id:
            raise SimulatorFault("backend_token_mismatch")
        if now_ms >= token.expires_at_ms:
            raise SimulatorFault("enable_token_expired")
