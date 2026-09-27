from __future__ import annotations

import asyncio
from contextlib import ExitStack
import json
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from starlette.datastructures import UploadFile

from poseidon_api import create_app
from poseidon_proto.companion import DOCUMENT_ROLES, PART_LIMITS, MAX_REQUEST_BYTES, MAX_FILE_PARTS, MAX_SCALAR_FIELDS


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("companion_api_fixtures", ROOT / "tests/trident/_companion_support.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
PREFIX = "/api/v1"
UPLOAD = PREFIX + "/acquisition-sessions/platform-context/recordings"


@pytest.fixture(scope="module")
def exports(tmp_path_factory):
    return fixtures.make_exports(tmp_path_factory.mktemp("synthetic-api-export"))


@pytest.fixture
def platform(tmp_path):
    root = tmp_path / "workspace"
    app = create_app(root, start_worker=False)
    with TestClient(app) as client:
        hub = app.state.hub
        fixtures.context(hub)
        development = {"Authorization": "Bearer " + hub.access_token()}
        yield client, hub, development, root


def actor(hub, role="admin", subject="scoped-admin", sites=None, device_id=None):
    issued = hub.create_principal({"subject": subject, "role": role, "site_ids": sites or ["synthetic-site"], "device_id": device_id})
    return {"Authorization": "Bearer " + issued["token"]}, issued


def post(client, headers, bundle, path=UPLOAD):
    return client.post(path, headers=headers, files=fixtures.multipart(bundle))


def test_actual_scoped_seven_role_import_candidate_zero_and_all_raw_documents(platform, exports):
    client, hub, _, _ = platform
    headers, _ = actor(hub)
    for bundle, expected_count in zip(exports, (1, 0)):
        response = client.post(UPLOAD, headers=headers, files=list(reversed(fixtures.multipart(bundle))))
        assert response.status_code == 202, response.text
        job = response.json()
        assert set(job) == {"id", "status", "recording_id", "created_at", "updated_at", "error"}
        base = PREFIX + f"/recordings/{job['recording_id']}/acquisition-companion"
        pending = client.get(base, headers=headers)
        assert pending.status_code == 200, pending.text
        body = pending.json()
        assert body["state"] == "retained" and body["job"]["status"] == "queued"
        assert body["platform_session_id"] == "platform-context"
        assert body["capture_session_id"] == "synthetic-capture"
        assert body["actor_subject"] == "scoped-admin" and body["auth_mode"] == "scoped_token"
        assert [channel["channel_id"] for channel in body["validation"]["source"]["channels"]] == ["right", "left"]
        assert body["validation"]["verification"]["acquisition_completeness_verified"] is False
        assert body["validation"]["verification"]["epoch_declaration_verified"] is False
        assert [document["role"] for document in body["documents"]] == list(DOCUMENT_ROLES)
        for role in DOCUMENT_ROLES:
            raw = client.get(base + "/documents/" + role, headers=headers)
            assert raw.status_code == 200
            assert raw.content == bundle["bytes"][role]
            assert raw.headers["content-type"] == "application/json"
            assert raw.headers["x-content-type-options"] == "nosniff"
            assert raw.headers["cache-control"] == "no-store"
            assert raw.headers["x-poseidon-document-sha256"] == hashlib.sha256(raw.content).hexdigest()
            assert raw.headers["content-disposition"] == f'attachment; filename="{bundle["names"][role]}"'
        hub.process_next_job()
        recording = client.get(PREFIX + f"/recordings/{job['recording_id']}", headers=headers).json()
        assert recording["event_count"] == expected_count
        assert recording["started_at"] == bundle["validated"].manifest.started_at
        assert client.get(base, headers=headers).json()["job"]["status"] == "succeeded"
    assert client.get(PREFIX + "/jobs", headers=headers).json()["total"] == 2
    assert client.get(PREFIX + "/status", headers=headers).json()["recordings"] == 2
    zero = client.get(PREFIX + "/recordings/synthetic-later/acquisition-companion", headers=headers).json()
    assert zero["validation"]["selected_receipt"]["missing_units"] == 7840
    assert zero["validation"]["verification"]["predecessor_receipt_bytes_verified"] is False


def test_noncanonical_utf16_source_final_is_downloaded_as_exact_bytes(platform, tmp_path):
    client, hub, development, _ = platform
    first, _ = fixtures.make_exports(tmp_path / "utf16", final_encoding="utf-16")
    response = post(client, development, first)
    assert response.status_code == 202, response.text
    raw = client.get(PREFIX + "/recordings/synthetic-first/acquisition-companion/documents/source_final", headers=development)
    assert raw.content == first["bytes"]["source_final"]
    assert raw.content.startswith((b"\xff\xfe", b"\xfe\xff"))
    assert client.get(PREFIX + "/recordings/synthetic-first/acquisition-companion", headers=development).status_code == 200


@pytest.mark.parametrize("role", ["viewer", "reviewer", "device"])
def test_unauthorized_roles_are_denied_before_multipart_parser(platform, exports, monkeypatch, role):
    from poseidon_api import companion_routes
    client, hub, _, _ = platform
    headers, _ = actor(hub, role, "actor-" + role, device_id="synthetic-device" if role == "device" else None)
    async def forbidden_parser(_request):
        raise AssertionError("denied user reached body parser")
    monkeypatch.setattr(companion_routes, "_parse_companion_form", forbidden_parser)
    response = post(client, headers, exports[0])
    assert response.status_code == 403, response.text
    assert hub.list_jobs()["total"] == 0
    with hub.companion_admission("platform-context"), hub.companion_admission("platform-context"):
        pass


def test_unauthenticated_cross_site_and_missing_context_denied_before_parse(platform, exports, monkeypatch):
    from poseidon_api import companion_routes
    client, hub, development, _ = platform
    headers, _ = actor(hub, sites=["other-site"])
    async def forbidden_parser(_request):
        raise AssertionError("unauthorized context reached body parser")
    monkeypatch.setattr(companion_routes, "_parse_companion_form", forbidden_parser)
    assert post(client, {}, exports[0]).status_code == 401
    assert post(client, headers, exports[0]).status_code == 404
    assert post(client, development, exports[0], PREFIX + "/acquisition-sessions/missing/recordings").status_code == 404


def test_third_admission_rejected_before_parsing_and_slots_release(platform, exports, monkeypatch):
    from poseidon_api import companion_routes
    client, hub, development, _ = platform
    async def forbidden_parser(_request):
        raise AssertionError("full admission reached body parser")
    monkeypatch.setattr(companion_routes, "_parse_companion_form", forbidden_parser)
    with ExitStack() as stack:
        stack.enter_context(hub.companion_admission("platform-context"))
        stack.enter_context(hub.companion_admission("platform-context"))
        response = post(client, development, exports[0])
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "companion_admission_full"
    with hub.companion_admission("platform-context"), hub.companion_admission("platform-context"):
        pass


@pytest.mark.parametrize("operation", ["revoke", "rotate"])
def test_credential_changed_during_upload_cannot_commit_and_all_uploads_close(platform, exports, monkeypatch, operation):
    from poseidon_api import companion_routes
    client, hub, _, root = platform
    headers, issued = actor(hub)
    original = companion_routes._parse_companion_form
    uploads = []
    async def revoke_after_parsing(request):
        form = await original(request)
        uploads.extend(value for _, value in form.multi_items() if isinstance(value, UploadFile))
        getattr(hub, operation + "_principal")(issued["principal"]["id"])
        return form
    monkeypatch.setattr(companion_routes, "_parse_companion_form", revoke_after_parsing)
    response = post(client, headers, exports[0])
    assert response.status_code == 401, response.text
    assert len(uploads) == 7 and all(upload.file.closed for upload in uploads)
    assert hub.list_jobs()["total"] == 0
    assert list((root / ".staging").iterdir()) == []
    with hub.companion_admission("platform-context"), hub.companion_admission("platform-context"):
        pass


def test_credential_revoked_after_rename_has_no_partial_202(platform, exports, monkeypatch):
    client, hub, _, root = platform
    headers, issued = actor(hub)
    def revoke(phase):
        if phase == "renamed":
            hub.revoke_principal(issued["principal"]["id"])
    monkeypatch.setattr(hub, "_companion_failpoint", revoke)
    response = post(client, headers, exports[0])
    assert response.status_code == 401, response.text
    assert hub.list_jobs()["total"] == 0
    assert list((root / "recordings").iterdir()) == []
    assert list((root / ".staging").iterdir()) == []


def test_qualified_retry_conflict_and_legacy_absence(platform, exports, tmp_path):
    client, hub, development, _ = platform
    first = post(client, development, exports[0])
    assert first.status_code == 202
    assert post(client, development, exports[0]).json() == first.json()
    changed, _ = fixtures.make_exports(tmp_path / "changed", epoch_operator="different-declarant")
    assert post(client, development, changed).status_code == 409
    assert hub.list_jobs()["total"] == 1
    legacy_job = client.post(PREFIX + "/recordings", headers=development, files=[part for part in fixtures.multipart(exports[1]) if part[0] in {"wav", "manifest"}])
    assert legacy_job.status_code == 202
    assert post(client, development, exports[1]).status_code == 409
    absent = client.get(PREFIX + "/recordings/synthetic-later/acquisition-companion", headers=development)
    assert absent.json() == {"schema_version": "poseidon.recording-acquisition-companion.v1", "state": "absent", "recording_id": "synthetic-later"}
    assert client.get(PREFIX + "/recordings/synthetic-later/acquisition-companion/documents/binding", headers=development).status_code == 404


def test_reader_rejects_rehashed_projection_lie_and_actual_multi_export(platform, exports, tmp_path):
    from poseidon_acoustic.legacy_export_cli import run_demo
    client, hub, development, _ = platform
    changed = fixtures.rewrite_binding(exports[0], lambda body: body["time"].update({"combined_start_uncertainty_s": "0"}))
    assert post(client, development, changed).status_code == 400
    multi = tmp_path.resolve() / "multi"
    run_demo(multi)
    changed = deepcopy(exports[0])
    changed["bytes"]["export_receipt"] = (multi / "export/export.receipt.json").read_bytes()
    assert post(client, development, changed).status_code == 400
    assert hub.list_jobs()["total"] == 0


@pytest.mark.parametrize("case,expected", [("missing", 400), ("duplicate", 400), ("extra", 413), ("scalar", 413), ("unsafe", 400), ("mime", 400), ("unknown_role", 400)])
def test_exact_role_name_type_and_part_count_limits(platform, exports, case, expected):
    client, hub, development, _ = platform
    parts = fixtures.multipart(exports[0])
    data = None
    if case == "missing":
        parts.pop()
    elif case == "duplicate":
        parts[-1] = parts[0]
    elif case == "extra":
        parts.append(("extra", ("unknown.json", b"{}", "application/json")))
    elif case == "scalar":
        data = {"session_id": "unexpected"}
    elif case == "unsafe":
        parts[2] = ("binding", ("../binding-000000.json", exports[0]["bytes"]["binding"], "application/json"))
    elif case == "mime":
        parts[2] = ("binding", (exports[0]["names"]["binding"], exports[0]["bytes"]["binding"], "text/plain"))
    else:
        parts[-1] = ("unknown", parts[-1][1])
    response = client.post(UPLOAD, headers=development, files=parts, data=data)
    assert response.status_code == expected, (case, response.text)
    assert hub.list_jobs()["total"] == 0
    with hub.companion_admission("platform-context"), hub.companion_admission("platform-context"):
        pass


@pytest.mark.parametrize("role", list(PART_LIMITS))
def test_each_actual_file_byte_cap(platform, exports, role):
    client, hub, development, _ = platform
    changed = deepcopy(exports[0])
    changed["bytes"][role] = b"x" * (PART_LIMITS[role] + 1)
    response = post(client, development, changed)
    assert response.status_code == 413, (role, response.text)
    assert hub.list_jobs()["total"] == 0


def test_total_actual_asgi_body_limit_and_exact_contract_constants(platform):
    from poseidon_api.app import RequestBodyLimitMiddleware
    client, hub, development, _ = platform
    assert MAX_REQUEST_BYTES == 12861440 and MAX_FILE_PARTS == 7 and MAX_SCALAR_FIELDS == 0
    assert RequestBodyLimitMiddleware._limit({"type": "http", "method": "POST", "path": UPLOAD}) == MAX_REQUEST_BYTES
    headers = development | {"Content-Type": "multipart/form-data; boundary=synthetic"}
    response = client.post(UPLOAD, headers=headers, content=(b"x" * size for size in (MAX_REQUEST_BYTES, 1)))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert hub.list_jobs()["total"] == 0


def test_actual_stream_overflow_closes_already_opened_multipart_spools(platform, monkeypatch):
    from poseidon_api import companion_routes
    client, hub, development, _ = platform
    instances = []
    original = companion_routes.MultiPartParser
    class TrackingParser(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)
    monkeypatch.setattr(companion_routes, "MultiPartParser", TrackingParser)
    prefix = b'--synthetic\r\nContent-Disposition: form-data; name="wav"; filename="chunk-000000.wav"\r\nContent-Type: audio/wav\r\n\r\n'
    chunks = iter([prefix, *([b"x" * (1024 * 1024)] * 13)])
    messages = []
    async def receive():
        try:
            return {"type": "http.request", "body": next(chunks), "more_body": True}
        except StopIteration:
            return {"type": "http.disconnect"}
    async def send(message):
        messages.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": UPLOAD, "raw_path": UPLOAD.encode(), "query_string": b"", "root_path": "",
             "headers": [(b"authorization", development["Authorization"].encode()), (b"content-type", b"multipart/form-data; boundary=synthetic")],
             "server": ("testserver", 80), "client": ("127.0.0.1", 12345)}
    asyncio.run(client.app(scope, receive, send))
    assert next(message for message in messages if message["type"] == "http.response.start")["status"] == 413
    assert instances and instances[0]._files_to_close_on_error
    assert all(handle.closed for parser in instances for handle in parser._files_to_close_on_error)
    assert hub.list_jobs()["total"] == 0
    with hub.companion_admission("platform-context"), hub.companion_admission("platform-context"):
        pass


