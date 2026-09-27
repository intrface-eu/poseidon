from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest
from poseidon_trident import Hub, HubError
from poseidon_trident.operating import allowed_transition, Watchdogs
from poseidon_proto.command import STATES, canonical_json
from _control_support import setup, command, signed, device, healthy, calibration, utc, FIXTURES


@pytest.fixture
def ready(tmp_path):
    hub = Hub(tmp_path / "workspace")
    op, issued, key = setup(hub)
    try:
        yield hub, op, issued, key
    finally:
        hub.close()


def test_all_state_commands_audit_and_no_implicit_admin(ready):
    hub, op, issued, key = ready
    for n, kind, state in [(1,"rearm","armed"),(2,"inhibit","inhibited"),(3,"resume","observe"),(4,"inhibit","inhibited")]:
        ack = op.execute_command(command(issued,key,n,kind))
        assert (ack["outcome"],ack["state_after"]) == ("executed",state)
    history = op.get_hub_state()["last_transitions"]
    assert [x["cause_id"] for x in history[:4]] == ["inhibit","resume","inhibit","rearm"]
    assert all(x["command_id"] for x in history[:4])
    assert op.current_identity()["role"] == "operator"
    assert "principal_id" not in op.current_identity()
    with pytest.raises(HubError, match="role"):
        hub.execute_command(command(issued,key,5,"rearm"))
    with hub._workspace.connect() as c:
        for table in ("hub_transitions","commands"):
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(f"DELETE FROM {table}")


@pytest.mark.parametrize("role", json.loads((FIXTURES/"command-negative-cases.json").read_text())["role_denials"])
def test_explicit_operator_role_not_other_roles(ready, role):
    hub, op, issued, key = ready
    enrolled = hub.create_principal({"subject":"role-"+role,"role":role,"site_ids":["site-1"],"device_id":"hub-1" if role=="device" else None})
    other = hub.for_principal(hub.authenticate(enrolled["token"]))
    for kind in ("rearm","resume","inhibit","clear-fault","wiper-run","health-request","config-apply"):
        with pytest.raises(HubError) as error:
            other.execute_command(command(issued,key,1,kind))
        assert error.value.status_code == 403
    assert op.command_context("hub-1")["sequence_seen"] == "0"


@pytest.mark.parametrize("reason", [row["name"] for row in json.loads((FIXTURES/"command-negative-cases.json").read_text())["runtime"]])
def test_every_runtime_rejection_fixture(ready,reason):
    hub, op, issued, key = ready
    body = command(issued,key)
    now = datetime.now(timezone.utc)
    retained = False
    if reason == "expired": body = command(issued,key,issued_at=utc(now-timedelta(minutes=5)),expires_at=utc(now-timedelta(seconds=1)))
    elif reason == "unknown_key": body = command(issued,key,key_id="missing")
    elif reason == "revoked_key": op.revoke_command_key("test-key")
    elif reason == "signature_mismatch": body["kind"]="wiper-run"
    elif reason == "retained_delivery": retained=True
    elif reason == "unknown_device": body=command(issued,key,device_id="missing")
    elif reason == "health_unprofiled": device(hub,"unprofiled",profile=False); body=command(issued,key,device_id="unprofiled")
    elif reason == "zone_mismatch": body=command(issued,key,zone_id="unknown")
    elif reason == "site_mismatch":
        device(hub,"other-site",site="site-2"); body=command(issued,key,device_id="other-site")
    elif reason == "principal_mismatch": body=command(issued,key,principal_id="not-this-principal")
    elif reason == "key_scope_mismatch":
        another=hub.create_principal({"subject":"other-op","role":"operator","site_ids":["site-1"],"device_id":None})
        other=hub.for_principal(hub.authenticate(another["token"]))
        other.enroll_command_key({"key_id":"other-key","principal_id":another["principal"]["id"],"public_key_hex":op.list_command_keys()["items"][0]["public_key_hex"]})
        body=command(issued,key,key_id="other-key")
    elif reason == "not_yet_issued": body=command(issued,key,issued_at=utc(now+timedelta(seconds=10)),expires_at=utc(now+timedelta(seconds=20)))
    elif reason == "digital_simulation_only": device(hub,"field-device",source="field"); body=command(issued,key,device_id="field-device")
    elif reason == "hub_target_mismatch": device(hub,"reef-1",kind="reef"); body=command(issued,key,kind="rearm",device_id="reef-1")
    elif reason == "sequence_not_increasing": op.execute_command(command(issued,key)); body=command(issued,key)
    elif reason == "command_id_conflict":
        op.execute_command(body); body=command(issued,key,2,command_id=body["command_id"])
    before=op.command_context(body["device_id"])["sequence_seen"] if reason != "unknown_device" and reason != "site_mismatch" else "0"
    ack=op.execute_command(body,retained=retained)
    assert ack["reason"] == reason
    assert ack["outcome"] == ("expired" if reason=="expired" else "rejected")
    assert ack["sequence_seen"] == before
    assert ack["state_after"] == "observe"


