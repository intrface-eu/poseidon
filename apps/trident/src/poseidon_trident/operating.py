"""Persisted digital state and local watchdogs. There is no output transition."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import threading
import time

from .errors import HubError
from .platform import canonical, now_utc, public, identifier

EMIT_ENTRY_ALLOWED = False
FAULTS = {"full-disk", "clock-regression", "journal-corruption", "unrecoverable-job-failure"}
WATCHDOG_DEFAULTS = {
    "schema_version": "poseidon.watchdogs.v1", "free_bytes_min": 16 * 1024 * 1024,
    "free_inodes_min": 32, "clock_regression_s": 1, "api_age_s": 10,
    "sensor_age_s": 10, "host_age_s": 5,
}


def document(connection, key, default=None):
    row = connection.execute("SELECT document_json FROM control_documents WHERE id=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put_document(connection, key, value):
    connection.execute("INSERT INTO control_documents VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document_json=excluded.document_json", (key, canonical(value)))


def allowed_transition(state: str, target: str, cause: str) -> bool:
    # Constant refusal applies even to faults, restart and test-only callers.
    if target == "emit":
        return EMIT_ENTRY_ALLOWED
    if state not in {"observe", "armed", "inhibited", "fault"} or target not in {"observe", "armed", "inhibited", "fault"}:
        return False
    if cause == "restart":
        return target in {"observe", "inhibited"}
    if cause in FAULTS:
        return target == "fault"
    if cause.startswith("watchdog."):
        return state == "armed" and target == "inhibited"
    return (state, target, cause) in {
        ("observe", "armed", "rearm"), ("observe", "inhibited", "inhibit"),
        ("armed", "inhibited", "inhibit"), ("inhibited", "observe", "resume"),
        ("fault", "inhibited", "clear-fault"),
    }


class Watchdogs:
    """Injectable clocks and samples; offline imports never call heartbeat()."""
    def __init__(self, root, *, monotonic=time.monotonic, wall=time.time):
        self.root, self.monotonic, self.wall = root, monotonic, wall
        self.lock = threading.RLock()
        self.last_mono, self.last_wall = monotonic(), wall()
        self.beats = {"api": None, "sensor": None, "host": None}
        self.injected = set()
        self.clock_failed = False

    def heartbeat(self, source: str):
        if source not in {"api", "host", "live_journal"}:
            raise HubError("invalid_heartbeat", "only a live journal is a sensor heartbeat", 400)
        with self.lock:
            self.beats["sensor" if source == "live_journal" else source] = self.monotonic()

    def inject(self, fault: str, enabled: bool = True):
        if fault not in FAULTS | {"hung-heartbeat", "network-loss", "sensor-disconnect", "full-inodes"} or type(enabled) is not bool:
            raise ValueError("unsupported synthetic watchdog fault")
        with self.lock:
            self.injected.add(fault) if enabled else self.injected.discard(fault)

    def sample(self, options: dict) -> tuple[list[dict], str | None]:
        with self.lock:
            mono, wall = self.monotonic(), self.wall()
            elapsed = mono - self.last_mono
            self.clock_failed = elapsed < 0 or wall - self.last_wall - elapsed < -options["clock_regression_s"]
            self.last_mono, self.last_wall = mono, wall
            try:
                info = os.statvfs(self.root)
                storage_ok = info.f_bavail * info.f_frsize >= options["free_bytes_min"] and (info.f_files == 0 or info.f_favail >= options["free_inodes_min"])
            except OSError:
                storage_ok = False
            storage_ok = storage_ok and not ({"full-disk", "full-inodes"} & self.injected)
            time_ok = not self.clock_failed and "clock-regression" not in self.injected
            readings = [{"id": "storage", "healthy": bool(storage_ok), "reason": "healthy" if storage_ok else "storage threshold exhausted"},
                        {"id": "time", "healthy": time_ok, "reason": "healthy" if time_ok else "wall/monotonic regression"}]
            for name, fault in (("host", "hung-heartbeat"), ("api", "network-loss"), ("sensor", "sensor-disconnect")):
                beat = self.beats[name]
                healthy = beat is not None and 0 <= mono - beat <= options[name + "_age_s"] and fault not in self.injected
                readings.append({"id": name, "healthy": healthy, "reason": "healthy" if healthy else "heartbeat missing or stale"})
            fatal = "full-disk" if not storage_ok else "clock-regression" if not time_ok else next((f for f in ("journal-corruption", "unrecoverable-job-failure") if f in self.injected), None)
            if fatal in {"journal-corruption", "unrecoverable-job-failure"}:
                readings.append({"id": fatal, "healthy": False, "reason": fatal})
            return readings, fatal


class OperatingMixin:
    def _start_operating(self):
        self._watchdogs = Watchdogs(self._workspace.root)
        self._control_lock = threading.RLock()
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = document(connection, "hub-state")
            restored = "observe" if prior is None or prior.get("clean_shutdown") is True else "inhibited"
            if prior is not None and prior.get("state") not in {"observe", "armed", "inhibited", "fault"}:
                raise HubError("unsafe_state", "persisted operating state is invalid; no repair attempted", 409)
            options = document(connection, "watchdogs", WATCHDOG_DEFAULTS)
            if options != WATCHDOG_DEFAULTS:
                # Unknown config versions or unreviewed persisted values fail closed.
                raise HubError("invalid_watchdog_config", "unsupported watchdog configuration", 409)
            put_document(connection, "watchdogs", options)
            put_document(connection, "hub-state", {"schema_version": "poseidon.hub-state.v1", "state": restored, "clean_shutdown": False})
            connection.execute("INSERT INTO hub_transitions(from_state,to_state,cause_id,command_id,reason,created_at) VALUES (?,?,?,NULL,?,?)",
                               (prior["state"] if prior else "observe", restored, "restart", "clean startup" if restored == "observe" else "unclean restart; armed state not restored", now_utc()))
            connection.commit()

    def _close_operating(self):
        # Called only after all workspace operations have drained, before lock release.
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = document(connection, "hub-state")
            if state is not None:
                put_document(connection, "hub-state", state | {"clean_shutdown": True})
            connection.commit()

    def _state(self, connection):
        if getattr(self, "_control_unavailable", False):
            raise HubError("workspace_unavailable", "digital supervision failed closed", 503)
        state = document(connection, "hub-state")
        if not state or state.get("schema_version") != "poseidon.hub-state.v1" or state.get("state") not in {"observe", "armed", "inhibited", "fault"}:
            raise HubError("unsafe_state", "operating state is unavailable or invalid", 409)
        return state["state"]

    def _binding(self, connection, *, authorize=True):
        binding = document(connection, "hub-binding")
        if binding:
            if authorize:
                self._require_site(binding["site_id"], binding["device_id"])
        elif authorize and self._actor()["auth_mode"] != "local_development_key":
            raise HubError("hub_unbound", "workspace has no explicit hub binding", 404)
        return binding

    @public
    def get_hub_binding(self):
        with self._workspace.connect(read_only=True) as connection:
            return self._binding(connection)

    @public
    def bind_hub(self, body):
        actor = self._require_role("admin")
        if actor["auth_mode"] != "local_development_key":
            raise HubError("forbidden", "only the local administrator can bind this workspace", 403)
        if type(body) is not dict or set(body) != {"device_id"}:
            raise HubError("invalid_request", "binding requires device_id", 400)
        device = self.get_device(identifier("device_id", body["device_id"]))
        profile = self.get_health_profile(device["id"])
        if device["kind"] != "hub" or device["source_kind"] != "synthetic" or device["revoked_at"]:
            raise HubError("invalid_hub_binding", "binding requires an active synthetic hub", 409)
        binding = {"device_id": device["id"], "site_id": device["site_id"], "zone_id": profile["zone_id"]}
        with self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = document(connection, "hub-binding")
            if old and old != binding:
                raise HubError("binding_conflict", "hub binding is immutable", 409)
            if old is None:
                put_document(connection, "hub-binding", binding)
                self._audit(connection, "hub.bind", site_id=binding["site_id"], device_id=binding["device_id"], details=binding)
            connection.commit()
        return binding

    def _transition(self, connection, target, cause, *, command_id=None, reason=None):
        state = self._state(connection)
        if not allowed_transition(state, target, cause):
            raise HubError("transition_refused", "digital state transition refused", 409)
        if state == target:
            return
        put_document(connection, "hub-state", {"schema_version": "poseidon.hub-state.v1", "state": target, "clean_shutdown": False})
        connection.execute("INSERT INTO hub_transitions(from_state,to_state,cause_id,command_id,reason,created_at) VALUES (?,?,?,?,?,?)",
                           (state, target, cause, command_id, reason or cause, now_utc()))

    def _evaluate_watchdogs(self, connection):
        readings, fatal = self._watchdogs.sample(document(connection, "watchdogs", WATCHDOG_DEFAULTS))
        binding = self._binding(connection, authorize=False)
        if binding:
            for reading in readings:
                self._alarm_condition(connection, source="hub", site_id=binding["site_id"], device_id=binding["device_id"],
                                      condition="watchdog." + reading["id"], failed=not reading["healthy"],
                                      severity="critical" if fatal else "warning", reason=reading["reason"])
        if fatal:
            self._transition(connection, "fault", fatal, reason="watchdog: " + fatal)
        elif self._state(connection) == "armed":
            failed = next((r for r in readings if not r["healthy"]), None)
            if failed:
                self._transition(connection, "inhibited", "watchdog." + failed["id"], reason=failed["reason"])
        return readings

    @public
    def get_hub_state(self):
        with self._control_lock, self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            binding = self._binding(connection)
            readings = self._evaluate_watchdogs(connection)
            rows = connection.execute("SELECT * FROM hub_transitions ORDER BY id DESC LIMIT 10").fetchall()
            result = {"state": self._state(connection), "simulation": True, "emission_enabled": False,
                      "binding": binding, "watchdogs": readings, "last_transitions": [dict(row) for row in rows]}
            connection.commit()
            return result

    def _integrity_failure(self, code):
        # A corrupt underlying DB is never rewritten to manufacture a fault record.
        try:
            with self._control_lock, self._workspace.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._transition(connection, "fault", "journal-corruption", reason=code)
                binding = self._binding(connection, authorize=False)
                if binding:
                    self._alarm_condition(connection, source="hub", site_id=binding["site_id"], device_id=binding["device_id"], condition="integrity",
                                          failed=True, severity="critical", reason=code)
                connection.commit()
        except Exception:
            self._control_unavailable = True

    def _watchdog_tick(self):
        # Trusted process hook only. No scoped facade or HTTP mutation endpoint.
        with self._workspace.operation(), self._control_lock, self._workspace.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._evaluate_watchdogs(connection)
            self._refresh_device_health(connection)
            connection.commit()
