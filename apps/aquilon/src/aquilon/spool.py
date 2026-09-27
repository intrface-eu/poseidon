"""Durable bounded offline spool. At-least-once delivery needs an idempotent sink."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import hashlib
import math
from pathlib import Path
import sqlite3
import threading
from typing import Protocol

from .adapter import Accepted, MAX_JSON_BYTES
from .wire import Rejected


class SpoolFull(Rejected):
    pass


class Sink(Protocol):
    def send(self, identity: str, body: bytes) -> None:
        """Durably accept once per identity, or raise; duplicates must be safe."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_seconds: int = 2
    max_seconds: int = 300

    def __post_init__(self):
        if (type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 32
                or type(self.base_seconds) is not int or type(self.max_seconds) is not int
                or not 1 <= self.base_seconds <= self.max_seconds <= 86400):
            raise ValueError("invalid bounded retry policy")

    def delay(self, failed_attempts):
        return min(self.max_seconds, self.base_seconds * 2 ** (failed_attempts - 1))


def _time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 2**40:
        raise ValueError("invalid scheduler time")
    return float(value)


class SQLiteSpool:
    COUNTERS = frozenset({"accepted", "duplicate", "replay_rejected", "identity_conflict",
                          "spool_full", "delivered", "delivery_failed", "retry_exhausted",
                          "requeued", "parser_rejected", "auth_rejected", "transport_rejected"})

    def __init__(self, path, *, max_rows=1024, max_bytes=4 * 1024 * 1024,
                 max_receipts=4096, max_devices=1024, max_disk_bytes=32 * 1024 * 1024,
                 retry_policy=None):
        for value, maximum in ((max_rows, 1000000), (max_bytes, 2**30),
                               (max_receipts, 1000000), (max_devices, 1024),
                               (max_disk_bytes, 2**34)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid spool bound")
        if max_disk_bytes < 262144:
            raise ValueError("disk bound must allow SQLite metadata")
        self.path = str(Path(path))
        self.max_rows, self.max_bytes = max_rows, max_bytes
        self.max_receipts, self.max_devices = max_receipts, max_devices
        self.retry = retry_policy or RetryPolicy()
        self._lock = threading.RLock()
        self._dispatch_lock = threading.Lock()
        self.db = sqlite3.connect(self.path, timeout=2, isolation_level=None,
                                  check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA busy_timeout=2000")
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            app_id = self.db.execute("PRAGMA application_id").fetchone()[0]
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if tables and (app_id != 0x41515549 or version not in (1, 2)):
                raise ValueError("not an AQUILON draft spool")
            self.db.execute("PRAGMA journal_mode=DELETE")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
            page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
            max_pages = max_disk_bytes // page_size
            if self.db.execute("PRAGMA page_count").fetchone()[0] > max_pages:
                raise ValueError("existing database exceeds disk bound")
            self.db.execute(f"PRAGMA max_page_count={max_pages}")
            with self._transaction():
                self.db.execute("""CREATE TABLE IF NOT EXISTS spool (
                    identity TEXT PRIMARY KEY, dev_eui TEXT NOT NULL, boot TEXT NOT NULL,
                    sequence INTEGER NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL,
                    exhausted INTEGER NOT NULL DEFAULT 0)""")
                self.db.execute("""CREATE TABLE IF NOT EXISTS highwater (
                    dev_eui TEXT PRIMARY KEY, boot TEXT NOT NULL, sequence INTEGER NOT NULL)""")
                self.db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                    position INTEGER PRIMARY KEY AUTOINCREMENT,
                    identity TEXT UNIQUE NOT NULL, digest TEXT NOT NULL)""")
                self.db.execute("CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
                self.db.execute("CREATE INDEX IF NOT EXISTS spool_due ON spool(exhausted,next_at)")
                self.db.execute(f"PRAGMA application_id={0x41515549}")
                # Additive v1 -> v2 migration; old accepted rows/floors remain.
                self.db.execute("""CREATE TABLE IF NOT EXISTS forwarding (
                    identity TEXT PRIMARY KEY REFERENCES spool(identity) ON DELETE CASCADE,
                    source_digest TEXT NOT NULL CHECK(length(source_digest)=64),
                    envelope BLOB NOT NULL CHECK(length(envelope)>0 AND length(envelope)<=16384))""")
                self.db.execute("PRAGMA user_version=2")
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def _transaction(self):
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def _count(self, name):
        self.db.execute("""INSERT INTO counters(name,value) VALUES (?,1)
                        ON CONFLICT(name) DO UPDATE SET value=MIN(value+1,9223372036854775807)""", (name,))

    def count(self, name):
        if name not in self.COUNTERS:
            raise ValueError("unknown health counter")
        with self._transaction():
            self._count(name)

    def enqueue(self, accepted: Accepted, *, now: float) -> str:
        now = _time(now)
        body = json.dumps(accepted.document, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
        identity = accepted.identity
        outcome = "accepted"
        try:
            with self._transaction():
                receipt = self.db.execute("SELECT digest FROM receipts WHERE identity=?", (identity,)).fetchone()
                if receipt is None:
                    receipt = self.db.execute("SELECT digest FROM spool WHERE identity=?", (identity,)).fetchone()
                if receipt is not None:
                    if receipt[0] != accepted.payload_sha256:
                        self._count("identity_conflict")
                        outcome = "identity_conflict"
                    else:
                        self._count("duplicate")
                        return "duplicate"
                else:
                    floor = self.db.execute("SELECT boot,sequence FROM highwater WHERE dev_eui=?",
                                            (accepted.dev_eui,)).fetchone()
                    if floor is not None and (accepted.boot_id < int(floor[0]) or
                            (accepted.boot_id == int(floor[0]) and accepted.sequence <= floor[1])):
                        self._count("replay_rejected")
                        outcome = "stale_or_replayed"
                    else:
                        rows, size = self._usage()
                        devices = self.db.execute("SELECT COUNT(*) FROM highwater").fetchone()[0]
                        if (rows >= self.max_rows or size + len(body) > self.max_bytes
                                or (floor is None and devices >= self.max_devices)):
                            raise SpoolFull("spool_full")
                        self.db.execute("INSERT INTO spool(identity,dev_eui,boot,sequence,digest,body,next_at) VALUES (?,?,?,?,?,?,?)",
                                        (identity, accepted.dev_eui, str(accepted.boot_id), accepted.sequence,
                                         accepted.payload_sha256, body, now))
                        self.db.execute("""INSERT INTO highwater(dev_eui,boot,sequence) VALUES (?,?,?)
                            ON CONFLICT(dev_eui) DO UPDATE SET boot=excluded.boot,sequence=excluded.sequence""",
                                        (accepted.dev_eui, str(accepted.boot_id), accepted.sequence))
                        self.db.execute("INSERT INTO receipts(identity,digest) VALUES (?,?)",
                                        (identity, accepted.payload_sha256))
                        self.db.execute("""DELETE FROM receipts WHERE position IN
                            (SELECT position FROM receipts ORDER BY position DESC LIMIT -1 OFFSET ?)""",
                                        (self.max_receipts,))
                        self._count("accepted")
        except SpoolFull:
            self.count("spool_full")
            raise
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL:
                raise SpoolFull("spool_disk_full") from exc
            raise
        if outcome != "accepted":
            raise Rejected(outcome)
        return outcome

    def _usage(self):
        return self.db.execute("""SELECT COUNT(*),COALESCE(SUM(length(body)),0) +
            (SELECT COALESCE(SUM(length(envelope)+length(source_digest)),0) FROM forwarding)
            FROM spool""").fetchone()

    def freeze_forwarding(self, identity: str, source_body: bytes, build_envelope) -> bytes:
        """Commit first-attempt bytes before IO; existing bytes never rebuild.

        build_envelope is a bounded local validator/serializer, never a network
        callback. Source digest and envelope commit in one transaction and count
        against the same byte budget as queued source documents.
        """
        if type(source_body) is not bytes or not 1 <= len(source_body) <= MAX_JSON_BYTES:
            raise Rejected("forwarding_source_bound")
        digest = hashlib.sha256(source_body).hexdigest()
        try:
            with self._transaction():
                source = self.db.execute("SELECT body FROM spool WHERE identity=?", (identity,)).fetchone()
                if source is None or bytes(source[0]) != source_body:
                    raise Rejected("forwarding_source_mismatch")
                frozen = self.db.execute("SELECT source_digest,envelope FROM forwarding WHERE identity=?",
                                         (identity,)).fetchone()
                if frozen is not None:
                    if frozen[0] != digest:
                        raise Rejected("forwarding_digest_mismatch")
                    return bytes(frozen[1])
                envelope = build_envelope()
                if type(envelope) is not bytes or not 1 <= len(envelope) <= MAX_JSON_BYTES:
                    raise Rejected("forwarding_envelope_bound")
                _, size = self._usage()
                if size + len(envelope) + len(digest) > self.max_bytes:
                    raise SpoolFull("forwarding_spool_full")
                self.db.execute("INSERT INTO forwarding(identity,source_digest,envelope) VALUES (?,?,?)",
                                (identity, digest, envelope))
            # The transaction context has committed before these bytes escape.
            return envelope
        except SpoolFull:
            self.count("spool_full")
            raise
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL:
                raise SpoolFull("forwarding_disk_full") from exc
            raise

    def deliver_due(self, sink: Sink, *, now: float, limit: int = 32) -> int:
        now = _time(now)
        if type(limit) is not int or not 1 <= limit <= 1024:
            raise ValueError("delivery batch bound")
        delivered = 0
        # Serial within this instance. Separate processes may retry the same key;
        # the sink must be idempotent even after response loss or a process crash.
        with self._dispatch_lock:
            with self._lock:
                rows = self.db.execute("""SELECT identity,body,attempts FROM spool
                    WHERE exhausted=0 AND next_at<=? ORDER BY next_at,identity LIMIT ?""", (now, limit)).fetchall()
            for row in rows:
                try:
                    sink.send(row["identity"], bytes(row["body"]))
                except Exception:
                    with self._transaction():
                        attempts = row["attempts"] + 1
                        exhausted = attempts >= self.retry.max_attempts
                        changed = self.db.execute("""UPDATE spool SET attempts=?,next_at=?,exhausted=?
                            WHERE identity=? AND attempts=? AND exhausted=0""",
                            (attempts, now + self.retry.delay(attempts), int(exhausted),
                             row["identity"], row["attempts"])).rowcount
                        if changed:
                            self._count("delivery_failed")
                            if exhausted:
                                self._count("retry_exhausted")
                else:
                    with self._transaction():
                        removed = self.db.execute("DELETE FROM spool WHERE identity=?", (row["identity"],)).rowcount
                        if removed:
                            self._count("delivered")
                    # Release sink-local evidence only after DELETE, cascading
                    # frozen-byte removal, and the delivered counter COMMIT.
                    if removed:
                        delivered += 1
                        local_committed = getattr(sink, "local_committed", None)
                        if callable(local_committed):
                            local_committed(row["identity"])
        return delivered

    def retry_exhausted(self, identity: str, *, now: float) -> bool:
        """Explicit local operator recovery; never weakens device replay floors."""
        now = _time(now)
        with self._transaction():
            changed = self.db.execute("UPDATE spool SET attempts=0,next_at=?,exhausted=0 WHERE identity=? AND exhausted=1",
                                      (now, identity)).rowcount
            if changed:
                self._count("requeued")
            return bool(changed)

    def health(self):
        with self._lock:
            # One read snapshot also works when another process is writing.
            self.db.execute("BEGIN")
            try:
                row = self.db.execute("""SELECT COUNT(*) rows,COALESCE(SUM(length(body)),0) bytes,
                    COALESCE(SUM(exhausted),0) exhausted,MIN(CASE WHEN exhausted=0 THEN next_at END) next_at
                    FROM spool""").fetchone()
                result = dict(row)
                frozen_rows, frozen_bytes = self.db.execute("""SELECT COUNT(*),
                    COALESCE(SUM(length(envelope)+length(source_digest)),0) FROM forwarding""").fetchone()
                result["frozen_rows"], result["frozen_bytes"] = frozen_rows, frozen_bytes
                result["bytes"] += frozen_bytes
                result["counters"] = {name: 0 for name in sorted(self.COUNTERS)}
                result["counters"].update(dict(self.db.execute("SELECT name,value FROM counters")))
                result["receipts"] = self.db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
                result["devices"] = self.db.execute("SELECT COUNT(*) FROM highwater").fetchone()[0]
                result["limits"] = {"rows": self.max_rows, "bytes": self.max_bytes,
                                    "receipts": self.max_receipts, "devices": self.max_devices}
                return result
            finally:
                self.db.execute("ROLLBACK")

    def close(self):
        with self._lock:
            self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
