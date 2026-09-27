from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
import threading
import time
from unittest import mock

from fastapi.testclient import TestClient
import pytest

from poseidon_trident import HubError


api_app = importlib.import_module("poseidon_api.app")
api_cli = importlib.import_module("poseidon_api.__main__")

TOKEN = "workspace-test-token"
WAV = b"RIFF\x04\x00\x00\x00WAVE"
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isom"
JOB = {
    "id": "job_1",
    "status": "queued",
    "recording_id": "recording-1",
    "created_at": "2026-09-07T00:00:00Z",
    "updated_at": "2026-09-07T00:00:00Z",
    "error": None,
}
RECORDING = {
    "schema_version": 1,
    "recording_id": "recording-1",
    "site_id": "site-1",
    "zone_id": "zone-1",
    "device_id": "device-1",
    "started_at": "2026-09-07T00:00:00Z",
    "provenance": "synthetic",
    "wav_sha256": "0" * 64,
    "calibration_status": "uncalibrated",
    "duration_s": 0.2,
    "sample_rate_hz": 8000,
    "channel_count": 1,
    "event_count": 1,
    "reviewed_count": 0,
    "imported_at": "2026-09-07T00:00:00Z",
    "video": None,
}
EVENT = {
    "schema_version": 1,
    "event_id": "evt_1",
    "recording_id": "recording-1",
    "site_id": "site-1",
    "zone_id": "zone-1",
    "device_id": "device-1",
    "event_type": "acoustic_candidate",
    "source": "replay",
    "provenance": "synthetic",
    "start_frame": 0,
    "end_frame": 10,
    "start_time_s": 0.0,
    "end_time_s": 0.00125,
    "sample_rate_hz": 8000,
    "channel_count": 1,
    "normalized_peak_max": 0.5,
    "normalized_rms_max": 0.4,
    "amplitude_units": "normalized_pcm16_full_scale",
    "calibration_status": "uncalibrated",
    "detector_version": "passive-window-rms-v1",
    "detector_config_id": "cfg_1",
    "run_id": "run_1",
    "emission_enabled": False,
    "review": None,
}


def page(items: list[dict], limit: int, offset: int) -> dict:
    return {"items": items, "total": len(items), "limit": limit, "offset": offset}


