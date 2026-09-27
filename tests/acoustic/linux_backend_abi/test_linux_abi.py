"""Separate non-skipping Linux profile/build/layout gate; never opens capture.

Run only in the root-provisioned Linux ARM64 environment:
PT_NATIVE_PROFILE=/abs/profile.json PT_NATIVE_BUILD=/abs/build.json \
PYTHONPATH=<acoustic src>:<nereid src> python3 -m unittest discover -s <this directory> -v

Missing profile/platform/artifact fails, it is never a skipped Mac success.
"""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import unittest

from poseidon_acoustic import linux_capture as native

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "apps/acoustic/native/linux_capture"


class LinuxNoDeviceABITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "linux" or platform.machine() != "aarch64":
            raise RuntimeError("Linux ARM64 qualification gate required; no hardware-dependent skips")
        if "PT_NATIVE_PROFILE" not in os.environ or "PT_NATIVE_BUILD" not in os.environ:
            raise RuntimeError("explicit real native profile and build record required")
        spec = importlib.util.spec_from_file_location("pt_pinned_build", SOURCE / "build.py")
        build_tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_tool)
        cls.profile, cls.profile_hash = build_tool.load_profile(Path(os.environ["PT_NATIVE_PROFILE"]))
        cls.build = json.loads(Path(os.environ["PT_NATIVE_BUILD"]).read_bytes())
        if cls.build["schema"] != "poseidon.linux-capture-build.v1" or cls.build["profile_sha256"] != cls.profile_hash:
            raise RuntimeError("native build/profile identity mismatch")
        for name in build_tool.SOURCE_NAMES:
            if hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() != cls.build["sources"][name]:
                raise RuntimeError("native source changed after pinned build")
        artifact = Path(cls.build["artifact"])
        if not artifact.is_absolute() or hashlib.sha256(artifact.read_bytes()).hexdigest() != cls.build["artifact_sha256"]:
            raise RuntimeError("production artifact hash mismatch")
        # Only pure ABI identity/layout functions are called. No open/start/poll/close.
        cls.library = ctypes.CDLL(str(artifact), mode=os.RTLD_LOCAL | os.RTLD_NOW)
        cls.api = native._NativeAPI(cls.library, build_sha256=cls.build["build_sha256"], profile_sha256=cls.profile_hash)

    def test_production_artifact_identity(self):
        self.assertFalse(self.api.synthetic)
        self.assertEqual(self.api.identity["kind"], native.PRODUCTION_LINUX)
        self.assertEqual(self.api.identity["pointer_bits"], 64)

    def test_every_record_size_and_field_offset(self):
        for index, record in enumerate(native.RECORDS, 1):
            self.assertEqual(self.library.pt_capture_size(index), ctypes.sizeof(record))
            for field_index, (name, _) in enumerate(record._fields_):
                self.assertEqual(self.library.pt_capture_offset(index, field_index), getattr(record, name).offset)

    def test_public_symbols_have_exact_ctypes_signatures(self):
        self.assertEqual(len(self.library.pt_alsa_poll_copy.argtypes), 7)
        self.assertEqual(len(self.library.pt_v4l2_poll_copy.argtypes), 7)
        self.assertIs(self.library.pt_alsa_open.restype, ctypes.c_int32)
        self.assertIs(self.library.pt_v4l2_open.restype, ctypes.c_int32)

    def test_invalid_layout_queries_are_bounded(self):
        self.assertEqual(self.library.pt_capture_size(0), 0)
        self.assertEqual(self.library.pt_capture_size(2**32-1), 0)
        self.assertEqual(self.library.pt_capture_offset(0, 0), 2**32-1)
        self.assertEqual(self.library.pt_capture_offset(1, 2**32-1), 2**32-1)


if __name__ == "__main__":
    unittest.main()