def test_retry_wire_identity_and_uint64_persist_across_keys_restart(ready):
    hub,op,issued,key=ready
    body=command(issued,key,2**64-2,"rearm")
    wire=json.dumps(body).encode()
    first=op.execute_command(wire)
    assert first["outcome"]=="executed"
    transitions=len(op.get_hub_state()["last_transitions"])
    assert op.execute_command(wire)["outcome"]=="duplicate"
    assert len(op.get_hub_state()["last_transitions"])==transitions
    assert op.execute_command(canonical_json(body))["outcome"]=="rejected"
    with hub._workspace.connect(read_only=True) as c:
        row=c.execute("SELECT sequence_seen,typeof(sequence_seen) FROM command_counters").fetchone()
        assert tuple(row)==(str(2**64-2),"text")
    root=hub._workspace.root; hub.close()
    with Hub(root) as reopened:
        again=reopened.for_principal(reopened.authenticate(issued["token"]))
        assert again.command_context("hub-1")["sequence_seen"]==str(2**64-2)
        assert again.get_hub_state()["state"]=="observe"
        assert again.execute_command(wire)["outcome"]=="duplicate"
        again.revoke_command_key("test-key")
        assert again.execute_command(wire)["reason"]=="revoked_key"


@pytest.mark.parametrize("fault,state", [("hung-heartbeat","inhibited"),("network-loss","inhibited"),("sensor-disconnect","inhibited"),("full-disk","fault"),("full-inodes","fault"),("clock-regression","fault"),("journal-corruption","fault"),("unrecoverable-job-failure","fault")])
def test_watchdog_faults_and_acknowledged_recovery(ready,fault,state):
    hub,op,issued,key=ready
    assert op.execute_command(command(issued,key,1,"rearm"))["state_after"]=="armed"
    hub._watchdogs.inject(fault)
    assert op.get_hub_state()["state"]==state
    assert op.get_hub_state()["last_transitions"][0]["cause_id"]
    if state=="fault":
        assert op.execute_command(command(issued,key,2,"inhibit"))["outcome"]=="failed"
        assert op.execute_command(command(issued,key,3,"clear-fault"))["reason"]=="fault_unacknowledged"
        for alarm in op.list_alarms(limit=200)["items"]:
            op.acknowledge_alarm(alarm["id"])
        hub._watchdogs.inject(fault,False); healthy(hub)
        assert op.execute_command(command(issued,key,4,"clear-fault"))["state_after"]=="inhibited"
        assert op.execute_command(command(issued,key,5,"resume"))["state_after"]=="observe"
    else:
        assert op.execute_command(command(issued,key,2,"rearm"))["outcome"]=="failed"
        hub._watchdogs.inject(fault,False); healthy(hub)
        assert op.execute_command(command(issued,key,3,"resume"))["state_after"]=="observe"


def test_restart_unclean_never_armed_and_last_ten(ready):
    hub,op,issued,key=ready
    for n in range(1,16):
        kind="inhibit" if n%2 else "resume"
        op.execute_command(command(issued,key,n,kind))
    assert len(op.get_hub_state()["last_transitions"])==10
    op.execute_command(command(issued,key,16,"resume"))
    op.execute_command(command(issued,key,17,"rearm"))
    root=hub._workspace.root
    hub._workspace.before_close=None  # Simulate process loss, not a clean Hub shutdown.
    hub.close()
    with Hub(root) as reopened:
        assert reopened.get_hub_state()["state"]=="inhibited"
        assert reopened.get_hub_state()["last_transitions"][0]["reason"].startswith("unclean restart")


@pytest.mark.parametrize("state",STATES)
@pytest.mark.parametrize("cause",["restart","rearm","inhibit","resume","clear-fault","watchdog.api","full-disk","journal-corruption","unrecoverable-job-failure"])
def test_emit_constant_refusal_all_states_and_causes(state,cause):
    assert not allowed_transition(state,"emit",cause)


def test_clean_restart_from_armed_restores_observe(ready):
    hub,op,issued,key=ready
    assert op.execute_command(command(issued,key,1,"rearm"))["state_after"]=="armed"
    root=hub._workspace.root
    hub.close()  # Clean shutdown: the closing callback records it.
    with Hub(root) as reopened:
        state=reopened.get_hub_state()
        assert state["state"]=="observe"
        assert (state["last_transitions"][0]["from_state"],state["last_transitions"][0]["cause_id"])==("armed","restart")
        assert state["last_transitions"][0]["reason"]=="clean startup"


def test_clock_and_heartbeat_ages_use_injected_samples(tmp_path):
    clock={"m":100.0,"w":1000.0}
    watch=Watchdogs(tmp_path,monotonic=lambda:clock["m"],wall=lambda:clock["w"])
    from poseidon_trident.operating import WATCHDOG_DEFAULTS
    with pytest.raises(HubError): watch.heartbeat("offline_import")
    for source in ("host","api","live_journal"): watch.heartbeat(source)
    assert all(r["healthy"] for r in watch.sample(WATCHDOG_DEFAULTS)[0])
    clock["m"]+=11; clock["w"]+=11
    readings,fatal=watch.sample(WATCHDOG_DEFAULTS)
    assert fatal is None and all(not r["healthy"] for r in readings if r["id"] in {"api","host","sensor"})
    clock["m"]+=1; clock["w"]-=5
    assert watch.sample(WATCHDOG_DEFAULTS)[1]=="clock-regression"


