"""Synthetic sample arithmetic only; no biological or output-chain validation."""

import itertools
import math
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

from poseidon_dsp import LimitedSignal, SignalSpec, export_wav, limit_samples, sine_samples
from poseidon_dsp import signal as dsp


class DspTests(unittest.TestCase):
    def test_synthetic_sine_frequency_peak_and_rms(self):
        spec = SignalSpec(sample_rate_hz=8_000, sample_count=800, frequency_hz=1_000, amplitude=0.8)
        values = sine_samples(spec)
        self.assertEqual(len(values), 800)
        self.assertAlmostEqual(max(values), 0.8)
        self.assertAlmostEqual(math.sqrt(math.fsum(x*x for x in values) / len(values)), 0.8 / math.sqrt(2))
        self.assertEqual(spec.reserved_duration_ms, 100)
        self.assertEqual(SignalSpec(sample_count=1).reserved_duration_ms, 1)

    def test_signal_spec_rejects_invalid_bounds(self):
        cases = [
            {"sample_rate_hz": 0}, {"sample_rate_hz": 96_001}, {"sample_rate_hz": True},
            {"sample_count": 0}, {"sample_count": 960_001}, {"sample_count": 80_001},
            {"sample_count": 1.0}, {"amplitude": -0.1}, {"amplitude": 1.1},
            {"amplitude": math.nan}, {"amplitude": math.inf}, {"amplitude": True},
            {"frequency_hz": 0}, {"frequency_hz": -1}, {"frequency_hz": 4_000},
            {"frequency_hz": math.nan}, {"frequency_hz": math.inf},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SignalSpec(**kwargs)

    def test_peak_limiter_attenuates_without_amplifying(self):
        result = limit_samples([1.0, 0.0, -1.0], peak_limit=0.2, rms_limit=0.2)
        self.assertLessEqual(result.peak, 0.2)
        self.assertLessEqual(result.rms, 0.2)
        self.assertLessEqual(result.gain, 1)
        self.assertTrue(result.simulation_only)
        self.assertFalse(result.physical_output_enabled)
        quiet = limit_samples([0.01, -0.01], peak_limit=0.5, rms_limit=0.4)
        self.assertEqual(quiet.samples, (0.01, -0.01))
        self.assertEqual(quiet.gain, 1)

    def test_rms_limiter_whole_buffer_silence_and_zero_limits(self):
        result = limit_samples([0.8] * 100, peak_limit=0.5, rms_limit=0.1)
        self.assertLessEqual(result.rms, 0.1)
        self.assertLessEqual(result.peak, 0.5)
        self.assertEqual(limit_samples([0, 0]).samples, (0.0, 0.0))
        self.assertEqual(limit_samples([1, -1], peak_limit=0, rms_limit=0).samples, (0.0, -0.0))

    def test_limiter_randomized_arithmetic_envelope(self):
        rng = random.Random(708)
        for _ in range(100):
            peak_limit = rng.random()
            rms_limit = peak_limit * rng.random()
            result = limit_samples([rng.uniform(-1, 1) for _ in range(200)],
                                   peak_limit=peak_limit, rms_limit=rms_limit)
            self.assertLessEqual(result.peak, peak_limit)
            self.assertLessEqual(result.rms, rms_limit)

    def test_limiter_rejects_nonfinite_unbounded_empty_and_invalid_limits(self):
        for sample in [math.nan, math.inf, -math.inf, True, "0.1", 1.01, -1.01]:
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                limit_samples([0, sample])
        with self.assertRaises(ValueError):
            limit_samples([])
        for limits in [{"peak_limit": math.nan}, {"rms_limit": math.inf}, {"peak_limit": -1},
                       {"peak_limit": True}, {"rms_limit": 0.6, "peak_limit": 0.5}]:
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                limit_samples([0.1], **limits)
        with patch.object(dsp, "MAX_SAMPLES", 4), self.assertRaises(ValueError):
            limit_samples(itertools.repeat(0.1))

    def test_wav_roundtrip_quantization_does_not_raise_levels(self):
        spec = SignalSpec(amplitude=0.9)
        result = limit_samples(sine_samples(spec))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.wav"
            report = export_wav(path, result, sample_rate_hz=spec.sample_rate_hz)
            with wave.open(str(path), "rb") as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()),
                                 (1, 2, 8_000, 2_000))
                pcm = wav.readframes(2_000)
            decoded = tuple(x / 32767 for x in struct.unpack("<2000h", pcm))
            self.assertLessEqual(max(abs(x) for x in decoded), result.peak)
            self.assertLessEqual(math.sqrt(math.fsum(x*x for x in decoded)/len(decoded)), result.rms)
            self.assertFalse(report["physical_output_enabled"])
            self.assertTrue(report["simulation_only"])
            self.assertIn("not underwater SPL", report["calibration_status"])
            self.assertIn("synthetic", report["provenance"])
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                export_wav(path, result, sample_rate_hz=8_000)
            self.assertEqual(path.read_bytes(), original)
            link = Path(temporary) / "link.wav"
            link.symlink_to(path)
            with self.assertRaises(FileExistsError):
                export_wav(link, result, sample_rate_hz=8_000)
            self.assertEqual(path.read_bytes(), original)

    def test_export_revalidates_forged_signal_and_duration(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.wav"
            for forged in [LimitedSignal((0.8,), 0.1, 0.1, 1),
                           LimitedSignal((math.nan,), 0.1, 0.1, 1),
                           LimitedSignal((0.01,) * 11, 0.1, 0.1, 1)]:
                with self.subTest(forged=forged), self.assertRaises(ValueError):
                    export_wav(path, forged, sample_rate_hz=1)
                self.assertFalse(path.exists())

    def test_export_propagates_write_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("wave.Wave_write.writeframes", side_effect=OSError("synthetic disk full")):
                with self.assertRaises(OSError):
                    export_wav(Path(temporary) / "partial.wav", limit_samples([0.1]), sample_rate_hz=8_000)


if __name__ == "__main__":
    unittest.main()
