"""Owned spawn processes, bounded payload queues and a deadline-isolated writer.

One source process per kind (at most two) owns its backend. A separate file-only
writer process owns journal mutation. No worker is restarted or reopened.
"""
from __future__ import annotations
from dataclasses import dataclass
import multiprocessing as mp
from pathlib import Path
import queue
import signal
import threading
import time

from .live_gate import DeviceAccessGrantV1, consume_device_access
from .live_journal import LiveJournal, VerifiedLiveJournalView
from .live_models import (BackendFault, CapturePlanV1, CapturedBlockV1, EndOfSource,
                          LiveValidationError, canonical, parse_canonical)


@dataclass(frozen=True)
class ClosedCaptureResult:
    journal_path: str
    reason: str
    committed_chunks: int | None
    finalized: bool
    synthetic: bool
    device_access_occurred: bool | None
    owned_workers_reaped: bool
    final_json: bytes | None


@dataclass(frozen=True)
class SyntheticSourceScript:
    source_id: str
    blocks: tuple[CapturedBlockV1, ...]
    delay_s: float = 0.0
    terminal_fault: str | None = None
    stall_s: float = 0.0

    def __post_init__(self):
        if type(self.blocks) is not tuple or any(type(b) is not CapturedBlockV1 for b in self.blocks):
            raise LiveValidationError("synthetic blocks must be an immutable tuple")
        for value in (self.delay_s, self.stall_s):
            if type(value) not in (int, float) or not 0 <= value <= 120:
                raise LiveValidationError("bounded synthetic delay required")


@dataclass(frozen=True)
class SyntheticBackendFactory:
    scripts: tuple[SyntheticSourceScript, ...]
    synthetic: bool = True

    def __post_init__(self):
        if self.synthetic is not True or type(self.scripts) is not tuple or len({s.source_id for s in self.scripts}) != len(self.scripts):
            raise LiveValidationError("synthetic factory cannot be relabelled")

    def open(self, source, limits, admission):
        if source.backend != "synthetic" or source.provenance != "synthetic" or admission is not None:
            raise LiveValidationError("synthetic factory refuses physical provenance/admission")
        script = next((s for s in self.scripts if s.source_id == source.source_id), None)
        if script is None or any(len(b.payload) > limits.max_chunk_bytes for b in script.blocks):
            raise LiveValidationError("missing/bounded synthetic script required")
        # This provider is a finite host fixture, not a synthetic-to-device adapter.
        return _SyntheticBackend(source, script)


class _SyntheticBackend:
    def __init__(self, source, script):
        self.source, self.script, self.index = source, script, 0
        self.started = False

    def configure(self):
        return canonical({"source_id": self.source.source_id, "source_plan_sha256": self.source.sha256,
                          "format": self.source.format, "synthetic": True, "device_access_occurred": False,
                          "implementation": "host-fake-script", "clock_quality": "unknown"})

    def start(self):
        self.started = True

    def read(self, timeout_s):
        if not self.started:
            raise BackendFault("not-started")
        if self.script.stall_s:
            time.sleep(self.script.stall_s)  # Deliberately uncooperative fixture; supervisor must reap it.
        if self.script.delay_s:
            time.sleep(min(self.script.delay_s, timeout_s))
        if self.index == len(self.script.blocks):
            if self.script.terminal_fault:
                raise BackendFault(self.script.terminal_fault, "synthetic-driver", None)
            raise EndOfSource()
        block = self.script.blocks[self.index]
        self.index += 1
        return block

    def close(self):
        self.started = False


def _reserve_bytes(lock, total, local, size, limits):
    if not lock.acquire(timeout=limits.poll_timeout_s):
        return False
    try:
        if total.value + size > limits.queue_bytes or local.value + size > limits.source_queue_bytes:
            return False
        total.value += size
        local.value += size
        return True
    finally:
        lock.release()


def _release_bytes(lock, total, local, size, timeout):
    if not lock.acquire(timeout=timeout):
        raise BackendFault("queue-accounting-lock-timeout")
    try:
        total.value -= size
        local.value -= size
    finally:
        lock.release()