def test_no_invented_zone_or_binding_and_scoped_operator(ready):
    hub,op,issued,key=ready
    device(hub,"legacy",profile=False)
    assert next(r for r in hub.list_device_health()["items"] if r["device_id"]=="legacy")["health"]=="unprofiled"
    with pytest.raises(HubError): hub.bind_hub({"device_id":"legacy"})
    other=hub.create_principal({"subject":"site2operator","role":"operator","site_ids":["site-2"],"device_id":None})
    scoped=hub.for_principal(hub.authenticate(other["token"]))
    for method,args in ((scoped.get_hub_state,()),(scoped.command_context,("hub-1",)),(scoped.execute_command,(command(issued,key),))):
        with pytest.raises(HubError) as e: method(*args)
        assert e.value.status_code==404


def test_telemetry_health_not_registration_duplicates_or_offline_imports(ready):
    hub,op,issued,key=ready
    assert hub.list_device_health()["items"][0]["health"]=="offline"
    token=hub.create_principal({"subject":"device-token","role":"device","site_ids":["site-1"],"device_id":"hub-1"})
    dev=hub.for_principal(hub.authenticate(token["token"]))
    body=json.loads((FIXTURES/"telemetry-envelope.valid.json").read_text())|{"site_id":"site-1","device_id":"hub-1"}
    body["delivery_age_s"]=0
    accepted=dev.ingest_telemetry(body)
    assert hub.list_device_health()["items"][0]["health"]=="online"
    assert dev.ingest_telemetry(body)["received_at"]==accepted["received_at"]
    with hub._workspace.connect() as c:
        c.execute("UPDATE telemetry SET received_at=?",(utc(datetime.now(timezone.utc)-timedelta(seconds=40)),))
    assert hub.list_device_health()["items"][0]["health"]=="stale"
    with hub._workspace.connect() as c:
        c.execute("UPDATE telemetry SET received_at=?",(utc(datetime.now(timezone.utc)-timedelta(seconds=121)),))
    assert hub.list_device_health()["items"][0]["health"]=="offline"
    hub.revoke_device("hub-1")
    assert hub.list_device_health()["items"][0]["health"]=="revoked"


def test_calibration_immutable_chain_expiry_and_signature(ready):
    hub,op,issued,key=ready
    first=calibration(issued,key)
    assert op.create_calibration(first)["validity"]=="current"
    second=calibration(issued,key,record_id="second",supersedes_id=first["record_id"])
    assert op.create_calibration(second)["record"]["digital_only"] is True
    assert op.get_calibration(first["record_id"])["validity"]=="superseded"
    for body in (first, calibration(issued,key,record_id="missing",supersedes_id="absent"), calibration(issued,key,record_id="wrongquantity",supersedes_id="second",quantity="voltage"), calibration(issued,key,record_id="fork",supersedes_id=first["record_id"]), calibration(issued,key,record_id="old",valid_until=utc(datetime.now(timezone.utc)-timedelta(seconds=1)))):
        with pytest.raises(HubError): op.create_calibration(body)
    with hub._workspace.connect() as c:
        with pytest.raises(sqlite3.IntegrityError): c.execute("UPDATE calibrations SET quantity='forged'")
        with pytest.raises(sqlite3.IntegrityError): c.execute("DELETE FROM calibrations")
    forged=calibration(issued,key,record_id="forged"); forged["value"]="99"
    with pytest.raises(HubError) as error: op.create_calibration(forged)
    assert error.value.code=="invalid_signature"


def test_config_apply_pure_migration_and_wiper_is_digital_only(ready):
    hub,op,issued,key=ready
    ack=op.execute_command(command(issued,key,1,"config-apply",params={"config":{"schema_version":"poseidon.digital-config.v1","health_interval_s":20}}))
    assert ack["outcome"]=="executed" and "no physical dispatch" in ack["reason"]
    with hub._workspace.connect(read_only=True) as c:
        assert json.loads(c.execute("SELECT document_json FROM control_documents WHERE id='device-config.hub-1'").fetchone()[0])=={"schema_version":"poseidon.digital-config.v2","health_interval_s":20,"simulation":True}
    assert op.execute_command(command(issued,key,2,"wiper-run"))["state_after"]=="observe"


def test_corrupt_underlying_database_fails_closed_without_repair(tmp_path):
    root=tmp_path/"workspace"
    with Hub(root): pass
    db=root/"hub.sqlite3"; original=b"not sqlite evidence"; db.write_bytes(original)
    with pytest.raises(HubError): Hub(root)
    assert db.read_bytes()==original
