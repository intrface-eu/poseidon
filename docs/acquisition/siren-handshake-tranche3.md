# SIREN tranche 3: simulator enable handshake

K4 adds an in-process acknowledgment to the persistent SIREN scheduler. It adds no output driver, playback, device path, transport, network service, or physical enable. Startup remains inhibited and sends no enable request. Tokens, reservations, audit entries, and diagnostics retain `simulation_only=true` and `physical_output_enabled=false`.

All deadlines and lifetimes below are **software fixture values**, not approved physical safety limits. Every timestamp comes from the caller's nondecreasing integer simulation clock. There are no sleeps, worker threads, polling loops, or background supervision in the handshake. If the caller does not advance the clock and invoke an operation, no simulated time passes. A passing test does not demonstrate real-time fault response or independent physical inhibit.

## Small interface and compatibility

```python
from poseidon_siren import Scheduler, SimulatorBackend

backend = SimulatorBackend(ack_delay_ms=30)
with Scheduler.initialize(new_directory, backend=backend, ack_timeout_ms=100) as scheduler:
    token = scheduler.rearm_simulation(0, acknowledge_simulation_only=True)
    assert token is None                 # pending, still inhibited
    assert scheduler.poll_simulation(29) is None
    token = scheduler.poll_simulation(30)
    reservation = scheduler.request(30, 250)
    scheduler.stop(30)                    # revokes token; all 250 ms stay charged
```

`new_directory` must be a new simulation workspace whose parent exists. Use temporary directories for tests; do not reuse or rewrite the older synthetic-demo evidence.

- **D1 — Default compatibility.** Omitting `backend` explicitly selects a new `SimulatorBackend` with an immediate acknowledgment and a 60,000 ms token lifetime. Existing calls to `rearm_simulation(..., acknowledge_simulation_only=True)` followed by `request(...)` still work within that lifetime. Rearm now returns an immutable `EnableToken`, or `None` if pending; callers that ignored its old `None` return need no change for the immediate default. A custom delayed backend requires explicit polling before reservations. Only the concrete in-process simulator is accepted, not a driver object or subclass. One simulator instance belongs to one open scheduler.
- **D2 — Bounded acknowledgment.** `ack_timeout_ms` defaults to 100 and accepts integers from 1 through 10,000. Rearm records one fresh enable request and performs one immediate poll. A missing acknowledgment before the deadline returns `None` and stays inhibited. `poll_simulation(deadline_ms)` accepts an acknowledgment observed exactly at the deadline; missing acknowledgment at that point faults. A later observation faults even if the simulator had an acknowledgment ready earlier. A non-poll operation reaching the deadline while acknowledgment is still pending faults rather than replacing or bypassing the handshake. Stop before the deadline can cancel it.
- **D3 — Fresh token and explicit recovery.** Each scheduler open has a new session ID. Each rearm has a new request ID. The acknowledgment must bind both IDs, carry a valid token ID and timestamps, and agree with the backend's current token. Tokens and pending requests live only in memory. Stop, close, or any fault revokes both; restart never restores them. Rearm while pending is denied with `poll_required`; rearm while already enabled is denied with `stop_required`. There is no retry, automatic rearm, token renewal, or fault-clear API. A latched fault cannot be cleared by rearm or restart.
- **D4 — Reservation coverage.** A token must be current at the reservation start and valid through its whole interval. Intervals are half-open: a reservation ending exactly at token expiry is allowed; one starting at expiry or ending after expiry faults inhibited. Health and token checks run before reservation persistence and again afterward. A post-persistence backend fault returns no grant but retains the full charged interval. Advancing the clock through old rearm/request/stop APIs cannot evade token expiry or an observed backend fault.

`poll_simulation(now_ms)` makes one bounded observation of a pending acknowledgment or an enabled token's health. It never begins a new request. When already inhibited without a pending request, it raises `SirenDenied`. Faults raise `SirenFault`. Budget, overlap, cooldown, and ordinary inhibit denials retain the existing behavior.