class FakeHub:
    instances: list["FakeHub"] = []

    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.closed = False
        self.calls: list[tuple] = []
        self.video = self.data_dir / "recording-1.mp4"
        self.process_calls = 0
        self.__class__.instances.append(self)

    def access_token(self) -> str:
        return TOKEN

    def authenticate(self, token: str) -> dict:
        if token != TOKEN:
            raise HubError("unauthorized", "authentication required", 401)
        return {"auth_mode": "local_development_key"}

    def for_principal(self, principal: dict):
        return self

    def close(self) -> None:
        self.closed = True

    def status(self) -> dict:
        return {
            "mode": "monitor_only",
            "emission_enabled": False,
            "state": "ready",
            "uptime_s": 0.1,
            "recordings": 1,
            "events": 1,
            "jobs": {"queued": 1, "running": 0, "failed": 0},
        }

    def submit_recording(self, wav_stream, manifest_bytes: bytes) -> dict:
        self.calls.append(("submit_recording", wav_stream.read(), manifest_bytes))
        return JOB.copy()

    def submit_demo(self) -> dict:
        self.calls.append(("submit_demo",))
        return JOB.copy()

    def process_next_job(self) -> bool:
        self.process_calls += 1
        return False

    def get_job(self, job_id: str) -> dict:
        if job_id != JOB["id"]:
            raise HubError("job_not_found", "Job was not found.", 404)
        return JOB.copy()

    def list_jobs(self, limit: int = 20, offset: int = 0) -> dict:
        self.calls.append(("list_jobs", limit, offset))
        return page([JOB.copy()], limit, offset)

    def list_recordings(self, limit: int = 50, offset: int = 0) -> dict:
        self.calls.append(("list_recordings", limit, offset))
        return page([RECORDING.copy()], limit, offset)

    def get_recording(self, recording_id: str) -> dict:
        if recording_id != RECORDING["recording_id"]:
            raise HubError("recording_not_found", "Recording was not found.", 404)
        return RECORDING.copy()

    def list_events(
        self,
        recording_id: str | None = None,
        review: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        self.calls.append(("list_events", recording_id, review, limit, offset))
        return page([EVENT.copy()], limit, offset)

    def get_event(self, event_id: str) -> dict:
        if event_id != EVENT["event_id"]:
            raise HubError("event_not_found", "Event was not found.", 404)
        return {"event": EVENT.copy(), "recording": RECORDING.copy()}

    def save_review(
        self,
        event_id: str,
        label: str,
        notes: str,
        reviewer: str,
        expected_revision: int,
    ) -> dict:
        if expected_revision != 0:
            raise HubError("review_conflict", "Review revision changed.", 409)
        self.calls.append(("save_review", event_id, label, notes, reviewer, expected_revision))
        return {
            "label": label,
            "notes": notes,
            "reviewer": reviewer,
            "revision": 1,
            "updated_at": "2026-09-07T00:00:00Z",
        }

    def waveform(self, recording_id: str, points: int = 512) -> dict:
        self.calls.append(("waveform", recording_id, points))
        return {
            "recording_id": recording_id,
            "duration_s": 0.2,
            "sample_rate_hz": 8000,
            "channel_count": 1,
            "amplitude_units": "normalized_pcm16_full_scale",
            "calibration_status": "uncalibrated",
            "buckets": [{"start_s": 0.0, "end_s": 0.2, "min": -0.5, "max": 0.5}],
        }

    def attach_video(self, recording_id: str, video_stream, offset_s: float = 0.0) -> dict:
        content = video_stream.read()
        self.video.write_bytes(content)
        self.calls.append(("attach_video", recording_id, content, offset_s))
        return {
            "sha256": "1" * 64,
            "offset_s": offset_s,
            "uploaded_at": "2026-09-07T00:00:00Z",
            "alignment": "operator_declared",
        }

    def video_path(self, recording_id: str) -> Path:
        if recording_id != RECORDING["recording_id"] or not self.video.exists():
            raise HubError("video_not_found", "Video was not found.", 404)
        return self.video


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    FakeHub.instances.clear()
    monkeypatch.setattr(api_app, "Hub", FakeHub)
    app = api_app.create_app(tmp_path, start_worker=False)
    with TestClient(app) as test_client:
        yield test_client, FakeHub.instances[-1]


def auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_is_public_and_api_routes_require_bearer_auth(client) -> None:
    test_client, hub = client
    assert test_client.get("/healthz").json() == {"status": "ok"}
    routes = [
        ("GET", "/api/v1/status"),
        ("POST", "/api/v1/recordings"),
        ("POST", "/api/v1/demo"),
        ("GET", "/api/v1/jobs"),
        ("GET", "/api/v1/jobs/job_1"),
        ("GET", "/api/v1/recordings"),
        ("GET", "/api/v1/recordings/recording-1"),
        ("GET", "/api/v1/events"),
        ("GET", "/api/v1/events/evt_1"),
        ("PUT", "/api/v1/events/evt_1/review"),
        ("GET", "/api/v1/recordings/recording-1/waveform"),
        ("POST", "/api/v1/recordings/recording-1/video"),
        ("GET", "/api/v1/recordings/recording-1/video"),
    ]
    for method, path in routes:
        response = test_client.request(method, path)
        assert response.status_code == 401, (method, path, response.text)
        assert response.json() == {
            "error": {"code": "unauthorized", "message": "Authentication required."}
        }
        assert response.headers["www-authenticate"] == "Bearer"
    wrong = test_client.get("/api/v1/status", headers=auth("do-not-reflect-this"))
    assert wrong.status_code == 401
    assert "do-not-reflect-this" not in wrong.text
    non_ascii = test_client.get(
        "/api/v1/status",
        headers={b"Authorization": b"Bearer \xff"},
    )
    assert non_ascii.status_code == 401
    assert non_ascii.json()["error"]["code"] == "unauthorized"
    assert hub.calls == []


def test_status_and_all_read_endpoints_forward_exact_filters(client) -> None:
    test_client, hub = client
    assert test_client.get("/api/v1/status", headers=auth()).json()["mode"] == "monitor_only"
    jobs = test_client.get("/api/v1/jobs?limit=7&offset=3", headers=auth())
    assert jobs.status_code == 200
    assert jobs.json()["limit"] == 7
    assert test_client.get("/api/v1/jobs/job_1", headers=auth()).json()["id"] == "job_1"
    recordings = test_client.get("/api/v1/recordings?limit=8&offset=2", headers=auth())
    assert recordings.json()["offset"] == 2
    assert (
        test_client.get("/api/v1/recordings/recording-1", headers=auth()).json()["video"]
        is None
    )
    events = test_client.get(
        "/api/v1/events?recording_id=recording-1&review=unreviewed&limit=9&offset=4",
        headers=auth(),
    )
    assert events.json()["limit"] == 9
    detail = test_client.get("/api/v1/events/evt_1", headers=auth())
    assert detail.json()["event"]["event_id"] == "evt_1"
    waveform = test_client.get(
        "/api/v1/recordings/recording-1/waveform?points=16", headers=auth()
    )
    assert waveform.status_code == 200
    assert waveform.json()["recording_id"] == "recording-1"
    assert ("list_jobs", 7, 3) in hub.calls
    assert ("list_recordings", 8, 2) in hub.calls
    assert ("list_events", "recording-1", "unreviewed", 9, 4) in hub.calls
    assert ("waveform", "recording-1", 16) in hub.calls


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/jobs?limit=true",
        "/api/v1/jobs?limit=1.0",
        "/api/v1/jobs?limit=0",
        "/api/v1/jobs?limit=201",
        "/api/v1/jobs?offset=-1",
        "/api/v1/jobs?limit=2&limit=3",
        "/api/v1/jobs?unknown=1",
        "/api/v1/events?review=confirmed",
        "/api/v1/events?recording_id=../../etc/passwd",
        "/api/v1/recordings/recording-1/waveform?points=15",
        "/api/v1/recordings/recording-1/waveform?points=false",
    ],
)
def test_query_validation_is_strict_and_uses_error_envelope(client, path: str) -> None:
    test_client, _ = client
    response = test_client.get(path, headers=auth())
    assert response.status_code == 400
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message"}