def test_scoped_reads_include_pending_failed_but_not_cross_site_and_revoke(platform, exports, monkeypatch):
    client, hub, development, _ = platform
    assert post(client, development, exports[0]).status_code == 202
    viewer, issued = actor(hub, "viewer", "reader")
    outside, _ = actor(hub, "viewer", "outside", ["other-site"])
    base = PREFIX + "/recordings/synthetic-first/acquisition-companion"
    assert client.get(base, headers=viewer).json()["job"]["status"] == "queued"
    assert client.get(base, headers=outside).status_code == 404
    assert client.get(base + "/documents/binding", headers=outside).status_code == 404
    assert client.get(base + "/documents/wav", headers=viewer).status_code == 400
    def failure(*_args, **_kwargs):
        raise RuntimeError("synthetic replay failure")
    monkeypatch.setattr("poseidon_trident.hub.replay_to_store", failure)
    hub.process_next_job()
    assert client.get(base, headers=viewer).json()["job"]["status"] == "failed"
    assert client.get(base + "/documents/binding", headers=viewer).content == exports[0]["bytes"]["binding"]
    hub.revoke_principal(issued["principal"]["id"])
    assert client.get(base, headers=viewer).status_code == 401
    assert client.get(base + "/documents/binding", headers=viewer).status_code == 401


def test_corrupt_stored_bytes_refused_by_both_real_read_routes(platform, exports):
    client, hub, development, _ = platform
    assert post(client, development, exports[0]).status_code == 202
    with hub._workspace.connect() as connection:
        connection.execute("UPDATE recording_companion_documents SET sha256 = ? WHERE role = 'source_final'", ("0" * 64,))
    base = PREFIX + "/recordings/synthetic-first/acquisition-companion"
    for path in (base, base + "/documents/binding", base + "/documents/source_final"):
        response = client.get(path, headers=development)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "companion_store_error"
        assert response.headers["cache-control"] == "no-store"
        assert "source-final.json" not in response.text


def test_companion_routes_reject_unknown_queries(platform, exports):
    client, _, development, _ = platform
    assert post(client, development, exports[0], UPLOAD + "?unexpected=1").status_code == 400
    assert post(client, development, exports[0]).status_code == 202
    base = PREFIX + "/recordings/synthetic-first/acquisition-companion"
    assert client.get(base + "?unexpected=1", headers=development).status_code == 400
    assert client.get(base + "/documents/binding?unexpected=1", headers=development).status_code == 400