def _source_worker(plan, source, factory, admission, packets, control, start_event,
                   cancel, budget_lock, total_bytes, source_bytes, deadline):
    backend = None
    fault = None
    queue_rejected = 0
    try:
        # No backend import/open happens before parent grant consumption. Native
        # factory.open additionally consumes the exact source admission pre-load.
        if admission is not None:
            from .live_gate import _install_spawned_admission
            _install_spawned_admission(admission)
        backend = factory.open(source, plan.limits, admission)
        config = backend.configure()
        parse_canonical(config)
        control.send(("ready", config))
        while not start_event.wait(plan.limits.poll_timeout_s):
            if cancel.is_set() or time.monotonic() >= deadline:
                return
        if cancel.is_set() or time.monotonic() >= deadline:
            return
        if admission is not None and time.monotonic() > admission.expires_monotonic:
            raise BackendFault("grant-expired-before-start", "gate")
        backend.start()
        control.send(("started", time.monotonic_ns()))
        while not cancel.is_set() and time.monotonic() < deadline:
            block = backend.read(min(plan.limits.poll_timeout_s, max(0.000001, deadline - time.monotonic())))
            if block is None:
                # Protect against a broken fake returning AGAIN without polling.
                cancel.wait(min(0.001, plan.limits.poll_timeout_s))
                continue
            if type(block) is not CapturedBlockV1 or len(block.payload) > plan.limits.max_chunk_bytes:
                raise BackendFault("invalid-owned-block")
            size = len(block.payload)
            if not _reserve_bytes(budget_lock, total_bytes, source_bytes, size, plan.limits):
                queue_rejected += 1
                raise BackendFault("queue-byte-budget")
            try:
                packets.put_nowait((source.source_id, block))
            except queue.Full:
                queue_rejected += 1
                _release_bytes(budget_lock, total_bytes, source_bytes, size, plan.limits.poll_timeout_s)
                raise BackendFault("queue-item-budget")
    except EndOfSource:
        if not plan.synthetic:
            fault = ("unexpected-native-eof", "backend", None)
            cancel.set()
    except BaseException as exc:
        fault = (str(getattr(exc, "code", type(exc).__name__))[:512],
                 str(getattr(exc, "domain", "application"))[:128], getattr(exc, "native_code", None))
        cancel.set()
    finally:
        if backend is not None:
            try:
                backend.close()
            except BaseException as exc:
                fault = fault or ("backend-close-failed", "application", None)
                cancel.set()
        try:
            control.send(("fault", (*fault, queue_rejected)) if fault else ("done", None))
        except (OSError, EOFError, BrokenPipeError):
            pass
        control.close()
        # Do not discard the queue feeder's accepted payloads. Parent drains it
        # before joining; a stuck feeder is terminated at the shutdown deadline.
        packets.close()
        packets.join_thread()


def _writer_worker(journal, commands, replies):
    operations = {"configuration": journal.record_configuration, "start-request": journal.record_start_request,
                  "started": journal.record_started, "append": journal.append_payload,
                  "finalize": journal.finalize}
    try:
        while True:
            operation, args, kwargs = commands.get()
            try:
                result = operations[operation](*args, **kwargs)
                replies.put(("ok", result))
            except BaseException as exc:
                replies.put(("error", f"{type(exc).__name__}: {str(exc)[:1024]}"))
            if operation == "finalize":
                break
    finally:
        journal.close_owner()
        commands.close()
        replies.close()
        replies.join_thread()


class _Writer:
    def __init__(self, context, journal):
        # Construction owns no resources: the supervisor registers this object
        # before start() can create queues or launch a child.
        self.context, self.journal = context, journal
        self.commands = self.replies = self.process = None
        self.timeout = journal.plan.limits.shutdown_timeout_s
        self.usable = False

    def start(self):
        try:
            self.journal._assert_owner()
            self.commands = self.context.Queue(1)
            self.replies = self.context.Queue(1)
            self.process = self.context.Process(target=_writer_worker,
                args=(self.journal, self.commands, self.replies), name="poseidon-live-writer")
            self.process.start()
            self.usable = True
        finally:
            # No failed startup grants the old parent a second capture attempt.
            # __getstate__ burns authority earlier, at the actual fd transfer.
            self.journal._transferred = True

    def call(self, operation, *args, **kwargs):
        if not self.usable:
            raise BackendFault("writer-unavailable")
        try:
            self.commands.put_nowait((operation, args, kwargs))
            status, result = self.replies.get(timeout=self.timeout)
        except (queue.Empty, queue.Full, EOFError, OSError):
            self.usable = False
            raise BackendFault("writer-deadline", "storage")
        if status != "ok":
            raise BackendFault(result, "storage")
        return result

    def close(self, errors):
        for channel in (self.commands, self.replies):
            if channel is not None:
                _cleanup(errors, channel.cancel_join_thread)
                _cleanup(errors, channel.close)


