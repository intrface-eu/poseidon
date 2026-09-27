import base64
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from poseidon_proto.command import parse_command, parse_command_ack, payload_bytes, decode_wire, COMMAND_SCHEMA, ACK_SCHEMA
from poseidon_proto.calibration import parse_calibration, CALIBRATION_SCHEMA
from poseidon_proto.config_migrations import MIGRATIONS, migrate_config, CURRENT_VERSION
from poseidon_proto.models import ModelValidationError
from poseidon_proto.platform import canonical_json

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "contracts/v1/fixtures"


def fixture(name): return json.loads((FIX/(name+".json")).read_text())


@pytest.mark.parametrize("name,parser,schema", [("command",parse_command,COMMAND_SCHEMA),("command-ack",parse_command_ack,ACK_SCHEMA),("calibration-record",parse_calibration,CALIBRATION_SCHEMA)])
def test_real_parsers_match_shipped_schemas_and_roundtrip(name,parser,schema):
    expected=fixture(name+".valid")
    assert parser(canonical_json(expected))==expected
    assert parser(expected)==expected
    saved=json.loads((ROOT/"contracts/v1"/(name+".schema.json")).read_text())
    assert {k:v for k,v in saved.items() if k not in {"$id","$schema"}}==schema
    bad=deepcopy(expected); bad["unexpected"]=True
    with pytest.raises(ModelValidationError): parser(bad)


@pytest.mark.parametrize("case",fixture("command-negative-cases")["parse"],ids=lambda c:c["name"])
def test_every_negative_parser_fixture(case):
    with pytest.raises(ModelValidationError): parse_command(fixture("command.valid")|case["patch"])


@pytest.mark.parametrize("wire",[b'{"x":1,"x":2}',b'{"x":{"x":1,"x":2}}',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":1.5}',b'{"x":"\\ud800"}',b'[]',b'{} trailing',b'\xff'])
def test_wire_unique_keys_finite_unicode_and_integer_domain(wire):
    with pytest.raises(ModelValidationError): decode_wire(wire)


def test_shared_golden_signing_vectors_are_verified_not_only_compared():
    golden=fixture("command-signing-golden")
    key=Ed25519PublicKey.from_public_bytes(bytes.fromhex(golden["public_key_hex"]))
    for prefix,name in (("command","command.valid"),("calibration","calibration-record.valid")):
        value=fixture(name)
        assert payload_bytes(value).hex()==golden[prefix+"_signing_hex"]
        key.verify(base64.b64decode(value["signature"]["value"]),payload_bytes(value))
        changed=value|{"key_id":"different"}
        assert payload_bytes(changed)!=payload_bytes(value)


@pytest.mark.parametrize("patch",[{"digital_only":False},{"value":1.2},{"value":"-0"},{"value":"1.20"},{"value":"1e3"},{"value":"+1"},{"unit":"["},{"unit":"m///s"},{"unit":"invented"},{"uncertainty":{"value":"-1","coverage_factor":"2"}},{"uncertainty":{"value":"1","coverage_factor":"0"}},{"supersedes_id":"synthetic-calibration-1"}])
def test_calibration_decimal_ucum_digital_only_and_immutability_shape(patch):
    with pytest.raises(ModelValidationError): parse_calibration(fixture("calibration-record.valid")|patch)


def test_ack_retained_emit_and_decimal_rejections():
    body=fixture("command-ack.valid")
    for patch in ({"state_after":"emit"},{"sequence_seen":1},{"sequence_seen":"18446744073709551616"},{"outcome":"ok"},{"reason":"x"*257}):
        with pytest.raises(ModelValidationError): parse_command_ack(body|patch)
    with pytest.raises(ModelValidationError): parse_command_ack(body,retained=True)


def test_every_shipped_digital_config_fixture_migrates_purely_and_unknown_fails():
    fixtures=sorted(FIX.glob("digital-config.v*.json"))
    assert len(fixtures)==2 and MIGRATIONS
    for path in fixtures:
        value=json.loads(path.read_text()); before=deepcopy(value)
        result=migrate_config(value)
        assert result["schema_version"]==CURRENT_VERSION and value==before
        assert result==migrate_config(result)
    for value in ({},{"schema_version":None},{"schema_version":"poseidon.digital-config.v99"},{"schema_version":1}):
        with pytest.raises(ModelValidationError): migrate_config(value)


def test_typescript_parsers_and_golden_vectors_in_locked_bun():
    result=subprocess.run(["bun","test",str(ROOT/"tests/proto/tranche3-contracts.test.ts")],cwd=ROOT,text=True,capture_output=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    assert "0 fail" in result.stderr+result.stdout