## Fault injection

| Fixture control | Meaning and observation |
|---|---|
| `SimulatorBackend(ack_delay_ms=N)` | Ack becomes available at request time plus N. Delay within the deadline can succeed; delay beyond the deadline faults. N is an integer from 0 through 86,400,000. |
| `SimulatorBackend(drop_ack=True)` | No acknowledgment arrives. Explicit polling at the deadline latches `enable_ack_deadline`. |
| `SimulatorBackend(token_ttl_ms=N)` | Token expires N ms after its simulated acknowledgment time, not its eventual observation time. N is an integer from 1 through 86,400,000. |
| `backend.inject_fault("disconnect", on=phase)` | Latches `backend_disconnect` at the selected checkpoint. |
| `backend.inject_fault("underrun", on=phase)` | Latches `backend_underrun` at the selected checkpoint. This is an injected status, not an audio-driver observation. |

The phase is `check` (default: next health check), `poll` (ack polling), `enable` (after durable enable audit, before returning a token), or `reserve` (after durable reservation, before returning a grant). The simulator stores at most one scheduled injection per phase. Inhibit does not clear a latched backend fault. Tests also substitute missing, malformed, wrong-request, wrong-session, forged, expired, and replayed acknowledgment values; no external acknowledgment submission interface exists.

## Persistent accounting and audit truth

The version-1 persistent state shape, budget configuration, full reservation history, rolling-window arithmetic, cooldown checks, checksum, single-writer lock, and atomic-write policy remain unchanged. The accepted audit actions now also include `enable_requested`, `enable_pending`, and `token_health`. Request and acknowledgment events share a request ID in the bounded reason field. Session IDs and token IDs are not persisted or restored.

The audit still has a 512-entry ceiling and the reservation history a 128-entry ceiling. Nothing discards history to make room. An immediate rearm now consumes two audit entries, for the request and acknowledgment. A pending poll or healthy-token poll consumes one. Exhaustion latches inhibit, reserves the remaining fault slot, and revokes tokens. The existing capacity test uses a five-entry fixture rather than four to account for the added request event; it still proves that the next operation faults instead of dropping history.

`status` keeps its existing detached persistent-state snapshot. The new detached `handshake_status` snapshot supplies session ID, timeout, pending-request metadata, token metadata, and `audit_persisted`. It reflects only the last caller-supplied time, not a live clock or a physical state.

A successful persistence operation sets `audit_persisted=true`. An audit or storage write failure revokes the token, inhibits the current instance, raises `SirenFault` with `audit durability unconfirmed`, and sets `audit_persisted=false`. In-memory fault events are **not durable evidence** in that case. A later successful persistence may save the fault and the full attempted reservation. If replacement happened but directory fsync failed, the instance still refuses writes against the uncertain snapshot; restart validates whichever snapshot survived and inhibits before use. No durable-fault claim is made when storage prevented it.

## Focused verification

Run in the locked API environment with an outer process timeout. The tranche 3 child used a 180-second `subprocess.communicate` deadline, a new owned process group, and kill/reap cleanup on timeout; it did not install tools or start a service.

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src:apps/siren/src:libs/dsp/src \
.local/assurance-integration-v1/api/venv/bin/python \
scripts/assurance/run_pytest.py \
-p no:cacheprovider -q tests/siren
```

`tests/siren/test_handshake.py` covers silent startup; valid delay; exact and missed deadlines; drop/missing/wrong/stale/late ack; token lifetime and replay boundaries; pending and enabled disconnect/underrun; faults before and after reservation persistence; durable full-charge retention; audit/storage failures; and bounded audit exhaustion. Existing scheduler and DSP tests remain part of the same zero-skip assurance guard.

The acquisition lead owns combined and final assurance runs. ARM64 verification, physical inhibit design, hardware fault response, acoustic limits, calibration, and release remain separate gates. Earlier guides and evidence files are unchanged by this tranche.
