from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("tranche3_acl", ROOT/"scripts/platform/generate_topic_acl.py")
acl=importlib.util.module_from_spec(spec); spec.loader.exec_module(acl)


def test_registry_acl_exact_regeneration_and_topic_taxonomy():
    registry=json.loads(acl.REGISTRY.read_text())
    generated=acl.generate(registry)
    assert generated==acl.OUTPUT.read_text()
    assert "topic write #" not in generated
    blocks={block.splitlines()[0]:block for block in generated.split("user ")[1:]}
    assert "/command" in blocks["synthetic-operator"]
    assert "write poseidon/" not in blocks["synthetic-admin"]
    assert "/command" not in blocks["synthetic-viewer"]
    assert "topic write poseidon/v1/synthetic-site-1/synthetic-zone-1/synthetic-hub-1/ack" in blocks["synthetic-device-hub"]
    assert "synthetic-reef-1" not in blocks["synthetic-device-hub"]
    for channel in acl.CHANNELS:
        assert acl.topic("site","zone","device",channel)==f"poseidon/v1/site/zone/device/{channel}"
    with pytest.raises(ValueError): acl.topic("site","zone","device","emit")


@pytest.mark.parametrize("mutation",["unprofiled","no-zone","revoked-device","revoked-principal"])
def test_missing_zone_profile_and_revocation_never_get_default_grants(mutation):
    registry=json.loads(acl.REGISTRY.read_text())
    if mutation=="unprofiled": registry["devices"][0]["health_profile"]=None
    elif mutation=="no-zone": registry["devices"][0]["zone_id"]=None
    elif mutation=="revoked-device": registry["devices"][0]["revoked"]=True
    else: registry["principals"][0]["revoked"]=True
    assert "user synthetic-device-hub\n" not in acl.generate(registry)


@pytest.mark.parametrize("value",["+","#","a/b","a\nuser intruder","",None])
def test_acl_identity_injection_rejected(value):
    with pytest.raises(ValueError): acl.topic("site",value,"device","command")
