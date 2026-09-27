"""No-device host gates. Portable C tests compile TEST-FAKE + real pure row code only."""
from __future__ import annotations

import ctypes as C
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from poseidon_acoustic import linux_capture as n
from poseidon_acoustic.live_models import BackendFault, CaptureLimitsV1, CapturePlanV1, SourcePlanV1, canonical

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "apps/acoustic/native/linux_capture"
BUILD, PROFILE = "a" * 64, "b" * 64


def limits():
    return CaptureLimitsV1(duration_s=2, chunk_frames=8, max_chunk_bytes=128,
                           queue_chunks=4, source_queue_bytes=512, queue_bytes=1024,
                           output_bytes=1_000_000, max_chunks=100, reserve_bytes=16384,
                           poll_timeout_s=0.1, shutdown_timeout_s=1)


def audio_source():
    return SourcePlanV1(source_id="fake-audio-test", kind="audio", backend="linux_alsa",
                        device_node="/dev/snd/pcmC123D45c", expected_identity_json=canonical({"pcm_id": "TEST-FAKE"}),
                        channels=("left", "right"), channel_roles=("test", "test"), sample_rate_hz=48000,
                        width=None, height=None, frame_rate_num=None, frame_rate_den=None, subdevice=0,
                        period_frames=4, period_frames_max=8, buffer_frames=16, buffer_frames_max=32,
                        mapped_buffers=None, mapped_bytes=None, provenance="bench")


def video_source():
    return SourcePlanV1(source_id="fake-video-test", kind="video", backend="linux_v4l2",
                        device_node="/dev/video123", expected_identity_json=canonical({"driver": "TEST", "card": "FAKE", "bus_info": "no-device"}),
                        channels=(), channel_roles=(), sample_rate_hz=None, width=2, height=2,
                        frame_rate_num=5, frame_rate_den=1, subdevice=None, period_frames=None,
                        period_frames_max=None, buffer_frames=None, buffer_frames_max=None,
                        mapped_buffers=2, mapped_bytes=64, provenance="bench")


def pointer(value, cls):
    return C.cast(value, C.POINTER(cls)).contents


class Function:
    def __init__(self, call):
        self.call = call
    def __call__(self, *args):
        return self.call(*args)


class Table:
    """Python function table, not a loaded native library and never live provenance."""
    def __init__(self):
        self.opens = self.closes = self.starts = self.reads = 0
        self.kind = n.TEST_FAKE
        self.scenario = "short"
        self.record_mutator = lambda r: None
        self.actual_mutator = lambda a: None
        self.pt_capture_abi_version = Function(lambda: 1)
        self.pt_capture_size = Function(lambda i: C.sizeof(n.RECORDS[i-1]))
        self.pt_capture_offset = Function(lambda i, j: getattr(n.RECORDS[i-1], n.RECORDS[i-1]._fields_[j][0]).offset if j < len(n.RECORDS[i-1]._fields_) else 2**32-1)
        self.pt_capture_identity = Function(self.identity)
        self.pt_copy_yuyv = Function(lambda *args: n.FAULT)
        for prefix in ("alsa", "v4l2"):
            setattr(self, f"pt_{prefix}_open", Function(self.open))
            setattr(self, f"pt_{prefix}_start", Function(self.start))
            setattr(self, f"pt_{prefix}_poll_copy", Function(self.read))
            setattr(self, f"pt_{prefix}_stop_close", Function(self.close))

    def identity(self, out):
        i = pointer(out, n.Identity)
        i.abi_version, i.struct_size, i.kind, i.pointer_bits = 1, C.sizeof(i), self.kind, C.sizeof(C.c_void_p)*8
        i.build_sha256, i.profile_sha256 = BUILD.encode(), PROFILE.encode()
        return n.OK

    def open(self, config, out, actual, error):
        self.opens += 1
        pointer(out, C.c_void_p).value = 123
        c, a = pointer(config, n.AudioConfig), pointer(actual, n.AudioActual)
        a.abi_version, a.struct_size = 1, C.sizeof(a)
        a.channels, a.rate = c.channels, c.rate
        a.period_frames, a.buffer_frames, a.poll_descriptors = c.period_frames, c.buffer_frames, 2
        a.format_s16_le, a.pcm_id = 1, c.expected_pcm_id
        self.actual_mutator(a)
        if self.scenario == "open_fault":
            e = pointer(error, n.Error)
            e.domain, e.code = 2, -19
            return n.FAULT
        return n.OK

    def start(self, handle, error):
        self.starts += 1
        if self.scenario == "start_fault":
            e = pointer(error, n.Error)
            e.domain, e.code = 2, -32
            return n.FAULT
        return n.OK

    def read(self, handle, dst, cap, cancel, timeout, record, error):
        self.reads += 1
        r, e = pointer(record, n.AudioRecord), pointer(error, n.Error)
        if self.scenario == "again":
            return n.AGAIN
        if self.scenario == "cancel":
            return n.CANCELLED
        if self.scenario in ("xrun", "suspend", "disconnect", "bad_sign"):
            e.domain = 2
            e.code = {"xrun": -32, "suspend": -86, "disconnect": -19, "bad_sign": 32}[self.scenario]
            return n.FAULT
        r.frames, r.bytes = 2, 8
        for index in range(r.bytes):
            dst[index] = self.reads
        self.record_mutator(r)
        return n.OK

    def close(self, handle, error):
        self.closes += 1
        return n.OK


