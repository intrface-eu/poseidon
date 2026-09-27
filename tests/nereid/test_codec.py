"""Real codec tests. Required environment (no skips or mock decoder fallback):

uv sync --project apps/nereid --locked --python 3.12 --no-python-downloads
PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src \
  apps/nereid/.venv/bin/python -m unittest discover -s tests/nereid -v

All media here are local SYNTHETIC files. No devices, network, calibration or
biological classifier are exercised. Native encoding/decoding runs in owned,
bounded processes. Direct unit tests also cover timing/MP4 preflight policies.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import venv

from poseidon_acoustic.session import Session, SessionError, canonical, load_json, sha256
from poseidon_nereid.codec import (
    DecodeLimits, MAP_NAME, PINNED_AV, _recorded_path, _supervise, build_codec_index,
    declaration, decode_file, export_codec_excerpt, presentation_intervals, synthetic_fixture,
)
from poseidon_nereid.codec_mp4 import boxes, preflight
from poseidon_nereid.video import Observation, build_index, decode_pgm


ROOT = Path(__file__).resolve().parents[2]


def box_location(data, target):
    def walk(start=0, end=None):
        for kind, lo, hi in boxes(data, start, end):
            if kind == target:
                return lo, hi
            if kind in {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf"}:
                found = walk(lo, hi)
                if found:
                    return found
        return None
    found = walk()
    if found is None:
        raise AssertionError(f"missing test box {target}")
    return found


class CodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import av
        except ImportError as exc:
            raise RuntimeError("Codec tests require apps/nereid/.venv with locked PyAV; see test_codec.py/doc command. No tests skipped.") from exc
        if av.__version__ != PINNED_AV:
            raise RuntimeError(f"Codec tests require PyAV {PINNED_AV}, found {av.__version__}")
        cls.shared = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.shared.cleanup)
        cls.fixture = Path(cls.shared.name) / "fixture"
        synthetic_fixture(cls.fixture)
        cls.original = (cls.fixture / "synthetic.mp4").read_bytes()
        cls.declared = load_json(cls.fixture / "declaration.codec-v1.json")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "input.mp4"
        self.input.write_bytes(self.original)
        self.declaration_path = self.root / "declaration.json"
        self.declaration_path.write_bytes(canonical(self.declared))

    def decode(self, *, name="decoded", limits=None):
        return decode_file(self.input, self.declaration_path, self.root / name, session_id="synthetic-codec-test", limits=limits)

    def change_input(self, data):
        self.input.write_bytes(data)
        value = deepcopy(self.declared)
        value["source_sha256"] = sha256(data)
        self.declaration_path.write_bytes(canonical(value))

    def change_declaration(self, **changes):
        value = deepcopy(self.declared)
        value.update(changes)
        self.declaration_path.write_bytes(canonical(value))
        return value

    def test_real_encoder_fixture_is_byte_reproducible_and_explicitly_synthetic(self):
        result = synthetic_fixture(self.root / "repeat")
        self.assertEqual((self.root / "repeat/synthetic.mp4").read_bytes(), self.original)
        self.assertEqual(result["source_sha256"], self.declared["source_sha256"])
        recipe = load_json(self.root / "repeat/synthetic-recipe.codec-v1.json")
        self.assertEqual(recipe["encoder"], "libx264")
        self.assertEqual(recipe["provenance"], "synthetic")
        self.assertEqual(recipe["bframes"], 2)
        self.assertFalse(recipe["biological_classifier"])
        self.assertEqual(recipe["calibration"], "none")
        self.assertIn(b"SYNTHETIC", self.original)

    def test_actual_vfr_nonzero_pts_bframes_exact_packet_and_luma_association(self):
        before = self.input.stat()
        result = self.decode()
        after = self.input.stat()
        self.assertEqual((before.st_ino, before.st_mtime_ns, before.st_size), (after.st_ino, after.st_mtime_ns, after.st_size))
        self.assertEqual(self.input.read_bytes(), self.original)
        self.assertEqual((self.root / "decoded/source.mp4").read_bytes(), self.original)
        self.assertEqual(result["frames"], 6)
        mapping = load_json(self.root / "decoded" / MAP_NAME)
        self.assertEqual(mapping["stream"]["index"], 0)
        self.assertEqual(mapping["stream"]["original_dimensions"], [32, 24])
        self.assertEqual([f["pts"] for f in mapping["frames"]], [32000, 32640, 33600, 33920, 35200, 35840])
        self.assertEqual({tuple(f["time_base"]) for f in mapping["frames"]}, {(1, 16000)})
        self.assertEqual([f["encoded_sample"]["sample_index"] for f in mapping["frames"]], [0, 2, 3, 1, 5, 4])
        self.assertIn("B", {f["picture_type"] for f in mapping["frames"]})
        durations = [Fraction(*f["duration_exact_s"]) for f in mapping["frames"]]
        self.assertEqual(durations, [Fraction(1, 25), Fraction(3, 50), Fraction(1, 50), Fraction(2, 25), Fraction(1, 25), Fraction(1, 50)])
        self.assertEqual(mapping["frames"][-1]["duration_basis"], "operator_attested_unverified")
        self.assertTrue(all(f["duration_basis"].startswith("inferred_") for f in mapping["frames"][:-1]))
        for i, frame in enumerate(mapping["frames"]):
            sample = frame["encoded_sample"]
            raw = self.original[sample["offset"]:sample["offset"] + sample["size"]]
            self.assertEqual(sha256(raw), sample["sha256"])
            self.assertEqual(frame["pts"] * Fraction(*frame["time_base"]), sample["pts"] * Fraction(*sample["time_base"]))
            width, height, pixels = decode_pgm((self.root / "decoded" / frame["path"]).read_bytes())
            self.assertEqual((width, height), (32, 24))
            self.assertEqual(set(pixels), {30 + 25 * i})
        self.assertFalse(mapping["transform"]["original_color_bytes"])
        self.assertFalse(mapping["hardware_verified"])
        self.assertFalse(mapping["biological_classifier"])
        self.assertIn("libavcodec", mapping["decoder"]["libraries"])
        self.assertEqual(mapping["decoder"]["pyav"], PINNED_AV)

    def test_repeated_decode_produces_identical_manifest_and_frame_bytes(self):
        a, b = self.decode(name="a"), self.decode(name="b")
        self.assertEqual(a, b)
        def contents(name):
            return {str(p.relative_to(self.root / name)): p.read_bytes() for p in (self.root / name).rglob("*") if p.is_file()}
        self.assertEqual(contents("a"), contents("b"))

    def test_existing_session_index_preserves_explicit_clock_and_derivative_binding(self):
        self.decode()
        session = Session(self.root / "decoded/session")
        source = session.source(self.declared["source_id"])
        self.assertEqual(source.media, "pgm8")
        self.assertEqual(source.provenance, "synthetic")
        self.assertEqual(source.source_origin_s, 2.0)
        self.assertIn("not original color bytes", source.origin)
        self.assertEqual(source.input_sha256, sha256((self.root / "decoded/frames.json").read_bytes()))
        old_index = build_index(session, source.source_id)
        new_index = build_codec_index(self.root / "decoded")
        self.assertEqual(old_index["frames"], new_index["frames"])
        self.assertEqual(new_index["frames"][0]["reference_start_s"], 10.0)
        self.assertEqual(new_index["reference_epoch"], "synthetic-codec-epoch")
        self.assertEqual(new_index["source_container"]["sha256"], self.declared["source_sha256"])
        self.assertTrue(all(not f["quality"]["biological_classifier"] for f in new_index["frames"]))

    def test_codec_excerpt_copies_pgm_and_keeps_selected_exact_source_mapping(self):
        self.decode()
        observation = Observation("synthetic-unknown", "reference_seconds", "synthetic-codec-epoch",
                                  10.04, 10.12, 0.0, "unknown", "synthetic-test-operator")
        result = export_codec_excerpt(self.root / "decoded", observation, self.root / "excerpt")
        old = load_json(self.root / "excerpt/excerpt.nereid-v1.json")
        self.assertEqual({f["frame_index"] for f in old["frames"]}, {f["frame_index"] for f in result["codec_frame_mapping"]})
        self.assertFalse(result["source_container_included"])
        self.assertTrue(result["requires_source_bundle"])
        self.assertFalse(result["transform"]["original_color_bytes"])
        for frame in old["frames"]:
            self.assertEqual((self.root / "excerpt" / frame["path"]).read_bytes(),
                             (self.root / "decoded/session" / frame["path"]).read_bytes())
        self.assertFalse((self.root / "excerpt/source.mp4").exists())
        self.assertLess(sum(p.stat().st_size for p in (self.root / "excerpt").iterdir()), 16 * 1024 * 1024)

    def test_excerpt_empty_interval_budget_epoch_and_overwrite_fail_closed(self):
        self.decode()
        observation = Observation("empty", "reference_seconds", "synthetic-codec-epoch", 20, 21, 0,
                                  "unknown", "synthetic-test-operator")
        result = export_codec_excerpt(self.root / "decoded", observation, self.root / "empty")
        self.assertEqual(result["codec_frame_mapping"], [])
        old = load_json(self.root / "empty/excerpt.nereid-v1.json")
        self.assertEqual(old["nominal_uncovered_intervals"], [[20, 21]])
        with self.assertRaises(SessionError):
            export_codec_excerpt(self.root / "decoded", observation, self.root / "too-small", max_bytes=1)
        with self.assertRaises(SessionError):
            export_codec_excerpt(self.root / "decoded", replace(observation, reference_epoch="other"), self.root / "other")
        with self.assertRaises(FileExistsError):
            export_codec_excerpt(self.root / "decoded", observation, self.root / "empty")
        self.assertFalse((self.root / "too-small").exists())
        self.assertFalse((self.root / "other").exists())

    def test_review_output_inside_bundle_or_symlink_alias_cannot_mutate_source(self):
        self.decode()
        bundle = self.root / "decoded"
        alias = self.root / "bundle-alias"
        alias.symlink_to(bundle, target_is_directory=True)
        before = {str(p.relative_to(bundle)): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
        observation = Observation("outside-only", "reference_seconds", "synthetic-codec-epoch", 10, 10.1, 0,
                                  "unknown", "synthetic-test-operator")
        for output in (bundle, bundle / "excerpt", bundle / "session/excerpt", alias / "session/excerpt"):
            with self.subTest(output=output), self.assertRaisesRegex(SessionError, "outside"):
                export_codec_excerpt(bundle, observation, output)
        completed = subprocess.run([sys.executable, "-m", "poseidon_nereid.codec_cli", "index", "--bundle", str(bundle),
                                    "--output-dir", str(alias / "session/index")], cwd=ROOT,
                                   text=True, capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("outside", completed.stderr)
        self.assertFalse((bundle / "session/excerpt").exists())
        self.assertFalse((bundle / "session/index").exists())
        self.assertEqual(before, {str(p.relative_to(bundle)): p.read_bytes() for p in bundle.rglob("*") if p.is_file()})
        self.assertEqual(len(build_codec_index(bundle)["frames"]), 6)

    def test_no_overwrite_source_existing_output_or_symlink(self):
        with self.assertRaises(FileExistsError):
            decode_file(self.input, self.declaration_path, self.input, session_id="same")
        self.assertEqual(self.input.read_bytes(), self.original)
        self.decode()
        before = (self.root / "decoded" / MAP_NAME).read_bytes()
        with self.assertRaises(FileExistsError):
            self.decode()
        self.assertEqual((self.root / "decoded" / MAP_NAME).read_bytes(), before)
        link = self.root / "input-link.mp4"
        link.symlink_to(self.input)
        with self.assertRaises(SessionError):
            decode_file(link, self.declaration_path, self.root / "link", session_id="link")

    def test_device_url_fifo_and_directory_inputs_never_reach_native_worker(self):
        fifo = self.root / "pipe.mp4"
        os.mkfifo(fifo)
        with patch("poseidon_nereid.codec._worker") as worker:
            for source in ("/dev/video0", "/dev/null", "/proc/self/mem", "rtsp://example.invalid/live",
                           "https://example.invalid/video.mp4", "file:/recording.mp4", "pipe:0", fifo, self.root):
                with self.subTest(source=source), self.assertRaises((SessionError, OSError)):
                    decode_file(source, self.declaration_path, self.root / "bad", session_id="bad")
            worker.assert_not_called()
        # Syntactic rejection happens before even stat/open on a device path.
        with patch("pathlib.Path.lstat", side_effect=AssertionError("device stat forbidden")):
            with self.assertRaises(SessionError):
                _recorded_path("/dev/video0")

    def test_original_checksum_is_required_and_postdecode_mutation_is_detected(self):
        self.change_declaration(source_sha256="0" * 64)
        with patch("poseidon_nereid.codec._worker") as worker, self.assertRaisesRegex(SessionError, "SHA256"):
            self.decode()
        worker.assert_not_called()
        self.change_declaration()
        import poseidon_nereid.codec as module
        real_worker = module._worker
        def mutate(*args, **kwargs):
            result = real_worker(*args, **kwargs)
            self.input.write_bytes(self.original + b"externally changed")
            return result
        with patch("poseidon_nereid.codec._worker", side_effect=mutate), self.assertRaisesRegex(SessionError, "changed"):
            self.decode()
        self.assertFalse((self.root / "decoded/frames.json").exists())
        self.assertEqual((self.root / "decoded/source.mp4").read_bytes(), self.original)

    def test_map_source_and_frame_tampering_break_review_chain(self):
        self.decode()
        path = self.root / "decoded" / MAP_NAME
        original_map = path.read_bytes()
        mapping = json.loads(original_map)
        mapping["frames"][1]["pts"] += 1
        path.write_bytes(canonical(mapping))
        with self.assertRaises(SessionError):
            build_codec_index(self.root / "decoded")
        path.write_bytes(original_map)
        archive = self.root / "decoded/source.mp4"
        archive.write_bytes(self.original + b"change")
        with self.assertRaises(SessionError):
            build_codec_index(self.root / "decoded")
        archive.write_bytes(self.original)
        frame = self.root / "decoded/frame-000001.pgm"
        frame.write_bytes(frame.read_bytes()[:-1] + b"\0")
        with self.assertRaises(SessionError):
            build_codec_index(self.root / "decoded")

    def test_malformed_truncated_nonmp4_and_unbounded_boxes_rejected_before_decode(self):
        bad_inputs = (b"", b"not an MP4", b"RIFF\x20\0\0\0AVI ", self.original[:30], self.original[:-1],
                      self.original + b"junk", b"\0\0\0\0ftypisom", b"\0\0\0\1ftyp" + b"\xff" * 8)
        with patch("poseidon_nereid.codec._worker") as worker:
            for data in bad_inputs:
                self.change_input(data)
                with self.subTest(size=len(data)), self.assertRaises(SessionError):
                    self.decode()
            worker.assert_not_called()

    def test_external_reference_and_fragmented_container_are_rejected_before_native(self):
        data = bytearray(self.original)
        lo, _ = box_location(data, b"dref")
        # self-contained URL fullbox flags become external; no URL is opened.
        data[lo + 19] = 0
        self.change_input(bytes(data))
        with patch("poseidon_nereid.codec._worker") as worker, self.assertRaisesRegex(SessionError, "external"):
            self.decode()
        worker.assert_not_called()
        self.change_input(self.original + struct.pack(">I4s", 8, b"moof"))
        with self.assertRaises(SessionError):
            self.decode()

    def test_malformed_sample_counts_offsets_and_timestamp_tables_are_bounded(self):
        mutations = []
        for kind, relative, value in ((b"stsz", 8, 0xffffffff), (b"stco", 8, 0xffffffff),
                                      (b"stts", 8, 0xffffffff), (b"stts", 12, 0),
                                      (b"ctts", 8, 0xffffffff)):
            data = bytearray(self.original)
            lo, _ = box_location(data, kind)
            struct.pack_into(">I", data, lo + relative, value)
            mutations.append(bytes(data))
        for data in mutations:
            self.change_input(data)
            with self.assertRaises(SessionError):
                self.decode()
        self.assertFalse((self.root / "decoded").exists())

    def test_corrupt_h264_access_unit_uses_real_decoder_path_and_refuses_bridge(self):
        data = bytearray(self.original)
        sample = preflight(self.original, DecodeLimits())["tracks"][0]["samples"][0]
        # Break an AVCC length inside mdat while retaining a valid MP4 container.
        data[sample["offset"]:sample["offset"] + 4] = b"\xff\xff\xff\xff"
        self.change_input(bytes(data))
        with self.assertRaises(SessionError):
            self.decode()
        self.assertTrue((self.root / "decoded/source.mp4").exists())
        self.assertFalse((self.root / "decoded/frames.json").exists())
        self.assertFalse((self.root / "decoded/session").exists())

    def test_repeated_pts_in_real_mp4_rejected_without_timestamp_repair(self):
        data = bytearray(self.original)
        lo, _ = box_location(data, b"ctts")
        # sample 2 DTS=1600; give it CTS=1600, same as sample 0.
        struct.pack_into(">I", data, lo + 12 + 2 * 8, 0)
        self.change_input(bytes(data))
        with self.assertRaisesRegex(SessionError, "repeated|presentation|incomplete"):
            self.decode()
        self.assertFalse((self.root / "decoded/frames.json").exists())

    def test_input_frames_dimensions_duration_and_storage_budgets(self):
        for limits in (DecodeLimits(max_input_bytes=len(self.original) - 1), DecodeLimits(max_frames=5),
                       DecodeLimits(max_dimension=16), DecodeLimits(max_pixels=512),
                       DecodeLimits(max_storage_bytes=1024)):
            with self.subTest(limits=limits), self.assertRaises(SessionError):
                self.decode(name="budget-" + str(limits.max_frames) + str(limits.max_dimension) + str(limits.max_pixels), limits=limits)
        data = bytearray(self.original)
        lo, _ = box_location(data, b"mdhd")
        struct.pack_into(">I", data, lo + 16, 16000 * 121)
        self.change_input(bytes(data))
        with self.assertRaisesRegex(SessionError, "duration"):
            self.decode()

    def test_limit_validation_rejects_bool_nan_overflow_and_disabled_watchdogs(self):
        for changes in ({"max_frames": True}, {"max_frames": 257}, {"max_pixels": 2**40},
                        {"timeout_s": 0}, {"timeout_s": float("nan")}, {"timeout_s": 31},
                        {"max_streams": 5}, {"max_rss_bytes": 0}, {"max_storage_bytes": -1}):
            with self.subTest(changes=changes), self.assertRaises(SessionError):
                DecodeLimits(**changes)

    def test_worker_uses_callers_interpreter_and_missing_dependency_is_explicit(self):
        environment = self.root / "no-codec-env"
        venv.EnvBuilder(with_pip=False).create(environment)
        executable = environment / "bin/python"
        completed = subprocess.run([str(executable), "-m", "poseidon_nereid.codec_cli", "fixture",
                                    "--output-dir", str(self.root / "no-codec")], cwd=ROOT,
                                   text=True, capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("PyAV unavailable", completed.stderr)
        self.assertIn("apps/nereid/.venv", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)
        self.assertFalse((self.root / "no-codec/synthetic.mp4").exists())
        self.assertEqual(list((self.root / "no-codec").glob(".codec-job-*")), [])

    def test_native_libraries_are_wheel_bundled_and_decoder_is_software_only(self):
        self.decode()
        decoder = load_json(self.root / "decoded" / MAP_NAME)["decoder"]
        self.assertEqual(set(decoder["bundled_library_paths"]), {"avcodec_version", "avformat_version", "avutil_version"})
        self.assertTrue(all(path.startswith(("av/.dylibs/", "av.libs/")) for path in decoder["bundled_library_paths"].values()))
        self.assertIn("software h264", decoder["implementation"])
        self.assertIn("thread_count=1", decoder["implementation"])
        self.assertEqual(decoder["resource_controls"]["network_protocols"], "none")
        self.assertEqual(decoder["resource_controls"]["max_native_single_allocation_bytes"], 16 * 1024 * 1024)
        self.assertFalse(decoder["resource_controls"]["security_sandbox"])

    def test_owned_process_hard_timeout_and_rss_guard_kill_and_reap(self):
        real_popen = subprocess.Popen
        children = []
        def start(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            children.append(process)
            return process
        for limits, message in ((DecodeLimits(timeout_s=0.05), "timeout"),
                                (DecodeLimits(max_rss_bytes=1), "RSS")):
            started = time.monotonic()
            with patch("poseidon_nereid.codec.subprocess.Popen", side_effect=start), self.assertRaisesRegex(SessionError, message):
                _supervise([sys.executable, "-c", "import time; time.sleep(10)"], limits)
            self.assertLess(time.monotonic() - started, 3)
            self.assertIsNotNone(children[-1].returncode)
            with self.assertRaises(ProcessLookupError):
                os.kill(children[-1].pid, 0)

    def test_actual_decoder_timeout_leaves_no_completed_bridge_or_job_process(self):
        with self.assertRaisesRegex(SessionError, "timeout"):
            self.decode(limits=DecodeLimits(timeout_s=0.0001))
        self.assertFalse((self.root / "decoded/frames.json").exists())
        self.assertEqual(list((self.root / "decoded").glob(".codec-job-*")), [])
        self.assertEqual(self.input.read_bytes(), self.original)

    def test_explicit_absolute_stream_index_selects_second_actual_h264_track(self):
        script = '''
from fractions import Fraction
from pathlib import Path
import sys
from poseidon_nereid._codec_worker import _native_environment
from poseidon_nereid.codec import DecodeLimits
av,_ = _native_environment(DecodeLimits())
with Path(sys.argv[1]).open('xb') as out:
 with av.open(out, mode='w', format='mp4') as c:
  streams=[]
  for i in range(2):
   s=c.add_stream('libx264', rate=25); s.width=32;s.height=24;s.pix_fmt='yuv420p'
   s.time_base=Fraction(1,1000);s.codec_context.time_base=Fraction(1,1000);s.codec_context.thread_count=1
   s.options={'x264-params':'bframes=0:threads=1:scenecut=0'}; streams.append(s)
  for i in range(3):
   for track,s in enumerate(streams):
    f=av.VideoFrame(32,24,'yuv420p')
    for n,p in enumerate(f.planes):p.update(bytes([40+80*track if n==0 else 128])*p.buffer_size)
    f.pts=2000+i*40;f.time_base=Fraction(1,1000)
    for p in s.encode(f):c.mux(p)
  for s in streams:
   for p in s.encode():c.mux(p)
'''
        path = self.root / "two-tracks.mp4"
        _supervise([sys.executable, "-c", script, str(path)], DecodeLimits())
        self.change_input(path.read_bytes())
        declared = load_json(self.declaration_path)
        declared["stream_index"] = 1
        declared["duration_attestations"] = [{"pts_s": [52, 25], "duration_s": [1, 25], "evidence_ref": "synthetic-two-track-recipe"}]
        self.declaration_path.write_bytes(canonical(declared))
        self.decode()
        mapping = load_json(self.root / "decoded" / MAP_NAME)
        self.assertEqual(mapping["stream"]["index"], 1)
        self.assertEqual(mapping["stream"]["track_id"], 2)
        self.assertEqual(len(mapping["frames"]), 3)
        for frame in mapping["frames"]:
            self.assertEqual(set(decode_pgm((self.root / "decoded" / frame["path"]).read_bytes())[2]), {120})
        with self.assertRaisesRegex(SessionError, "stream count"):
            self.decode(name="one-stream-limit", limits=DecodeLimits(max_streams=1))

    def test_absent_or_unsupported_stream_index_is_not_auto_selected(self):
        self.change_declaration(stream_index=1)
        with self.assertRaisesRegex(SessionError, "index is absent"):
            self.decode()
        with self.assertRaises(SessionError):
            declaration(dict(self.declared, stream_index=True))
        data = bytearray(self.original)
        lo, _ = box_location(data, b"stsd")
        data[lo + 12:lo + 16] = b"mp4v"
        self.change_input(bytes(data))
        with self.assertRaises(SessionError):
            self.decode(name="unsupported")

    def test_cli_fixture_decode_index_excerpt_and_human_errors(self):
        def run(*args):
            return subprocess.run([sys.executable, "-m", "poseidon_nereid.codec_cli", *map(str, args)],
                                  cwd=ROOT, text=True, capture_output=True, timeout=30)
        commands = [("fixture", "--output-dir", self.root / "cli-fixture"),
                    ("decode", "--input", self.input, "--declaration", self.declaration_path,
                     "--output-dir", self.root / "cli", "--session-id", "cli-synthetic"),
                    ("index", "--bundle", self.root / "cli", "--output-dir", self.root / "cli-index"),
                    ("excerpt", "--bundle", self.root / "cli", "--output-dir", self.root / "cli-excerpt",
                     "--observation-id", "cli-unknown", "--reference-domain", "reference_seconds",
                     "--reference-epoch", "synthetic-codec-epoch", "--start-s", "10.04", "--end-s", "10.12",
                     "--uncertainty-s", "0", "--label", "unknown", "--observer", "synthetic-test-operator")]
        for command in commands:
            completed = run(*command)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIsInstance(json.loads(completed.stdout), dict)
        failed = run(*commands[1])
        self.assertEqual(failed.returncode, 2)
        self.assertNotIn("Traceback", failed.stderr)
        failed = run("decode", "--input", "rtsp://example.invalid/live", "--declaration", self.declaration_path,
                     "--output-dir", self.root / "no-network", "--session-id", "bad")
        self.assertEqual(failed.returncode, 2)
        self.assertFalse((self.root / "no-network").exists())

    def test_missing_clock_epoch_provenance_or_duration_never_defaults(self):
        for key in ("clock", "provenance", "source_sha256", "infer_intervals_from_next_pts", "duration_attestations"):
            value = deepcopy(self.declared)
            del value[key]
            with self.subTest(key=key), self.assertRaises(SessionError):
                declaration(value)
        for key in ("source_domain", "reference_domain", "reference_epoch", "source_anchor_s"):
            value = deepcopy(self.declared)
            del value["clock"][key]
            with self.subTest(key=key), self.assertRaises(SessionError):
                declaration(value)
        with self.assertRaises(SessionError):
            declaration(dict(self.declared, provenance="field"))
        value = deepcopy(self.declared)
        value["clock"]["reference_epoch"] = ""
        with self.assertRaises(SessionError):
            declaration(value)

    def test_file_provenance_and_reference_are_declared_not_inferred_utc(self):
        value = self.change_declaration(provenance="file", origin="operator supplied local SYNTHETIC copy for file-path test")
        value["clock"]["reference_epoch"] = "operator-named-non-UTC-epoch"
        self.declaration_path.write_bytes(canonical(value))
        self.decode()
        index = build_codec_index(self.root / "decoded")
        self.assertEqual(index["provenance"], "file")
        self.assertEqual(index["reference_epoch"], "operator-named-non-UTC-epoch")
        self.assertNotIn("field", index["provenance"])

    def test_missing_final_attestation_wrong_pts_and_no_optin_inference_fail(self):
        for changes in ({"duration_attestations": [{"pts_s": [2, 1], "duration_s": [1, 25], "evidence_ref": "synthetic"}]},
                        {"duration_attestations": [{"pts_s": [9, 1], "duration_s": [1, 25], "evidence_ref": "synthetic"}]},
                        {"infer_intervals_from_next_pts": False}, {"max_frame_interval_s": [1, 1000]}):
            self.change_declaration(**changes)
            name = "bad-" + str(len(list(self.root.glob("bad-*"))))
            with self.assertRaises(SessionError):
                self.decode(name=name)
            self.assertFalse((self.root / name / "frames.json").exists())

    def test_all_attested_intervals_preserve_gap_without_guessing_dropped_count(self):
        starts = [Fraction(2), Fraction(51, 25), Fraction(21, 10), Fraction(53, 25), Fraction(11, 5), Fraction(56, 25)]
        attestations = [{"pts_s": [p.numerator, p.denominator], "duration_s": [1, 100],
                         "evidence_ref": "synthetic-short-intervals"} for p in starts]
        self.change_declaration(infer_intervals_from_next_pts=False, duration_attestations=attestations)
        self.decode()
        index = build_codec_index(self.root / "decoded")
        self.assertGreater(index["frames"][1]["gap_source_s"], 0)
        self.assertEqual(index["frames"][1]["dropped_frames"], 0)
        self.assertTrue(all(f["duration_basis"] == "operator_attested_unverified" for f in index["codec_frame_mapping"]))
        self.assertIn("missing frame count unknown", index["codec_frame_mapping"][1]["gap_reason"])

    def test_presentation_policy_rejects_missing_repeated_backwards_and_unrepresentable_times(self):
        base = [{"pts": 2000, "time_base": [1, 1000]}, {"pts": 2240, "time_base": [1, 1000]}]
        declared = deepcopy(self.declared)
        declared["max_frame_interval_s"] = [1, 1]
        for frames in ([dict(base[0], pts=None), base[1]], [base[0], base[0]], list(reversed(base)),
                       [dict(base[0], time_base=[1, 0]), base[1]]):
            with self.assertRaises(SessionError):
                presentation_intervals(frames, declared, DecodeLimits())
        tiny = [{"pts": 2**62, "time_base": [1, 1]}, {"pts": 2**62 + 1, "time_base": [1, 1]}]
        declared["duration_attestations"] = [{"pts_s": [2**62 + 1, 1], "duration_s": [1, 1], "evidence_ref": "synthetic"}]
        with self.assertRaisesRegex(SessionError, "representable|positive duration"):
            presentation_intervals(tiny, declared, DecodeLimits())
        declared = deepcopy(self.declared)
        declared["max_frame_interval_s"] = [1, 1]
        declared["clock"]["reference_anchor_s"] = 1e30
        with self.assertRaisesRegex(SessionError, "positive duration"):
            presentation_intervals(base, declared, DecodeLimits())

    def test_positive_negative_anchors_and_explicit_discontinuity_policy(self):
        # Negative raw source timestamps are not normalized to zero or called UTC.
        frames = [{"pts": -2000, "time_base": [1, 1000]}, {"pts": -1960, "time_base": [1, 1000]}]
        declared = deepcopy(self.declared)
        declared["duration_attestations"] = [{"pts_s": [-49, 25], "duration_s": [1, 25], "evidence_ref": "synthetic-negative"}]
        intervals = presentation_intervals(frames, declared, DecodeLimits())
        self.assertEqual(intervals[0]["source_start_s"], -2.0)
        declared["duration_attestations"][0]["duration_s"] = [1, 1]
        with self.assertRaises(SessionError):
            presentation_intervals(frames, declared, DecodeLimits())


if __name__ == "__main__":
    unittest.main()