def test_oversized_numeric_queries_are_normalized_without_integer_conversion_failure(client) -> None:
    test_client, _ = client
    digits = "9" * 5000
    for path in (
        f"/api/v1/jobs?limit={digits}",
        f"/api/v1/jobs?offset={digits}",
        f"/api/v1/recordings/recording-1/waveform?points={digits}",
    ):
        response = test_client.get(path, headers=auth())
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"


def test_multipart_recording_import_is_streamed_to_hub_and_idempotent(client) -> None:
    test_client, hub = client
    files = {
        "wav": ("recording.wav", WAV, "audio/wav"),
        "manifest": ("manifest.json", b'{"schema_version":1}', "application/json"),
    }
    first = test_client.post("/api/v1/recordings", files=files, headers=auth())
    second = test_client.post("/api/v1/recordings", files=files, headers=auth())
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json() == second.json() == JOB
    calls = [call for call in hub.calls if call[0] == "submit_recording"]
    assert len(calls) == 2
    assert calls[0][1] == WAV
    assert calls[0][2] == b'{"schema_version":1}'


@pytest.mark.parametrize(
    ("files", "status"),
    [
        (
            {
                "wav": ("recording.wav", b"truncated", "audio/wav"),
                "manifest": ("manifest.json", b"{}", "application/json"),
            },
            400,
        ),
        (
            {
                "wav": ("recording.wav", WAV, "application/octet-stream"),
                "manifest": ("manifest.json", b"{}", "application/json"),
            },
            400,
        ),
        ({"wav": ("recording.wav", WAV, "audio/wav")}, 400),
        (
            {
                "wav": ("recording.wav", WAV, "audio/wav"),
                "manifest": ("manifest.json", b"{}", "text/plain"),
            },
            400,
        ),
        (
            {
                "wav": ("recording.wav", WAV, "audio/wav"),
                "manifest": ("manifest.json", b"{}", "application/json"),
                "extra": ("extra.bin", b"x", "application/octet-stream"),
            },
            400,
        ),
    ],
)
def test_recording_import_rejects_wrong_or_missing_parts(client, files, status: int) -> None:
    test_client, hub = client
    response = test_client.post("/api/v1/recordings", files=files, headers=auth())
    assert response.status_code == status
    assert response.json()["error"]["code"] == "invalid_request"
    assert not [call for call in hub.calls if call[0] == "submit_recording"]


