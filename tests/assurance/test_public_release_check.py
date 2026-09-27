"""Behavioral checks for the public release boundary."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/assurance"))
from public_release_check import REQUIRED, scan, vendor_artifact  # noqa: E402


class PublicReleaseCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in REQUIRED:
            (self.root / name).write_text("public\n", encoding="utf-8")

    def test_personal_paths_mail_and_agent_prose_have_locations_without_values(self) -> None:
        doc = self.root / "docs/report.md"
        doc.parent.mkdir()
        doc.write_text("safe\nowner /" + "Users/person/project\ncontact someone@" + "gmail.com\n" + "Cl" + "aude wrote this\n")
        binary = self.root / "files/image.bin"
        binary.parent.mkdir()
        binary.write_bytes(b"\0/" + b"home/person/secret\0")
        findings, _ = scan(self.root, ["docs/report.md", "files/image.bin"], {})
        self.assertEqual(findings, [
            "docs/report.md:2: home-path", "docs/report.md:3: gmail",
            "docs/report.md:4: agent-name", "files/image.bin:1: home-path",
        ])
        self.assertNotIn("person", "\n".join(findings))

    def test_no_prose_filter_on_machine_configuration(self) -> None:
        config = self.root / "config.json"
        config.write_text('{"model": "Cl' + 'aude"}')
        findings, _ = scan(self.root, ["config.json"], {})
        self.assertEqual(findings, [])

    def test_guest_account_exception_does_not_allow_other_home_paths(self) -> None:
        name = "scripts/assurance/linux_python_env/runner.py"
        path = self.root / name
        path.parent.mkdir(parents=True)
        path.write_text('guest = "/' + 'home/builder/python-source-run"\nother = "/' + 'home/builder2/secrets"\n')
        findings, allowed = scan(self.root, [name], {})
        self.assertEqual(findings, [f"{name}:2: home-path"])
        self.assertEqual(len(allowed), 1)
        self.assertIn("fixed isolated vm", allowed[0].lower())

    def test_supplier_inputs_not_first_party_generated_cad(self) -> None:
        self.assertTrue(vendor_artifact("hardware/boards/sources/source.step"))
        self.assertTrue(vendor_artifact("hardware/boards/sources/datasheet.pdf"))
        self.assertTrue(vendor_artifact("hardware/cad/vendor/part.zip"))
        self.assertFalse(vendor_artifact("hardware/cad/generated/assembly.step"))
        source = self.root / "hardware/boards/sources/datasheet.pdf"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"pdf")
        findings, _ = scan(self.root, ["hardware/boards/sources/datasheet.pdf"], {})
        self.assertEqual(findings, ["hardware/boards/sources/datasheet.pdf: vendor CAD/datasheet artifact"])

    def test_size_boundary_and_missing_required_file(self) -> None:
        (self.root / "NOTICE").unlink()
        huge = self.root / "data.bin"
        with huge.open("wb") as stream:
            stream.truncate(10 * 1024 * 1024 + 1)
        findings, _ = scan(self.root, ["data.bin"], {})
        self.assertEqual(findings, ["NOTICE: missing required regular file", "data.bin: exceeds 10 MiB (10485761 bytes)"])

    def test_exception_is_bound_to_exact_value_and_reason(self) -> None:
        doc = self.root / "docs/attribution.md"
        doc.parent.mkdir()
        doc.write_text("origin author@" + "gmail.com\nreplacement other@" + "gmail.com\n")
        digest = hashlib.sha256(b"author@" + b"gmail.com").hexdigest()
        findings, allowed = scan(self.root, ["docs/attribution.md"], {("docs/attribution.md", "gmail", digest): "Original attributed author"})
        self.assertEqual(findings, ["docs/attribution.md:2: gmail"])
        self.assertEqual(allowed, ["docs/attribution.md:1: allowed gmail (Original attributed author)"])
        findings, _ = scan(self.root, ["docs/attribution.md"], {("docs/attribution.md", "gmail", digest): ""})
        self.assertIn("docs/attribution.md:1: allowlist entry lacks a reason", findings)


if __name__ == "__main__":
    unittest.main()
