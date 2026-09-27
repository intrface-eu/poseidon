from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import wave

from fastapi.testclient import TestClient
import pytest

from poseidon_api import create_app
from poseidon_proto import RecordingManifest


FIXTURES = Path(__file__).resolve().parents[2] / "contracts/v1/fixtures"
PREFIX = "/api/v1"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.valid.json").read_text())


def device(device_id="test-device-1", site="test-site-1"):
    return {"id": device_id, "site_id": site, "label": "Synthetic API test device", "kind": "reef",
            "hardware_revision": "synthetic-r1", "source_kind": "synthetic"}


@pytest.fixture
def platform(tmp_path):
    root = tmp_path / "workspace"
    app = create_app(root, start_worker=False)
    with TestClient(app) as client:
        # Only this owned, temporary workspace credential is read.
        headers = {"Authorization": "Bearer " + (root / "access.token").read_text().strip()}
        yield client, headers, app.state.hub, root


def issue(client, headers, subject, role, sites=None, device_id=None):
    response = client.post(PREFIX + "/principals", headers=headers,
                           json={"subject": subject, "role": role, "site_ids": sites or ["test-site-1"], "device_id": device_id})
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    return {"Authorization": "Bearer " + body["token"]}, body


def import_recording(client, headers, hub, *, recording_id="test-recording-1", device_id="test-device-1", site="test-site-1", silent=True, bound=True):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(1000)
        writer.writeframes((b"\x00\x00" if silent else b"\x20\x4e") * 100)
    raw = output.getvalue()
    manifest = RecordingManifest(schema_version=1, recording_id=recording_id, site_id=site, zone_id="test-zone",
                                 device_id=device_id, started_at="2026-09-01T00:00:00Z", provenance="synthetic",
                                 wav_sha256=hashlib.sha256(raw).hexdigest(), calibration_status="uncalibrated")
    response = client.post(PREFIX + "/recordings", headers=headers,
                           files={"wav": ("test.wav", raw, "audio/wav"), "manifest": ("manifest.json", manifest.to_json().encode(), "application/json")})
    assert response.status_code == 202, response.text
    hub.process_next_job()
    if bound:
        response_device = client.post(PREFIX + "/devices", headers=headers, json=device(device_id, site))
        assert response_device.status_code in {201, 409}
        body = fixture("acquisition-session") | {"id": "session-" + recording_id, "site_id": site, "device_id": device_id}
        assert client.post(PREFIX + "/acquisition-sessions", headers=headers, json=body).status_code == 201
        binding = client.put(PREFIX + f"/recordings/{recording_id}/acquisition-session", headers=headers, json={"session_id": body["id"]})
        assert binding.status_code == 200, binding.text
    return response.json()


NEW_ROUTES = [
    ("GET", "/identity"), ("GET", "/principals"), ("POST", "/principals"),
    ("POST", "/principals/id/rotate"), ("POST", "/principals/id/revoke"),
    ("GET", "/devices"), ("POST", "/devices"), ("GET", "/devices/id"), ("POST", "/devices/id/revoke"),
    ("GET", "/devices/id/aquilon-mapping"), ("PUT", "/devices/id/aquilon-mapping"),
    ("GET", "/acquisition-sessions"), ("POST", "/acquisition-sessions"), ("GET", "/acquisition-sessions/id"),
    ("GET", "/recordings/id/acquisition-session"), ("PUT", "/recordings/id/acquisition-session"),
    ("GET", "/recordings/id/observations"), ("POST", "/recordings/id/observations"),
    ("PUT", "/recordings/id/observations/obs"), ("GET", "/recordings/id/observations/obs/history"),
    ("GET", "/telemetry"), ("POST", "/telemetry"), ("GET", "/audit"),
    ("GET", "/lifecycle/keys"), ("POST", "/lifecycle/keys"), ("GET", "/lifecycle/targets"),
    ("POST", "/lifecycle/targets/id/stage"), ("POST", "/lifecycle/targets/id/activate"),
]