def test_recording_part_and_streamed_request_limits_are_enforced(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, hub = client
    oversized_manifest = b"{" + b" " * api_app.MANIFEST_MAX_BYTES + b"}"
    response = test_client.post(
        "/api/v1/recordings",
        files={
            "wav": ("recording.wav", WAV, "audio/wav"),
            "manifest": ("manifest.json", oversized_manifest, "application/json"),
        },
        headers=auth(),
    )
    assert response.status_code == 413
    assert not [call for call in hub.calls if call[0] == "submit_recording"]

    monkeypatch.setattr(api_app, "WAV_MAX_BYTES", len(WAV) - 1)
    response = test_client.post(
        "/api/v1/recordings",
        files={
            "wav": ("recording.wav", WAV, "audio/wav"),
            "manifest": ("manifest.json", b"{}", "application/json"),
        },
        headers=auth(),
    )
    assert response.status_code == 413


def test_asgi_guard_counts_actual_bytes_without_content_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_app, "IMPORT_REQUEST_MAX_BYTES", 4)
    received_by_inner = False

    async def inner(scope, receive, send):
        nonlocal received_by_inner
        received_by_inner = True
        await receive()

    middleware = api_app.RequestBodyLimitMiddleware(inner)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/recordings",
        "raw_path": b"/api/v1/recordings",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 80),
    }
    request_messages = iter(
        [{"type": "http.request", "body": b"12345", "more_body": False}]
    )
    sent: list[dict] = []

    async def receive():
        return next(request_messages)

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))
    assert received_by_inner
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["error"]["code"] == "request_too_large"


def test_demo_requires_empty_body_and_returns_job(client) -> None:
    test_client, hub = client
    response = test_client.post("/api/v1/demo", headers=auth())
    assert response.status_code == 202
    assert response.json() == JOB
    assert ("submit_demo",) in hub.calls
    rejected = test_client.post("/api/v1/demo", content=b"not empty", headers=auth())
    assert rejected.status_code == 413


