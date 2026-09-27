"""Authenticated ChirpStack HTTP integration and loopback-only reference sink.

The handler is usable with an owned HTTPServer. Deployment/TLS and production
network egress are deliberately not started or supplied by this reference.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hmac
import http.client
from http.server import BaseHTTPRequestHandler
import json
import re
import sqlite3
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .adapter import MAX_JSON_BYTES, bounded_json
from .spool import SpoolFull
from .wire import Rejected


@dataclass(frozen=True)
class HTTPIntegrationConfig:
    shared_secret: str = field(repr=False)
    auth_header: str = "X-Aquilon-Integration-Key"
    path: str = "/chirpstack"
    integration_id: str = "synthetic-local-integration"
    timeout_seconds: float = 2.0

    def __post_init__(self):
        if (type(self.shared_secret) is not str or not 24 <= len(self.shared_secret) <= 256
                or not all(33 <= ord(c) <= 126 for c in self.shared_secret)):
            raise ValueError("integration secret must be 24..256 printable ASCII characters")
        if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", self.auth_header)
                or self.auth_header.lower() in {"content-length", "content-type", "host",
                    "transfer-encoding", "connection", "expect", "content-encoding"}):
            raise ValueError("invalid integration auth header")
        if not re.fullmatch(r"/[A-Za-z0-9/_-]{1,127}", self.path):
            raise ValueError("invalid integration path")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", self.integration_id):
            raise ValueError("invalid integration identifier")
        if type(self.timeout_seconds) not in (int, float) or not 0.05 <= self.timeout_seconds <= 10:
            raise ValueError("integration timeout bound")


def make_webhook_handler(runtime, config: HTTPIntegrationConfig, *, clock=None):
    """ChirpStack v4 JSON integration: POST configured-path?event=up.

    Only this authenticated boundary sets the HTTP authenticated provenance.
    Unknown envelope fields are bounded but ignored for v4 protobuf evolution.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))

    class Handler(BaseHTTPRequestHandler):
        server_version = "AquilonDraft"
        sys_version = ""
        protocol_version = "HTTP/1.0"

        def setup(self):
            super().setup()
            self.connection.settimeout(config.timeout_seconds)

        def log_message(self, *_):
            # No paths, headers, payloads, credentials, or exception strings.
            pass

        def send_error(self, code, message=None, explain=None):
            self._reply(code, {"error": "http_rejected"})

        def _reply(self, status, result):
            self.close_connection = True
            data = json.dumps(result, separators=(",", ":")).encode("ascii")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                pass

        def _reject_transport(self, status):
            runtime.spool.count("transport_rejected")
            self._reply(status, {"error": "transport_rejected"})

        def do_POST(self):
            try:
                if len(self.path) > 2048 or sum(len(k) + len(v) for k, v in self.headers.items()) > 8192:
                    self._reject_transport(431)
                    return
                secrets = self.headers.get_all(config.auth_header, [])
                candidate = secrets[0] if len(secrets) == 1 else ""
                # compare_digest receives bytes so malformed non-ASCII input cannot
                # throw or escape to a credential-bearing framework traceback.
                if not hmac.compare_digest(candidate.encode("utf-8"), config.shared_secret.encode("ascii")):
                    runtime.spool.count("auth_rejected")
                    self._reply(401, {"error": "unauthorized"})
                    return
                route = urlsplit(self.path)
                if (route.scheme or route.netloc or route.path != config.path or route.fragment
                        or parse_qs(route.query, keep_blank_values=True, max_num_fields=4) != {"event": ["up"]}):
                    self._reject_transport(400)
                    return
                lengths = self.headers.get_all("Content-Length", [])
                types = self.headers.get_all("Content-Type", [])
                if (self.headers.get_all("Transfer-Encoding") or self.headers.get_all("Content-Encoding")
                        or self.headers.get_all("Expect") or len(lengths) != 1
                        or not re.fullmatch(r"[0-9]{1,6}", lengths[0])
                        or len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json"):
                    self._reject_transport(400)
                    return
                size = int(lengths[0])
                if not 1 <= size <= MAX_JSON_BYTES:
                    self._reject_transport(413)
                    return
                received_at = clock()
                deadline, body = time.monotonic() + config.timeout_seconds, bytearray()
                while len(body) < size:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    self.connection.settimeout(remaining)
                    chunk = self.rfile.read1(min(4096, size - len(body)))
                    if not chunk:
                        self._reject_transport(400)
                        return
                    body.extend(chunk)
                result = runtime.ingest(bytes(body), event="up", received_at=received_at,
                                        transport="authenticated-chirpstack-http-integration",
                                        integration_id=config.integration_id)
                self._reply(200, result)
            except SpoolFull:
                # No accepted identity/floor was committed. ChirpStack can retry.
                self._reply(503, {"error": "spool_full"})
            except Rejected:
                self._reply(422, {"error": "uplink_rejected"})
            except (TimeoutError, OSError):
                self._reject_transport(408)
            except ValueError:
                self._reject_transport(400)
            except sqlite3.Error:
                self._reply(503, {"error": "storage_unavailable"})
            except SinkFailure:
                self._reply(503, {"error": "forwarding_evidence_unavailable"})

    return Handler


class SinkFailure(RuntimeError):
    pass


class LoopbackJSONTransport:
    """Bounded local HTTP exchange shared by mock and approved API adapters."""
    def __init__(self, endpoint: str, *, timeout_seconds=2.0):
        if type(timeout_seconds) not in (int, float) or not 0.05 <= timeout_seconds <= 10:
            raise ValueError("HTTP timeout bound")
        self.timeout_seconds = timeout_seconds
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1")
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or not parsed.port
                or not re.fullmatch(r"/[A-Za-z0-9/_-]{1,127}", parsed.path)):
            raise ValueError("mock sink requires an explicit loopback HTTP endpoint")
        self._host, self._port, self._path = parsed.hostname, parsed.port, parsed.path

    def post(self, body: bytes, headers: dict, *, max_response_bytes=4096):
        if (type(body) is not bytes or not 1 <= len(body) <= MAX_JSON_BYTES
                or type(max_response_bytes) is not int or not 1 <= max_response_bytes <= MAX_JSON_BYTES):
            raise SinkFailure("sink_request_invalid")
        connection = http.client.HTTPConnection(self._host, self._port,
                                                 timeout=self.timeout_seconds)
        deadline = time.monotonic() + self.timeout_seconds
        watchdog = None
        response = None
        try:
            connection.connect()  # Numeric loopback, no DNS; bounded connect timeout.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SinkFailure("sink_deadline")
            owned_socket = connection.sock

            def expire():
                # shutdown interrupts a trickling response/header read, unlike a
                # per-read socket timeout that a peer could keep resetting.
                try:
                    owned_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            watchdog = threading.Timer(remaining, expire)
            watchdog.daemon = True
            watchdog.start()
            connection.request("POST", self._path, body=body,
                               headers={"Content-Type": "application/json", **headers})
            response = connection.getresponse()
            lengths = response.headers.get_all("Content-Length", [])
            if (response.status not in (200, 201) or response.headers.get_all("Transfer-Encoding")
                    or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,5}", lengths[0])
                    or not 1 <= int(lengths[0]) <= max_response_bytes):
                raise SinkFailure("sink_response_rejected")
            result = bounded_json(response.read(int(lengths[0]) + 1))
            if time.monotonic() > deadline:
                raise SinkFailure("sink_deadline")
            return result
        except (OSError, http.client.HTTPException, ValueError):
            # Never include endpoint headers/body or original exception text.
            raise SinkFailure("sink_delivery_failed") from None
        finally:
            if watchdog is not None:
                watchdog.cancel()
                watchdog.join(timeout=1)
            if response is not None:
                response.close()
            connection.close()


class LocalHTTPSink:
    """Private mock acknowledgement protocol, not the platform ingest API."""
    def __init__(self, endpoint: str, shared_secret: str, *, timeout_seconds=2.0):
        self._config = HTTPIntegrationConfig(shared_secret, timeout_seconds=timeout_seconds)
        self._transport = LoopbackJSONTransport(endpoint, timeout_seconds=timeout_seconds)

    def send(self, identity: str, body: bytes) -> None:
        if not re.fullmatch(r"reef-draft-v1:[0-9a-f]{16}:[0-9]{1,20}:[0-9]{1,10}", identity):
            raise SinkFailure("sink_request_invalid")
        result = self._transport.post(body, {"Idempotency-Key": identity,
            self._config.auth_header: self._config.shared_secret})
        if result.get("identity") != identity or result.get("accepted") is not True:
            raise SinkFailure("sink_ack_rejected")
