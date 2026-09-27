"""Fixed seven-role, preauthorized single-export transport."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException, MultiPartParser

from poseidon_proto import ModelValidationError
from poseidon_proto.companion import (
    UPLOAD_ROLES, DOCUMENT_ROLES, PART_LIMITS, MAX_FILE_PARTS, MAX_SCALAR_FIELDS,
    MAX_COMPANION_BYTES, validate_filenames,
)
from .app import (
    API_PREFIX, InvalidRequestBody, RequestBodyTooLarge, _reject_unknown_query,
    _require_identifier, _require_multipart, _exact_uploads, _media_type,
    _upload_size, _check_magic, _WAV_CONTENT_TYPES,
)


async def _parse_companion_form(request: Request) -> FormData:
    _require_multipart(request)
    parser = MultiPartParser(request.headers, request.stream(), max_files=MAX_FILE_PARTS,
                             max_fields=MAX_SCALAR_FIELDS, max_part_size=max(PART_LIMITS.values()))
    try:
        try:
            return await parser.parse()
        except BaseException:
            # Starlette closes these only for MultiPartException. The ASGI byte
            # bound and disconnect/cancellation use different exception types.
            # This new route owns and closes every already-opened parser spool.
            for handle in parser._files_to_close_on_error:
                handle.close()
            raise
    except (MultiPartException, StarletteHTTPException) as exc:
        detail = str(getattr(exc, "detail", exc))
        if detail.startswith(("Too many files", "Too many fields", "Part exceeded")):
            raise RequestBodyTooLarge from None
        raise InvalidRequestBody("invalid companion multipart request") from None


def register_companion_routes(app: FastAPI, require_auth) -> None:
    @app.post(f"{API_PREFIX}/acquisition-sessions/{{session_id}}/recordings", status_code=202)
    async def import_companions(session_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        _require_identifier(session_id, name="session_id")
        # This is an eager authorized lease, not a lazy contextmanager generator:
        # ScopedHub's principal ContextVar is active during the method call.
        with hub.companion_admission(session_id):
            form = None
            try:
                form = await _parse_companion_form(request)
                uploads = _exact_uploads(form, set(UPLOAD_ROLES))
                try:
                    names = validate_filenames({role: uploads[role].filename for role in UPLOAD_ROLES})
                except ModelValidationError as exc:
                    raise InvalidRequestBody("invalid companion role or export basename") from exc
                for role, upload in uploads.items():
                    valid_type = _media_type(upload) in _WAV_CONTENT_TYPES if role == "wav" else _media_type(upload) == "application/json"
                    if not valid_type:
                        raise InvalidRequestBody("companion files must use their WAV or JSON content type")
                    await _upload_size(upload, maximum=PART_LIMITS[role], name=role)
                await _check_magic(uploads["wav"], kind="wav")
                metadata = {}
                for role in UPLOAD_ROLES:
                    if role != "wav":
                        raw = await uploads[role].read(PART_LIMITS[role] + 1)
                        if len(raw) > PART_LIMITS[role]:
                            raise RequestBodyTooLarge
                        metadata[role] = raw
                if sum(len(metadata[role]) for role in DOCUMENT_ROLES) > MAX_COMPANION_BYTES:
                    raise RequestBodyTooLarge
                await uploads["wav"].seek(0)
                job = await run_in_threadpool(
                    hub.submit_recording_with_companions, uploads["wav"].file,
                    metadata["manifest"], {role: metadata[role] for role in DOCUMENT_ROLES},
                    session_id=session_id, filenames_by_role=names,
                )
                return JSONResponse(job, status_code=202)
            finally:
                if form is not None:
                    await form.close()

    @app.get(f"{API_PREFIX}/recordings/{{recording_id}}/acquisition-companion")
    def companion(recording_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_acquisition_companion(_require_identifier(recording_id, name="recording_id"))

    @app.get(f"{API_PREFIX}/recordings/{{recording_id}}/acquisition-companion/documents/{{role}}")
    def document(recording_id: str, role: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        result = hub.get_companion_document(_require_identifier(recording_id, name="recording_id"), role)
        return Response(result["bytes"], media_type="application/json", headers={
            "Content-Disposition": f'attachment; filename="{result["name"]}"',
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
            "X-Poseidon-Document-SHA256": result["sha256"],
        })
