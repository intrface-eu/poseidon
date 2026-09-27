from __future__ import annotations

from array import array
import hashlib
import io
from pathlib import Path
import stat
import sys
import time
import wave

from fastapi.testclient import TestClient

from poseidon_api import create_app
from poseidon_proto import RecordingManifest
from poseidon_trident import Hub


DEMO_RECORDING_ID = "synthetic-demo-recording-v1"
VALID_MP4 = b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00"


def _auth(root: Path) -> dict[str, str]:
    token = (root / "access.token").read_text(encoding="ascii").strip()
    return {"Authorization": f"Bearer {token}"}


def _wav_bytes(*amplitudes: int) -> bytes:
    frames_per_window = 20
    samples = array(
        "h",
        (
            amplitude
            for amplitude in amplitudes
            for _ in range(frames_per_window)
        ),
    )
    if sys.byteorder != "little":
        samples.byteswap()
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(1000)
        writer.writeframes(samples.tobytes())
    return output.getvalue()


def _manifest(wav_bytes: bytes, recording_id: str) -> bytes:
    manifest = RecordingManifest(
        schema_version=1,
        recording_id=recording_id,
        site_id="api-test-site",
        zone_id="api-test-zone",
        device_id="api-test-device",
        started_at="2026-09-07T00:00:00Z",
        provenance="synthetic",
        wav_sha256=hashlib.sha256(wav_bytes).hexdigest(),
        calibration_status="uncalibrated",
    )
    return (manifest.to_json() + "\n").encode("utf-8")


def _upload(client: TestClient, headers: dict[str, str], wav: bytes, manifest: bytes):
    return client.post(
        "/api/v1/recordings",
        headers=headers,
        files={
            "wav": ("source.wav", wav, "audio/wav"),
            "manifest": ("manifest.json", manifest, "application/json"),
        },
    )


