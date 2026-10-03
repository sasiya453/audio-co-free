"""
Unit tests for core.audio_engine.

Run with either:
    python -m pytest tests/ -q
    python -m unittest tests.test_engine -v

Tests generate synthetic signals (no fixture files required) so the suite is
self-contained and fast.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.audio_engine import (  # noqa: E402
    AudioEngineError,
    AudioLoadError,
    AudioMasker,
    AudioWriteError,
    MaskSettings,
)

SR = 22_050
DURATION = 2.0  # seconds


def _sine(freq: float, sr: int = SR, dur: float = DURATION,
          amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(sr * dur)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _dominant_freq(y: np.ndarray, sr: int) -> float:
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1.0 / sr)
    return float(freqs[int(np.argmax(spec))])


class TestMaskSettings(unittest.TestCase):
    def test_defaults_valid(self):
        s = MaskSettings().validate()
        self.assertEqual(s.output_format, "wav")
        self.assertGreater(s.bandpass_high_hz, s.bandpass_low_hz)

    def test_clamping(self):
        s = MaskSettings(pitch_semitones=99, speed_factor=0.1,
                         reverb_feedback=2.0).validate()
        self.assertEqual(s.pitch_semitones, 4.0)
        self.assertEqual(s.speed_factor, 0.90)
        self.assertEqual(s.reverb_feedback, 0.95)

    def test_bad_format_falls_back(self):
        s = MaskSettings(output_format="xyz").validate()
        self.assertEqual(s.output_format, "wav")

    def test_to_dict_excludes_limits(self):
        d = MaskSettings().to_dict()
        self.assertNotIn("LIMITS", d)
        self.assertIn("pitch_semitones", d)


class TestDSPPrimitives(unittest.TestCase):
    def setUp(self):
        self.m = AudioMasker()
        self.y = _sine(440.0)

    def test_time_stretch_changes_length(self):
        out = self.m.time_stretch(self.y, 1.10)
        self.assertAlmostEqual(len(out) / len(self.y), 1 / 1.10, delta=0.02)
        out = self.m.time_stretch(self.y, 0.90)
        self.assertAlmostEqual(len(out) / len(self.y), 1 / 0.90, delta=0.02)

    def test_time_stretch_invalid_rate(self):
        with self.assertRaises(AudioEngineError):
            self.m.time_stretch(self.y, 0.0)

    def test_pitch_shift_moves_frequency(self):
        out = self.m.pitch_shift(self.y, SR, 2.0)  # +2 semitones
        self.assertEqual(len(out), len(self.y))
        expected = 440.0 * 2 ** (2 / 12)
        self.assertAlmostEqual(_dominant_freq(out, SR), expected, delta=8.0)

    def test_pitch_shift_fractional(self):
        out = self.m.pitch_shift(self.y, SR, -1.5)
        expected = 440.0 * 2 ** (-1.5 / 12)
        self.assertAlmostEqual(_dominant_freq(out, SR), expected, delta=8.0)

    def test_bandpass_attenuates_out_of_band(self):
        low = _sine(30.0)      # below 80 Hz cut-off
        mid = _sine(1000.0)    # in band
        out_low = self.m.bandpass_filter(low, SR, 80, 8000, mix=1.0)
        out_mid = self.m.bandpass_filter(mid, SR, 80, 8000, mix=1.0)
        rms = lambda a: float(np.sqrt(np.mean(a[SR // 2:] ** 2)))  # noqa: E731
        self.assertLess(rms(out_low), rms(low) * 0.25)
        self.assertGreater(rms(out_mid), rms(mid) * 0.8)

    def test_bandpass_mix_zero_is_identity(self):
        out = self.m.bandpass_filter(self.y, SR, 80, 8000, mix=0.0)
        np.testing.assert_allclose(out, self.y, atol=1e-6)

    def test_bandpass_invalid_range(self):
        with self.assertRaises(AudioEngineError):
            self.m.bandpass_filter(self.y, SR, 5000, 100)

    def test_bandpass_stereo(self):
        stereo = np.stack([self.y, self.y * 0.5])
        out = self.m.bandpass_filter(stereo, SR, 80, 8000)
        self.assertEqual(out.shape, stereo.shape)

    def test_micro_reverb_impulse_response(self):
        """A unit impulse through the comb should produce echoes at D, 2D..."""
        sr = 1000
        imp = np.zeros(200, dtype=np.float32)
        imp[0] = 1.0
        out = self.m.micro_reverb(imp, sr, delay_ms=30, feedback=0.5, mix=1.0)
        # delay = 30 samples; wet = z^-D/(1 - fb z^-D) -> taps at 30, 60, 90
        self.assertAlmostEqual(out[30], 1.0, places=5)
        self.assertAlmostEqual(out[60], 0.5, places=5)
        self.assertAlmostEqual(out[90], 0.25, places=5)
        self.assertAlmostEqual(out[0], 0.0, places=5)

    def test_micro_reverb_mix_zero_is_identity(self):
        out = self.m.micro_reverb(self.y, SR, mix=0.0)
        np.testing.assert_array_equal(out, self.y)

    def test_micro_reverb_stereo_shape(self):
        stereo = np.stack([self.y, self.y])
        out = self.m.micro_reverb(stereo, SR)
        self.assertEqual(out.shape, stereo.shape)

    def test_normalize_peak(self):
        loud = self.y * 4.0  # clipping
        out = self.m.normalize_peak(loud, -1.0)
        self.assertAlmostEqual(float(np.max(np.abs(out))),
                               10 ** (-1.0 / 20), places=4)

    def test_normalize_silence_safe(self):
        out = self.m.normalize_peak(np.zeros(100, dtype=np.float32))
        self.assertEqual(float(np.max(np.abs(out))), 0.0)

    def test_normalize_strips_nan(self):
        y = self.y.copy()
        y[10] = np.nan
        out = self.m.normalize_peak(y)
        self.assertFalse(np.isnan(out).any())


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.m = AudioMasker()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_wav(self, name: str, y: np.ndarray, sr: int = SR) -> Path:
        import soundfile as sf
        p = self.dir / name
        sf.write(str(p), y.T if y.ndim == 2 else y, sr)
        return p

    def test_process_array_mono(self):
        y = _sine(440.0)
        out = self.m.process_array(y, SR, MaskSettings(pitch_semitones=1.0,
                                                       speed_factor=1.05))
        self.assertEqual(out.dtype, np.float32)
        self.assertEqual(out.ndim, 1)
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0)
        self.assertAlmostEqual(len(out) / len(y), 1 / 1.05, delta=0.03)

    def test_process_array_stereo(self):
        y = np.stack([_sine(440.0), _sine(660.0)])
        out = self.m.process_array(y, SR)
        self.assertEqual(out.ndim, 2)
        self.assertEqual(out.shape[0], 2)

    def test_process_array_empty_raises(self):
        with self.assertRaises(AudioEngineError):
            self.m.process_array(np.array([], dtype=np.float32), SR)

    def test_process_file_roundtrip(self):
        src = self._write_wav("tone.wav", _sine(440.0))
        out_dir = self.dir / "out"
        progress = []
        result = self.m.process_file(src, out_dir, MaskSettings(),
                                     progress_cb=lambda f, m: progress.append(f))
        self.assertTrue(result.exists())
        self.assertEqual(result.name, "tone_masked.wav")
        self.assertEqual(progress[-1], 1.0)
        self.assertEqual(progress, sorted(progress))  # monotonic

    def test_process_file_collision_avoidance(self):
        src = self._write_wav("tone.wav", _sine(440.0))
        r1 = self.m.process_file(src, self.dir)
        r2 = self.m.process_file(src, self.dir)
        self.assertNotEqual(r1, r2)
        self.assertTrue(r2.name.endswith("_1.wav"))

    def test_process_file_flac_output(self):
        src = self._write_wav("tone.wav", _sine(440.0))
        r = self.m.process_file(src, self.dir,
                                MaskSettings(output_format="flac"))
        self.assertEqual(r.suffix, ".flac")

    def test_load_stereo_file_shape(self):
        src = self._write_wav("st.wav", np.stack([_sine(440.0), _sine(880.0)]))
        audio, sr = self.m.load_audio(src)
        self.assertEqual(sr, SR)
        self.assertEqual(audio.shape[0], 2)

    def test_load_with_resample(self):
        src = self._write_wav("tone.wav", _sine(440.0))
        audio, sr = AudioMasker(target_sr=16_000).load_audio(src)
        self.assertEqual(sr, 16_000)
        self.assertAlmostEqual(len(audio) / 16_000, DURATION, delta=0.01)

    def test_missing_file_raises(self):
        with self.assertRaises(AudioLoadError):
            self.m.process_file(self.dir / "nope.wav", self.dir)

    def test_corrupt_file_raises(self):
        bad = self.dir / "bad.wav"
        bad.write_bytes(b"this is not audio at all" * 10)
        with self.assertRaises(AudioLoadError):
            self.m.load_audio(bad)

    def test_write_to_invalid_path_raises(self):
        # A path whose parent is a *file* cannot be created.
        blocker = self.dir / "blocker"
        blocker.write_text("x")
        with self.assertRaises(AudioWriteError):
            self.m.write_audio(blocker / "out.wav", _sine(440.0), SR)

    def test_cancel(self):
        m = AudioMasker()
        calls = []

        def cb(frac, msg):
            calls.append(frac)
            if len(calls) == 2:
                m.cancel()

        src = self._write_wav("tone.wav", _sine(440.0))
        with self.assertRaises(AudioEngineError):
            m.process_file(src, self.dir, progress_cb=cb)

    @unittest.skipUnless(os.path.exists("/usr/bin/ffmpeg") or
                         os.environ.get("AUDIOMASK_TEST_MP3"),
                         "ffmpeg not available for MP3 test")
    def test_mp3_input(self):
        import shutil
        import subprocess
        src_wav = self._write_wav("tone.wav", _sine(440.0))
        mp3 = self.dir / "tone.mp3"
        subprocess.run([shutil.which("ffmpeg"), "-y", "-v", "error",
                        "-i", str(src_wav), str(mp3)], check=True)
        audio, sr = self.m.load_audio(mp3)
        self.assertEqual(sr, SR)
        self.assertGreater(len(audio), SR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
