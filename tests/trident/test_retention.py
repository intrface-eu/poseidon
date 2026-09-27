from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from poseidon_trident import Hub, HubError
from poseidon_trident.retention import DEFAULT_POLICY
from _companion_support import make_exports, context, submit
from _support import mp4_bytes


@pytest.fixture
def retained(tmp_path):
    hub=Hub(tmp_path/"workspace")
    policy=hub.put_retention_policy({"schema_version":DEFAULT_POLICY["schema_version"],"media":{"enabled":True,"max_age_s":1},"companions":{"enabled":True,"max_age_s":1}})
    bundle,_=make_exports(tmp_path/"exports")
    context(hub); submit(hub,bundle); hub.process_next_job()
    hub.attach_video("synthetic-first",io.BytesIO(mp4_bytes()),0)
    future=datetime.now(timezone.utc)+timedelta(seconds=5)
    class Clock:
        @staticmethod
        def now(tz): return future
    try:
        with patch("poseidon_trident.retention.datetime",Clock):
            yield hub,bundle,policy
    finally:
        hub.close()


def preview(hub,classes=None):
    return hub.preview_retention({"recording_ids":["synthetic-first"],"data_classes":classes or ["media","companions"]})


def test_exact_media_and_companion_deletion_tombstone_audit_and_reopen(retained):
    hub,bundle,policy=retained
    root=hub._workspace.root
    wav=root/"recordings/synthetic-first/source.wav"
    manifest=root/"recordings/synthetic-first/manifest.json"
    manifest_before=manifest.read_bytes()
    evidence_hash=hashlib.sha256((root/"evidence.sqlite3").read_bytes()).hexdigest()
    plan=preview(hub)
    assert plan["state"]=="preview" and wav.exists()
    with pytest.raises(HubError): hub.execute_retention(plan["plan_id"],{"sha256":plan["sha256"]})
    with pytest.raises(HubError): hub.approve_retention(plan["plan_id"],{"sha256":"0"*64})
    approved=hub.approve_retention(plan["plan_id"],{"sha256":plan["sha256"]})
    assert approved["approved_by"]=="local-development"
    result=hub.execute_retention(plan["plan_id"],{"sha256":plan["sha256"]})
    assert result["state"]=="executed" and not wav.exists()
    assert list((root/"videos").iterdir())==[]
    assert manifest.read_bytes()==manifest_before
    assert hashlib.sha256((root/"evidence.sqlite3").read_bytes()).hexdigest()==evidence_hash
    with hub._workspace.connect(read_only=True) as c:
        assert c.execute("SELECT COUNT(*) FROM recording_companion_documents").fetchone()[0]==0
        assert bytes(c.execute("SELECT projection_bytes FROM recording_companion_imports").fetchone()[0])==b""
        assert c.execute("SELECT COUNT(*) FROM sources").fetchone()[0]==1
    tombstones=hub.get_retention_tombstones("synthetic-first")["items"]
    assert {t["data_class"] for t in tombstones}=={"media","companions"}
    assert all(t["complete_evidence"] is False and t["state"]=="expired" for t in tombstones)
    assert next(t for t in tombstones if t["data_class"]=="media")["source_sha256"]==hashlib.sha256(bundle["bytes"]["wav"]).hexdigest()
    assert hub.list_recordings()["total"]==0
    for method,args in ((hub.get_recording,("synthetic-first",)),(hub.waveform,("synthetic-first",)),(hub.video_path,("synthetic-first",)),(hub.get_acquisition_companion,("synthetic-first",)),(hub.get_companion_document,("synthetic-first","binding"))):
        with pytest.raises(HubError) as error: method(*args)
        assert error.value.status_code==410
    deletes=[row for row in hub.list_audit(limit=200)["items"] if row["action"]=="retention.delete"]
    assert len(deletes)==2 and all(row["details"]["plan_id"]==plan["plan_id"] for row in deletes)
    hub.close()
    with Hub(root) as reopened:
        assert reopened.get_retention_tombstones("synthetic-first")["items"]==tombstones
        assert reopened.list_recordings()["total"]==0
        with pytest.raises(HubError) as error: reopened.get_acquisition_companion("synthetic-first")
        assert error.value.status_code==410


@pytest.mark.parametrize("classes",[["media"],["companions"]])
def test_independent_data_classes_remain_explicit_and_reopen(retained,classes):
    hub,bundle,_=retained
    root=hub._workspace.root
    plan=preview(hub,classes); hub.approve_retention(plan["plan_id"],{"sha256":plan["sha256"]}); hub.execute_retention(plan["plan_id"],{"sha256":plan["sha256"]})
    assert (root/"recordings/synthetic-first/source.wav").exists()==("media" not in classes)
    with hub._workspace.connect(read_only=True) as c:
        assert (c.execute("SELECT COUNT(*) FROM recording_companion_documents").fetchone()[0]==0)==("companions" in classes)
    hub.close()
    with Hub(root) as reopened:
        assert len(reopened.get_retention_tombstones("synthetic-first")["items"])==1
        with pytest.raises(HubError) as error: reopened.get_acquisition_companion("synthetic-first")
        assert error.value.status_code==410


