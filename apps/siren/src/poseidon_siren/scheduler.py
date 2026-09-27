"""Persistent, single-writer scheduler for synthetic time and file simulations.

There is deliberately no output driver. Software state is not a physical inhibit.
An acknowledged request reserves its FULL interval durably before returning.
"""

from dataclasses import asdict, dataclass, field
import fcntl
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
from uuid import uuid4

from .simulator import EnableToken, MAX_ACK_TIMEOUT_MS, MAX_TOKEN_TTL_MS, SimulatorBackend, SimulatorFault

MAX_CLOCK_MS = 1_000_000_000_000
MAX_AUDIT = 512
MAX_RESERVATIONS = 128
MAX_STATE_BYTES = 1_048_576
PROVENANCE = "synthetic clock and reservations; software test only"


class SirenFault(RuntimeError):
    """Latched fault or failed startup; no further reservation is allowed."""


class SirenDenied(RuntimeError):
    """Inhibited, overlap, cooldown, or exhausted window budget."""


def _integer(value: object, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"invalid {name}")
    return value


@dataclass(frozen=True)
class Budget:
    """Milliseconds; all defaults/ceilings are software test envelopes ONLY."""

    window_ms: int = 10_000
    max_on_ms: int = 1_000
    max_burst_ms: int = 500
    cooldown_ms: int = 1_000

    def __post_init__(self) -> None:
        _integer(self.window_ms, 1, 86_400_000, "window_ms")
        _integer(self.max_on_ms, 1, self.window_ms, "max_on_ms")
        _integer(self.max_burst_ms, 1, min(10_000, self.max_on_ms), "max_burst_ms")
        _integer(self.cooldown_ms, 0, 86_400_000, "cooldown_ms")


@dataclass(frozen=True)
class Reservation:
    start_ms: int
    end_ms: int
    simulation_only: bool = field(default=True, init=False)
    physical_output_enabled: bool = field(default=False, init=False)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _atomic_write(directory: Path, state: dict) -> str:
    payload = _canonical(state)
    data = _canonical({"payload": state, "sha256": hashlib.sha256(payload).hexdigest()})
    if len(data) > MAX_STATE_BYTES:
        raise OSError("state capacity exceeded")
    fd, name = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, directory / "state.json")
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(name).unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def _open_regular(path: Path, flags: int):
    # Refuse symlinks and nonregular files, including FIFOs and device nodes.
    if not stat.S_ISREG(path.lstat().st_mode):
        raise OSError("not a regular simulation-state file")
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular simulation-state file")
        return os.fdopen(fd, "rb" if flags == os.O_RDONLY else "r+b")
    except BaseException:
        os.close(fd)
        raise


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _window_charge(intervals: list, window_ms: int) -> int:
    """Exact maximum occupied milliseconds in ANY rolling window, future included.

    Occupancy is piecewise linear. Its extrema occur at interval boundaries or
    those boundaries shifted by the window length. Integer arithmetic avoids
    rounded clock/duty allowance. Intervals must be sorted and nonoverlapping.
    """
    points = {point for a, b in intervals for point in (a, b, a + window_ms, b + window_ms)}
    return max(
        (sum(max(0, min(b, end) - max(a, end - window_ms)) for a, b in intervals) for end in points),
        default=0,
    )