def api(table, test_only=True):
    return n._NativeAPI(table, build_sha256=BUILD, profile_sha256=PROFILE, test_only=test_only)


def backend(table, source=None, expiry=None):
    source = source or audio_source()
    return n._NativeBackend(api(table), source, limits(), n._source_config(source, limits()),
                            time.monotonic()+60 if expiry is None else expiry)


class FunctionTableTests(unittest.TestCase):
    def setUp(self):
        self.table = Table()

    def running(self):
        b = backend(self.table)
        self.addCleanup(b.close)
        b.configure()
        b.start()
        return b

    def test_all_exact_signatures(self):
        api(self.table)
        self.assertEqual(self.table.pt_alsa_open.argtypes, [C.POINTER(n.AudioConfig), C.POINTER(C.c_void_p), C.POINTER(n.AudioActual), C.POINTER(n.Error)])
        self.assertIs(self.table.pt_alsa_poll_copy.restype, C.c_int32)
        self.assertIs(self.table.pt_v4l2_poll_copy.argtypes[3], C.c_int32)
        for name in vars(self.table):
            if name.startswith("pt_"):
                self.assertTrue(hasattr(getattr(self.table, name), "argtypes"), name)

    def test_test_fake_cannot_be_live_artifact(self):
        with self.assertRaisesRegex(BackendFault, "test_artifact_not_live"):
            api(self.table, False)
        self.assertEqual(self.table.opens, 0)

    def test_production_artifact_cannot_enter_test_provider(self):
        self.table.kind = n.PRODUCTION_LINUX
        with self.assertRaisesRegex(BackendFault, "test_artifact_required"):
            api(self.table)

    def test_bad_abi_size_and_offsets(self):
        for name in ("pt_capture_size", "pt_capture_offset", "pt_capture_abi_version"):
            with self.subTest(name=name):
                t = Table()
                setattr(t, name, Function(lambda *args: 999))
                with self.assertRaises(BackendFault):
                    api(t)
                self.assertEqual(t.opens, 0)

    def test_bad_build_identity(self):
        with self.assertRaisesRegex(BackendFault, "native_build_profile_mismatch"):
            n._NativeAPI(self.table, build_sha256="c"*64, profile_sha256=PROFILE, test_only=True)

    def test_guard_before_all_artifact_io_and_load(self):
        source = audio_source()
        plan = CapturePlanV1("denied-native", (source,), limits(), "TEST-only-not-permission", "test")
        factory = n.LinuxBackendFactory(plan, artifact_path="/not-a-device/fake.so", artifact_sha256=BUILD, build_sha256=BUILD, profile_sha256=PROFILE)
        with patch.object(n.C, "CDLL") as load, patch.object(n.os, "open") as open_, patch.object(n.os, "stat") as stat_:
            with self.assertRaises(Exception):
                factory.open(source, plan.limits, None)
            load.assert_not_called()
            open_.assert_not_called()
            stat_.assert_not_called()

    def test_unsupported_host_after_gate_still_no_artifact_io(self):
        source = audio_source()
        plan = CapturePlanV1("denied-platform", (source,), limits(), "TEST-only", "test")
        factory = n.LinuxBackendFactory(plan, artifact_path="/not-a-device/fake.so", artifact_sha256=BUILD, build_sha256=BUILD, profile_sha256=PROFILE)
        with patch("poseidon_acoustic.live_gate.validate_worker_admission"), patch.object(n.sys, "platform", "darwin"), patch.object(n.os, "open") as open_, patch.object(n.C, "CDLL") as load:
            with self.assertRaisesRegex(BackendFault, "unsupported_linux_native_platform"):
                factory.open(source, plan.limits, object())
            open_.assert_not_called()
            load.assert_not_called()

    def test_artifact_wrong_file_type_uses_only_path_descriptor(self):
        source = audio_source()
        plan = CapturePlanV1("wrong-artifact", (source,), limits(), "TEST-only", "test")
        factory = n.LinuxBackendFactory(plan, artifact_path="/not-a-device/artifact", artifact_sha256=BUILD, build_sha256=BUILD, profile_sha256=PROFILE)
        from types import SimpleNamespace
        with patch("poseidon_acoustic.live_gate.validate_worker_admission"), patch.object(n.sys,"platform","linux"), patch.object(n.os,"O_PATH",0x200000,create=True), patch.object(n.os,"open",return_value=91) as open_, patch.object(n.os,"fstat",return_value=SimpleNamespace(st_mode=n.stat.S_IFCHR,st_size=0)), patch.object(n.os,"close") as close, patch.object(n.C,"CDLL") as load:
            with self.assertRaisesRegex(BackendFault,"native_artifact_file_bounds"):
                factory.open(source,plan.limits,object())
            self.assertEqual(open_.call_count,1)
            self.assertTrue(open_.call_args.args[1] & 0x200000)
            close.assert_called_once_with(91)
            load.assert_not_called()

    def test_native_config_is_numeric_and_no_default(self):
        c = n._source_config(audio_source(), limits())
        self.assertEqual((c.card, c.device, c.subdevice), (123, 45, 0))
        self.assertEqual((c.channels, c.rate, c.period_min, c.buffer_min), (2, 48000, 4, 16))
        with self.assertRaises(BackendFault):
            n._source_config(replace(audio_source(), expected_identity_json=canonical({"pcm_id": "\0injected"})), limits())

    def test_short_read_owned_bytes_and_unknown_timestamps(self):
        b = self.running()
        first = b.read(0.05)
        second = b.read(0.05)
        self.assertEqual((first.units, len(first.payload)), (2, 8))
        self.assertEqual(first.payload, b"\1"*8)
        self.assertEqual(second.payload, b"\2"*8)
        metadata = json.loads(first.raw_metadata_json)
        self.assertIsNone(metadata["status_htstamp"])
        self.assertIsNone(metadata["audio_accuracy_ns"])
        self.assertIsNone(metadata["physical_loss_units"])
        self.assertFalse(metadata["device_access_occurred"])
        self.assertTrue(metadata["synthetic"])

    def test_retry_returns_no_payload_and_keeps_handle(self):
        b = self.running()
        self.table.scenario = "again"
        self.assertIsNone(b.read(0.05))
        self.assertEqual(self.table.closes, 0)

    def test_negative_alsa_faults_stop_and_close_without_reopen(self):
        for scenario, code in (("xrun", -32), ("suspend", -86), ("disconnect", -19)):
            with self.subTest(scenario=scenario):
                t = Table()
                b = backend(t)
                b.configure(); b.start(); t.scenario = scenario
                with self.assertRaises(BackendFault) as caught:
                    b.read(0.05)
                self.assertEqual((caught.exception.domain, caught.exception.native_code), ("alsa", code))
                self.assertEqual((t.opens, t.closes), (1, 1))
                with self.assertRaises(BackendFault):
                    b.start()
                b.close()
                self.assertEqual(t.closes, 1)

    def test_wrong_error_sign_is_abi_fault(self):
        b = self.running(); self.table.scenario = "bad_sign"
        with self.assertRaisesRegex(BackendFault, "native_error_sign"):
            b.read(0.05)
        self.assertEqual(self.table.closes, 1)

    def test_cancellation_closes_owned_descriptors(self):
        b = self.running(); fds = b.pipe; self.table.scenario = "cancel"
        with self.assertRaisesRegex(BackendFault, "native_cancelled"):
            b.read(0.05)
        for fd in fds:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_partial_open_error_and_config_mismatch_close(self):
        self.table.scenario = "open_fault"
        with self.assertRaises(BackendFault):
            backend(self.table)
        self.assertEqual(self.table.closes, 1)
        t = Table(); t.actual_mutator = lambda a: setattr(a, "rate", 44100)
        with self.assertRaisesRegex(BackendFault, "alsa_returned_configuration"):
            backend(t)
        self.assertEqual(t.closes, 1)

    def test_start_error_closes(self):
        b = backend(self.table); b.configure(); self.table.scenario = "start_fault"
        with self.assertRaises(BackendFault):
            b.start()
        self.assertEqual(self.table.closes, 1)

    def test_expired_admission_never_starts(self):
        b = backend(self.table); b.configure(); b.expiry = time.monotonic()-1
        with self.assertRaisesRegex(BackendFault, "expired_before_start"):
            b.start()
        self.assertEqual((self.table.starts, self.table.closes), (0, 1))

    def test_expired_admission_never_opens_after_library_checks(self):
        with self.assertRaisesRegex(BackendFault, "expired_before_open"):
            backend(self.table, expiry=time.monotonic()-1)
        self.assertEqual((self.table.opens, self.table.closes), (0, 0))

    def test_zero_accuracy_report_is_not_unknown_or_uncertainty(self):
        def report(r):
            r.valid = n.VALID_AUDIO_STAMP | n.VALID_ACCURACY
            r.audio_report_valid = r.audio_accuracy_report = 1
            r.audio_actual_type = 1
        self.table.record_mutator = report
        b = self.running()
        m = json.loads(b.read(0.05).raw_metadata_json)
        self.assertEqual(m["audio_accuracy_ns"], 0)
        self.assertIsNone(m["physical_uncertainty_s"])
        self.assertEqual(m["audio_htstamp"], {"seconds": 0, "nanoseconds": 0})

    def test_invalid_record_lengths_validity_and_time_close(self):
        mutations = (("bytes", 129), ("frames", 9), ("valid", 2**31), ("audio_report_valid", 1), ("struct_size", 0))
        for key, value in mutations:
            with self.subTest(key=key):
                t = Table(); t.record_mutator = lambda r: setattr(r, key, value)
                b = backend(t); b.configure(); b.start()
                with self.assertRaises(BackendFault):
                    b.read(0.05)
                self.assertEqual(t.closes, 1)

    def test_timestamp_report_change_stops(self):
        b = self.running(); b.read(0.05)
        self.table.record_mutator = lambda r: setattr(r, "audio_actual_type", 1)
        with self.assertRaisesRegex(BackendFault, "timestamp_type_change"):
            b.read(0.05)

    def test_requires_configuration_and_poll_budget(self):
        b = backend(self.table); self.addCleanup(b.close)
        with self.assertRaisesRegex(BackendFault, "start_state"):
            b.start()
        b.configure(); b.start()
        for timeout in (0, -1, True, float("nan"), 0.2):
            with self.assertRaises(BackendFault):
                b.read(timeout)
        self.assertEqual(self.table.reads, 0)

    def test_build_refuses_missing_profile_without_compiler(self):
        spec = importlib.util.spec_from_file_location("capture_build_test", NATIVE / "build.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with patch.object(module.subprocess, "run") as run:
            self.assertEqual(module.main(["--native-profile", "/nonexistent/native-profile.json", "--output", "/unused/build"]), 2)
            run.assert_not_called()


class PortableCFakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This gate does not compile ALSA/V4L2 or include Linux headers.
        compiler = shutil.which("clang")
        if not compiler:
            raise RuntimeError("explicit host fake C gate requires existing clang; no skip/install")
        cls.temp = tempfile.TemporaryDirectory(prefix="poseidon-test-fake-abi-")
        cls.addClassCleanup(cls.temp.cleanup)
        target = Path(cls.temp.name) / ("TEST-FAKE.dylib" if sys.platform == "darwin" else "TEST-FAKE.so")
        command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fPIC",
                   "-dynamiclib" if sys.platform == "darwin" else "-shared", "-DPT_TEST_FAKE=1",
                   f'-DPT_BUILD_SHA256="{BUILD}"', f'-DPT_PROFILE_SHA256="{PROFILE}"',
                   "-I", str(NATIVE), str(NATIVE / "capture_common.c"),
                   str(Path(__file__).parent / "linux_backend_abi/fake_abi.c"), "-o", str(target)]
        subprocess.run(command, check=True, capture_output=True, timeout=30)
        cls.lib = C.CDLL(str(target))
        cls.lib.pt_test_scenario.argtypes = [C.c_uint32]; cls.lib.pt_test_scenario.restype = None
        for name in ("pt_test_opened", "pt_test_closed"):
            fn = getattr(cls.lib, name); fn.argtypes = []; fn.restype = C.c_uint32

    def setUp(self):
        self.lib.pt_test_scenario(0)

    def test_real_ctypes_layout_matches_compiled_portable_header(self):
        native = api(self.lib)
        self.assertTrue(native.synthetic)
        self.assertEqual(native.identity["kind"], n.TEST_FAKE)
        with self.assertRaisesRegex(BackendFault, "test_artifact_not_live"):
            api(self.lib, False)

    def test_compiled_short_read_and_error_domain(self):
        b = backend(self.lib); self.addCleanup(b.close); b.configure(); b.start()
        self.assertEqual(b.read(0.05).payload, b"\1"*8)
        self.lib.pt_test_scenario(2)
        with self.assertRaises(BackendFault) as caught:
            b.read(0.05)
        self.assertEqual((caught.exception.domain, caught.exception.native_code), ("alsa", -32))

    def test_compiled_video_preserves_chroma_after_fake_reuse(self):
        b = backend(self.lib, video_source()); self.addCleanup(b.close); b.configure(); b.start()
        first = b.read(0.05); b.read(0.05)
        self.assertEqual(first.payload, bytes(range(1, 9)))
        m = json.loads(first.raw_metadata_json)
        self.assertTrue(m["padding_removed"])
        self.assertEqual(m["original_stride"], 6)
        self.assertFalse(m["full_kernel_buffer_byte_identical"])
        self.assertFalse(m["device_access_occurred"])

    def test_binding_rejects_substituted_cadence_and_accepts_equal_rational(self):
        b = backend(self.lib, video_source()); self.addCleanup(b.close)
        b.actual.cadence_numerator *= 2; b.actual.cadence_denominator *= 2
        b._validate_actual()
        b.actual.cadence_denominator += 1
        with self.assertRaisesRegex(BackendFault,"v4l2_returned_configuration"):
            b._validate_actual()

    def test_compiled_video_sequence_gap_stops(self):
        b = backend(self.lib, video_source()); b.configure(); b.start(); b.read(0.05)
        self.lib.pt_test_scenario(12)
        with self.assertRaisesRegex(BackendFault, "video_layout_or_discontinuity"):
            b.read(0.05)
        self.assertTrue(b.closed)

    def test_production_common_row_arithmetic_refuses_overflow(self):
        api(self.lib)
        src, dst = (C.c_uint8*12)(*range(12)), (C.c_uint8*8)()
        written = C.c_uint32(99)
        call = self.lib.pt_copy_yuyv
        self.assertEqual(call(src, 12, 10, 2, 2, 6, dst, 8, C.byref(written)), n.OK)
        self.assertEqual(bytes(dst), bytes((0,1,2,3,6,7,8,9)))
        for mapped, used, width, height, stride, cap in ((12,9,2,2,6,8),(12,13,2,2,6,8),(12,12,3,2,6,8),(12,12,2,2,3,8),(12,12,2,2,6,7),(12,12,2**32-1,2**32-1,2**32-1,8)):
            self.assertEqual(call(src,mapped,used,width,height,stride,dst,cap,C.byref(written)), n.FAULT)
            self.assertEqual(written.value, 0)

    def test_compiled_partial_handle_is_closed_once(self):
        before = self.lib.pt_test_closed(); self.lib.pt_test_scenario(10)
        with self.assertRaises(BackendFault):
            backend(self.lib)
        self.assertEqual(self.lib.pt_test_closed(), before+1)