def _wait_for_terminal_job(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
    *,
    timeout: float = 5.0,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish before timeout")


def test_real_hub_fresh_workspace_auth_status_and_lifespan_close(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    app = create_app(root, start_worker=False)
    with TestClient(app) as client:
        token_path = root / "access.token"
        assert token_path.is_file()
        assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
        headers = _auth(root)
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/api/v1/status").status_code == 401
        status = client.get("/api/v1/status", headers=headers)
        assert status.status_code == 200
        assert status.json() == {
            "mode": "monitor_only",
            "emission_enabled": False,
            "state": "ready",
            "uptime_s": status.json()["uptime_s"],
            "recordings": 0,
            "events": 0,
            "jobs": {"queued": 0, "running": 0, "failed": 0},
        }
        assert isinstance(status.json()["uptime_s"], float)
        assert status.json()["uptime_s"] >= 0

    reopened = Hub(root)
    reopened.close()


def test_real_demo_runs_in_background_and_all_monitor_endpoints_round_trip(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    with TestClient(create_app(root, start_worker=True)) as client:
        headers = _auth(root)
        submitted = client.post("/api/v1/demo", headers=headers)
        assert submitted.status_code == 202
        job = submitted.json()
        assert job["recording_id"] == DEMO_RECORDING_ID
        assert job["status"] in {"queued", "running", "succeeded"}

        finished = _wait_for_terminal_job(client, headers, job["id"])
        assert finished["status"] == "succeeded"
        assert finished["error"] is None

        repeated = client.post("/api/v1/demo", headers=headers)
        assert repeated.status_code == 202
        assert repeated.json()["id"] == job["id"]
        jobs = client.get("/api/v1/jobs?limit=1&offset=0", headers=headers).json()
        assert jobs["total"] == 1
        assert jobs["items"][0]["id"] == job["id"]

        recordings = client.get("/api/v1/recordings", headers=headers).json()
        assert recordings["total"] == 1
        recording = recordings["items"][0]
        assert recording["recording_id"] == DEMO_RECORDING_ID
        assert recording["provenance"] == "synthetic"
        assert recording["event_count"] > 0
        assert recording["video"] is None
        detail = client.get(
            f"/api/v1/recordings/{DEMO_RECORDING_ID}", headers=headers
        )
        assert detail.status_code == 200
        assert detail.json() == recording

        waveform = client.get(
            f"/api/v1/recordings/{DEMO_RECORDING_ID}/waveform?points=16",
            headers=headers,
        )
        assert waveform.status_code == 200
        waveform_body = waveform.json()
        assert waveform_body["recording_id"] == DEMO_RECORDING_ID
        assert waveform_body["amplitude_units"] == "normalized_pcm16_full_scale"
        assert 1 <= len(waveform_body["buckets"]) <= 16

        events = client.get(
            f"/api/v1/events?recording_id={DEMO_RECORDING_ID}&review=unreviewed",
            headers=headers,
        ).json()
        assert events["total"] > 0
        event_id = events["items"][0]["event_id"]
        assert events["items"][0]["review"] is None
        event_detail = client.get(f"/api/v1/events/{event_id}", headers=headers)
        assert event_detail.status_code == 200
        assert event_detail.json()["recording"]["recording_id"] == DEMO_RECORDING_ID

        review_body = {
            "label": "confirmed_feeding",
            "notes": "Operator marked this synthetic test event.",
            "reviewer": "api-test-operator",
            "expected_revision": 0,
        }
        saved = client.put(
            f"/api/v1/events/{event_id}/review",
            headers=headers,
            json=review_body,
        )
        assert saved.status_code == 200
        assert saved.json()["revision"] == 1
        stale = client.put(
            f"/api/v1/events/{event_id}/review",
            headers=headers,
            json=review_body,
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "review_conflict"
        reloaded = client.get(f"/api/v1/events/{event_id}", headers=headers).json()
        assert reloaded["event"]["review"] == saved.json()
        reviewed = client.get(
            "/api/v1/events?review=confirmed_feeding", headers=headers
        ).json()
        assert reviewed["total"] == 1

        uploaded = client.post(
            f"/api/v1/recordings/{DEMO_RECORDING_ID}/video",
            headers=headers,
            files={"video": ("evidence.mp4", VALID_MP4, "video/mp4")},
            data={"offset_s": "1.5"},
        )
        assert uploaded.status_code == 201
        assert uploaded.json()["offset_s"] == 1.5
        conflict = client.post(
            f"/api/v1/recordings/{DEMO_RECORDING_ID}/video",
            headers=headers,
            files={"video": ("evidence.mp4", VALID_MP4, "video/mp4")},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "video_conflict"
        recording_with_video = client.get(
            f"/api/v1/recordings/{DEMO_RECORDING_ID}", headers=headers
        ).json()
        assert recording_with_video["video"] == uploaded.json()

        media = client.get(
            f"/api/v1/recordings/{DEMO_RECORDING_ID}/video",
            headers={**headers, "Range": "bytes=0-7"},
        )
        assert media.status_code == 206
        assert media.content == VALID_MP4[:8]
        assert media.headers["content-range"] == f"bytes 0-7/{len(VALID_MP4)}"

        status = client.get("/api/v1/status", headers=headers).json()
        assert status["recordings"] == 1
        assert status["events"] == recordings["items"][0]["event_count"]
        assert status["jobs"] == {"queued": 0, "running": 0, "failed": 0}


def test_real_import_is_idempotent_and_rejects_conflict_hash_and_truncation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    valid_wav = _wav_bytes(0, 20_000, 20_000, 0, 20_000, 0)
    valid_manifest = _manifest(valid_wav, "uploaded-recording")
    with TestClient(create_app(root, start_worker=False)) as client:
        headers = _auth(root)
        first = _upload(client, headers, valid_wav, valid_manifest)
        second = _upload(client, headers, valid_wav, valid_manifest)
        assert first.status_code == second.status_code == 202
        assert first.json()["id"] == second.json()["id"]
        assert client.get("/api/v1/jobs", headers=headers).json()["total"] == 1
        assert client.get("/api/v1/recordings", headers=headers).json()["total"] == 0

        conflicting_wav = _wav_bytes(0, 25_000, 0)
        conflict = _upload(
            client,
            headers,
            conflicting_wav,
            _manifest(conflicting_wav, "uploaded-recording"),
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "recording_conflict"

        wrong_hash_manifest = RecordingManifest(
            schema_version=1,
            recording_id="wrong-hash-recording",
            site_id="api-test-site",
            zone_id="api-test-zone",
            device_id="api-test-device",
            started_at="2026-09-07T00:00:00Z",
            provenance="synthetic",
            wav_sha256="0" * 64,
            calibration_status="uncalibrated",
        )
        wrong_hash = _upload(
            client,
            headers,
            valid_wav,
            (wrong_hash_manifest.to_json() + "\n").encode("utf-8"),
        )
        assert wrong_hash.status_code == 400
        assert wrong_hash.json()["error"]["code"] == "wav_hash_mismatch"

        truncated = valid_wav[:-1]
        truncated_response = _upload(
            client,
            headers,
            truncated,
            _manifest(truncated, "truncated-recording"),
        )
        assert truncated_response.status_code == 400
        assert truncated_response.json()["error"]["code"] == "invalid_wav"
        assert client.get("/api/v1/jobs", headers=headers).json()["total"] == 1


def test_real_worker_marks_replay_failure_without_publishing_recording(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    wav_bytes = _wav_bytes(0, 20_000, 0)
    manifest = _manifest(wav_bytes, "tampered-recording")
    with TestClient(create_app(root, start_worker=False)) as client:
        headers = _auth(root)
        submitted = _upload(client, headers, wav_bytes, manifest)
        assert submitted.status_code == 202
        job_id = submitted.json()["id"]

    source = root / "recordings" / "tampered-recording" / "source.wav"
    source.chmod(0o600)
    altered = bytearray(source.read_bytes())
    altered[-1] ^= 0x01
    source.write_bytes(altered)
    source.chmod(0o400)

    with TestClient(create_app(root, start_worker=True)) as client:
        headers = _auth(root)
        failed = _wait_for_terminal_job(client, headers, job_id)
        assert failed["status"] == "failed"
        assert failed["error"]
        assert client.get("/api/v1/recordings", headers=headers).json()["total"] == 0
        assert client.get("/api/v1/events", headers=headers).json()["total"] == 0
        status = client.get("/api/v1/status", headers=headers).json()
        assert status["jobs"]["failed"] == 1
