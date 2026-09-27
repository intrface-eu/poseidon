"""Additive loopback simulation routes; no device transport or state setter."""
from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from starlette.concurrency import run_in_threadpool

from .app import API_PREFIX, InvalidRequestBody, _pagination, _reject_unknown_query
from .platform_routes import json_object, empty_body


def register_control_routes(app: FastAPI, require_auth):
    prefix = API_PREFIX

    @app.get(prefix + "/command-keys")
    def keys(request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.list_command_keys()

    @app.post(prefix + "/command-keys", status_code=201)
    async def enroll_key(request: Request, hub=Depends(require_auth)):
        return await run_in_threadpool(hub.enroll_command_key, await json_object(request))

    @app.post(prefix + "/command-keys/{key_id}/revoke")
    async def revoke_key(key_id: str, request: Request, hub=Depends(require_auth)):
        await empty_body(request)
        return await run_in_threadpool(hub.revoke_command_key, key_id)

    @app.get(prefix + "/command-context/{device_id}")
    def context(device_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.command_context(device_id)

    @app.get(prefix + "/command-sequence/{device_id}")
    def sequence(device_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        value = hub.command_context(device_id)
        return {key: value[key] for key in ("device_id", "principal_id", "sequence_seen")}

    @app.post(prefix + "/commands")
    async def command(request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/json":
            raise InvalidRequestBody("Content-Type must be application/json")
        flags = request.headers.getlist("x-poseidon-retained")
        if len(flags) > 1 or (flags and flags[0] not in {"true", "false"}):
            raise InvalidRequestBody("X-Poseidon-Retained must be true or false exactly once")
        # A local LOOPBACK SIMULATION of transport retain metadata, not an MQTT claim.
        return await run_in_threadpool(hub.execute_command, await request.body(), retained=flags == ["true"])

    @app.get(prefix + "/commands")
    def commands(request: Request, hub=Depends(require_auth)):
        limit, offset = _pagination(request, default_limit=50)
        return hub.list_commands(limit=limit, offset=offset)

    @app.get(prefix + "/commands/{command_id}")
    def get_command(command_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_command(command_id)

    @app.put(prefix + "/devices/{device_id}/health-profile")
    async def profile_put(device_id: str, request: Request, hub=Depends(require_auth)):
        return await run_in_threadpool(hub.put_health_profile, device_id, await json_object(request))

    @app.get(prefix + "/devices/{device_id}/health-profile")
    def profile_get(device_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_health_profile(device_id)

    @app.get(prefix + "/device-health")
    def health(request: Request, hub=Depends(require_auth)):
        limit, offset = _pagination(request, default_limit=50)
        return hub.list_device_health(limit=limit, offset=offset)

    @app.get(prefix + "/hub-binding")
    def binding(request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_hub_binding()

    @app.put(prefix + "/hub-binding")
    async def bind(request: Request, hub=Depends(require_auth)):
        return await run_in_threadpool(hub.bind_hub, await json_object(request))

    @app.get(prefix + "/hub-state")
    def state(request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_hub_state()

    @app.get(prefix + "/alarms")
    def alarms(request: Request, hub=Depends(require_auth)):
        limit, offset = _pagination(request, default_limit=50)
        return hub.list_alarms(limit=limit, offset=offset)

    @app.post(prefix + "/alarms/{alarm_id}/acknowledge")
    async def acknowledge(alarm_id: str, request: Request, hub=Depends(require_auth)):
        await empty_body(request)
        return await run_in_threadpool(hub.acknowledge_alarm, alarm_id)

    @app.get(prefix + "/calibrations")
    def calibrations(request: Request, hub=Depends(require_auth)):
        limit, offset = _pagination(request, default_limit=50)
        return hub.list_calibrations(limit=limit, offset=offset)

    @app.get(prefix + "/calibrations/{record_id}")
    def calibration(record_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_calibration(record_id)

    @app.post(prefix + "/calibrations", status_code=201)
    async def calibration_add(request: Request, hub=Depends(require_auth)):
        return await run_in_threadpool(hub.create_calibration, await json_object(request))

    @app.get(prefix + "/retention-policy")
    def retention_policy(request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_retention_policy()

    @app.put(prefix + "/retention-policy")
    async def policy_put(request: Request, hub=Depends(require_auth)):
        return await run_in_threadpool(hub.put_retention_policy, await json_object(request))

    @app.post(prefix + "/retention/preview")
    async def preview(request: Request, hub=Depends(require_auth)):
        return await run_in_threadpool(hub.preview_retention, await json_object(request))

    @app.post(prefix + "/retention/plans/{plan_id}/approve")
    async def approve(plan_id: str, request: Request, hub=Depends(require_auth)):
        return await run_in_threadpool(hub.approve_retention, plan_id, await json_object(request))

    @app.post(prefix + "/retention/plans/{plan_id}/execute")
    async def execute(plan_id: str, request: Request, hub=Depends(require_auth)):
        return await run_in_threadpool(hub.execute_retention, plan_id, await json_object(request))

    @app.get(prefix + "/retention/tombstones/{recording_id}")
    def tombstones(recording_id: str, request: Request, hub=Depends(require_auth)):
        _reject_unknown_query(request, set())
        return hub.get_retention_tombstones(recording_id)