def _validate_state(state: dict) -> Budget:
    fields = {"version", "simulation_only", "physical_output_enabled", "provenance", "config",
              "last_now_ms", "inhibited", "fault", "reservations", "audit"}
    if not isinstance(state, dict) or set(state) != fields:
        raise ValueError("invalid state fields")
    if type(state["version"]) is not int or state["version"] != 1:
        raise ValueError("unsupported state version")
    if state["simulation_only"] is not True or state["physical_output_enabled"] is not False:
        raise ValueError("simulation boundary changed")
    if state["provenance"] != PROVENANCE or type(state["inhibited"]) is not bool:
        raise ValueError("invalid provenance/inhibit")
    fault = state["fault"]
    if fault is not None and (type(fault) is not str or not 1 <= len(fault) <= 80 or not state["inhibited"]):
        raise ValueError("invalid fault")
    config = Budget(**state["config"])
    if state["config"] != asdict(config):
        raise ValueError("invalid config fields")
    now = state["last_now_ms"]
    if now is not None:
        _integer(now, 0, MAX_CLOCK_MS, "persisted clock")
    intervals = state["reservations"]
    if type(intervals) is not list or len(intervals) > MAX_RESERVATIONS:
        raise ValueError("invalid reservation history")
    previous_end = None
    for interval in intervals:
        if type(interval) is not list or len(interval) != 2:
            raise ValueError("invalid interval")
        a = _integer(interval[0], 0, MAX_CLOCK_MS, "interval start")
        b = _integer(interval[1], a + 1, MAX_CLOCK_MS, "interval end")
        if b - a > config.max_burst_ms or now is None or a > now:
            raise ValueError("invalid reserved duration/clock")
        if previous_end is not None and a < previous_end + config.cooldown_ms:
            raise ValueError("overlapping/cooldown-violating history")
        previous_end = b
    if _window_charge(intervals, config.window_ms) > config.max_on_ms:
        raise ValueError("history exceeds window budget")
    audit = state["audit"]
    if type(audit) is not list or not 1 <= len(audit) <= MAX_AUDIT:
        raise ValueError("invalid audit history")
    audit_clock = None
    granted = []
    for sequence, event in enumerate(audit, 1):
        if type(event) is not dict or set(event) != {"sequence", "action", "now_ms", "reason", "inhibited",
                                                    "simulation_only", "physical_output_enabled", "interval"}:
            raise ValueError("invalid audit fields")
        if type(event["sequence"]) is not int or event["sequence"] != sequence:
            raise ValueError("invalid audit sequence")
        if event["simulation_only"] is not True or event["physical_output_enabled"] is not False:
            raise ValueError("invalid audit simulation boundary")
        if type(event["inhibited"]) is not bool or type(event["reason"]) is not str or len(event["reason"]) > 80:
            raise ValueError("invalid audit status")
        if event["action"] not in {"initialize", "boot_inhibit", "simulation_rearm", "stop", "close", "fault", "deny", "reserve",
                                    "enable_requested", "enable_pending", "token_health"}:
            raise ValueError("invalid audit action")
        stamp = event["now_ms"]
        if stamp is not None:
            _integer(stamp, 0, MAX_CLOCK_MS, "audit clock")
            if now is None or stamp > now or (audit_clock is not None and stamp < audit_clock):
                raise ValueError("invalid audit clock order")
            audit_clock = stamp
        if event["action"] == "reserve":
            if event["inhibited"] is not False or event["interval"] not in intervals or stamp != event["interval"][0]:
                raise ValueError("invalid reservation audit")
            granted.append(event["interval"])
        elif event["interval"] is not None:
            raise ValueError("unexpected audit interval")
    if granted != intervals:
        raise ValueError("reservation/audit mismatch")
    return config


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._mutex:
            return method(self, *args, **kwargs)
    return call


