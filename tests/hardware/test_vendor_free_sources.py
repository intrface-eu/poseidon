"""Purchased source bytes never enter the distributed hardware tree."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/hardware/fetch_vendor_sources.py"
spec = importlib.util.spec_from_file_location("vendor_fetch", MODULE)
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


class VendorSourceTests(unittest.TestCase):
    def test_source_directories_contain_only_original_records(self):
        for folder in ("hardware/cad/sources", "hardware/candidates/passive-v2/power/sources",
                       "hardware/candidates/passive-v2/sources", "hardware/candidates/passive-v3/sources"):
            for path in (ROOT / folder).glob("*"):
                self.assertNotIn(path.suffix.lower(), (".step", ".stp", ".zip", ".pdf", ".html", ".png", ".txt"), path)

    def test_private_fetch_rejects_corrupt_cached_bytes(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(fetch, "CACHE", Path(temp)):
            record = {"path": "passive-v3/example.step", "sha256": hashlib.sha256(b"original").hexdigest(),
                      "license_status": "supplier_redistribution_unverified"}
            file = fetch.safe_path(record["path"])
            file.parent.mkdir(parents=True)
            file.write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "Vendor cache hash mismatch"):
                fetch.verified_bytes(record, offline=True)
            file.write_bytes(b"original")
            self.assertEqual(fetch.verified_bytes(record, offline=True), b"original")


if __name__ == "__main__":
    unittest.main()