@pytest.mark.parametrize("change",["unknown-file","tampered-wav","hardlink","changed-policy"])
def test_approved_plan_never_deletes_unknown_or_tampered_files(retained,change):
    hub,_,_=retained
    root=hub._workspace.root; path=root/"recordings/synthetic-first/source.wav"
    plan=preview(hub); hub.approve_retention(plan["plan_id"],{"sha256":plan["sha256"]})
    if change=="unknown-file": (path.parent/"user-notes.txt").write_text("unknown user file")
    elif change=="tampered-wav":
        altered=path.read_bytes()+b"tampered"
        path.unlink()  # Replace only this test-owned synthetic copy, never chmod evidence.
        path.write_bytes(altered)
    elif change=="hardlink": (root.parent/"linked-user-copy.wav").hardlink_to(path)
    else: hub.put_retention_policy(DEFAULT_POLICY)
    before=path.read_bytes()
    with pytest.raises(HubError): hub.execute_retention(plan["plan_id"],{"sha256":plan["sha256"]})
    assert path.read_bytes()==before
    with hub._workspace.connect(read_only=True) as c:
        assert c.execute("SELECT COUNT(*) FROM recording_companion_documents").fetchone()[0]==5
        assert c.execute("SELECT COUNT(*) FROM retention_tombstones").fetchone()[0]==0


def _interrupt(path):
    raise RuntimeError("simulated power loss during deletion")


def test_interrupted_execution_fails_closed_without_repair_or_completion(retained):
    hub,_,_=retained
    root=hub._workspace.root
    wav=root/"recordings/synthetic-first/source.wav"
    plan=preview(hub,["media"])
    hub.approve_retention(plan["plan_id"],{"sha256":plan["sha256"]})
    with patch.object(Hub,"_sync_directory",staticmethod(_interrupt)):
        with pytest.raises(RuntimeError):
            hub.execute_retention(plan["plan_id"],{"sha256":plan["sha256"]})
    assert not wav.exists()
    with hub._workspace.connect(read_only=True) as c:
        assert c.execute("SELECT COUNT(*) FROM retention_tombstones").fetchone()[0]==0
        stored=json.loads(c.execute("SELECT document_json FROM control_documents WHERE id=?",(plan["plan_id"],)).fetchone()[0])
    assert stored["state"]=="executing" and stored["executed_at"] is None
    manifest_before=(root/"recordings/synthetic-first/manifest.json").read_bytes()
    hub.close()
    for _ in range(2):  # Reopening never repairs; it refuses again on the same evidence.
        with pytest.raises(HubError) as error:
            Hub(root)
        assert error.value.code in {"companion_store_error","incompatible_workspace","retention_integrity"}
        assert error.value.status_code>=409
    assert not wav.exists()  # No rewritten evidence and no completion claim.
    assert (root/"recordings/synthetic-first/manifest.json").read_bytes()==manifest_before


def test_default_policy_and_preexisting_campaign_evidence_are_never_eligible(tmp_path):
    with Hub(tmp_path/"workspace") as hub:
        assert all(not hub.get_retention_policy()[c]["enabled"] for c in ("media","companions"))
        bundle,_=make_exports(tmp_path/"old-campaign-evidence")
        context(hub); submit(hub,bundle); hub.process_next_job()
        with pytest.raises(HubError): preview(hub)
        hub.put_retention_policy({"schema_version":DEFAULT_POLICY["schema_version"],"media":{"enabled":True,"max_age_s":1},"companions":{"enabled":True,"max_age_s":1}})
        with pytest.raises(HubError) as error: preview(hub)
        assert error.value.code=="retention_ineligible"
        assert hub.get_acquisition_companion("synthetic-first")["state"]=="retained"


def test_retention_role_and_scope_denial(retained):
    hub,_,_=retained
    for role in ("operator","viewer","reviewer","device"):
        issued=hub.create_principal({"subject":"retain-"+role,"role":role,"site_ids":["synthetic-site"],"device_id":"synthetic-device" if role=="device" else None})
        scoped=hub.for_principal(hub.authenticate(issued["token"]))
        with pytest.raises(HubError) as error: preview(scoped)
        assert error.value.status_code==403
    issued=hub.create_principal({"subject":"other-admin","role":"admin","site_ids":["other-site"],"device_id":None})
    scoped=hub.for_principal(hub.authenticate(issued["token"]))
    with pytest.raises(HubError) as error: preview(scoped)
    assert error.value.status_code==404