def _cleanup(errors, operation, *args):
    """A failed cleanup must not skip another owned resource."""
    try:
        return operation(*args)
    except BaseException as exc:
        errors.append(f"{type(exc).__name__}: {str(exc)[:256]}")
        return None


def _reap(process, deadline):
    if process.pid is None:
        return True  # Registered but start() never launched it.
    errors = []
    _cleanup(errors, process.join, max(0.0, deadline - time.monotonic()))
    for action in (process.terminate, process.kill):
        if process.exitcode is not None:
            break
        _cleanup(errors, action)
        _cleanup(errors, process.join, 0.5)
    return process.exitcode is not None


class _SignalLatch:
    def __init__(self):
        self.signum = 0

    def handler(self, signum, frame):
        # In particular: no Event.set(), exception, I/O or wait inside start().
        # Repeated signals remain deferred throughout cleanup.
        self.signum = signum


class _Cancelled(Exception):
    pass


class LiveCaptureSupervisor:
    def run(self, plan: CapturePlanV1, backend_factory, journal: LiveJournal | str | Path,
            *, grant: DeviceAccessGrantV1 | None = None, cancellation=None) -> ClosedCaptureResult:
        if type(plan) is not CapturePlanV1:
            raise LiveValidationError("validated immutable plan required")
        if getattr(backend_factory, "synthetic", None) is not plan.synthetic:
            raise LiveValidationError("backend provenance cannot be relabelled")
        admissions = consume_device_access(plan, grant)
        if admissions:
            from .live_gate import _transfer_worker_admissions
            _transfer_worker_admissions(admissions)
        if threading.current_thread() is not threading.main_thread():
            raise LiveValidationError("live supervisor requires main-thread signal ownership")
        latch, previous = _SignalLatch(), {}
        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.getsignal(signum)
                signal.signal(signum, latch.handler)
            return self._run_owned(plan, backend_factory, journal, admissions, cancellation, latch)
        finally:
            # Both handlers stay installed until every owned cleanup was attempted.
            errors = []
            for signum, handler in previous.items():
                _cleanup(errors, signal.signal, signum, handler)
            if errors:
                raise RuntimeError("signal handler restoration failed: " + "; ".join(errors))

    def _run_owned(self, plan, backend_factory, journal, admissions, cancellation, latch):
        # The journal must be new; no same-session resume. Existing object permits
        # callers to inject file-only writer fault fixtures without opening devices.
        if isinstance(journal, LiveJournal):
            if journal.plan != plan or journal.count or journal.requested or journal.closed or journal.failed:
                raise LiveValidationError("new matching journal required")
            journal._assert_owner()
        else:
            journal = LiveJournal.create(journal, plan)
        workers, controls, senders = [], {}, []
        terminal, started, ready = set(), set(), set()
        writer = cancel = packets = None
        view = None
        reason, domain, native_code = "source-exhausted", None, None
        deadline = time.monotonic() + plan.limits.duration_s
        drain_deadline = None
        observed_queue_rejected = 0
        cleanup_errors = []

        def cancelled():
            return bool(latch.signum or (cancellation is not None and cancellation.is_set()))

        def startup_boundary():
            if cancelled():
                raise _Cancelled()
            if time.monotonic() >= deadline:
                raise BackendFault("duration-deadline", "application")

        try:
            context = mp.get_context("spawn")
            cancel, start_event = context.Event(), context.Event()
            packets = context.Queue(plan.limits.queue_chunks)
            lock, total = context.Lock(), context.RawValue("q", 0)
            source_bytes = {s.source_id: context.RawValue("q", 0) for s in plan.sources}
            writer = _Writer(context, journal)
            writer.start()
            startup_boundary()
            for index, source in enumerate(plan.sources):
                receive, send = context.Pipe(duplex=False)
                controls[source.source_id] = receive
                senders.append(send)
                process = context.Process(target=_source_worker, name="poseidon-live-" + source.kind,
                                          args=(plan, source, backend_factory, None if plan.synthetic else admissions[index],
                                                packets, send, start_event, cancel, lock, total,
                                                source_bytes[source.source_id], deadline))
                workers.append(process)
                startup_boundary()
                process.start()
                send.close()
                startup_boundary()
            while True:
                now = time.monotonic()
                if cancelled() and drain_deadline is None:
                    reason, domain = "cancelled", "application"
                    cancel.set()
                if now >= deadline and drain_deadline is None:
                    reason, domain = "duration-deadline", "application"
                    cancel.set()
                for sid, connection in controls.items():
                    if sid in terminal:
                        continue
                    while connection.poll():
                        try:
                            event, data = connection.recv()
                        except EOFError:
                            event, data = "fault", ("worker-exited-without-terminal", "process", None, 0)
                        if event == "ready":
                            writer.call("configuration", sid, data)
                            ready.add(sid)
                        elif event == "started":
                            writer.call("started", sid, data)
                            started.add(sid)
                        elif event == "fault":
                            reason, domain, native_code, rejected = data
                            observed_queue_rejected += rejected
                            terminal.add(sid)
                            cancel.set()
                            break
                        elif event == "done":
                            terminal.add(sid)
                            break
                        else:
                            raise BackendFault("unknown-worker-message")
                if cancelled() and drain_deadline is None:
                    reason, domain = "cancelled", "application"
                    cancel.set()
                if len(ready) == len(plan.sources) and not start_event.is_set() and not cancel.is_set():
                    writer.call("start-request")
                    # A signal during the file-only call cannot authorize a start.
                    if cancelled():
                        reason, domain = "cancelled", "application"
                        cancel.set()
                    else:
                        start_event.set()
                if cancel.is_set() and drain_deadline is None:
                    drain_deadline = time.monotonic() + plan.limits.shutdown_timeout_s
                try:
                    sid, block = packets.get(timeout=min(0.02, plan.limits.poll_timeout_s))
                except queue.Empty:
                    if len(terminal) == len(plan.sources) and all(not p.is_alive() for p in workers):
                        break
                else:
                    if sid not in started:
                        # The per-source pipe carries start-return before the
                        # source enqueues data; consume that control event first.
                        connection = controls[sid]
                        if connection.poll(plan.limits.poll_timeout_s):
                            event, data = connection.recv()
                            if event == "started":
                                writer.call("started", sid, data)
                                started.add(sid)
                            else:
                                raise BackendFault("payload-before-start-evidence")
                        else:
                            raise BackendFault("payload-before-start-evidence")
                    writer.call("append", sid, block)
                    _release_bytes(lock, total, source_bytes[sid], len(block.payload), plan.limits.poll_timeout_s)
                if drain_deadline is not None and time.monotonic() >= drain_deadline:
                    if len(terminal) < len(plan.sources):
                        reason, domain = "shutdown-deadline", "process"
                    break
        except _Cancelled:
            reason, domain = "cancelled", "application"
        except BaseException as exc:
            reason = str(getattr(exc, "code", type(exc).__name__))[:1024]
            domain = str(getattr(exc, "domain", "application"))[:128]
            native_code = getattr(exc, "native_code", None)
        finally:
            journal._transferred = True
            if cancel is not None:
                _cleanup(cleanup_errors, cancel.set)
            end = time.monotonic() + plan.limits.shutdown_timeout_s
            outcomes = []
            for process in workers:
                outcomes.append((process, _cleanup(cleanup_errors, _reap, process, end) is True))
            for connection in (*controls.values(), *senders):
                _cleanup(cleanup_errors, connection.close)
            if writer is not None:
                try:
                    if writer.usable:
                        view = writer.call("finalize", reason, fault_domain=domain, native_code=native_code,
                                           application_discarded_chunks=None,
                                           observed_queue_rejected_chunks=observed_queue_rejected)
                except BaseException as exc:
                    reason = "unsealed-writer-failure: " + str(exc)[:900]
                finally:
                    if writer.process is not None:
                        outcomes.append((writer.process, _cleanup(cleanup_errors, _reap, writer.process,
                            time.monotonic() + plan.limits.shutdown_timeout_s) is True))
                    _cleanup(cleanup_errors, writer.close, cleanup_errors)
            if packets is not None:
                _cleanup(cleanup_errors, packets.cancel_join_thread)
                _cleanup(cleanup_errors, packets.close)
            reaped = all(stopped for _, stopped in outcomes)
            for process, stopped in outcomes:
                if stopped:
                    _cleanup(cleanup_errors, process.close)
            # Close the passive lease only after ALL child cleanup attempts.
            # A surviving writer still holds its duplicate; never LOCK_UN here.
            _cleanup(cleanup_errors, journal.close_owner)
            if cleanup_errors:
                reason = "cleanup-failure: " + "; ".join(cleanup_errors)[:900]
        return ClosedCaptureResult(str(journal.path), reason, view.committed_chunks if view else None,
                                   bool(view and view.closed), plan.synthetic, False if plan.synthetic else None,
                                   reaped, view.final_json if view else None)
