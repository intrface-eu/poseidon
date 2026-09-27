"""Transport parity only; these tests do not stand in for the acquisition reader."""
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from poseidon_proto.companion import (
    COMPANION_SCHEMA_VERSION, DOCUMENT_ROLES, MAX_ADMISSIONS,
    MAX_COMPANION_BYTES, MAX_FILE_PARTS, MAX_QUEUE_SLOTS,
    MAX_REQUEST_BYTES, MAX_RETAINED_COMPANION_BYTES, MAX_SCALAR_FIELDS,
    MULTIPART_OVERHEAD_BYTES, PART_LIMITS, UPLOAD_ROLES, validate_filenames,
)
from poseidon_proto.models import ModelValidationError

ROOT = Path(__file__).resolve().parents[2]


class CompanionTransportTests(unittest.TestCase):
    def names(self, index="000001"):
        return {"wav": f"chunk-{index}.wav", "manifest": f"recording-{index}.v1.json",
                "binding": f"binding-{index}.json", "source_receipt": f"source-receipt-{index}.json",
                "source_header": "source-header.json", "source_final": "source-final.json",
                "export_receipt": "export.receipt.json"}

    def test_ratified_caps_and_exact_roles(self):
        self.assertEqual(dict(PART_LIMITS), {
            "wav": 8388608, "manifest": 16384, "binding": 262144,
            "source_receipt": 16384, "source_header": 1048576,
            "source_final": 2097152, "export_receipt": 65536,
        })
        self.assertEqual(UPLOAD_ROLES, tuple(self.names()))
        self.assertEqual(DOCUMENT_ROLES, UPLOAD_ROLES[2:])
        self.assertEqual(MAX_REQUEST_BYTES, PART_LIMITS["wav"] + PART_LIMITS["manifest"] + MAX_COMPANION_BYTES + MULTIPART_OVERHEAD_BYTES)
        self.assertEqual((MAX_FILE_PARTS, MAX_SCALAR_FIELDS, MAX_ADMISSIONS, MAX_QUEUE_SLOTS, MAX_RETAINED_COMPANION_BYTES), (7, 0, 2, 32, 268435456))

    def test_caps_cannot_be_mutated_by_an_import_caller(self):
        with self.assertRaises(TypeError):
            PART_LIMITS["wav"] = 1

    def test_names_are_checked_without_paths_or_index_inference(self):
        for index in ("000000", "000001", "004095"):
            with self.subTest(index=index):
                self.assertEqual(validate_filenames(self.names(index)), self.names(index))
        # Cross-file index correspondence is the real reader's responsibility.
        mixed = self.names()
        mixed["manifest"] = "recording-000002.v1.json"
        self.assertEqual(validate_filenames(mixed), mixed)

    def test_traversal_aliases_unicode_and_non_text_are_rejected(self):
        for role in UPLOAD_ROLES:
            for value in ("../source-header.json", "/source-header.json", "folder/source-header.json", "source-header.json\n", "source-header.json\x00", "source-header.json/..", "source%2dheader.json", "sourcé-header.json", True, 1, None):
                with self.subTest(role=role, value=value):
                    names = self.names()
                    names[role] = value
                    with self.assertRaises(ModelValidationError):
                        validate_filenames(names)

    def test_exact_role_set_and_detached_result(self):
        names = self.names()
        result = validate_filenames(names)
        names["wav"] = "bad"
        self.assertEqual(result["wav"], "chunk-000001.wav")
        for invalid in ({}, {**self.names(), "extra": "notes.json"}, {key: value for key, value in self.names().items() if key != "binding"}, []):
            with self.assertRaises(ModelValidationError):
                validate_filenames(invalid)

    def test_read_schema_matches_transport_contract(self):
        schema = json.loads((ROOT / "contracts/v1/companion-read.schema.json").read_text())
        absent, retained = schema["oneOf"]
        self.assertEqual(absent["properties"]["schema_version"]["const"], COMPANION_SCHEMA_VERSION)
        self.assertEqual(set(absent["required"]), {"schema_version", "state", "recording_id"})
        self.assertFalse(absent["additionalProperties"])
        self.assertFalse(retained["additionalProperties"])
        self.assertEqual(retained["properties"]["binding"]["type"], "object")
        self.assertEqual(retained["properties"]["validation"]["type"], "object")
        roles = retained["properties"]["documents"]["prefixItems"]
        self.assertEqual(tuple(item["allOf"][1]["properties"]["role"]["const"] for item in roles), DOCUMENT_ROLES)
        self.assertEqual(tuple(item["allOf"][1]["properties"]["bytes"]["maximum"] for item in roles), tuple(PART_LIMITS[role] for role in DOCUMENT_ROLES))

    def test_typescript_limits_match_python_without_a_second_scientific_schema(self):
        source = (ROOT / "libs/proto-ts/src/companion-v1.ts").read_text()
        self.assertIn(f'COMPANION_SCHEMA_VERSION = "{COMPANION_SCHEMA_VERSION}"', source)
        constants = re.search(r"COMPANION_PART_LIMITS:[^=]+?=\s*\{(.*?)\};", source, re.S)
        self.assertIsNotNone(constants)
        actual = {name: int(value) for name, value in re.findall(r"(\w+)\s*:\s*(\d+)", constants.group(1))}
        self.assertEqual(actual, dict(PART_LIMITS))
        for name, expected in (("COMPANION_MAX_BYTES", MAX_COMPANION_BYTES), ("COMPANION_MAX_REQUEST_BYTES", MAX_REQUEST_BYTES), ("COMPANION_MAX_ADMISSIONS", MAX_ADMISSIONS), ("COMPANION_MAX_QUEUE_SLOTS", MAX_QUEUE_SLOTS), ("COMPANION_MAX_RETAINED_BYTES", MAX_RETAINED_COMPANION_BYTES)):
            self.assertIn(f"{name} = {expected};", source)


if __name__ == "__main__":
    unittest.main()
