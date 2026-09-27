"""Additive platform HTTP routes with strict, bounded JSON requests."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .app import API_PREFIX, InvalidRequestBody, _pagination, _parse_integer, _reject_unknown_query, _require_identifier


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError("nonfinite JSON number")


async def json_object(request: Request) -> dict:
    _reject_unknown_query(request, set())
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/json":
        raise InvalidRequestBody("Content-Type must be application/json")
    try:
        body = json.loads(await request.body(), object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidRequestBody("request must contain a valid JSON object with unique keys") from None
    if type(body) is not dict:
        raise InvalidRequestBody("request must contain a JSON object")
    return body


async def empty_body(request: Request) -> None:
    _reject_unknown_query(request, set())
    if await request.body():
        raise InvalidRequestBody("request body must be empty")


def exact(body: dict, keys: set[str]) -> dict:
    if set(body) != keys:
        raise InvalidRequestBody("request contains missing or unknown fields")
    return body


def register_platform_routes(app: FastAPI, require_auth) -> None:
    @app.get(f"{API_PREFIX}/identity")
    def identity(request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return JSONResponse(hub.current_identity(), headers={"Cache-Control": "no-store"})

    @app.get(f"{API_PREFIX}/principals")
    def principals(request: Request, hub=Depends(require_auth)):
        limit, offset = _pagination(request, default_limit=50)
        return JSONResponse(hub.list_principals(limit=limit, offset=offset), headers={"Cache-Control": "no-store"})

    @app.post(f"{API_PREFIX}/principals", status_code=201)
    async def enroll(request: Request, hub=Depends(require_auth)):
        return JSONResponse(hub.create_principal(await json_object(request)), status_code=201, headers={"Cache-Control": "no-store"})

    @app.post(f"{API_PREFIX}/principals/{{principal_id}}/rotate")
    async def rotate(principal_id: str, request: Request, hub=Depends(require_auth)):
        await empty_body(request)
        return JSONResponse(hub.rotate_principal(principal_id), headers={"Cache-Control": "no-store"})

    @app.post(f"{API_PREFIX}/principals/{{principal_id}}/revoke")
    async def revoke(principal_id: str, request: Request, hub=Depends(require_auth)):
        await empty_body(request)
        return JSONResponse(hub.revoke_principal(principal_id), headers={"Cache-Control": "no-store"})

    @app.get(f"{API_PREFIX}/devices")
    def devices(request: Request, hub=Depends(require_auth)):
        limit, offset = _pagination(request, default_limit=50)
        return hub.list_devices(limit=limit, offset=offset)

    @app.post(f"{API_PREFIX}/devices", status_code=201)
    async def register_device(request: Request, hub=Depends(require_auth)):
        return hub.create_device(await json_object(request))

    @app.get(f"{API_PREFIX}/devices/{{device_id}}")
    def device(device_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_device(device_id)

    @app.post(f"{API_PREFIX}/devices/{{device_id}}/revoke")
    async def disable_device(device_id: str, request: Request, hub=Depends(require_auth)):
        await empty_body(request)
        return hub.revoke_device(device_id)

    @app.put(f"{API_PREFIX}/devices/{{device_id}}/aquilon-mapping")
    async def mapping_put(device_id: str, request: Request, hub=Depends(require_auth)):
        return hub.put_aquilon_mapping(device_id, await json_object(request))

    @app.get(f"{API_PREFIX}/devices/{{device_id}}/aquilon-mapping")
    def mapping_get(device_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_aquilon_mapping(device_id)

    @app.get(f"{API_PREFIX}/acquisition-sessions")
    def sessions(request: Request, hub=Depends(require_auth)):
        limit, offset = _pagination(request, default_limit=50)
        return hub.list_sessions(limit=limit, offset=offset)

    @app.post(f"{API_PREFIX}/acquisition-sessions", status_code=201)
    async def session_create(request: Request, hub=Depends(require_auth)):
        return hub.create_session(await json_object(request))

    @app.get(f"{API_PREFIX}/acquisition-sessions/{{session_id}}")
    def session_get(session_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_session(session_id)

    @app.get(f"{API_PREFIX}/recordings/{{recording_id}}/acquisition-session")
    def binding_get(recording_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_recording_session(recording_id)

    @app.put(f"{API_PREFIX}/recordings/{{recording_id}}/acquisition-session")
    async def binding_put(recording_id: str, request: Request, hub=Depends(require_auth)):
        body = exact(await json_object(request), {"session_id"})
        return hub.bind_recording_session(recording_id, body["session_id"])

    @app.get(f"{API_PREFIX}/recordings/{{recording_id}}/observations")
    def observations(recording_id: str, request: Request, hub=Depends(require_auth)):
        limit, offset = _pagination(request, default_limit=50)
        return hub.list_observations(recording_id, limit=limit, offset=offset)

    @app.post(f"{API_PREFIX}/recordings/{{recording_id}}/observations", status_code=201)
    async def observation_create(recording_id: str, request: Request, hub=Depends(require_auth)):
        return hub.create_observation(recording_id, await json_object(request))

    @app.put(f"{API_PREFIX}/recordings/{{recording_id}}/observations/{{observation_id}}")
    async def observation_update(recording_id: str, observation_id: str, request: Request, hub=Depends(require_auth)):
        return hub.update_observation(recording_id, observation_id, await json_object(request))

    @app.get(f"{API_PREFIX}/recordings/{{recording_id}}/observations/{{observation_id}}/history")
    def observation_history(recording_id: str, observation_id: str, request: Request, hub=Depends(require_auth)):
        limit, offset = _pagination(request, default_limit=50)
        return hub.observation_history(recording_id, observation_id, limit=limit, offset=offset)

    @app.post(f"{API_PREFIX}/telemetry")
    async def ingest(request: Request, hub=Depends(require_auth)):
        return hub.ingest_telemetry(await json_object(request))

    @app.get(f"{API_PREFIX}/telemetry")
    def telemetry(request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, {"device_id", "site_id", "limit", "offset"})
        limit = _parse_integer(request.query_params.get("limit", "50"), name="limit", minimum=1, maximum=200)
        offset = _parse_integer(request.query_params.get("offset", "0"), name="offset", minimum=0, maximum=2**63 - 1)
        return hub.list_telemetry(device_id=request.query_params.get("device_id"), site_id=request.query_params.get("site_id"), limit=limit, offset=offset)

    @app.get(f"{API_PREFIX}/audit")
    def audit(request: Request, hub=Depends(require_auth)):
        limit, offset = _pagination(request, default_limit=50)
        return hub.list_audit(limit=limit, offset=offset)

    # Import cryptography only when invoking a lifecycle route. Passive Hub/replay
    # imports and existing monitor routes remain dependency-free at the Hub layer.
    def lifecycle():
        from poseidon_trident.lifecycle import LocalLifecycle
        return LocalLifecycle(app.state.hub)

    prefix = f"{API_PREFIX}/lifecycle"

    @app.get(f"{prefix}/keys")
    def keys(request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return lifecycle().list_keys(hub.current_identity())

    @app.post(f"{prefix}/keys", status_code=201)
    async def key_add(request: Request, hub=Depends(require_auth)):
        body = exact(await json_object(request), {"id", "site_ids", "public_key_hex"})
        return lifecycle().add_key(hub.current_identity(), body)

    @app.post(f"{prefix}/keys/{{key_id}}/revoke")
    async def key_revoke(key_id: str, request: Request, hub=Depends(require_auth)):
        await empty_body(request)
        return lifecycle().revoke_key(hub.current_identity(), _require_identifier(key_id, name="key_id"))

    @app.get(f"{prefix}/targets")
    def targets(request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return lifecycle().list_targets(hub.current_identity())

    @app.post(f"{prefix}/targets", status_code=201)
    async def target_add(request: Request, hub=Depends(require_auth)):
        body = exact(await json_object(request), {"id", "device_id", "simulation", "initial_sha256", "initial_version", "security_floor"})
        return lifecycle().create_target(hub.current_identity(), body)

    @app.get(f"{prefix}/targets/{{target_id}}")
    def target_get(target_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return lifecycle().get_target(hub.current_identity(), _require_identifier(target_id, name="target_id"))

    @app.get(f"{prefix}/targets/{{target_id}}/history")
    def target_history(target_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return lifecycle().history(hub.current_identity(), _require_identifier(target_id, name="target_id"))

    @app.post(f"{prefix}/targets/{{target_id}}/stage")
    async def target_stage(target_id: str, request: Request, hub=Depends(require_auth)):
        body = exact(await json_object(request), {"manifest", "artifact_base64"})
        return lifecycle().stage(hub.current_identity(), _require_identifier(target_id, name="target_id"), body)

    def transition_route(action: str):
        async def transition(target_id: str, request: Request, hub=Depends(require_auth)) -> Any:
            await empty_body(request)
            return lifecycle().transition(hub.current_identity(), _require_identifier(target_id, name="target_id"), action)
        return transition

    for action in ("activate", "confirm", "rollback", "recover"):
        app.post(f"{prefix}/targets/{{target_id}}/{action}", name=f"lifecycle_{action}")(transition_route(action))
