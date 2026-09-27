"""One-run accidental-operation guard. Not an operating permit or security boundary.

This module does not import ctypes, inspect device paths, or consult environment flags.
Grants exist only in this process and are consumed before workers are spawned.
"""
from __future__ import annotations
from dataclasses import dataclass
import secrets
import sys
import threading
import time

from .live_models import CapturePlanV1, SourcePlanV1


class DeviceAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class DeviceAccessGrantV1:
    plan_sha256: str
    nonce: str
    issued_monotonic: float
    expires_monotonic: float
    operation_scope: str


@dataclass(frozen=True)
class WorkerAdmissionV1:
    plan_sha256: str
    source_sha256: str
    expires_monotonic: float
    nonce: str


_lock = threading.Lock()
_grants: dict[str, DeviceAccessGrantV1] = {}
_issued_captures: set[str] = set()
_worker_uses: set[tuple[str, str]] = set()
_worker_tickets: dict[tuple[str, str], WorkerAdmissionV1] = {}
_challenges: dict[str, tuple[str, float, float]] = {}


def acknowledgment_text(plan: CapturePlanV1) -> str:
    """Issue a 60-second process-local challenge, not a reusable CLI/config flag.

    The caller must display this exact text and obtain a separate local decision.
    Calling this helper is file/device-free and does not itself grant access.
    """
    with _lock:
        if plan.sha256 not in _challenges:
            now = time.monotonic()
            text = f"CAPTURE ONCE {plan.capture_id} {plan.sha256} {secrets.token_hex(16)}"
            _challenges[plan.sha256] = (text, now, now + 60.0)
        return _challenges[plan.sha256][0]


def authorize_device_access(plan: CapturePlanV1, explicit_local_ack: str | None,
                            operation_scope: str) -> DeviceAccessGrantV1:
    """Require a separate exact acknowledgment; never read one from env/config."""
    if type(plan) is not CapturePlanV1 or plan.synthetic:
        raise DeviceAccessDenied("a physical plan is required for a device grant")
    if type(explicit_local_ack) is not str or operation_scope != "capture-only":
        raise DeviceAccessDenied("separate exact-plan local capture-only acknowledgment required")
    if sys.platform != "linux":
        raise DeviceAccessDenied("live native capture requires Linux")
    now = time.monotonic()
    with _lock:
        challenge = _challenges.pop(plan.sha256, None)
        if (challenge is None or explicit_local_ack != challenge[0] or
                not challenge[1] <= now <= challenge[2]):
            raise DeviceAccessDenied("absent, mismatched, reused or stale local acknowledgment")
        if plan.capture_id in _issued_captures:
            raise DeviceAccessDenied("capture identity already granted; use a new plan and decision")
        grant = DeviceAccessGrantV1(plan.sha256, secrets.token_hex(32), now, now + 60.0, operation_scope)
        _grants[grant.nonce] = grant
        _issued_captures.add(plan.capture_id)
    return grant


def consume_device_access(plan: CapturePlanV1, grant: DeviceAccessGrantV1 | None) -> tuple[WorkerAdmissionV1, ...]:
    """Consume once in the coordinator, before any journal, process or native access."""
    if plan.synthetic:
        if grant is not None:
            raise DeviceAccessDenied("synthetic runs must not carry device grants")
        return ()
    if sys.platform != "linux" or type(grant) is not DeviceAccessGrantV1:
        raise DeviceAccessDenied("no admissible local Linux grant")
    with _lock:
        stored = _grants.pop(grant.nonce, None)
    now = time.monotonic()
    if stored != grant or grant.plan_sha256 != plan.sha256 or grant.operation_scope != "capture-only" or not grant.issued_monotonic <= now <= grant.expires_monotonic:
        raise DeviceAccessDenied("absent, mismatched, reused or stale grant")
    tickets = tuple(WorkerAdmissionV1(plan.sha256, source.sha256,
                                     grant.expires_monotonic, grant.nonce) for source in plan.sources)
    with _lock:
        for ticket in tickets:
            _worker_tickets[(ticket.nonce, ticket.source_sha256)] = ticket
    return tickets


def _transfer_worker_admissions(tickets: tuple[WorkerAdmissionV1, ...]) -> None:
    """Burn the coordinator's local tickets before transferring them to spawn."""
    with _lock:
        for ticket in tickets:
            key = (ticket.nonce, ticket.source_sha256)
            if _worker_tickets.pop(key, None) != ticket or key in _worker_uses:
                raise DeviceAccessDenied("worker transfer ticket absent/reused")
            _worker_uses.add(key)


def _install_spawned_admission(ticket: WorkerAdmissionV1) -> None:
    """Internal owned-spawn bootstrap, not an acknowledgment or public grant API."""
    import multiprocessing
    if multiprocessing.parent_process() is None or type(ticket) is not WorkerAdmissionV1:
        raise DeviceAccessDenied("ticket transfer requires the owned spawned worker")
    with _lock:
        key = (ticket.nonce, ticket.source_sha256)
        if key in _worker_tickets or key in _worker_uses:
            raise DeviceAccessDenied("worker ticket already installed")
        _worker_tickets[key] = ticket


def validate_worker_admission(admission: WorkerAdmissionV1 | None,
                              plan: CapturePlanV1, source: SourcePlanV1) -> None:
    """Recheck the transferred one-run ticket immediately before native access.

    A ticket belongs only to the owned worker. It is not an IPC authorization
    service and does not defend against arbitrary code in the same process.
    """
    if sys.platform != "linux" or plan.synthetic or type(admission) is not WorkerAdmissionV1:
        raise DeviceAccessDenied("native worker has no Linux admission")
    if (source not in plan.sources or admission.plan_sha256 != plan.sha256 or
            admission.source_sha256 != source.sha256 or not admission.nonce or
            not time.monotonic() <= admission.expires_monotonic):
        raise DeviceAccessDenied("native worker admission mismatch or expiry")
    with _lock:
        key = (admission.nonce, source.sha256)
        registered = _worker_tickets.pop(key, None)
        if key in _worker_uses or registered != admission:
            raise DeviceAccessDenied("worker admission absent/already used; no reopen")
        _worker_uses.add(key)