def test_review_save_validation_and_conflict(client) -> None:
    test_client, hub = client
    body = {
        "label": "confirmed_feeding",
        "notes": "Operator saw a matching action.",
        "reviewer": "operator",
        "expected_revision": 0,
    }
    response = test_client.put("/api/v1/events/evt_1/review", json=body, headers=auth())
    assert response.status_code == 200
    assert response.json()["revision"] == 1
    assert ("save_review", "evt_1", body["label"], body["notes"], "operator", 0) in hub.calls

    stale = {**body, "expected_revision": 1}
    response = test_client.put("/api/v1/events/evt_1/review", json=stale, headers=auth())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "review_conflict"

    invalid_bodies = [
        {**body, "expected_revision": True},
        {**body, "label": "confirmed_feeding", "notes": ""},
        {**body, "reviewer": " "},
        {**body, "notes": "x" * 2001},
        {**body, "extra": "field"},
    ]
    for invalid in invalid_bodies:
        response = test_client.put(
            "/api/v1/events/evt_1/review", json=invalid, headers=auth()
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"


def test_video_upload_requires_mp4_and_supports_authenticated_ranges(client) -> None:
    test_client, hub = client
    response = test_client.post(
        "/api/v1/recordings/recording-1/video",
        files={"video": ("evidence.mp4", MP4, "video/mp4")},
        data={"offset_s": "-1.25"},
        headers=auth(),
    )
    assert response.status_code == 201
    assert response.json()["offset_s"] == -1.25
    assert ("attach_video", "recording-1", MP4, -1.25) in hub.calls

    assert test_client.get("/api/v1/recordings/recording-1/video").status_code == 401
    full = test_client.get("/api/v1/recordings/recording-1/video", headers=auth())
    assert full.status_code == 200
    assert full.content == MP4
    assert full.headers["accept-ranges"] == "bytes"

    partial = test_client.get(
        "/api/v1/recordings/recording-1/video",
        headers={**auth(), "Range": "bytes=4-7"},
    )
    assert partial.status_code == 206
    assert partial.content == MP4[4:8]
    assert partial.headers["content-range"] == f"bytes 4-7/{len(MP4)}"
    assert partial.headers["content-length"] == "4"

    suffix = test_client.get(
        "/api/v1/recordings/recording-1/video",
        headers={**auth(), "Range": "bytes=-4"},
    )
    assert suffix.status_code == 206
    assert suffix.content == MP4[-4:]

    invalid = test_client.get(
        "/api/v1/recordings/recording-1/video",
        headers={**auth(), "Range": "bytes=999-1000"},
    )
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == f"bytes */{len(MP4)}"
    assert invalid.json()["error"]["code"] == "range_not_satisfiable"
    huge_range = test_client.get(
        "/api/v1/recordings/recording-1/video",
        headers={**auth(), "Range": f"bytes={'9' * 5000}-"},
    )
    assert huge_range.status_code == 416
    assert huge_range.json()["error"]["code"] == "range_not_satisfiable"


@pytest.mark.parametrize(
    ("content", "content_type", "offset"),
    [
        (b"not-mp4", "video/mp4", "0"),
        (MP4, "application/octet-stream", "0"),
        (MP4, "video/mp4", "NaN"),
        (MP4, "video/mp4", "true"),
    ],
)
def test_video_upload_rejects_bad_content_and_nonfinite_offsets(
    client, content: bytes, content_type: str, offset: str
) -> None:
    test_client, hub = client
    response = test_client.post(
        "/api/v1/recordings/recording-1/video",
        files={"video": ("evidence.mp4", content, content_type)},
        data={"offset_s": offset},
        headers=auth(),
    )
    assert response.status_code == 400
    assert not [call for call in hub.calls if call[0] == "attach_video"]


def test_video_part_size_limit_is_enforced(client, monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, hub = client
    monkeypatch.setattr(api_app, "VIDEO_MAX_BYTES", len(MP4) - 1)
    response = test_client.post(
        "/api/v1/recordings/recording-1/video",
        files={"video": ("evidence.mp4", MP4, "video/mp4")},
        headers=auth(),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert not [call for call in hub.calls if call[0] == "attach_video"]


def test_missing_resources_out_of_scope_routes_and_methods_use_envelopes(client) -> None:
    test_client, _ = client
    missing = test_client.get("/api/v1/jobs/missing", headers=auth())
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "job_not_found"
    for method, path in [
        ("POST", "/api/v1/emit"),
        ("POST", "/api/v1/fetch-url"),
        ("POST", "/api/v1/shell"),
        ("GET", "/docs"),
        ("GET", "/openapi.json"),
    ]:
        response = test_client.request(method, path, headers=auth())
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    wrong_method = test_client.delete("/api/v1/jobs", headers=auth())
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"
    cors = test_client.get(
        "/api/v1/status",
        headers={**auth(), "Origin": "https://example.invalid"},
    )
    assert cors.status_code == 200
    assert "access-control-allow-origin" not in cors.headers
    preflight = test_client.options(
        "/api/v1/status",
        headers={
            "Origin": "https://example.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 405
    assert "access-control-allow-origin" not in preflight.headers


def test_unexpected_backend_errors_are_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenHub(FakeHub):
        def status(self) -> dict:
            raise RuntimeError("private-path-and-token-value")

    monkeypatch.setattr(api_app, "Hub", BrokenHub)
    app = api_app.create_app(tmp_path, start_worker=False)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/v1/status", headers=auth())
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "The request could not be completed.",
        }
    }
    assert "private-path-and-token-value" not in response.text


def test_worker_survives_processing_exception_and_hub_closes_after_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class WorkerHub(FakeHub):
        def __init__(self, data_dir: Path | str) -> None:
            super().__init__(data_dir)
            self.processed_after_error = threading.Event()
            self.worker_alive_at_close: bool | None = None

        def process_next_job(self) -> bool:
            self.process_calls += 1
            if self.process_calls == 1:
                raise RuntimeError("forced worker error")
            self.processed_after_error.set()
            return False

        def close(self) -> None:
            thread = threading.current_thread()
            assert thread.name != "poseidon-api-queue-worker"
            self.worker_alive_at_close = any(
                item.name == "poseidon-api-queue-worker" and item.is_alive()
                for item in threading.enumerate()
            )
            super().close()

    WorkerHub.instances.clear()
    monkeypatch.setattr(api_app, "Hub", WorkerHub)
    app = api_app.create_app(tmp_path, start_worker=True)
    with TestClient(app) as test_client:
        hub = WorkerHub.instances[-1]
        assert hub.processed_after_error.wait(timeout=2)
        assert test_client.get("/api/v1/status", headers=auth()).status_code == 200
    assert hub.closed
    assert hub.worker_alive_at_close is False
    assert hub.process_calls >= 2


def test_lifespan_closes_hub_without_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    FakeHub.instances.clear()
    monkeypatch.setattr(api_app, "Hub", FakeHub)
    app = api_app.create_app(tmp_path, start_worker=False)
    with TestClient(app):
        hub = FakeHub.instances[-1]
        assert not hub.closed
        assert app.state.worker_thread is None
    assert hub.closed


def test_lifespan_closes_hub_when_token_initialization_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TokenFailureHub(FakeHub):
        def access_token(self) -> str:
            raise RuntimeError("forced token read failure")

    TokenFailureHub.instances.clear()
    monkeypatch.setattr(api_app, "Hub", TokenFailureHub)
    with pytest.raises(RuntimeError, match="forced token read failure"):
        with TestClient(api_app.create_app(tmp_path, start_worker=False)):
            pass
    assert TokenFailureHub.instances[-1].closed


def test_cli_refuses_nonloopback_and_prints_only_token_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with mock.patch.object(api_cli.uvicorn, "run") as run:
        with pytest.raises(SystemExit) as exc:
            api_cli.main(["--data-dir", str(tmp_path), "--host", "0.0.0.0"])
        assert exc.value.code == 2
        run.assert_not_called()

    with mock.patch.object(api_cli.uvicorn, "run") as run:
        assert (
            api_cli.main(
                ["--data-dir", str(tmp_path), "--host", "127.0.0.1", "--port", "8181"]
            )
            == 0
        )
        run.assert_called_once()
    output = capsys.readouterr()
    assert str(tmp_path.resolve() / "access.token") in output.out
    assert TOKEN not in output.out
