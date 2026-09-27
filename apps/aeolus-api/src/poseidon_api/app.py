"""Loopback-only FastAPI adapter for the Poseidon monitor hub."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import logging
import math
from pathlib import Path
import re
import threading
from collections.abc import Iterator
from typing import Any, AsyncIterator, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from poseidon_trident import Hub, HubError
from poseidon_proto.companion import MAX_REQUEST_BYTES as COMPANION_REQUEST_MAX_BYTES


LOGGER = logging.getLogger("poseidon_api")
API_PREFIX = "/api/v1"
WAV_MAX_BYTES = 64 * 1024 * 1024
VIDEO_MAX_BYTES = 64 * 1024 * 1024
MANIFEST_MAX_BYTES = 16 * 1024
MULTIPART_OVERHEAD_MAX_BYTES = 256 * 1024
IMPORT_REQUEST_MAX_BYTES = WAV_MAX_BYTES + MANIFEST_MAX_BYTES + MULTIPART_OVERHEAD_MAX_BYTES
VIDEO_REQUEST_MAX_BYTES = VIDEO_MAX_BYTES + MULTIPART_OVERHEAD_MAX_BYTES
REVIEW_REQUEST_MAX_BYTES = 16 * 1024
STREAM_CHUNK_BYTES = 1024 * 1024
WORKER_IDLE_SECONDS = 0.1
WORKER_ERROR_SECONDS = 1.0
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_INTEGER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_NUMBER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_RANGE_RE = re.compile(r"bytes=([0-9]*)-([0-9]*)\Z")
_REVIEW_PATH_RE = re.compile(r"^/api/v1/events/[^/]+/review$")
_REVIEW_VALUES = {
    "unreviewed",
    "confirmed_feeding",
    "non_feeding",
    "uncertain",
}
_WAV_CONTENT_TYPES = {"audio/wav", "audio/wave", "audio/x-wav"}


class RequestBodyTooLarge(Exception):
    pass


class InvalidRequestBody(Exception):
    pass


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


class RequestBodyLimitMiddleware:
    """Count ASGI request bytes before framework body or multipart parsing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _limit(scope: Scope) -> int | None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT"}:
            return None
        path = scope.get("path", "")
        if re.fullmatch(r"/api/v1/acquisition-sessions/[^/]+/recordings", path):
            return COMPANION_REQUEST_MAX_BYTES
        if path == f"{API_PREFIX}/recordings":
            return IMPORT_REQUEST_MAX_BYTES
        if path == f"{API_PREFIX}/demo":
            return 0
        if path.endswith("/video") and path.startswith(f"{API_PREFIX}/recordings/"):
            return VIDEO_REQUEST_MAX_BYTES
        if _REVIEW_PATH_RE.fullmatch(path):
            return REVIEW_REQUEST_MAX_BYTES
        if re.fullmatch(r"/api/v1/lifecycle/targets/[^/]+/stage", path):
            return 1536 * 1024
        if path == f"{API_PREFIX}/telemetry":
            return 16 * 1024
        if path.startswith(f"{API_PREFIX}/"):
            return 64 * 1024
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Authenticated evidence must not survive in a shared browser/proxy cache
        # after a user changes credentials. Apply to errors and media ranges too.
        if scope["type"] == "http" and scope.get("path", "").startswith(f"{API_PREFIX}/"):
            original_send = send

            async def private_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    headers = [(name, value) for name, value in message.get("headers", []) if name.lower() != b"cache-control"]
                    message = {**message, "headers": [*headers, (b"cache-control", b"no-store")]}
                await original_send(message)

            send = private_send
        limit = self._limit(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return

        raw_lengths = [value for name, value in scope.get("headers", []) if name == b"content-length"]
        if len(raw_lengths) > 1:
            await _error_response(400, "invalid_request", "Invalid Content-Length header.")(
                scope, receive, send
            )
            return
        if raw_lengths:
            try:
                content_length = int(raw_lengths[0].decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                await _error_response(400, "invalid_request", "Invalid Content-Length header.")(
                    scope, receive, send
                )
                return
            if content_length < 0:
                await _error_response(400, "invalid_request", "Invalid Content-Length header.")(
                    scope, receive, send
                )
                return
            if content_length > limit:
                await _error_response(413, "request_too_large", "Request body exceeds the size limit.")(
                    scope, receive, send
                )
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await _error_response(413, "request_too_large", "Request body exceeds the size limit.")(
                scope, receive, send
            )


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    label: Literal["confirmed_feeding", "non_feeding", "uncertain"]
    notes: str = Field(max_length=2000)
    reviewer: str = Field(min_length=1, max_length=80)
    expected_revision: int = Field(ge=0, le=2**63 - 1)

    @model_validator(mode="after")
    def validate_text(self) -> "ReviewRequest":
        if not self.reviewer.strip():
            raise ValueError("reviewer must not be blank")
        if self.label == "confirmed_feeding" and not self.notes.strip():
            raise ValueError("notes are required for confirmed_feeding")
        return self


def _hub_error_response(exc: HubError) -> JSONResponse:
    return _error_response(exc.status_code, exc.code, exc.message,
                           headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None)


def _parse_integer(value: str, *, name: str, minimum: int, maximum: int) -> int:
    if not _INTEGER_RE.fullmatch(value):
        raise InvalidRequestBody(f"{name} must be an integer")
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > len(str(maximum)):
        raise InvalidRequestBody(f"{name} must be from {minimum} through {maximum}")
    try:
        parsed = int(value)
    except ValueError:
        raise InvalidRequestBody(f"{name} must be an integer") from None
    if parsed < minimum or parsed > maximum:
        raise InvalidRequestBody(f"{name} must be from {minimum} through {maximum}")
    return parsed


def _parse_number(value: str, *, name: str) -> float:
    if not _NUMBER_RE.fullmatch(value):
        raise InvalidRequestBody(f"{name} must be a finite number")
    try:
        parsed = float(value)
    except (OverflowError, ValueError):
        raise InvalidRequestBody(f"{name} must be a finite number") from None
    if not math.isfinite(parsed):
        raise InvalidRequestBody(f"{name} must be a finite number")
    return parsed


def _require_identifier(value: str, *, name: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise InvalidRequestBody(
            f"{name} must use only letters, digits, '.', '_' or '-' and be at most 128 characters"
        )
    return value


def _reject_unknown_query(request: Request, allowed: set[str]) -> None:
    seen: set[str] = set()
    for key, _ in request.query_params.multi_items():
        if key not in allowed:
            raise InvalidRequestBody("request contains an unknown query parameter")
        if key in seen:
            raise InvalidRequestBody("each query parameter must appear once")
        seen.add(key)


def _pagination(request: Request, *, default_limit: int) -> tuple[int, int]:
    _reject_unknown_query(request, {"limit", "offset"})
    limit = _parse_integer(
        request.query_params.get("limit", str(default_limit)),
        name="limit",
        minimum=1,
        maximum=200,
    )
    offset = _parse_integer(
        request.query_params.get("offset", "0"),
        name="offset",
        minimum=0,
        maximum=2**63 - 1,
    )
    return limit, offset


def _require_multipart(request: Request) -> None:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data;"):
        raise InvalidRequestBody("Content-Type must be multipart/form-data with a boundary")


def _media_type(upload: UploadFile) -> str:
    return (upload.content_type or "").partition(";")[0].strip().lower()


async def _parse_form(
    request: Request,
    *,
    max_files: int,
    max_fields: int,
    max_part_size: int,
) -> FormData:
    _require_multipart(request)
    try:
        return await request.form(
            max_files=max_files,
            max_fields=max_fields,
            max_part_size=max_part_size,
        )
    except (MultiPartException, StarletteHTTPException) as exc:
        raise InvalidRequestBody("invalid multipart request") from exc


def _exact_uploads(form: FormData, expected: set[str], *, fields: set[str] | None = None) -> dict[str, UploadFile]:
    allowed_fields = set() if fields is None else fields
    uploads: dict[str, UploadFile] = {}
    found_fields: set[str] = set()
    for name, value in form.multi_items():
        if isinstance(value, UploadFile):
            if name not in expected or name in uploads:
                raise InvalidRequestBody("multipart request contains unexpected or duplicate files")
            uploads[name] = value
        else:
            if name not in allowed_fields or name in found_fields:
                raise InvalidRequestBody("multipart request contains unexpected or duplicate fields")
            found_fields.add(name)
    if set(uploads) != expected:
        raise InvalidRequestBody(f"multipart request must contain: {', '.join(sorted(expected))}")
    return uploads


async def _upload_size(upload: UploadFile, *, maximum: int, name: str) -> int:
    if upload.size is not None:
        size = upload.size
    else:
        size = 0
        await upload.seek(0)
        while True:
            chunk = await upload.read(STREAM_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                break
        await upload.seek(0)
    if size > maximum:
        raise RequestBodyTooLarge
    if size <= 0:
        raise InvalidRequestBody(f"{name} file is empty")
    return size


async def _check_magic(upload: UploadFile, *, kind: Literal["wav", "video"]) -> None:
    await upload.seek(0)
    header = await upload.read(12)
    await upload.seek(0)
    if kind == "wav":
        valid = len(header) == 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    else:
        valid = len(header) == 12 and header[4:8] == b"ftyp"
    if not valid:
        raise InvalidRequestBody(f"{kind} file has an invalid or truncated header")


def _worker_loop(hub: Hub, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            processed = hub.process_next_job()
        except Exception as exc:  # A job failure must not end queue processing.
            LOGGER.error("background job processing raised %s", type(exc).__name__)
            stop_event.wait(WORKER_ERROR_SECONDS)
            continue
        if not processed:
            stop_event.wait(WORKER_IDLE_SECONDS)


def _parse_range(value: str, size: int) -> tuple[int, int]:
    match = _RANGE_RE.fullmatch(value.strip())
    if match is None or "," in value:
        raise InvalidRequestBody("invalid byte range")
    first, last = match.groups()
    if not first and not last:
        raise InvalidRequestBody("invalid byte range")
    if len(first) > 20 or len(last) > 20:
        raise InvalidRequestBody("byte range is not satisfiable")
    try:
        start = int(first) if first else None
        parsed_last = int(last) if last else None
    except ValueError:
        raise InvalidRequestBody("invalid byte range") from None
    if start is not None:
        end = size - 1 if parsed_last is None else parsed_last
        if start >= size or end < start:
            raise InvalidRequestBody("byte range is not satisfiable")
        return start, min(end, size - 1)
    suffix_length = parsed_last
    if suffix_length is None:
        raise InvalidRequestBody("invalid byte range")
    if suffix_length <= 0 or size <= 0:
        raise InvalidRequestBody("byte range is not satisfiable")
    return max(size - suffix_length, 0), size - 1


def _file_chunks(path: Path, start: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as stream:
        stream.seek(start)
        while remaining:
            chunk = stream.read(min(STREAM_CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def create_app(data_dir: Path | str, start_worker: bool = True, *, _hub_factory=None) -> FastAPI:
    """Create an app whose lifespan owns one Hub and at most one queue worker."""

    workspace = Path(data_dir).expanduser()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        hub = (_hub_factory or Hub)(workspace)
        stop_event = threading.Event()
        worker: threading.Thread | None = None
        watchdog_thread = None
        pulse = None
        try:
            app.state.hub = hub
            if hasattr(hub, "_watchdogs"):
                from .watchdogs import event_loop_pulse, sample_loop
                pulse = asyncio.create_task(event_loop_pulse(hub))
                watchdog_thread = threading.Thread(target=sample_loop, args=(hub, stop_event), name="poseidon-digital-watchdogs", daemon=False)
                watchdog_thread.start()
            hub.access_token()  # Validate the private development credential before serving.
            app.state.worker_stop = stop_event
            if start_worker:
                candidate = threading.Thread(
                    target=_worker_loop,
                    args=(hub, stop_event),
                    name="poseidon-api-queue-worker",
                    daemon=False,
                )
                candidate.start()
                worker = candidate
            app.state.worker_thread = worker
            yield
        finally:
            stop_event.set()
            try:
                if pulse is not None:
                    pulse.cancel()
                    try:
                        await pulse
                    except asyncio.CancelledError:
                        pass
                if watchdog_thread is not None:
                    watchdog_thread.join()
                if worker is not None:
                    worker.join()
            finally:
                hub.close()

    app = FastAPI(
        title="Poseidon local monitor API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(RequestBodyLimitMiddleware)

    @app.exception_handler(HubError)
    async def handle_hub_error(_request: Request, exc: HubError) -> JSONResponse:
        return _hub_error_response(exc)

    @app.exception_handler(InvalidRequestBody)
    async def handle_invalid_request(_request: Request, exc: InvalidRequestBody) -> JSONResponse:
        return _error_response(400, "invalid_request", str(exc))

    @app.exception_handler(RequestBodyTooLarge)
    async def handle_request_too_large(
        _request: Request, _exc: RequestBodyTooLarge
    ) -> JSONResponse:
        return _error_response(413, "request_too_large", "Request body exceeds the size limit.")

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(400, "invalid_request", "Request validation failed.")

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 401:
            return _error_response(
                401,
                "unauthorized",
                "Authentication required.",
                headers=dict(exc.headers or {"WWW-Authenticate": "Bearer"}),
            )
        if exc.status_code == 404:
            return _error_response(404, "not_found", "Route not found.")
        if exc.status_code == 405:
            return _error_response(405, "method_not_allowed", "Method not allowed.")
        return _error_response(exc.status_code, "http_error", "HTTP request failed.")

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        LOGGER.error("request handling raised %s", type(exc).__name__)
        return _error_response(500, "internal_error", "The request could not be completed.")

    def require_auth(request: Request) -> Hub:
        values = request.headers.getlist("authorization")
        if len(values) != 1:
            raise StarletteHTTPException(
                status_code=401,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scheme, separator, supplied = values[0].partition(" ")
        valid_shape = separator == " " and scheme.lower() == "bearer" and bool(supplied)
        try:
            if not valid_shape:
                raise HubError("unauthorized", "authentication required", 401)
            principal = app.state.hub.authenticate(supplied)
        except HubError as exc:
            if exc.status_code != 401:
                raise
            raise StarletteHTTPException(
                status_code=401,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
        return app.state.hub.for_principal(principal)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        hub = app.state.hub
        if hasattr(hub, "_watchdogs"):
            if getattr(hub, "_control_unavailable", False):
                raise HubError("workspace_unavailable", "digital supervision storage is unavailable", 503)
            hub._watchdogs.heartbeat("api")
        return {"status": "ok"}

    @app.get(f"{API_PREFIX}/status")
    def status(request: Request, hub: Hub = Depends(require_auth)) -> dict[str, Any]:
        _reject_unknown_query(request, set())
        return hub.status()

    @app.post(f"{API_PREFIX}/recordings", status_code=202)
    async def submit_recording(request: Request, hub: Hub = Depends(require_auth)) -> JSONResponse:
        form: FormData | None = None
        uploads: dict[str, UploadFile] = {}
        try:
            form = await _parse_form(
                request,
                max_files=2,
                max_fields=0,
                max_part_size=MANIFEST_MAX_BYTES,
            )
            uploads = _exact_uploads(form, {"wav", "manifest"})
            wav = uploads["wav"]
            manifest = uploads["manifest"]
            if _media_type(wav) not in _WAV_CONTENT_TYPES:
                raise InvalidRequestBody("wav file must use an audio/wav content type")
            if _media_type(manifest) != "application/json":
                raise InvalidRequestBody("manifest file must use application/json content type")
            await _upload_size(wav, maximum=WAV_MAX_BYTES, name="wav")
            await _upload_size(manifest, maximum=MANIFEST_MAX_BYTES, name="manifest")
            await _check_magic(wav, kind="wav")
            manifest_bytes = await manifest.read(MANIFEST_MAX_BYTES + 1)
            if len(manifest_bytes) > MANIFEST_MAX_BYTES:
                raise RequestBodyTooLarge
            await wav.seek(0)
            job = await run_in_threadpool(hub.submit_recording, wav.file, manifest_bytes)
            return JSONResponse(status_code=202, content=job)
        finally:
            for upload in uploads.values():
                await upload.close()
            if form is not None:
                await form.close()

    @app.post(f"{API_PREFIX}/demo", status_code=202)
    async def submit_demo(request: Request, hub: Hub = Depends(require_auth)) -> JSONResponse:
        _reject_unknown_query(request, set())
        await request.body()
        job = await run_in_threadpool(hub.submit_demo)
        return JSONResponse(status_code=202, content=job)

    @app.get(f"{API_PREFIX}/jobs")
    def list_jobs(request: Request, hub: Hub = Depends(require_auth)) -> dict[str, Any]:
        limit, offset = _pagination(request, default_limit=20)
        return hub.list_jobs(limit=limit, offset=offset)

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}")
    def get_job(job_id: str, request: Request, hub: Hub = Depends(require_auth)) -> dict[str, Any]:
        _reject_unknown_query(request, set())
        return hub.get_job(_require_identifier(job_id, name="job_id"))

    @app.get(f"{API_PREFIX}/recordings")
    def list_recordings(request: Request, hub: Hub = Depends(require_auth)) -> dict[str, Any]:
        limit, offset = _pagination(request, default_limit=50)
        return hub.list_recordings(limit=limit, offset=offset)

    @app.get(f"{API_PREFIX}/recordings/{{recording_id}}")
    def get_recording(recording_id: str, request: Request, hub: Hub = Depends(require_auth)) -> dict[str, Any]:
        _reject_unknown_query(request, set())
        return hub.get_recording(_require_identifier(recording_id, name="recording_id"))

    @app.get(f"{API_PREFIX}/events")
    def list_events(request: Request, hub: Hub = Depends(require_auth)) -> dict[str, Any]:
        _reject_unknown_query(request, {"recording_id", "review", "limit", "offset"})
        limit = _parse_integer(
            request.query_params.get("limit", "50"),
            name="limit",
            minimum=1,
            maximum=200,
        )
        offset = _parse_integer(
            request.query_params.get("offset", "0"),
            name="offset",
            minimum=0,
            maximum=2**63 - 1,
        )
        recording_id = request.query_params.get("recording_id")
        if recording_id is not None:
            recording_id = _require_identifier(recording_id, name="recording_id")
        review = request.query_params.get("review")
        if review is not None and review not in _REVIEW_VALUES:
            raise InvalidRequestBody(
                "review must be unreviewed, confirmed_feeding, non_feeding or uncertain"
            )
        return hub.list_events(
            recording_id=recording_id,
            review=review,
            limit=limit,
            offset=offset,
        )

    @app.get(f"{API_PREFIX}/events/{{event_id}}")
    def get_event(event_id: str, request: Request, hub: Hub = Depends(require_auth)) -> dict[str, Any]:
        _reject_unknown_query(request, set())
        return hub.get_event(_require_identifier(event_id, name="event_id"))

    @app.put(f"{API_PREFIX}/events/{{event_id}}/review")
    def save_review(
        event_id: str,
        body: ReviewRequest,
        request: Request,
        hub: Hub = Depends(require_auth),
    ) -> dict[str, Any]:
        _reject_unknown_query(request, set())
        return hub.save_review(
            _require_identifier(event_id, name="event_id"),
            body.label,
            body.notes,
            body.reviewer,
            body.expected_revision,
        )

    @app.get(f"{API_PREFIX}/recordings/{{recording_id}}/waveform")
    def waveform(recording_id: str, request: Request, hub: Hub = Depends(require_auth)) -> dict[str, Any]:
        _reject_unknown_query(request, {"points"})
        points = _parse_integer(
            request.query_params.get("points", "512"),
            name="points",
            minimum=16,
            maximum=2048,
        )
        return hub.waveform(
            _require_identifier(recording_id, name="recording_id"),
            points=points,
        )

    @app.post(f"{API_PREFIX}/recordings/{{recording_id}}/video", status_code=201)
    async def attach_video(
        recording_id: str,
        request: Request,
        hub: Hub = Depends(require_auth),
    ) -> JSONResponse:
        _reject_unknown_query(request, set())
        form: FormData | None = None
        uploads: dict[str, UploadFile] = {}
        try:
            form = await _parse_form(
                request,
                max_files=1,
                max_fields=1,
                max_part_size=1024,
            )
            uploads = _exact_uploads(form, {"video"}, fields={"offset_s"})
            video = uploads["video"]
            if _media_type(video) != "video/mp4":
                raise InvalidRequestBody("video file must use video/mp4 content type")
            await _upload_size(video, maximum=VIDEO_MAX_BYTES, name="video")
            await _check_magic(video, kind="video")
            raw_offset = form.get("offset_s", "0.0")
            if not isinstance(raw_offset, str):
                raise InvalidRequestBody("offset_s must be a finite number")
            offset_s = _parse_number(raw_offset, name="offset_s")
            await video.seek(0)
            result = await run_in_threadpool(
                hub.attach_video,
                _require_identifier(recording_id, name="recording_id"),
                video.file,
                offset_s=offset_s,
            )
            return JSONResponse(status_code=201, content=result)
        finally:
            for upload in uploads.values():
                await upload.close()
            if form is not None:
                await form.close()

    @app.get(f"{API_PREFIX}/recordings/{{recording_id}}/video")
    def stream_video(recording_id: str, request: Request, hub: Hub = Depends(require_auth)):
        _reject_unknown_query(request, set())
        path = Path(hub.video_path(_require_identifier(recording_id, name="recording_id")))
        try:
            size = path.stat().st_size
        except OSError:
            raise HubError("video_not_found", "Video evidence was not found.", 404) from None
        range_header = request.headers.get("range")
        common_headers = {"Accept-Ranges": "bytes"}
        if range_header is None:
            return FileResponse(
                path,
                media_type="video/mp4",
                headers=common_headers,
                content_disposition_type="inline",
            )
        try:
            start, end = _parse_range(range_header, size)
        except InvalidRequestBody:
            return _error_response(
                416,
                "range_not_satisfiable",
                "Requested byte range is not satisfiable.",
                headers={**common_headers, "Content-Range": f"bytes */{size}"},
            )
        length = end - start + 1
        return StreamingResponse(
            _file_chunks(path, start, length),
            status_code=206,
            media_type="video/mp4",
            headers={
                **common_headers,
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(length),
            },
        )

    from .platform_routes import register_platform_routes
    register_platform_routes(app, require_auth)
    from .control_routes import register_control_routes
    register_control_routes(app, require_auth)
    from .companion_routes import register_companion_routes
    register_companion_routes(app, require_auth)
    return app