class InjectedNativeAlgorithmTests(unittest.TestCase):
    """Real ALSA/V4L2 C algorithms against Mac TEST-FAKE APIs, not Linux headers."""
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang")
        if not compiler:
            raise RuntimeError("explicit algorithm-fake gate requires existing clang")
        cls.temp = tempfile.TemporaryDirectory(prefix="poseidon-test-fake-algorithms-")
        cls.addClassCleanup(cls.temp.cleanup)
        fake_dir = Path(__file__).parent / "linux_backend_abi"
        target = Path(cls.temp.name) / ("TEST-FAKE-algorithms.dylib" if sys.platform == "darwin" else "TEST-FAKE-algorithms.so")
        command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fPIC",
                   "-dynamiclib" if sys.platform == "darwin" else "-shared", "-DPT_TEST_FAKE=1",
                   f'-DPT_BUILD_SHA256="{BUILD}"', f'-DPT_PROFILE_SHA256="{PROFILE}"',
                   "-I", str(NATIVE), "-I", str(fake_dir),
                   *(str(NATIVE / name) for name in ("capture_common.c", "alsa_capture.c", "v4l2_capture.c")),
                   str(fake_dir / "fake_system.c"), "-o", str(target)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError("TEST-FAKE algorithm compilation failed: " + result.stderr)
        cls.lib = C.CDLL(str(target))
        cls.lib.pt_test_reset.argtypes = [C.c_uint32]; cls.lib.pt_test_reset.restype = None
        cls.lib.pt_test_counter.argtypes = [C.c_uint32]; cls.lib.pt_test_counter.restype = C.c_uint32

    def setUp(self):
        self.lib.pt_test_reset(0)

    def running(self, source=None, mode=0):
        self.lib.pt_test_reset(mode)
        b = backend(self.lib, source)
        self.addCleanup(b.close)
        b.configure(); b.start()
        return b

    def test_actual_audio_uses_all_poll_descriptors_and_short_reads(self):
        b = self.running()
        block = b.read(0.05)
        self.assertEqual((block.units, block.payload), (2, b"\1"*8))
        metadata = json.loads(block.raw_metadata_json)
        self.assertEqual(metadata["state"], 3)
        self.assertEqual(metadata["available_frames"], 3)
        self.assertEqual(metadata["delay_frames"], 4)
        self.assertIsNone(metadata["trigger_htstamp"])
        self.assertEqual(metadata["status_htstamp"], {"seconds":1,"nanoseconds":2})
        self.assertGreater(self.lib.pt_test_counter(0), 0)

    def test_actual_audio_eagain_and_eintr_repoll_same_deadline(self):
        for mode in (1,39):
            b = self.running(mode=mode)
            self.assertEqual(b.read(0.05).payload, b"\2"*8)
            self.assertEqual(self.lib.pt_test_counter(0), 2)
            b.close()

    def test_actual_audio_faults_stop_and_cleanup(self):
        for mode, code in ((2,-32),(3,-86),(4,-19),(6,-32),(12,-32),(13,-22)):
            with self.subTest(mode=mode):
                b = self.running(mode=mode)
                with self.assertRaises(BackendFault) as caught:
                    b.read(0.05)
                self.assertEqual(caught.exception.domain, "alsa")
                # ESTRPIPE is explicitly fake 86; other errno values match this host.
                self.assertEqual(caught.exception.native_code, code)
                self.assertEqual((self.lib.pt_test_counter(6),self.lib.pt_test_counter(7)),(1,1))

    def test_actual_audio_negotiation_and_partial_start_cleanup(self):
        for mode in (8,10):
            self.lib.pt_test_reset(mode)
            with self.assertRaises(BackendFault):
                backend(self.lib)
            self.assertEqual(self.lib.pt_test_counter(6),1)
        self.lib.pt_test_reset(11)
        b = backend(self.lib); b.configure()
        with self.assertRaises(BackendFault):
            b.start()
        self.assertEqual(self.lib.pt_test_counter(6),1)

    def test_actual_audio_valid_zero_accuracy_remains_raw_claim(self):
        b = self.running(mode=7)
        metadata = json.loads(b.read(0.05).raw_metadata_json)
        self.assertEqual(metadata["audio_accuracy_ns"],0)
        self.assertEqual(metadata["audio_htstamp"],{"seconds":0,"nanoseconds":0})
        self.assertIsNone(metadata["physical_uncertainty_s"])

    def test_actual_video_copies_pixels_and_metadata_before_qbuf_reuse(self):
        b = self.running(video_source())
        block = b.read(0.05)
        self.assertEqual(block.payload,bytes(range(1,9)))
        metadata = json.loads(block.raw_metadata_json)
        self.assertEqual(metadata["original_bytesused"],12)
        self.assertTrue(metadata["padding_removed"])
        self.assertEqual(metadata["raw_timestamp"]["timestamp_domain"],"unknown")
        b.close()
        self.assertEqual((self.lib.pt_test_counter(1),self.lib.pt_test_counter(2),self.lib.pt_test_counter(3),self.lib.pt_test_counter(4),self.lib.pt_test_counter(5)),(1,2,2,1,1))

    def test_actual_video_partial_configuration_paths_release_all_maps(self):
        for mode in (21,22,23,24,33,34,35,36):
            with self.subTest(mode=mode):
                self.lib.pt_test_reset(mode)
                with self.assertRaises(BackendFault):
                    backend(self.lib,video_source())
                self.assertEqual(self.lib.pt_test_counter(1),1)
                self.assertEqual(self.lib.pt_test_counter(2),self.lib.pt_test_counter(3))
                if mode in (21,22,23,24,36):
                    self.assertEqual(self.lib.pt_test_counter(5),1)

    def test_actual_video_failed_streamon_attempts_streamoff_and_cleanup(self):
        self.lib.pt_test_reset(25)
        b = backend(self.lib,video_source()); b.configure()
        with self.assertRaises(BackendFault):
            b.start()
        self.assertEqual((self.lib.pt_test_counter(1),self.lib.pt_test_counter(3),self.lib.pt_test_counter(4),self.lib.pt_test_counter(5)),(1,2,1,1))

    def test_actual_video_bad_dq_metadata_never_requeues_invalid_buffer(self):
        for mode in (26,27,28,32):
            with self.subTest(mode=mode):
                b = self.running(video_source(),mode=mode)
                with self.assertRaises(BackendFault):
                    b.read(0.05)
                self.assertEqual(self.lib.pt_test_counter(8),2)  # only initial queues
                self.assertEqual((self.lib.pt_test_counter(1),self.lib.pt_test_counter(3)),(1,2))

    def test_actual_video_sequence_and_timestamp_domain_change_stop(self):
        for mode in (29,30):
            b = self.running(video_source(),mode=mode); b.read(0.05)
            with self.assertRaises(BackendFault):
                b.read(0.05)
            self.assertEqual(self.lib.pt_test_counter(8),3)
            self.assertEqual(self.lib.pt_test_counter(4),1)

    def test_actual_video_qbuf_failure_does_not_publish_copied_payload(self):
        b = self.running(video_source(),mode=31)
        with self.assertRaises(BackendFault) as caught:
            b.read(0.05)
        self.assertEqual(caught.exception.domain,"errno")
        self.assertEqual(self.lib.pt_test_counter(3),2)

    def test_actual_clocks_reject_ranges_overflow_and_backward_observations(self):
        for source in (audio_source(),video_source()):
            for mode in (40,41,42,43,44,46,47):
                with self.subTest(kind=source.kind,mode=mode):
                    b = self.running(source,mode=mode)
                    with self.assertRaises(BackendFault):
                        b.read(0.05)
                    self.assertTrue(b.closed)
                    self.assertLess(self.lib.pt_test_counter(0),3)

    def test_actual_clock_cannot_move_backwards_between_read_calls(self):
        for source in (audio_source(),video_source()):
            b = self.running(source,mode=45)
            b.read(0.05)
            with self.assertRaises(BackendFault):
                b.read(0.05)
            self.assertTrue(b.closed)

    def test_actual_video_cadence_substitution_refused_exact_rational_accepted(self):
        self.lib.pt_test_reset(48)
        with self.assertRaises(BackendFault):
            backend(self.lib,video_source())
        self.assertEqual(self.lib.pt_test_counter(1),1)
        self.assertEqual(self.lib.pt_test_counter(2),0)
        b = self.running(video_source(),mode=49)
        self.assertEqual((b.actual.cadence_numerator,b.actual.cadence_denominator),(2,10))
        self.assertEqual(b.read(0.05).payload,bytes(range(1,9)))

    def test_actual_poll_cancellation_and_eintr_timeout_are_bounded(self):
        b = self.running(mode=37)
        with self.assertRaisesRegex(BackendFault,"native_cancelled"):
            b.read(0.05)
        b = self.running(mode=38)
        self.assertIsNone(b.read(0.01))
        self.assertLess(self.lib.pt_test_counter(0),20)
        b.close()


if __name__ == "__main__":
    unittest.main()
