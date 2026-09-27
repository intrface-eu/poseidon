"""The published registry must cover contracts/v1 exactly and change no earlier rule."""
from copy import deepcopy
import json

import pytest
from poseidon_proto import platform, registry
from poseidon_proto.calibration import parse_calibration
from poseidon_proto.command import parse_command, parse_command_ack
from poseidon_proto.companion import COMPANION_SCHEMA_VERSION
from poseidon_proto.models import ModelValidationError

FIX = registry.SCHEMA_DIR / "fixtures"
NAMES = sorted(registry.CONTRACTS)
EARLIER = sorted(platform.CONTRACTS)


def fixture(name):
    return json.loads((FIX / f"{name}.valid.json").read_text())


def test_registry_is_exactly_the_published_schema_directory():
    assert registry.SCHEMA_DIR is platform.SCHEMA_DIR
    assert {p.name.removesuffix(".schema.json") for p in registry.SCHEMA_DIR.glob("*.schema.json")} == registry.CONTRACTS
    assert registry.CONTRACTS == platform.CONTRACTS | {"calibration-record", "command", "command-ack", "companion-read"}
    assert registry.CONTRACTS > platform.CONTRACTS


@pytest.mark.parametrize("name", NAMES)
def test_every_registered_name_has_a_schema_file_that_identifies_it(name):
    """Two published `$id` forms exist; the registry reads neither, and asserts only identity.

    The eight earlier schemas use the URL form. calibration-record, command and
    command-ack ship the bare version string that is also their schema_version
    const. Reconciling the two is a contract decision, not this test's business.
    """
    schema = json.loads((registry.SCHEMA_DIR / f"{name}.schema.json").read_text())
    published = schema["$id"]
    url = f"https://poseidon.invalid/contracts/v1/{name}.schema.json"
    version = schema.get("properties", {}).get("schema_version", {}).get("const")
    assert published == url or published == version, published


def test_published_schema_ids_are_unique():
    ids = [json.loads((registry.SCHEMA_DIR / f"{name}.schema.json").read_text())["$id"] for name in NAMES]
    assert len(set(ids)) == len(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_every_fixture_validates_and_returns_a_detached_equal_copy(name):
    value = fixture(name)
    result = registry.validate_contract(name, value)
    assert result == value
    assert result is not value


@pytest.mark.parametrize("name", NAMES)
def test_unknown_schema_version_is_rejected(name):
    value = deepcopy(fixture(name))
    value["schema_version"] = "poseidon.unknown.v99"
    with pytest.raises(ModelValidationError):
        registry.validate_contract(name, value)


@pytest.mark.parametrize("name", NAMES)
def test_unknown_fields_are_rejected(name):
    value = deepcopy(fixture(name))
    value["synthetic_unknown_field"] = 1
    with pytest.raises(ModelValidationError):
        registry.validate_contract(name, value)


@pytest.mark.parametrize("name", ["", "unknown", "../secrets", "command.schema", "COMMAND", None, 1])
def test_unknown_contract_names_are_rejected(name):
    with pytest.raises(ModelValidationError):
        registry.validate_contract(name, {})


@pytest.mark.parametrize("name", EARLIER)
def test_earlier_names_are_routed_to_platform_unchanged(name):
    value = fixture(name)
    assert registry.validate_contract(name, value) == platform.validate_contract(name, value)
    broken = deepcopy(value)
    broken["synthetic_unknown_field"] = 1
    with pytest.raises(ModelValidationError):
        platform.validate_contract(name, broken)
    with pytest.raises(ModelValidationError):
        registry.validate_contract(name, broken)


@pytest.mark.parametrize("name,parser", [("command", parse_command), ("command-ack", parse_command_ack),
                                         ("calibration-record", parse_calibration)])
def test_new_names_agree_with_the_parser_that_owns_them(name, parser):
    value = fixture(name)
    assert registry.validate_contract(name, value) == parser(value)


@pytest.mark.parametrize("name,patch", [
    # Schema-valid documents that only the owning parser can reject.
    ("command", {"expires_at": "2026-09-08T12:00:00Z"}),
    ("command", {"kind": "config-apply"}),
    ("command-ack", {"state_after": "emit"}),
    ("calibration-record", {"value": "-0"}),
    ("calibration-record", {"valid_until": "2026-09-08T00:00:00Z", "valid_from": "2026-09-08T00:00:00Z"}),
])
def test_semantic_rules_are_not_lost_when_routing_through_the_registry(name, patch):
    with pytest.raises(ModelValidationError):
        registry.validate_contract(name, fixture(name) | patch)


def test_companion_read_uses_the_published_transport_constants():
    value = fixture("companion-read")
    assert value["schema_version"] == COMPANION_SCHEMA_VERSION
    assert registry.validate_contract("companion-read", value) == value
    absent = {"schema_version": COMPANION_SCHEMA_VERSION, "state": "absent", "recording_id": value["recording_id"]}
    assert registry.validate_contract("companion-read", absent) == absent
    for patch in ({"documents": list(reversed(value["documents"]))},
                  {"documents": [value["documents"][0] | {"bytes": 262145}] + value["documents"][1:]},
                  {"selected_index": 4096}, {"auth_mode": "root"}, {"imported_at": "2026-09-08 00:00:00"},
                  {"job": {"id": "synthetic-job-1", "status": "unknown"}}):
        with pytest.raises(ModelValidationError):
            registry.validate_contract("companion-read", value | patch)


def test_registry_validation_is_detached_from_its_input():
    value = fixture("command")
    result = registry.validate_contract("command", value)
    result["site_id"] = "changed"
    assert value["site_id"] != "changed"
