"""Deterministic host models, not an ESP bootloader or a flash driver.

SQLite transactions model durable commit boundaries. Ed25519 verification is real;
its connection to immutable device trust, secure boot and flash remains unverified.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class Rejected(ValueError):
    """An input cannot alter the reference device state."""


def _integer(value: object, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise Rejected(f"invalid {name}")
    return value


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise Rejected("duplicate manifest field")
        result[key] = value
    return result


@dataclass(frozen=True)
class Manifest:
    schema: str
    board: str
    version: int
    security_version: int
    command_id: int
    expires_at: int
    image_size: int
    image_sha256: str
    key_id: str

    def canonical(self) -> bytes:
        return _canonical(asdict(self))

    @classmethod
    def parse(cls, raw: bytes) -> Manifest:
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= 1024:
            raise Rejected("manifest size")
        try:
            obj = json.loads(raw, object_pairs_hook=_object)
            if type(obj) is not dict or set(obj) != set(cls.__dataclass_fields__):
                raise Rejected("manifest fields")
            manifest = cls(**obj)
        except (TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise Rejected("malformed manifest") from exc
        if manifest.schema != "poseidon.reef.image.v1-proposal":
            raise Rejected("manifest schema")
        for name in ("board", "key_id"):
            value = getattr(manifest, name)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
                raise Rejected(f"invalid {name}")
        for name in ("version", "security_version", "command_id", "expires_at", "image_size"):
            _integer(getattr(manifest, name), 1, 0xFFFFFFFF, name)
        if not isinstance(manifest.image_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest.image_sha256):
            raise Rejected("image digest")
        if manifest.canonical() != raw:
            raise Rejected("noncanonical manifest")
        return manifest


class ImageVerifier:
    profile = "reef-private-image-v1"

    @staticmethod
    def validate_version(value: object) -> None:
        _integer(value, 1, 0xFFFFFFFF, "image version")

    @staticmethod
    def validate_digest(value: object) -> None:
        if value is not None and (type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value)):
            raise Rejected("stored image digest")

    @staticmethod
    def candidate_from_state(value: dict) -> Manifest:
        return Manifest.parse(_canonical(value))

    @staticmethod
    def newer_version(candidate: Manifest, current_version: int) -> bool:
        return candidate.version > current_version

    def __init__(self, board: str, keys: Mapping[str, bytes], max_image_bytes: int = 2 * 1024 * 1024):
        self.board = board
        self.keys = {name: Ed25519PublicKey.from_public_bytes(key) for name, key in keys.items()}
        self.max_image_bytes = _integer(max_image_bytes, 1, 16 * 1024 * 1024, "image limit")

    def verify(self, raw: bytes, signature: bytes, image: bytes, *, now: int | None,
               security_floor: int, current_version: int, last_command_id: int,
               current_digest: str | None = None) -> Manifest:
        if now is None:
            raise Rejected("trusted UTC required for image expiry")
        _integer(now, 0, 0xFFFFFFFF, "now")
        manifest = Manifest.parse(raw)
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise Rejected("missing or malformed signature")
        key = self.keys.get(manifest.key_id)
        if key is None:
            raise Rejected("untrusted key")
        try:
            key.verify(signature, raw)
        except InvalidSignature as exc:
            raise Rejected("signature invalid") from exc
        if manifest.board != self.board:
            raise Rejected("incompatible board")
        if manifest.expires_at <= now:
            raise Rejected("expired image authorization")
        if manifest.security_version < security_floor or manifest.version <= current_version:
            raise Rejected("image downgrade")
        if manifest.command_id <= last_command_id:
            raise Rejected("replayed image authorization")
        if (not isinstance(image, bytes) or not 1 <= len(image) <= self.max_image_bytes
                or len(image) != manifest.image_size):
            raise Rejected("image size")
        if hashlib.sha256(image).hexdigest() != manifest.image_sha256:
            raise Rejected("image digest mismatch")
        return manifest


class BootStore:
    """A/B trial-boot state model with real signature checks before staging.

    Factory construction only seeds an empty, explicitly created store. Never use
    deletion/recreation as corruption recovery: that would erase the replay floor.
    The initial installed image is an external trusted bootstrap assumption.
    """
    def __init__(self, path: Path, verifier: ImageVerifier, *, create: bool = False,
                 initial_version: int | str = 1, initial_security_floor: int = 1,
                 initial_sha256: str | None = None,
                 fault: Callable[[str], None] | None = None):
        self.verifier = verifier
        self.fault = fault or (lambda _: None)
        self.path = Path(path)
        if create and self.path.exists():
            raise Rejected("factory store already exists")
        if not create and not self.path.is_file():
            raise Rejected("missing provisioned state")
        if create:
            verifier.validate_version(initial_version)
            verifier.validate_digest(initial_sha256)
            _integer(initial_security_floor, 1, 0xFFFFFFFF, "security floor")
        self.db = sqlite3.connect(self.path)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            if create:
                with self.db:
                    self.db.execute("CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)")
                    self.db.execute("CREATE TABLE image (id INTEGER PRIMARY KEY CHECK(id=1), body BLOB NOT NULL, manifest BLOB NOT NULL, signature BLOB NOT NULL)")
                    self.db.execute("CREATE TABLE configuration (id INTEGER PRIMARY KEY CHECK(id=1), boot TEXT NOT NULL, command INTEGER NOT NULL, digest TEXT NOT NULL, interval INTEGER NOT NULL)")
                    state = {"board": verifier.board, "verifier_profile": verifier.profile,
                             "current_version": initial_version, "current_sha256": initial_sha256,
                             "security_floor": initial_security_floor, "last_command_id": 0,
                             "phase": "confirmed", "candidate": None}
                    self._save(state)
            state = self.snapshot()
            if state["board"] != verifier.board:
                raise Rejected("store board mismatch")
        except Exception:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> BootStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def snapshot(self) -> dict:
        row = self.db.execute("SELECT body FROM state WHERE id=1").fetchone()
        if row is None:
            raise Rejected("missing provisioned state")
        try:
            state = json.loads(row[0], object_pairs_hook=_object)
        except (TypeError, json.JSONDecodeError) as exc:
            raise Rejected("corrupt boot state") from exc
        if (type(state) is not dict or set(state) != {"board", "verifier_profile", "current_version",
                "current_sha256", "security_floor", "last_command_id", "phase", "candidate"}
                or state["board"] != self.verifier.board
                or state["verifier_profile"] != self.verifier.profile):
            raise Rejected("corrupt boot state")
        if state["phase"] not in ("confirmed", "staged", "pending", "trial"):
            raise Rejected("corrupt boot phase")
        self.verifier.validate_version(state["current_version"])
        self.verifier.validate_digest(state["current_sha256"])
        _integer(state["security_floor"], 1, 0xFFFFFFFF, "stored security floor")
        _integer(state["last_command_id"], 0, 0xFFFFFFFF, "stored command")
        if state["phase"] == "confirmed":
            if state["candidate"] is not None:
                raise Rejected("unexpected candidate")
        else:
            manifest = self.verifier.candidate_from_state(state["candidate"])
            if (manifest.board != state["board"] or manifest.command_id != state["last_command_id"]
                    or not self.verifier.newer_version(manifest, state["current_version"])
                    or manifest.security_version < state["security_floor"]):
                raise Rejected("corrupt candidate state")
        return state

    def _save(self, state: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO state(id,body) VALUES(1,?)",
                        (_canonical(state).decode("ascii"),))

    def _transaction(self, change: Callable[[dict], object]) -> object:
        # BEGIN IMMEDIATE serializes state validation and mutation across clients.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            state = self.snapshot()
            result = change(state)
            self.fault("before_state_write")
            self._save(state)
            self.fault("before_commit")
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise

    def stage(self, raw: bytes, signature: bytes, image: bytes, *, now: int | None) -> None:
        def change(state: dict) -> None:
            if state["phase"] != "confirmed":
                raise Rejected("update already pending")
            manifest = self.verifier.verify(raw, signature, image, now=now,
                security_floor=state["security_floor"], current_version=state["current_version"],
                last_command_id=state["last_command_id"], current_digest=state["current_sha256"])
            self.db.execute("INSERT OR REPLACE INTO image VALUES(1,?,?,?)", (image, raw, signature))
            self.fault("after_image_write")
            state.update(phase="staged", candidate=asdict(manifest), last_command_id=manifest.command_id)
        self._transaction(change)

    def _check_candidate(self, state: dict, now: int | None) -> Manifest:
        row = self.db.execute("SELECT body,manifest,signature FROM image WHERE id=1").fetchone()
        if row is None:
            raise Rejected("missing candidate image")
        manifest = self.verifier.verify(row[1], row[2], row[0], now=now,
            security_floor=state["security_floor"], current_version=state["current_version"],
            last_command_id=state["last_command_id"] - 1, current_digest=state["current_sha256"])
        if asdict(manifest) != state["candidate"]:
            raise Rejected("candidate metadata mismatch")
        return manifest

    def schedule(self, *, now: int | None) -> None:
        def change(state: dict) -> None:
            if state["phase"] != "staged":
                raise Rejected("no staged image")
            self._check_candidate(state, now)
            state["phase"] = "pending"
        self._transaction(change)

    @staticmethod
    def _rollback(state: dict) -> None:
        state.update(phase="confirmed", candidate=None)

    def boot(self, *, now: int | None) -> dict:
        def change(state: dict) -> dict:
            if state["phase"] == "trial":
                self._rollback(state)
                self.db.execute("DELETE FROM image WHERE id=1")
                return {"version": state["current_version"], "image_sha256": state["current_sha256"], "trial": False, "reason": "unconfirmed_trial_rollback"}
            if state["phase"] == "pending":
                try:
                    manifest = self._check_candidate(state, now)
                except Rejected:
                    self._rollback(state)
                    self.db.execute("DELETE FROM image WHERE id=1")
                    return {"version": state["current_version"], "image_sha256": state["current_sha256"], "trial": False, "reason": "candidate_rejected"}
                # Persist trial BEFORE returning a candidate boot decision.
                state["phase"] = "trial"
                return {"version": manifest.version, "image_sha256": manifest.image_sha256,
                        "trial": True, "reason": "candidate_trial"}
            return {"version": state["current_version"], "image_sha256": state["current_sha256"], "trial": False, "reason": "known_good"}
        return self._transaction(change)

    def confirm(self, *, running_version: int | str, running_sha256: str,
                healthy: bool, now: int | None) -> None:
        def change(state: dict) -> None:
            if state["phase"] != "trial" or healthy is not True:
                raise Rejected("healthy trial required")
            manifest = self._check_candidate(state, now)
            self.verifier.validate_version(running_version)
            if (running_version != manifest.version or type(running_sha256) is not str
                    or running_sha256 != manifest.image_sha256):
                raise Rejected("wrong running image")
            state.update(current_version=manifest.version, current_sha256=manifest.image_sha256,
                         security_floor=max(state["security_floor"], manifest.security_version),
                         phase="confirmed", candidate=None)
            self.db.execute("DELETE FROM image WHERE id=1")
        self._transaction(change)

    def cancel(self) -> None:
        def change(state: dict) -> None:
            if state["phase"] == "trial":
                raise Rejected("reboot to roll back a running trial")
            self._rollback(state)
            self.db.execute("DELETE FROM image WHERE id=1")
        self._transaction(change)


# A private 21-byte config proposal, not the published platform wire contract.
_CONFIG = struct.Struct(">BQIII")


def encode_configuration(boot: int, command: int, expires_at: int, interval_s: int) -> bytes:
    _integer(boot, 1, 0xFFFFFFFFFFFFFFFF, "boot")
    _integer(command, 1, 0xFFFFFFFF, "command")
    _integer(expires_at, 1, 0xFFFFFFFF, "expiry")
    _integer(interval_s, 60, 86400, "sample interval")
    return _CONFIG.pack(1, boot, command, expires_at, interval_s)


class ConfigurationController:
    """Config only: no output-enable, wiper, radio or image-transfer command.

    authenticated must come from the trusted LoRaWAN/network adapter, not an
    untrusted payload property. An authenticated channel is a precondition here,
    not a substitute for future device key/provisioning validation.
    """
    def __init__(self, store: BootStore, boot_id: int, initial_interval_s: int = 300):
        self.store = store
        self.boot_id = _integer(boot_id, 1, 0xFFFFFFFFFFFFFFFF, "boot")
        _integer(initial_interval_s, 60, 86400, "initial interval")
        with store.db:
            store.db.execute("INSERT OR IGNORE INTO configuration VALUES(1,0,0,'',?)", (initial_interval_s,))

    def apply(self, payload: bytes, *, authenticated: bool, now: int | None) -> dict:
        if authenticated is not True:
            raise Rejected("authenticated downlink required")
        if now is None:
            raise Rejected("trusted UTC required for config expiry")
        _integer(now, 0, 0xFFFFFFFF, "now")
        if not isinstance(payload, bytes) or len(payload) != _CONFIG.size:
            raise Rejected("config payload size")
        version, boot, command, expiry, interval = _CONFIG.unpack(payload)
        if version != 1 or boot != self.boot_id:
            raise Rejected("config version or target boot")
        encode_configuration(boot, command, expiry, interval)
        if expiry <= now or expiry - now > 86400:
            raise Rejected("config expired or validity exceeds one day")
        digest = hashlib.sha256(payload).hexdigest()
        def change(_: dict) -> dict:
            last_boot, last_command, last_digest, current_interval = self.store.db.execute(
                "SELECT boot,command,digest,interval FROM configuration WHERE id=1").fetchone()
            last_boot = int(last_boot)
            if boot < last_boot or (boot == last_boot and command < last_command):
                raise Rejected("stale config")
            if boot == last_boot and command == last_command:
                if digest != last_digest:
                    raise Rejected("command identity collision")
                return {"boot_id": str(boot), "command_id": command, "status": "duplicate", "interval_s": current_interval}
            self.store.db.execute("UPDATE configuration SET boot=?,command=?,digest=?,interval=? WHERE id=1",
                                  (str(boot), command, digest, interval))
            self.store.fault("after_config_write")
            return {"boot_id": str(boot), "command_id": command, "status": "applied", "interval_s": interval}
        return self.store._transaction(change)
