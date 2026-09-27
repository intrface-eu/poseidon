from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from poseidon_acoustic.session import (
    Channel, ClockMap, Session, SessionError, Source, canonical, load_json, sha256,
)
from poseidon_nereid.video import (
    Frame, Observation, QualityPolicy, ROI, build_index, capture_frames, decode_pgm,
    encode_pgm, export_excerpt, file_frames, quality, synthetic_frames, write_fixture,
)


ROOT = Path(__file__).resolve().parents[2]


def camera():
    return Source("camera-1", "pgm8", "synthetic", (Channel("gray", "synthetic grayscale"),),
                  ClockMap("reference_seconds", "test-session", reference_anchor_s=10,
                           drift_ppm=1000, anchor_uncertainty_s=0.1, drift_uncertainty_ppm=100),
                  origin="synthetic test frames")


def observation(**changes):
    return replace(Observation("obs-1", "reference_seconds", "test-session", 10.2, 10.6, 0.02,
                               "unknown", "synthetic-test-operator"), **changes)


class VideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session = Session.create(self.root / "session", "test-session", (camera(),))

    def capture(self):
        capture_frames(self.session, "camera-1", synthetic_frames(count=4))
        self.session.finalize()

    def test_canonical_pgm_roundtrip_preserves_whitespace_and_zero_pixels(self):
        pixels = bytes((10, 32, 0, 255, 13, 9))
        self.assertEqual(decode_pgm(encode_pgm(3, 2, pixels)), (3, 2, pixels))

    def test_invalid_truncated_oversized_pgm_and_unsupported_codecs(self):
        for data in (b"", b"P2\n1 1\n255\n3", b"P5\n1 1\n65535\n\0\0", b"P5\n0 1\n255\n",
                     b"P5\n9999999 9999999\n255\n", b"P5\n2 2\n255\n\x01",
                     b"P5\n1 1\n255\n\x01EXTRA", b"\0\0\0\x20ftypisom"):
            with self.subTest(data=data[:40]), self.assertRaises(SessionError):
                decode_pgm(data)
        with self.assertRaises(SessionError):
            encode_pgm(10000, 10000, b"")

    def test_frame_index_maps_timestamps_and_keeps_quality_separate_from_occlusion(self):
        self.capture()
        index = build_index(self.session, "camera-1", roi=ROI(2, 2, 8, 6), operator_occluded_frames=(3,))
        self.assertEqual(len(index["frames"]), 4)
        first = index["frames"][0]
        self.assertEqual(first["reference_start_s"], 10)
        self.assertAlmostEqual(first["reference_end_s"], 10.25025)
        self.assertAlmostEqual(first["end_uncertainty_s"], 0.100025)
        self.assertIn("dark_rule", first["quality"]["flags"])
        self.assertEqual(first["quality"]["occlusion"], "not_assessed")
        self.assertFalse(first["quality"]["biological_classifier"])
        self.assertEqual(index["frames"][3]["quality"]["occlusion"], "operator_declared")
        self.assertEqual(index["provenance"], "synthetic")
        self.assertFalse(index["hardware_verified"])

    def test_roi_is_checked_against_actual_frame_not_silently_clamped(self):
        self.capture()
        for roi in (ROI(15, 0, 2, 1), ROI(0, 11, 1, 2), ROI(100, 0, 1, 1)):
            with self.assertRaises(SessionError):
                build_index(self.session, "camera-1", roi=roi)
        for args in ((-1, 0, 1, 1), (0, 0, 0, 1), (True, 0, 1, 1), (0, 0, float("nan"), 1)):
            with self.assertRaises(SessionError):
                ROI(*args)

    def test_quality_rules_are_configurable_not_a_visibility_classifier(self):
        policy = QualityPolicy(dark_mean_below=0.2, bright_mean_above=0.8, contrast_below=0.2,
                               clipped_fraction_above=0.4)
        result = quality(bytes((0, 255)), policy)
        self.assertIn("clipping_rule", result["flags"])
        self.assertNotIn("low_contrast_rule", result["flags"])
        self.assertIn("bright_rule", quality(bytes([250]) * 4, policy)["flags"])
        for change in ({"dark_mean_below": float("nan")}, {"contrast_below": -1},
                       {"bright_mean_above": 2}, {"dark_mean_below": 0.95}):
            with self.assertRaises(SessionError):
                QualityPolicy(**change)

    def test_unknown_occlusion_frame_is_not_silently_ignored(self):
        self.capture()
        with self.assertRaises(SessionError):
            build_index(self.session, "camera-1", operator_occluded_frames=(999,))

    def test_unfinalized_session_not_ready_for_review(self):
        capture_frames(self.session, "camera-1", synthetic_frames(count=1))
        with self.assertRaises(SessionError):
            build_index(self.session, "camera-1")

    def test_independent_excerpt_has_uncertainty_expanded_selection_and_exact_copies(self):
        self.capture()
        out = self.root / "excerpt"
        result = export_excerpt(self.session, "camera-1", observation(), out, roi=ROI(0, 0, 8, 8))
        self.assertEqual([f["frame_index"] for f in result["frames"]], [0, 1, 2])
        self.assertEqual(result["observation"]["label"], "unknown")
        self.assertNotIn("candidate_id", result)
        self.assertEqual(result["nominal_uncovered_intervals"], [])
        for frame in result["frames"]:
            self.assertEqual((out / frame["path"]).read_bytes(), (self.session.directory / frame["path"]).read_bytes())
            self.assertEqual(sha256((out / frame["path"]).read_bytes()), frame["sha256"])
        self.assertFalse(result["biological_validation"])

    def test_no_frame_interval_still_exports_independent_unknown_observation(self):
        self.capture()
        request = observation(reference_start_s=20, reference_end_s=21)
        result = export_excerpt(self.session, "camera-1", request, self.root / "empty")
        self.assertEqual(result["frames"], [])
        self.assertEqual(result["nominal_uncovered_intervals"], [[20, 21]])
        self.assertTrue((self.root / "empty/excerpt.nereid-v1.json").exists())

    def test_reference_epoch_or_domain_mismatch_refuses_synchronization(self):
        self.capture()
        for change in ({"reference_domain": "unix_seconds"}, {"reference_epoch": "different-session"}):
            with self.assertRaises(SessionError):
                export_excerpt(self.session, "camera-1", observation(**change), self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_excerpt_negative_nan_and_overflow_bounds(self):
        self.capture()
        for change in ({"reference_start_s": float("nan")}, {"reference_end_s": float("inf")},
                       {"uncertainty_s": -0.1}, {"uncertainty_s": True}, {"label": "confirmed_orada"},
                       {"observer": ""}, {"reference_end_s": 10}):
            with self.assertRaises(SessionError):
                observation(**change)
        with self.assertRaises(SessionError):
            export_excerpt(self.session, "camera-1", observation(), self.root / "bad", padding_s=float("nan"))
        with self.assertRaises(SessionError):
            export_excerpt(self.session, "camera-1", observation(reference_start_s=1e307, reference_end_s=1e308,
                           uncertainty_s=1e308), self.root / "bad")

    def test_excerpt_frame_and_byte_budget_fail_before_creating_output(self):
        self.capture()
        for options in ({"max_frames": 1}, {"max_bytes": 1}, {"max_frames": 0}, {"max_bytes": -1}):
            with self.assertRaises(SessionError):
                export_excerpt(self.session, "camera-1", observation(), self.root / "budget", **options)
            self.assertFalse((self.root / "budget").exists())

    def test_review_output_inside_session_or_symlink_alias_preserves_source(self):
        self.capture()
        directory = self.session.directory
        alias = self.root / "session-alias"
        alias.symlink_to(directory, target_is_directory=True)
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        for target in (directory, directory / "excerpt", alias / "excerpt"):
            with self.subTest(target=target), self.assertRaisesRegex(SessionError, "outside"):
                export_excerpt(self.session, "camera-1", observation(), target)
        result = subprocess.run([sys.executable, "-m", "poseidon_nereid.cli", "index", "--session", str(directory),
                                 "--source-id", "camera-1", "--output-dir", str(alias / "index")], cwd=ROOT,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside", result.stderr)
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})
        self.assertEqual(len(build_index(self.session, "camera-1")["frames"]), 4)

    def test_existing_excerpt_is_never_overwritten(self):
        self.capture()
        target = self.root / "excerpt"
        export_excerpt(self.session, "camera-1", observation(), target)
        before = {p.name: p.read_bytes() for p in target.iterdir()}
        with self.assertRaises(FileExistsError):
            export_excerpt(self.session, "camera-1", observation(), target)
        self.assertEqual(before, {p.name: p.read_bytes() for p in target.iterdir()})

    def test_frame_drop_and_uncovered_interval_are_reported(self):
        frames = list(synthetic_frames(count=4))
        capture_frames(self.session, "camera-1", iter((frames[0], replace(frames[3], dropped_before=2,
                                                                         gap_reason="simulated dropped frames"))))
        self.session.finalize()
        index = build_index(self.session, "camera-1")
        self.assertEqual(index["frames"][1]["dropped_frames"], 2)
        request = observation(reference_start_s=10, reference_end_s=11)
        result = export_excerpt(self.session, "camera-1", request, self.root / "gap")
        self.assertEqual(result["nominal_uncovered_intervals"], [[10.25025, 10.75075]])

    def test_video_source_failure_and_corruption_preserve_prior_frames(self):
        def failing():
            yield next(synthetic_frames(count=1))
            yield Frame(1, 0.25, 0.5, b"invalid")
        with self.assertRaises(SessionError):
            capture_frames(self.session, "camera-1", failing())
        self.assertEqual(self.session.finalize()["state"], "source_failed")
        self.assertEqual(len(build_index(self.session, "camera-1")["frames"]), 1)
        target = self.session.directory / "chunk-000000.pgm"
        target.write_bytes(b"corrupt")
        with self.assertRaises(SessionError):
            build_index(self.session, "camera-1")
        self.assertEqual(target.read_bytes(), b"corrupt")

    def test_fixture_is_byte_reproducible_and_file_capture_binds_input_checksum(self):
        manifests = [write_fixture(self.root / name, count=4) for name in ("a", "b")]
        self.assertEqual({p.name: p.read_bytes() for p in manifests[0].parent.iterdir()},
                         {p.name: p.read_bytes() for p in manifests[1].parent.iterdir()})
        source, frames = file_frames(manifests[0])
        self.assertEqual(source.input_sha256, sha256(manifests[0].read_bytes()))
        self.assertEqual(source.provenance, "synthetic")
        self.assertEqual(len(list(frames)), 4)

    def test_file_source_rejects_corruption_traversal_nan_and_duplicate_paths(self):
        manifest = write_fixture(self.root / "input", count=2)
        original = load_json(manifest)
        for field, bad in (("path", "../outside.pgm"), ("frame_index", 0),
                           ("source_start_s", -1), ("dropped_before", 2), ("sha256", "bad")):
            value = json.loads(canonical(original))
            value["frames"][1][field] = bad
            manifest.write_bytes(canonical(value))
            with self.subTest(field=field), self.assertRaises(SessionError):
                source, frames = file_frames(manifest)
                list(frames)
        value = json.loads(canonical(original))
        value["frames"][1]["path"] = value["frames"][0]["path"]
        manifest.write_bytes(canonical(value))
        with self.assertRaises(SessionError):
            file_frames(manifest)
        manifest.write_bytes(canonical(original))
        (manifest.parent / original["frames"][1]["path"]).write_bytes(b"damaged")
        with self.assertRaisesRegex(SessionError, "checksum"):
            list(file_frames(manifest)[1])

    def test_file_source_input_budgets_and_symlink_refused(self):
        manifest = write_fixture(self.root / "input", count=2)
        with self.assertRaises(SessionError):
            file_frames(manifest, max_frames=1)
        with self.assertRaises(SessionError):
            file_frames(manifest, max_input_bytes=1)
        with self.assertRaises(SessionError):
            list(file_frames(manifest, max_input_bytes=manifest.stat().st_size + 1)[1])
        value = load_json(manifest)
        frame = manifest.parent / value["frames"][0]["path"]
        other = self.root / "copy.pgm"
        other.write_bytes(frame.read_bytes())
        frame.unlink()
        frame.symlink_to(other)
        with self.assertRaises(SessionError):
            list(file_frames(manifest)[1])

    def test_manifest_edit_during_stream_is_detected(self):
        manifest = write_fixture(self.root / "input", count=2)
        _, frames = file_frames(manifest)
        next(frames)
        manifest.write_bytes(manifest.read_bytes() + b" ")
        with self.assertRaisesRegex(SessionError, "changed during capture"):
            list(frames)

    def test_half_open_interval_boundary_with_zero_uncertainty(self):
        source = replace(camera(), clock=ClockMap("reference_seconds", "test-session"))
        session = Session.create(self.root / "exact", "exact", (source,))
        capture_frames(session, source.source_id, synthetic_frames(count=4))
        session.finalize()
        result = export_excerpt(session, source.source_id,
                                observation(reference_start_s=0.25, reference_end_s=0.5, uncertainty_s=0),
                                self.root / "exact-excerpt")
        self.assertEqual([f["frame_index"] for f in result["frames"]], [1])

    def test_cli_demo_reproducible_and_live_refusal(self):
        def run(*args):
            return subprocess.run([sys.executable, "-m", "poseidon_nereid.cli", *args],
                                  cwd=ROOT, text=True, capture_output=True, timeout=30)
        roots = [self.root / "demo-a", self.root / "demo-b"]
        for root in roots:
            completed = run("demo", "--output-dir", str(root))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["frames"], 8)
            self.assertEqual(result["excerpt_frames"], 4)
            self.assertFalse(result["wiper_energized"])
        self.assertEqual({str(p.relative_to(roots[0])): p.read_bytes() for p in roots[0].rglob("*") if p.is_file()},
                         {str(p.relative_to(roots[1])): p.read_bytes() for p in roots[1].rglob("*") if p.is_file()})
        self.assertEqual(run("demo", "--output-dir", str(roots[0])).returncode, 2)
        failed = run("live")
        self.assertEqual(failed.returncode, 2)
        self.assertNotIn("Traceback", failed.stderr)


if __name__ == "__main__":
    unittest.main()