class Scheduler:
    """Use as a context manager. Only explicit initialize creates a workspace.

    Every open persists startup inhibit. No reset, budget-clear, automatic rearm,
    clock reset, config migration, or fault-clear operation exists.
    """

    @classmethod
    def initialize(cls, directory: str | Path, config: Budget = Budget(), *,
                   backend: SimulatorBackend | None = None, ack_timeout_ms: int = 100):
        config.__post_init__()
        _integer(ack_timeout_ms, 1, MAX_ACK_TIMEOUT_MS, "ack_timeout_ms")
        if backend is not None and type(backend) is not SimulatorBackend:
            raise ValueError("only the in-process SimulatorBackend is supported")
        directory = Path(directory)
        directory.mkdir(parents=False, exist_ok=False)
        with (directory / "writer.lock").open("xb"):
            pass
        state = {
            "version": 1, "simulation_only": True, "physical_output_enabled": False,
            "provenance": PROVENANCE, "config": asdict(config), "last_now_ms": None,
            "inhibited": True, "fault": None, "reservations": [],
            "audit": [{"sequence": 1, "action": "initialize", "now_ms": None, "reason": "new_simulation_workspace",
                       "inhibited": True, "simulation_only": True, "physical_output_enabled": False, "interval": None}],
        }
        try:
            _atomic_write(directory, state)
        except OSError as error:
            raise SirenFault("initialization_persistence_failure") from error
        return cls(directory, expected_config=config, backend=backend, ack_timeout_ms=ack_timeout_ms)

    def __init__(self, directory: str | Path, *, expected_config: Budget | None = None,
                 backend: SimulatorBackend | None = None, ack_timeout_ms: int = 100):
        _integer(ack_timeout_ms, 1, MAX_ACK_TIMEOUT_MS, "ack_timeout_ms")
        if backend is not None and type(backend) is not SimulatorBackend:
            raise ValueError("only the in-process SimulatorBackend is supported")
        self.directory = Path(directory)
        self._mutex = threading.RLock()
        self._lock = None
        self._closed = False
        self._backend = backend if backend is not None else SimulatorBackend()
        self._ack_timeout_ms = ack_timeout_ms
        self._session_id = uuid4().hex
        self._pending = None
        self._token = None
        self._audit_persisted = False
        attached = False
        try:
            self._backend._attach(self._session_id)
            attached = True
            if not stat.S_ISDIR(self.directory.lstat().st_mode):
                raise ValueError("workspace must be an existing real directory")
            self._lock = _open_regular(self.directory / "writer.lock", os.O_RDWR)
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with _open_regular(self.directory / "state.json", os.O_RDONLY) as source:
                raw = source.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise ValueError("state size exceeded")
            document = json.loads(raw, object_pairs_hook=_unique_object)
            if type(document) is not dict or set(document) != {"payload", "sha256"}:
                raise ValueError("invalid persistence envelope")
            state = document["payload"]
            if document["sha256"] != hashlib.sha256(_canonical(state)).hexdigest():
                raise ValueError("state checksum mismatch")
            self._config = _validate_state(state)
            if expected_config is not None:
                expected_config.__post_init__()
                if expected_config != self.config:
                    raise ValueError("persisted config mismatch; no automatic expansion")
            self._disk_digest = hashlib.sha256(raw).hexdigest()
            self._state = state
            self._state["inhibited"] = True
            self._record("boot_inhibit", "restart_requires_explicit_simulation_rearm")
        except (OSError, ValueError, TypeError, KeyError, RecursionError, SirenFault) as error:
            self._closed = True
            if self._lock is not None:
                self._lock.close()
            if attached:
                self._backend._detach()
            raise SirenFault(f"startup_inhibited: {error}") from error

    @property
    def config(self) -> Budget:
        return self._config

    @property
    @_serialized
    def status(self) -> dict:
        # Detached snapshot; callers cannot mutate accounting through status.
        return json.loads(_canonical(self._state))

    @property
    @_serialized
    def handshake_status(self) -> dict:
        """Ephemeral diagnostics at the last supplied clock; never restored."""
        return {
            "simulation_only": True, "physical_output_enabled": False,
            "session_id": self._session_id, "ack_timeout_ms": self._ack_timeout_ms,
            "pending": dict(self._pending) if self._pending is not None else None,
            "token": asdict(self._token) if self._token is not None else None,
            "audit_persisted": self._audit_persisted,
        }

    def _revoke(self) -> None:
        self._state["inhibited"] = True
        self._pending = None
        self._token = None
        self._backend.inhibit()

    def _persist(self) -> None:
        try:
            with _open_regular(self.directory / "state.json", os.O_RDONLY) as source:
                raw = source.read(MAX_STATE_BYTES + 1)
            if hashlib.sha256(raw).hexdigest() != self._disk_digest:
                raise OSError("state changed outside this writer; refusing to overwrite")
            self._disk_digest = _atomic_write(self.directory, self._state)
            self._audit_persisted = True
        except OSError as error:
            self._audit_persisted = False
            self._revoke()
            self._state["fault"] = self._state["fault"] or "persistence_failure"
            if len(self._state["audit"]) < MAX_AUDIT:
                self._append_event("fault", "persistence_failure")
            raise SirenFault("persistence_failure; simulation inhibited; audit durability unconfirmed") from error

    def _record(self, action: str, reason: str = "", interval=None) -> None:
        if len(self._state["audit"]) >= MAX_AUDIT - 1:
            self._fail("audit_capacity")
        self._append_event(action, reason, interval)
        self._persist()

    def _append_event(self, action: str, reason: str, interval=None) -> None:
        self._audit_persisted = False
        self._state["audit"].append({
            "sequence": len(self._state["audit"]) + 1, "action": action,
            "now_ms": self._state["last_now_ms"], "reason": reason,
            "inhibited": self._state["inhibited"], "simulation_only": True,
            "physical_output_enabled": False, "interval": interval,
        })

    def _fail(self, reason: str) -> None:
        self._revoke()
        self._state["fault"] = self._state["fault"] or reason
        if len(self._state["audit"]) < MAX_AUDIT:
            self._append_event("fault", reason)
        self._persist()
        raise SirenFault(self._state["fault"])

    def _clock(self, now_ms: int, *, polling_ack: bool = False) -> None:
        if self._closed:
            raise SirenFault("closed; simulation inhibited")
        if len(self._state["audit"]) >= MAX_AUDIT - 1:
            self._fail("audit_capacity")
        try:
            _integer(now_ms, 0, MAX_CLOCK_MS, "clock")
        except ValueError:
            self._fail("invalid_clock")
        previous = self._state["last_now_ms"]
        if previous is not None and now_ms < previous:
            self._fail("backward_clock")
        self._state["last_now_ms"] = now_ms
        if self._state["fault"]:
            self._fail(self._state["fault"])
        if self._pending is not None:
            try:
                self._backend.check_health()
            except SimulatorFault as error:
                self._fail(str(error))
            deadline = self._pending["deadline_ms"]
            if now_ms > deadline or (now_ms == deadline and not polling_ack):
                self._fail("enable_ack_deadline")
        if self._token is not None:
            self._check_token(now_ms)

    def _check_token(self, now_ms: int, *, end_ms: int | None = None, phase: str = "check") -> None:
        token = self._token
        if token is None:
            self._fail("missing_enable_token")
        if now_ms >= token.expires_at_ms or (end_ms is not None and end_ms > token.expires_at_ms):
            self._fail("enable_token_expired")
        try:
            self._backend.check_token(token, now_ms, phase=phase)
        except SimulatorFault as error:
            self._fail(str(error))

    def _deny(self, reason: str) -> None:
        self._record("deny", reason)
        raise SirenDenied(reason)

    @_serialized
    def rearm_simulation(self, now_ms: int, *, acknowledge_simulation_only: bool = False) -> EnableToken | None:
        """Begin one enable request; immediate default ack preserves old callers.

        A delayed backend returns None, still inhibited. The caller must explicitly
        poll on the same simulation timeline by the inclusive acknowledgment deadline.
        """
        self._clock(now_ms)
        if acknowledge_simulation_only is not True:
            self._deny("explicit_simulation_acknowledgment_required")
        if self._pending is not None:
            self._deny("enable_pending; poll_required")
        if self._token is not None:
            self._deny("already_rearmed; stop_required")
        self._revoke()
        self._pending = {"request_id": uuid4().hex, "requested_at_ms": now_ms,
                         "deadline_ms": now_ms + self._ack_timeout_ms}
        self._record("enable_requested", self._pending["request_id"])
        try:
            self._backend.begin_enable(self._session_id, self._pending["request_id"], now_ms)
        except SimulatorFault as error:
            self._fail(str(error))
        return self._poll_enable(now_ms)

    def _poll_enable(self, now_ms: int) -> EnableToken | None:
        pending = self._pending
        if now_ms > pending["deadline_ms"]:
            self._fail("enable_ack_deadline")
        try:
            token = self._backend.poll_ack(now_ms)
        except SimulatorFault as error:
            self._fail(str(error))
        if token is None:
            if now_ms >= pending["deadline_ms"]:
                self._fail("enable_ack_deadline")
            self._record("enable_pending", pending["request_id"])
            return None
        if (type(token) is not EnableToken or token.session_id != self._session_id
                or token.request_id != pending["request_id"]
                or type(token.token_id) is not str or len(token.token_id) != 32
                or any(c not in "0123456789abcdef" for c in token.token_id)
                or token.simulation_only is not True or token.physical_output_enabled is not False
                or type(token.acknowledged_at_ms) is not int or type(token.expires_at_ms) is not int
                or not pending["requested_at_ms"] <= token.acknowledged_at_ms <= now_ms
                or not token.acknowledged_at_ms < token.expires_at_ms <= token.acknowledged_at_ms + MAX_TOKEN_TTL_MS):
            self._fail("invalid_enable_ack")
        if now_ms >= token.expires_at_ms:
            self._fail("enable_token_expired")
        self._token = token
        self._check_token(now_ms)
        self._pending = None
        self._state["inhibited"] = False
        self._record("simulation_rearm", token.request_id)
        # No successful enable return until both durable audit and backend agree.
        self._check_token(now_ms, phase="enable")
        return token

    @_serialized
    def poll_simulation(self, now_ms: int) -> EnableToken | None:
        """One bounded simulation step: observe acknowledgment or token health."""
        self._clock(now_ms, polling_ack=True)
        if self._pending is not None:
            return self._poll_enable(now_ms)
        if self._state["inhibited"]:
            self._deny("inhibited")
        self._check_token(now_ms)
        # Persist the advanced clock without granting or retrying anything.
        self._record("token_health")
        return self._token

    @_serialized
    def request(self, now_ms: int, duration_ms: int) -> Reservation:
        self._clock(now_ms)
        try:
            _integer(duration_ms, 1, self.config.max_burst_ms, "duration_ms")
            _integer(now_ms + duration_ms, 1, MAX_CLOCK_MS, "end_ms")
        except ValueError:
            self._fail("invalid_duration")
        if self._state["inhibited"]:
            self._deny("inhibited")
        self._check_token(now_ms, end_ms=now_ms + duration_ms)
        intervals = self._state["reservations"]
        if intervals:
            end = intervals[-1][1]
            if now_ms < end:
                self._deny("overlap")
            if now_ms < end + self.config.cooldown_ms:
                self._deny("cooldown")
        if len(intervals) >= MAX_RESERVATIONS:
            self._fail("reservation_capacity")
        interval = [now_ms, now_ms + duration_ms]
        if _window_charge(intervals + [interval], self.config.window_ms) > self.config.max_on_ms:
            self._deny("window_budget")
        # Reserve before returning. Stop, close, or crash never refunds any part.
        intervals.append(interval)
        self._record("reserve", interval=interval)
        # A failure here returns no grant and never refunds the committed interval.
        self._check_token(now_ms, end_ms=interval[1], phase="reserve")
        return Reservation(*interval)

    @_serialized
    def stop(self, now_ms: int) -> None:
        self._clock(now_ms)
        self._revoke()
        self._record("stop", "full_reservations_retained")

    @_serialized
    def inject_fault(self, now_ms: int) -> None:
        self._clock(now_ms)
        self._fail("injected_simulation_fault")

    @_serialized
    def close(self) -> None:
        if self._closed:
            return
        self._revoke()
        try:
            self._record("close", "full_reservations_retained")
        finally:
            self._closed = True
            self._backend._detach()
            self._lock.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False