@pytest.mark.parametrize("method,path", NEW_ROUTES)
def test_new_routes_require_auth(platform, method, path):
    client, _, _, _ = platform
    response = client.request(method, PREFIX + path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


def test_empty_platform_identity_and_credential_rotation(platform):
    client, development, _, root = platform
    identity = client.get(PREFIX + "/identity", headers=development)
    assert identity.json() == {"subject": "local-development", "role": "admin", "site_ids": [], "device_id": None, "auth_mode": "local_development_key"}
    for route in ("/devices", "/principals", "/acquisition-sessions", "/telemetry", "/audit"):
        result = client.get(PREFIX + route, headers=development)
        assert result.status_code == 200
        assert result.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    viewer, issued = issue(client, development, "test-viewer", "viewer")
    assert client.get(PREFIX + "/identity", headers=viewer).json() == {
        "subject": "test-viewer", "role": "viewer", "site_ids": ["test-site-1"], "device_id": None, "auth_mode": "scoped_token"}
    principal_id = issued["principal"]["id"]
    rotated = client.post(PREFIX + f"/principals/{principal_id}/rotate", headers=development)
    assert rotated.status_code == 200
    assert rotated.headers["cache-control"] == "no-store"
    assert client.get(PREFIX + "/identity", headers=viewer).status_code == 401
    current = {"Authorization": "Bearer " + rotated.json()["token"]}
    assert client.get(PREFIX + "/identity", headers=current).status_code == 200
    assert client.post(PREFIX + f"/principals/{principal_id}/revoke", headers=development).status_code == 200
    assert client.get(PREFIX + "/identity", headers=current).status_code == 401
    assert issued["token"].encode() not in (root / "hub.sqlite3").read_bytes()
    assert rotated.json()["token"] not in client.get(PREFIX + "/audit", headers=development).text


def test_zero_candidate_observation_routes_preserve_draft_conflict_and_history(platform):
    client, development, hub, _ = platform
    import_recording(client, development, hub)
    reviewer, _ = issue(client, development, "test-reviewer", "reviewer")
    recording = client.get(PREFIX + "/recordings/test-recording-1", headers=reviewer).json()
    assert recording["event_count"] == 0
    body = fixture("independent-observation")
    body["review_context"] = {"protocol_id": None, "evidence_refs": [], "visibility": "unknown", "sync_uncertainty_s": None, "reviewed_coverage": False}
    base = PREFIX + "/recordings/test-recording-1/observations"
    created = client.post(base, headers=reviewer, json=body)
    assert created.status_code == 201, created.text
    first = created.json()
    assert first["actor_subject"] == "test-reviewer"
    assert first["observer"] == body["observer"]
    assert first["provenance"] == {"recording_sha256": recording["wav_sha256"], "source_kind": "synthetic"}
    draft = body | {"expected_revision": 1, "label": "feeding_observed", "notes": "Synthetic browser workflow only."}
    detail = base + "/" + body["id"]
    saved = client.put(detail, headers=reviewer, json=draft)
    assert saved.status_code == 200
    conflict = client.put(detail, headers=reviewer, json=draft)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "observation_conflict"
    assert draft["expected_revision"] == 1
    assert client.get(detail + "/history", headers=reviewer).json()["items"] == [first, saved.json()]
    assert client.get(base, headers=reviewer).json()["items"] == [saved.json()]
    assert saved.json()["review_context"] == body["review_context"]
    assert client.get(PREFIX + "/events", headers=reviewer).json()["total"] == 0
    assert client.post(base, headers=reviewer, json=body | {"id": "outside-duration", "end_s": 0.11}).status_code == 400


def test_existing_routes_scope_evidence_media_jobs_and_counts(platform):
    client, development, hub, _ = platform
    allowed = import_recording(client, development, hub, silent=False)
    hidden = import_recording(client, development, hub, recording_id="hidden", device_id="other-device", site="other-site", silent=False)
    unbound = import_recording(client, development, hub, recording_id="unbound", bound=False)
    viewer, _ = issue(client, development, "test-viewer", "viewer")
    scoped_admin, _ = issue(client, development, "test-admin", "admin")
    status = client.get(PREFIX + "/status", headers=viewer).json()
    assert status["recordings"] == 1 and status["events"] == 1
    for route in ("/recordings", "/events", "/jobs"):
        page = client.get(PREFIX + route + "?limit=1", headers=viewer).json()
        assert page["total"] == 1 and len(page["items"]) == 1
        assert client.get(PREFIX + route + "?offset=1", headers=viewer).json()["items"] == []
    hidden_event = hub.list_events(recording_id="hidden")["items"][0]["event_id"]
    hidden_paths = [f"/jobs/{hidden['id']}", f"/jobs/{unbound['id']}", f"/events/{hidden_event}",
                    "/recordings/hidden", "/recordings/hidden/waveform", "/recordings/hidden/video", "/recordings/hidden/observations",
                    "/recordings/hidden/acquisition-session", "/recordings/unbound"]
    for path in hidden_paths:
        response = client.get(PREFIX + path, headers=viewer)
        assert response.status_code == 404, (path, response.text)
    assert client.get(PREFIX + "/events?recording_id=hidden", headers=viewer).json()["total"] == 0
    assert client.get(PREFIX + f"/jobs/{allowed['id']}", headers=viewer).status_code == 200
    assert client.get(PREFIX + "/recordings/test-recording-1/waveform", headers=viewer).status_code == 200
    assert client.post(PREFIX + "/demo", headers=scoped_admin).status_code == 403
    assert client.put(PREFIX + "/recordings/unbound/acquisition-session", headers=scoped_admin,
                      json={"session_id": "session-test-recording-1"}).status_code == 404
    event_id = hub.list_events(recording_id="test-recording-1")["items"][0]["event_id"]
    assert client.put(PREFIX + f"/events/{event_id}/review", headers=viewer,
                      json={"label": "uncertain", "notes": "", "reviewer": "declared", "expected_revision": 0}).status_code == 403
    assert client.post(PREFIX + "/recordings/test-recording-1/observations", headers=viewer,
                       json=fixture("independent-observation")).status_code == 403


def test_principal_scope_grants_and_audit_do_not_leak_other_sites(platform):
    client, development, _, _ = platform
    admin, _ = issue(client, development, "site-admin", "admin")
    _, broader = issue(client, development, "broad-admin", "admin", ["test-site-1", "other-site"])
    response = client.get(PREFIX + "/principals", headers=admin)
    assert response.json()["total"] == 1
    assert client.post(PREFIX + "/principals", headers=admin,
                       json={"subject": "outside", "role": "admin", "site_ids": ["other-site"], "device_id": None}).status_code == 403
    principal_id = broader["principal"]["id"]
    assert client.post(PREFIX + f"/principals/{principal_id}/rotate", headers=admin).status_code == 404
    assert client.post(PREFIX + f"/principals/{principal_id}/revoke", headers=admin).status_code == 404
    page = client.get(PREFIX + "/audit?limit=200", headers=admin).json()
    assert all(item["site_id"] == "test-site-1" for item in page["items"])
    assert "token_hash" not in json.dumps(page)


def test_device_registry_mapping_telemetry_roundtrip_and_revoke(platform):
    client, development, _, _ = platform
    assert client.post(PREFIX + "/devices", headers=development, json=device()).status_code == 201
    assert client.post(PREFIX + "/devices", headers=development, json=device("other-device")).status_code == 201
    actor, _ = issue(client, development, "device-actor", "device", device_id="test-device-1")
    mapping = {"dev_eui": "0011223344556677", "calibration_refs": [{"code": 7, "sensor_kind": "temperature", "calibration_id": "synthetic-ref"}]}
    url = PREFIX + "/devices/test-device-1/aquilon-mapping"
    assert client.put(url, headers=development, json=mapping).status_code == 200
    assert client.get(url, headers=actor).json() == mapping
    assert client.put(PREFIX + "/devices/other-device/aquilon-mapping", headers=development, json=mapping).status_code == 409
    assert client.get(PREFIX + "/devices/other-device", headers=actor).status_code == 404
    assert client.get(PREFIX + "/devices", headers=actor).json()["total"] == 1
    body = fixture("telemetry-envelope") | {"device_id": "test-device-1", "site_id": "test-site-1", "boot_id": "18446744073709551615"}
    body["provenance"]["transport"] = "aquilon"
    body["measurements"][0] |= {"quality": "calibrated", "calibration_id": "synthetic-ref"}
    body["radio"] = {"dev_eui": mapping["dev_eui"], "uptime_s": 1, "power_mode": "normal", "clock_claim": "unsynchronized",
                     "observed_at_unix_s": None, "network_received_at": None, "frame_sha256": "0" * 64, "calibration_code": 7}
    rejected = deepcopy(body)
    rejected["measurements"][0]["calibration_id"] = "unknown-ref"
    assert client.post(PREFIX + "/telemetry", headers=actor, json=rejected).status_code == 400
    created = client.post(PREFIX + "/telemetry", headers=actor, json=body)
    assert created.status_code == 200, created.text
    assert created.json()["actor_subject"] == "device-actor"
    assert created.json()["envelope"] == body
    duplicate = client.post(PREFIX + "/telemetry", headers=actor, json=body)
    assert duplicate.json() == created.json() | {"duplicate": True}
    assert client.post(PREFIX + "/telemetry", headers=actor, json=body | {"delivery_age_s": 1}).status_code == 409
    assert client.post(PREFIX + "/telemetry", headers=actor, json=body | {"boot_id": "9"}).status_code == 409
    assert client.post(PREFIX + "/telemetry", headers=development, json=body).status_code == 403
    assert client.get(PREFIX + "/telemetry", headers=actor).json()["total"] == 1
    assert client.get(PREFIX + "/telemetry?device_id=other-device", headers=actor).json()["total"] == 0
    assert client.post(PREFIX + "/devices/test-device-1/revoke", headers=development).status_code == 200
    assert client.get(PREFIX + "/identity", headers=actor).status_code == 401
    assert client.post(PREFIX + "/telemetry", headers=actor, json=body).status_code == 401


@pytest.mark.parametrize("path", ["/devices", "/principals", "/acquisition-sessions", "/telemetry", "/audit", "/identity", "/lifecycle/targets"])
def test_new_queries_reject_unknown_and_duplicate_parameters(platform, path):
    client, headers, _, _ = platform
    assert client.get(PREFIX + path + "?unexpected=1", headers=headers).status_code == 400
    assert client.get(PREFIX + path + "?limit=1&limit=2", headers=headers).status_code == 400


@pytest.mark.parametrize("payload", [b'{"id":"one","id":"two"}', b'{"id":NaN}', b'{"id":Infinity}', b'[]', b'{'])
def test_new_json_rejects_duplicate_keys_and_nonfinite_numbers(platform, payload):
    client, headers, _, _ = platform
    response = client.post(PREFIX + "/devices", headers=headers | {"Content-Type": "application/json"}, content=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_new_body_limits_count_actual_streamed_bytes_and_lifecycle_stage_exception(platform):
    client, headers, _, _ = platform
    headers = headers | {"Content-Type": "application/json"}
    for path, limit in (("/devices", 65536), ("/telemetry", 16384), ("/lifecycle/targets/test/stage", 1536 * 1024)):
        response = client.post(PREFIX + path, headers=headers, content=(b"x" * chunk for chunk in (limit, 1)))
        assert response.status_code == 413, (path, response.text)
        assert response.json()["error"]["code"] == "request_too_large"
    # A stage body above 64KiB passes the route's larger transport limit and then
    # fails domain/target validation, rather than incorrectly returning 413.
    response = client.post(PREFIX + "/lifecycle/targets/missing/stage", headers=headers,
                           content=json.dumps({"manifest": {}, "artifact_base64": "A" * 70000}))
    assert response.status_code in {400, 404}, response.text


def test_protected_json_errors_and_media_ranges_are_not_cacheable(platform):
    client, development, hub, _ = platform
    import_recording(client, development, hub)
    video = b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00"
    attached = client.post(PREFIX + "/recordings/test-recording-1/video", headers=development,
                           files={"video": ("synthetic.mp4", video, "video/mp4")})
    assert attached.status_code == 201
    for path, headers in (("/status", development), ("/status", {}),
                          ("/recordings/test-recording-1/video", development),
                          ("/recordings/test-recording-1/video", development | {"Range": "bytes=0-3"}),
                          ("/recordings/test-recording-1/video", development | {"Range": "bytes=100-200"})):
        response = client.get(PREFIX + path, headers=headers)
        assert response.headers["cache-control"] == "no-store"


def test_lifecycle_real_api_roles_target_and_no_side_effect_commands(platform):
    client, development, _, _ = platform
    assert client.post(PREFIX + "/devices", headers=development, json=device()).status_code == 201
    viewer, _ = issue(client, development, "lifecycle-viewer", "viewer")
    actor, _ = issue(client, development, "lifecycle-device", "device", device_id="test-device-1")
    target = {"id": "synthetic-target", "device_id": "test-device-1", "simulation": True,
              "initial_sha256": "0" * 64, "initial_version": "synthetic-v0", "security_floor": 0}
    response = client.post(PREFIX + "/lifecycle/targets", headers=development, json=target)
    assert response.status_code == 201, response.text
    assert response.json()["simulation"] is True
    assert client.get(PREFIX + "/lifecycle/targets", headers=viewer).json()["total"] == 1
    assert client.get(PREFIX + "/lifecycle/targets", headers=actor).status_code == 403
    assert client.post(PREFIX + "/lifecycle/targets", headers=viewer, json=target | {"id": "denied"}).status_code == 403
    assert client.post(PREFIX + "/lifecycle/targets/synthetic-target/activate", headers=viewer).status_code == 403
    assert client.post(PREFIX + "/lifecycle/targets/synthetic-target/stage", headers=viewer,
                       json={"manifest": {}, "artifact_base64": ""}).status_code == 403
    assert client.post(PREFIX + "/lifecycle/targets/synthetic-target/confirm", headers=development, json={"unexpected": True}).status_code == 400
    assert client.get(PREFIX + "/lifecycle/targets/synthetic-target/history", headers=viewer).status_code == 200
    assert client.get(PREFIX + "/status", headers=development).json()["emission_enabled"] is False
