"""Offline synthetic lock/metadata tests plus the actual repository stale gate."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("poseidon_software_inventory", ROOT / "scripts/assurance/software_inventory.py")
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def uv_package(name="example-lib", version="1.2.3", source='registry = "https://pypi.org/simple"'):
    return f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {{ {source} }}\n'


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="poseidon-inventory-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "apps/example"
        self.app.mkdir(parents=True)
        self.lock = self.app / "uv.lock"
        self.lock.write_text("version = 1\n" + uv_package())
        self.out = self.root / inventory.OUTPUT
        self.out.mkdir(parents=True)
        shutil.copytree(ROOT / inventory.OUTPUT / "schema", self.out / "schema")
        # copytree keeps the source mode. On a read-only frozen tree (Linux VM
        # verification, run lp3-stage1-005) the copies were unwritable for the
        # tamper tests; the synthetic copy is always ours to edit.
        for copied in (self.out / "schema").rglob("*"):
            if copied.is_file():
                copied.chmod(copied.stat().st_mode | stat.S_IWUSR)

    def snapshot(self, external=None):
        inputs, manifests = inventory.discover(self.root)
        components = inventory.locked_components(self.root, inputs)
        return inventory.capture_metadata(self.root, inputs, manifests, components, external)

    def write_metadata(self, name="example-lib", version="1.2.3", license_text="License-Expression: MIT\n"):
        path = self.root / ".venv/lib/python3.12/site-packages/example_lib-1.2.3.dist-info/METADATA"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n{license_text}\nSynthetic package description.\n")
        return path

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = inventory.main(["--root", str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def test_deterministic_generation_schema_and_check(self):
        self.write_metadata()
        self.assertEqual(self.cli("--refresh-metadata")[0], 0)
        first = {p.name: p.read_bytes() for p in self.out.glob("*.json")}
        self.assertEqual(self.cli()[0], 0)
        second = {p.name: p.read_bytes() for p in self.out.glob("*.json")}
        self.assertEqual(first, second)
        self.assertEqual(self.cli("--check", "--check-local-metadata")[0], 0)
        bom = json.loads(first["sbom.cdx.json"])
        inventory.validate_bom(bom, self.out / "schema")
        self.assertEqual((bom["bomFormat"], bom["specVersion"]), ("CycloneDX", "1.5"))
        self.assertNotIn("serialNumber", bom)
        self.assertNotIn("timestamp", bom["metadata"])

    def test_root_manifest_refresh_keeps_frozen_metadata_and_rejects_other_drift(self):
        self.write_metadata()
        root_manifest = self.root / "pyproject.toml"
        root_manifest.write_text('[project]\nname = "workspace"\nversion = "0.0.0"\ndescription = "before"\n')
        self.assertEqual(self.cli("--refresh-metadata")[0], 0)
        original = json.loads((self.out / "metadata-snapshot.json").read_text())
        root_manifest.write_text(root_manifest.read_text().replace("before", "after"))
        self.assertEqual(self.cli("--check")[0], 1)
        code, _, err = self.cli("--refresh-metadata", "--only", "pyproject.toml")
        self.assertEqual(code, 0, err)
        refreshed = json.loads((self.out / "metadata-snapshot.json").read_text())
        self.assertEqual({k: v for k, v in refreshed.items() if k != "manifests"},
                         {k: v for k, v in original.items() if k != "manifests"})
        self.assertEqual(self.cli("--check")[0], 0)
        self.lock.write_bytes(self.lock.read_bytes() + b"\n")
        self.assertEqual(self.cli("--refresh-metadata", "--only", "pyproject.toml")[0], 1)

    def test_whitespace_lock_change_fails_without_regeneration(self):
        self.assertEqual(self.cli("--refresh-metadata")[0], 0)
        self.lock.write_bytes(self.lock.read_bytes() + b"\n")
        code, _, err = self.cli("--check")
        self.assertEqual(code, 1)
        self.assertIn("snapshot is stale", err)

    def test_new_and_deleted_locks_change_gate(self):
        self.assertEqual(self.cli("--refresh-metadata")[0], 0)
        other = self.root / "apps/new/uv.lock"
        other.parent.mkdir()
        other.write_bytes(self.lock.read_bytes())
        self.assertEqual(self.cli("--check")[0], 1)
        other.unlink()
        self.lock.unlink()
        self.assertEqual(self.cli("--check")[0], 1)

    def test_tampered_generated_output_fails(self):
        self.assertEqual(self.cli("--refresh-metadata")[0], 0)
        (self.out / "sbom.cdx.json").write_text("{}")
        self.assertEqual(self.cli("--check")[0], 1)

    def test_name_version_exact_match_and_unresolved_license(self):
        self.write_metadata(version="1.2.4")
        snapshot = self.snapshot()
        self.assertEqual(snapshot["components"][0]["status"], "unresolved-no-matching-installed-metadata")
        bom, result = inventory.generate(self.root, snapshot)
        self.assertNotIn("licenses", bom["components"][0])
        self.assertEqual(result["counts"]["components"], 1)
        self.write_metadata(name="Example_Lib", license_text="License: Custom synthetic terms, not an SPDX ID\n")
        bom, _ = inventory.generate(self.root, self.snapshot())
        self.assertEqual(bom["components"][0]["licenses"], [{"license": {"name": "Custom synthetic terms, not an SPDX ID"}}])

    def test_absent_declaration_distinct_from_absent_metadata(self):
        self.write_metadata(license_text="License: UNKNOWN\n")
        snapshot = self.snapshot()
        self.assertEqual(snapshot["components"][0]["status"], "absent-declaration")
        self.assertTrue(snapshot["components"][0]["metadata"])

    def test_metadata_hash_and_offline_snapshot_portability(self):
        path = self.write_metadata()
        snapshot = self.snapshot()
        self.assertEqual(snapshot["components"][0]["metadata"][0]["sha256"], inventory.digest(path.read_bytes()))
        self.assertEqual(self.cli("--refresh-metadata")[0], 0)
        path.unlink()
        self.assertEqual(self.cli("--check")[0], 0)
        self.assertEqual(self.cli("--check", "--check-local-metadata")[0], 1)

    def test_scoped_refresh_preserves_retired_sources_and_replaces_only_site_metadata(self):
        site = self.root / "apps/site"
        site.mkdir()
        lock = site / "bun.lock"
        lock.write_text(json.dumps({"lockfileVersion": 1, "packages": {
            "shared": ["shared@1.0.0", "", {}, ""], "old": ["old@1.0.0", "", {}, ""]}}))
        other = self.root / "apps/other"
        other.mkdir()
        (other / "bun.lock").write_text(json.dumps({"lockfileVersion": 1, "packages": {
            "shared": ["shared@1.0.0", "", {}, ""]}}))
        site_shared = site / "node_modules/shared/package.json"
        site_shared.parent.mkdir(parents=True)
        site_shared.write_text(json.dumps({"name": "shared", "version": "1.0.0", "license": "MIT"}))
        other_shared = other / "node_modules/shared/package.json"
        other_shared.parent.mkdir(parents=True)
        other_shared.write_text(json.dumps({"name": "shared", "version": "1.0.0", "license": "Apache-2.0"}))
        retired = self.root / "external/platforms/tool"
        retired.mkdir(parents=True)
        (retired / "platform.json").write_text(json.dumps({"name": "tool", "version": "1.0.0", "license": "BSD-3-Clause"}))
        fw = self.root / "firmware/reference"
        fw.mkdir(parents=True)
        (fw / "platformio.ini").write_text("[env]\nplatform = tool@1.0.0\n")
        self.assertEqual(self.cli("--refresh-metadata", "--metadata-source", f"firmware-platformio={retired.parent.parent}")[0], 0)
        before = json.loads((self.out / "metadata-snapshot.json").read_bytes())
        shutil.rmtree(retired.parent.parent)
        lock.write_text(json.dumps({"lockfileVersion": 1, "packages": {
            "shared": ["shared@1.0.0", "", {}, ""], "new": ["new@2.0.0", "", {}, ""]}}))
        site_shared.write_text(json.dumps({"name": "shared", "version": "1.0.0", "license": "ISC"}))
        new = site / "node_modules/new/package.json"
        new.parent.mkdir()
        new.write_text(json.dumps({"name": "new", "version": "2.0.0", "license": "MIT"}))
        self.assertEqual(self.cli("--check")[0], 1)
        code, _, err = self.cli("--refresh-metadata", "--only", "apps/site")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.cli("--check")[0], 0)
        after = json.loads((self.out / "metadata-snapshot.json").read_bytes())
        records = {r["bom-ref"]: r for r in after["components"]}
        self.assertEqual(set(records), {c["bom-ref"] for c in inventory.locked_components(self.root, inventory.discover(self.root)[0])})
        self.assertEqual(next(r for r in after["environments"] if r["path"] == "metadata-source:firmware-platformio"),
                         next(r for r in before["environments"] if r["path"] == "metadata-source:firmware-platformio"))
        self.assertEqual(next(r for r in after["components"] if any(m["ecosystem"] == "platformio" for m in r["metadata"])),
                         next(r for r in before["components"] if any(m["ecosystem"] == "platformio" for m in r["metadata"])))
        shared = next(r for r in records.values() if any(m["name"] == "shared" for m in r["metadata"]))
        self.assertEqual({m["declarations"][0]["value"] for m in shared["metadata"]}, {"Apache-2.0", "ISC"})
        self.assertEqual([m["path"] for m in shared["metadata"]],
                         ["apps/other/node_modules/shared/package.json", "apps/site/node_modules/shared/package.json"])
        self.assertFalse(any(any(m["name"] == "old" for m in r["metadata"]) for r in records.values()))
        self.assertTrue(any(any(m["name"] == "new" for m in r["metadata"]) for r in records.values()))

    def test_scoped_refresh_rejects_changes_outside_scope_and_missing_install(self):
        site = self.root / "apps/site"
        site.mkdir()
        lock = site / "bun.lock"
        lock.write_text(json.dumps({"lockfileVersion": 1, "packages": {"x": ["x@1.0.0", "", {}, ""]}}))
        metadata = site / "node_modules/x/package.json"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({"name": "x", "version": "1.0.0", "license": "MIT"}))
        self.assertEqual(self.cli("--refresh-metadata")[0], 0)
        original = {p.name: p.read_bytes() for p in self.out.glob("*.json")}
        self.lock.write_bytes(self.lock.read_bytes() + b"\n")
        code, _, err = self.cli("--refresh-metadata", "--only", "apps/site")
        self.assertEqual(code, 1)
        self.assertIn("outside apps/site changed", err)
        self.lock.write_bytes(self.lock.read_bytes()[:-1])
        shutil.rmtree(site / "node_modules")
        code, _, err = self.cli("--refresh-metadata", "--only", "apps/site")
        self.assertEqual(code, 1)
        self.assertIn("unavailable", err)
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.out.glob("*.json")})

    def test_deduplicate_same_registry_but_preserve_versions_sources_and_local_namespaces(self):
        self.lock.write_text("version = 1\n" + uv_package() + uv_package(version="2.0.0") + uv_package(name="local-app", version="0.1.0", source='virtual = "."'))
        other = self.root / "apps/other/uv.lock"
        other.parent.mkdir()
        other.write_text("version = 1\n" + uv_package() + uv_package(source='registry = "https://example.invalid/simple"') + uv_package(name="local-app", version="0.1.0", source='virtual = "."'))
        inputs, _ = inventory.discover(self.root)
        records = inventory.locked_components(self.root, inputs)
        self.assertEqual(len(records), 5)
        self.assertEqual(sorted(len(r["occurrences"]) for r in records), [1, 1, 1, 1, 2])
        self.assertEqual(len({r["bom-ref"] for r in records}), 5)

    def test_bun_scoped_nested_and_optional_records_not_host_filtered(self):
        (self.app / "bun.lock").write_text('''{
          // Synthetic text lock with a URL/string comma that must survive.
          "lockfileVersion": 1,
          "packages": {
            "@scope/example": ["@scope/example@1.0.0", "", {"os": "linux", "note": "https://example.invalid/,}"}, "sha512-synthetic"],
            "other/@scope/example": ["@scope/example@2.0.0", "", {}, "sha512-synthetic-other"],
          },
        }''')
        bom, result = inventory.generate(self.root, self.snapshot())
        npm = [c for c in bom["components"] if c.get("purl", "").startswith("pkg:npm/")]
        self.assertEqual(len(npm), 2)
        self.assertEqual(npm[0]["name"], "@scope/example")
        self.assertTrue(all(c["purl"].startswith("pkg:npm/%40scope/example@") for c in npm))
        raw = [c for c in result["components"] if c["ecosystem"] == "npm" and c["version"] == "1.0.0"][0]
        self.assertEqual(raw["occurrences"][0]["locked_details"]["os"], "linux")
        self.assertEqual(raw["occurrences"][0]["locked_details"]["note"], "https://example.invalid/,}")

    def test_firmware_constraints_preserve_crypto_versions_and_pin_gaps(self):
        fw = self.root / "firmware/toolchain"
        fw.mkdir(parents=True)
        (fw / "idf-python-constraints.txt").write_text("cryptography==41.0.7\n")
        (fw / "uv.lock").write_text("version = 1\n" + uv_package("cryptography", "46.0.3"))
        (fw / "platformio.ini").write_text("[env]\nplatform = espressif32@6.9.0\nplatform_packages =\n platformio/framework-espidf@3.50301.0\n")
        _, result = inventory.generate(self.root, self.snapshot())
        self.assertEqual({c["version"] for c in result["components"] if c["name"] == "cryptography"}, {"41.0.7", "46.0.3"})
        self.assertEqual(len([c for c in result["components"] if c["ecosystem"] == "platformio"]), 2)
        self.assertIn("not a complete transitive firmware lock", " ".join(result["coverage"]["gaps"]))

    def test_host_selected_ninja_records_both_exact_versions_and_rejects_other_variables(self):
        selector = "ESP_NINJA_VERSION := $(if $(filter Darwin,$(shell uname -s)),1.13.2,1.7.1)\n"
        makefile = self.root / "Makefile"
        recipes = (
            'compile-esp: prepare-verification\n'
            '\t@set -eu; \\\n'
            '\t\tPOSEIDON_NINJA_VERSION="$(ESP_NINJA_VERSION)" \\\n'
            '\t\ttrue\n'
            'compile-esp-monitor: prepare-verification\n'
            '\t@set -eu; \\\n'
            '\t\tPOSEIDON_NINJA_VERSION="$(ESP_NINJA_VERSION)" \\\n'
            '\t\ttrue\n'
        )
        makefile.write_text(selector + recipes)
        for project in ("reference", "monitor-target"):
            config = self.root / f"firmware/{project}/platformio.ini"
            config.parent.mkdir(parents=True)
            config.write_text(
                "[env]\nplatform = espressif32@6.9.0\nplatform_packages =\n"
                " platformio/tool-ninja@${sysenv.POSEIDON_NINJA_VERSION}\n"
                " platformio/tool-cmake@3.16.4\n"
            )
        inputs, _ = inventory.discover(self.root)
        pin_bytes = inventory.esp_ninja_pin_bytes(makefile)
        self.assertIn({"path": "Makefile", "kind": "platformio-host-pins",
                       "sha256": inventory.digest(pin_bytes), "bytes": len(pin_bytes)}, inputs)
        records = inventory.locked_components(self.root, inputs)
        ninja = [record for record in records if record["ecosystem"] == "platformio" and record["name"] == "tool-ninja"]
        self.assertEqual({record["version"] for record in ninja}, {"1.13.2", "1.7.1"})
        self.assertEqual({record["version"]: {o["locked_details"]["system"] for o in record["occurrences"]}
                          for record in ninja}, {"1.13.2": {"darwin"}, "1.7.1": {"linux_x86_64"}})
        self.assertTrue(all(len(record["occurrences"]) == 2 for record in ninja))
        self.assertEqual(self.cli("--refresh-metadata")[0], 0)
        makefile.write_text(selector + recipes + "# unrelated target\n")
        self.assertEqual(self.cli("--check")[0], 0)
        makefile.write_text(selector.replace("1.7.1", "1.7.2") + recipes)
        self.assertEqual(self.cli("--check")[0], 1)
        makefile.write_text("ESP_NINJA_VERSION := 1.13.2\n" + recipes)
        with self.assertRaisesRegex(ValueError, "exact ESP_NINJA_VERSION pair"):
            self.snapshot()
        makefile.write_text(selector + recipes.replace('POSEIDON_NINJA_VERSION="$(ESP_NINJA_VERSION)"',
                                                      'POSEIDON_NINJA_VERSION="1.13.2"', 1))
        with self.assertRaisesRegex(ValueError, "changed compile-esp Ninja export"):
            self.snapshot()
        makefile.write_text(selector + recipes)
        config = self.root / "firmware/reference/platformio.ini"
        config.write_text(config.read_text().replace("tool-cmake@3.16.4", "tool-cmake@${sysenv.POSEIDON_NINJA_VERSION}"))
        with self.assertRaisesRegex(ValueError, "unpinned PlatformIO dependency"):
            self.snapshot()

    def test_external_platformio_metadata_exact_name_and_version(self):
        fw = self.root / "firmware/toolchain"
        fw.mkdir(parents=True)
        (fw / "platformio.ini").write_text("[env]\nplatform = espressif32@6.9.0\n")
        external = self.root / "owned-external/platforms/espressif32"
        external.mkdir(parents=True)
        path = external / "platform.json"
        path.write_text(json.dumps({"name": "espressif32", "version": "6.9.0", "license": "Declared synthetic terms"}))
        snapshot = self.snapshot({"firmware-platformio": self.root / "owned-external"})
        _, result = inventory.generate(self.root, snapshot)
        component = next(c for c in result["components"] if c["ecosystem"] == "platformio")
        self.assertEqual(component["status"], "declared")
        self.assertEqual(component["metadata"][0]["path"], "metadata-source:firmware-platformio/platforms/espressif32/platform.json")
        path.write_text(json.dumps({"name": "espressif32", "version": "9.9.9", "license": "Wrong version"}))
        snapshot = self.snapshot({"firmware-platformio": self.root / "owned-external"})
        self.assertTrue(any(c["status"] == "unresolved-no-matching-installed-metadata" for c in snapshot["components"]))

    def test_unlocked_environment_manifest_recorded_and_hashed(self):
        manifest = self.root / "apps/unlocked/pyproject.toml"
        manifest.parent.mkdir()
        manifest.write_text('[project]\nname="synthetic"\nversion="0.1.0"\n')
        snapshot = self.snapshot()
        self.assertIsNone(snapshot["manifests"][0]["adjacent_lock"])
        self.assertFalse(next(e for e in snapshot["environments"] if e["path"] == "apps/unlocked/.venv")["present"])
        manifest.write_text(manifest.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            inventory.generate(self.root, snapshot)

    def test_unknown_locks_unpinned_firmware_and_bun_fail_closed(self):
        (self.app / "Cargo.lock").write_text("version = 3\n")
        with self.assertRaisesRegex(ValueError, "unsupported dependency lock"):
            inventory.discover(self.root)
        (self.app / "Cargo.lock").unlink()
        (self.app / "bun.lock").write_text(json.dumps({"lockfileVersion": 1, "packages": {"example": ["example@^1.0.0", "", {}, ""]}}))
        with self.assertRaisesRegex(ValueError, "unpinned"):
            self.snapshot()
        (self.app / "bun.lock").unlink()
        fw = self.root / "firmware/toolchain"
        fw.mkdir(parents=True)
        (fw / "platformio.ini").write_text("[env]\nplatform = espressif32@^6.9.0\n")
        with self.assertRaisesRegex(ValueError, "unpinned"):
            self.snapshot()

    def test_official_schema_rejects_wrong_structure(self):
        bom, _ = inventory.generate(self.root, self.snapshot())
        variants = []
        bad = copy.deepcopy(bom); bad["specVersion"] = "1.4"; variants.append(bad)
        bad = copy.deepcopy(bom); bad["components"][0]["type"] = "made-up"; variants.append(bad)
        bad = copy.deepcopy(bom); bad["components"][0]["bogus"] = "field"; variants.append(bad)
        bad = copy.deepcopy(bom); del bad["components"][0]["name"]; variants.append(bad)
        bad = copy.deepcopy(bom); bad["components"][0]["licenses"] = ["MIT"]; variants.append(bad)
        bad = copy.deepcopy(bom); bad["components"][0]["licenses"] = [{"license": {"id": "not-an-SPDX-license"}}]; variants.append(bad)
        bad = copy.deepcopy(bom); bad["components"].append(copy.deepcopy(bad["components"][0])); variants.append(bad)
        for index, variant in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                inventory.validate_bom(variant, self.out / "schema")

    def test_applicable_unsupported_schema_keyword_fails_closed(self):
        bom, _ = inventory.generate(self.root, self.snapshot())
        path = self.out / "schema/bom-1.5.schema.json"
        schema = json.loads(path.read_bytes())
        schema["definitions"]["metadata"]["minProperties"] = 1
        path.write_bytes(inventory.encoded(schema))
        hashes = inventory.SCHEMA_HASHES | {"bom-1.5.schema.json": inventory.digest(path.read_bytes())}
        # Synthetic future schema fixture only, never modify the retained schema.
        with patch.object(inventory, "SCHEMA_HASHES", hashes):
            with self.assertRaisesRegex(ValueError, "unsupported schema keyword"):
                inventory.validate_bom(bom, self.out / "schema")

    def test_app_without_any_manifest_is_still_a_coverage_gap(self):
        (self.root / "apps/unlocked-code-only").mkdir()
        _, result = inventory.generate(self.root, self.snapshot())
        gap = next(d for d in result["coverage"]["software_directories"] if d["path"] == "apps/unlocked-code-only")
        self.assertEqual(gap["inventory_inputs"], [])
        self.assertIn("no-own-dependency-lock", gap["status"])

    def test_schema_hash_tamper_fails(self):
        bom, _ = inventory.generate(self.root, self.snapshot())
        schema = self.out / "schema/bom-1.5.schema.json"
        schema.write_bytes(schema.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "schema hash mismatch"):
            inventory.validate_bom(bom, self.out / "schema")

    def test_actual_repository_generated_files_are_current(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = inventory.main(["--root", str(ROOT), "--check"])
        self.assertEqual(code, 0, err.getvalue())


if __name__ == "__main__":
    unittest.main()
