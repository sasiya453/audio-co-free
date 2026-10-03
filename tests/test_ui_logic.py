"""
Task 3 tests: logging bootstrap, engine hardening paths and the pure UI
helper functions. **No Tk display is required** - the UI module is imported
only for its Tk-free helpers (importing customtkinter does not open a window).
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import logging_setup  # noqa: E402
from core.audio_engine import (  # noqa: E402
    AudioLoadError,
    AudioMasker,
    AudioWriteError,
    MaskSettings,
)

SR = 22_050


def _write_wav(path: Path, seconds: float = 0.5, channels: int = 1,
               sr: int = SR) -> Path:
    n = int(seconds * sr)
    t = np.arange(n) / sr
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    data = tone if channels == 1 else np.stack([tone] * channels, axis=1)
    sf.write(str(path), data, sr)
    return path


# --------------------------------------------------------------------------- #
# logging_setup
# --------------------------------------------------------------------------- #
class LoggingSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Remove our handlers after each test so files can be deleted on Windows
        self.addCleanup(self._strip_handlers)

    @staticmethod
    def _strip_handlers() -> None:
        root = logging.getLogger()
        for h in list(root.handlers):
            if getattr(h, "_audiomask", False):
                root.removeHandler(h)
                h.close()

    def test_localappdata_preferred(self) -> None:
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name}):
            path = logging_setup.configure_logging(debug=True, console=False)
        self.assertIsNotNone(path)
        self.assertEqual(path.parent, Path(self.tmp.name) / "AudioMaskPro" / "logs")
        logging.getLogger("audiomask.test").debug("hello file")
        for h in logging.getLogger().handlers:
            h.flush()
        self.assertIn("hello file", path.read_text(encoding="utf-8"))

    def test_home_fallback(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "LOCALAPPDATA"}
        env["HOME"] = self.tmp.name
        env["USERPROFILE"] = self.tmp.name
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("pathlib.Path.home", return_value=Path(self.tmp.name)):
                path = logging_setup.configure_logging(console=False)
        self.assertIsNotNone(path)
        self.assertEqual(path.parent, Path(self.tmp.name) / ".audiomask" / "logs")

    def test_idempotent(self) -> None:
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": self.tmp.name}):
            logging_setup.configure_logging(console=True)
            logging_setup.configure_logging(console=True)
        ours = [h for h in logging.getLogger().handlers
                if getattr(h, "_audiomask", False)]
        self.assertEqual(len(ours), 2)  # one console + one file

    def test_never_crashes_when_unwritable(self) -> None:
        with mock.patch.object(logging_setup, "get_log_dir", return_value=None):
            path = logging_setup.configure_logging(console=False)
        self.assertIsNone(path)

    def test_log_environment_reports_ffmpeg_backend(self) -> None:
        with self.assertLogs("audiomask.main", level="INFO") as cm:
            logging_setup.log_environment()
        self.assertTrue(any("FFmpeg backend:" in line for line in cm.output),
                        cm.output)

    def test_log_environment_does_not_raise(self) -> None:
        logging_setup.log_environment(logging.getLogger("audiomask.test"))


# --------------------------------------------------------------------------- #
# Engine hardening
# --------------------------------------------------------------------------- #
class EngineHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.masker = AudioMasker()

    # -- probe ------------------------------------------------------------
    def test_probe_wav(self) -> None:
        p = _write_wav(self.dir / "a.wav", seconds=1.0, channels=2)
        info = self.masker.probe(p)
        self.assertAlmostEqual(info["duration"], 1.0, places=2)
        self.assertEqual(info["sr"], SR)
        self.assertEqual(info["channels"], 2)
        self.assertGreater(info["size"], 0)

    def test_probe_missing(self) -> None:
        with self.assertRaises(AudioLoadError):
            self.masker.probe(self.dir / "nope.wav")

    def test_probe_empty_file(self) -> None:
        p = self.dir / "empty.wav"
        p.write_bytes(b"")
        with self.assertRaisesRegex(AudioLoadError, "empty"):
            self.masker.probe(p)

    def test_probe_garbage(self) -> None:
        p = self.dir / "garbage.wav"
        p.write_bytes(os.urandom(2048))
        with self.assertRaisesRegex(AudioLoadError, "Cannot read"):
            self.masker.probe(p)

    # -- load_audio -------------------------------------------------------
    def test_load_zero_length_audio(self) -> None:
        p = self.dir / "zero.wav"
        sf.write(str(p), np.zeros((0, 1), dtype=np.float32), SR)
        with self.assertRaisesRegex(AudioLoadError, "no audio"):
            self.masker.load_audio(p)

    def test_load_empty_file_via_process(self) -> None:
        p = self.dir / "empty.wav"
        p.write_bytes(b"")
        with self.assertRaisesRegex(AudioLoadError, "empty"):
            self.masker.process_file(p, self.dir)

    def test_load_scrubs_nan_inf(self) -> None:
        p = self.dir / "nan.wav"
        data = np.full(SR // 2, 0.25, dtype=np.float32)
        data[10] = np.nan
        data[20] = np.inf
        data[30] = -np.inf
        sf.write(str(p), data, SR, subtype="FLOAT")
        audio, sr = self.masker.load_audio(p)
        self.assertTrue(np.all(np.isfinite(audio)))
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(sr, SR)

    def test_max_duration_enforced(self) -> None:
        p = _write_wav(self.dir / "long.wav", seconds=2.5)
        strict = AudioMasker(max_duration_s=1.0)
        with self.assertRaisesRegex(AudioLoadError, "exceeds"):
            strict.load_audio(p)
        # Disabled guard loads fine
        AudioMasker(max_duration_s=None).load_audio(p)

    def test_max_duration_in_finalise(self) -> None:
        strict = AudioMasker(max_duration_s=1.0)
        audio = np.zeros(int(SR * 3), dtype=np.float32)
        with self.assertRaisesRegex(AudioLoadError, "exceeds"):
            strict._finalise_loaded(audio, SR)

    def test_loaded_dtype_float32(self) -> None:
        audio, _ = self.masker._finalise_loaded(
            np.ones(100, dtype=np.float64) * 0.1, SR)
        self.assertEqual(audio.dtype, np.float32)
        self.assertTrue(audio.flags["C_CONTIGUOUS"])

    # -- ffmpeg fallback --------------------------------------------------
    def test_ffmpeg_missing_binary(self) -> None:
        m = AudioMasker(ffmpeg_path="/definitely/not/ffmpeg")
        with self.assertRaisesRegex(AudioLoadError, "not found"):
            m._load_via_ffmpeg(self.dir / "x.mp3")

    def test_ffmpeg_timeout(self) -> None:
        import subprocess
        m = AudioMasker(ffmpeg_path="ffmpeg")
        with mock.patch("core.audio_engine.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("ffmpeg", 1)):
            with self.assertRaisesRegex(AudioLoadError, "timed out"):
                m._load_via_ffmpeg(self.dir / "x.mp3")

    def test_ffmpeg_nonzero_exit(self) -> None:
        m = AudioMasker(ffmpeg_path="ffmpeg")
        fake = mock.Mock(returncode=1, stderr="x.mp3: Invalid data found")
        with mock.patch("core.audio_engine.subprocess.run", return_value=fake):
            with self.assertRaisesRegex(AudioLoadError, "Invalid data"):
                m._load_via_ffmpeg(self.dir / "x.mp3")

    def test_decode_failure_mentions_ffmpeg_hint(self) -> None:
        p = self.dir / "bad.mp3"
        p.write_bytes(b"\xff\xfb" + os.urandom(4096))
        m = AudioMasker()
        m.ffmpeg_path = None  # force the "binary not found" branch
        with self.assertRaisesRegex(AudioLoadError, "FFmpeg"):
            m.load_audio(p)

    # -- write_audio ------------------------------------------------------
    def test_write_permission_error(self) -> None:
        with mock.patch("core.audio_engine.sf.write",
                        side_effect=PermissionError(13, "denied")):
            with self.assertRaisesRegex(AudioWriteError, "close it"):
                self.masker.write_audio(self.dir / "o.wav",
                                        np.zeros(10, np.float32), SR)

    def test_write_disk_full(self) -> None:
        with mock.patch("core.audio_engine.sf.write",
                        side_effect=OSError(28, "No space left")):
            with self.assertRaisesRegex(AudioWriteError, "disk may be full"):
                self.masker.write_audio(self.dir / "o.wav",
                                        np.zeros(10, np.float32), SR)

    def test_write_unwritable_dir(self) -> None:
        if os.name == "nt" or os.geteuid() == 0:  # root ignores chmod
            self.skipTest("permission test not meaningful here")
        ro = self.dir / "ro"
        ro.mkdir()
        ro.chmod(0o500)
        try:
            with self.assertRaises(AudioWriteError):
                self.masker.write_audio(ro / "o.wav",
                                        np.zeros(10, np.float32), SR)
        finally:
            ro.chmod(0o700)

    # -- process_array memory guard --------------------------------------
    def test_process_array_memoryerror_wrapped(self) -> None:
        from core.audio_engine import AudioEngineError
        with mock.patch.object(AudioMasker, "time_stretch",
                               side_effect=MemoryError()):
            with self.assertRaisesRegex(AudioEngineError, "Out of memory"):
                self.masker.process_array(np.zeros(1000, np.float32), SR,
                                          MaskSettings(speed_factor=1.05))


# --------------------------------------------------------------------------- #
# UI pure helpers (no Tk)
# --------------------------------------------------------------------------- #
class UiHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ui import app_ui  # noqa: F401
        except Exception as exc:  # noqa: BLE001 - customtkinter missing
            raise unittest.SkipTest(f"ui module not importable: {exc}")
        cls.ui = app_ui

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_settings_round_trip(self) -> None:
        s = self.ui.settings_from_values(
            pitch=1.2345, speed=1.03456, reverb_on=1, reverb_mix=0.1849,
            bp_on=0, bp_int=0.75, fmt="flac")
        self.assertIsInstance(s, MaskSettings)
        self.assertEqual(s.pitch_semitones, 1.23)
        self.assertEqual(s.speed_factor, 1.035)
        self.assertTrue(s.reverb_enabled)
        self.assertEqual(s.reverb_mix, 0.185)
        self.assertFalse(s.bandpass_enabled)
        self.assertEqual(s.bandpass_intensity, 0.75)
        self.assertEqual(s.output_format, "flac")

    def test_settings_clamped_and_format_fallback(self) -> None:
        s = self.ui.settings_from_values(
            pitch=99, speed=0.1, reverb_on=True, reverb_mix=5,
            bp_on=True, bp_int=-1, fmt="xyz")
        self.assertEqual(s.pitch_semitones, 4.0)
        self.assertEqual(s.speed_factor, 0.90)
        self.assertEqual(s.reverb_mix, 1.0)
        self.assertEqual(s.bandpass_intensity, 0.0)
        self.assertEqual(s.output_format, "wav")

    def test_overwrite_conflicts(self) -> None:
        src = _write_wav(self.dir / "song.wav")
        s = MaskSettings(output_format="wav")
        self.assertEqual(self.ui.find_overwrite_conflicts([src], self.dir, s), [])
        (self.dir / "song_masked.wav").write_bytes(b"x")
        self.assertEqual(self.ui.find_overwrite_conflicts([src], self.dir, s),
                         [src])

    def test_dir_is_writable(self) -> None:
        self.assertTrue(self.ui.dir_is_writable(self.dir))
        self.assertTrue(self.ui.dir_is_writable(self.dir / "new" / "nested"))
        if os.name != "nt" and os.geteuid() != 0:
            ro = self.dir / "ro"
            ro.mkdir()
            ro.chmod(0o500)
            try:
                self.assertFalse(self.ui.dir_is_writable(ro))
            finally:
                ro.chmod(0o700)

    def test_open_in_file_browser_never_raises(self) -> None:
        with mock.patch("ui.app_ui.subprocess.Popen", side_effect=OSError("no")):
            with mock.patch("ui.app_ui.sys.platform", "linux"):
                self.assertFalse(self.ui.open_in_file_browser(self.dir))

    # -- F2: FFmpeg banner + universal-format dialog ----------------------
    def test_ffmpeg_status_line_bundled(self) -> None:
        from core.ffmpeg_locator import FFmpegInfo
        info = FFmpegInfo(path=r"C:\App\_internal\bin\ffmpeg.exe",
                          source="bundled", version="7.1")
        masker = mock.Mock(ffmpeg_available=True, ffmpeg_info=info,
                           ffmpeg_path=info.path)
        msg, ok = self.ui.ffmpeg_status_line(masker)
        self.assertTrue(ok)
        self.assertTrue(msg.startswith("[INFO] FFmpeg backend: "), msg)
        self.assertIn("Bundled", msg)
        self.assertIn("7.1", msg)
        self.assertIn(info.path, msg)

    def test_ffmpeg_status_line_system_path(self) -> None:
        from core.ffmpeg_locator import FFmpegInfo
        info = FFmpegInfo(path="/usr/bin/ffmpeg", source="path", version="6.0")
        masker = mock.Mock(ffmpeg_available=True, ffmpeg_info=info,
                           ffmpeg_path=info.path)
        msg, ok = self.ui.ffmpeg_status_line(masker)
        self.assertTrue(ok)
        self.assertTrue(msg.startswith("[INFO] FFmpeg backend: "), msg)
        self.assertIn("System PATH", msg)

    def test_ffmpeg_status_line_found_without_info(self) -> None:
        # Explicit ffmpeg_path injected into AudioMasker -> no FFmpegInfo.
        masker = mock.Mock(ffmpeg_available=True, ffmpeg_info=None,
                           ffmpeg_path="/opt/ffmpeg")
        msg, ok = self.ui.ffmpeg_status_line(masker)
        self.assertTrue(ok)
        self.assertEqual(msg, "[INFO] FFmpeg backend: Found -> /opt/ffmpeg")

    def test_ffmpeg_status_line_missing(self) -> None:
        masker = mock.Mock(ffmpeg_available=False, ffmpeg_info=None,
                           ffmpeg_path=None)
        msg, ok = self.ui.ffmpeg_status_line(masker)
        self.assertFalse(ok)
        self.assertTrue(msg.startswith("[WARN] FFmpeg backend: not found"), msg)
        self.assertIn("bin/ffmpeg.exe", msg)

    def test_ffmpeg_status_line_real_masker(self) -> None:
        msg, ok = self.ui.ffmpeg_status_line(AudioMasker())
        self.assertIsInstance(msg, str)
        self.assertTrue(msg.startswith("[INFO]") or msg.startswith("[WARN]"))
        self.assertEqual(ok, msg.startswith("[INFO]"))

    def test_file_dialog_filetypes_cover_all_supported(self) -> None:
        from core.audio_engine import (COMPRESSED_INPUT_EXTENSIONS,
                                       SUPPORTED_INPUT_EXTENSIONS,
                                       VIDEO_CONTAINER_EXTENSIONS)
        types = self.ui.build_file_dialog_filetypes()
        self.assertGreaterEqual(len(types), 3)
        for label, pattern in types:
            self.assertIsInstance(label, str)
            self.assertIsInstance(pattern, str)
            self.assertTrue(pattern)
        all_label, all_pattern = types[0]
        self.assertIn("All media", all_label)
        pats = set(all_pattern.split())
        for ext in SUPPORTED_INPUT_EXTENSIONS:
            self.assertIn(f"*{ext}", pats)
        for must in ("*.m4a", "*.aac", "*.wma", "*.ogg", "*.flac", "*.mp4",
                     "*.mkv", "*.mp3", "*.wav"):
            self.assertIn(must, pats)
        # dedicated groups exist and are populated from the engine tables
        joined = {lbl: set(p.split()) for lbl, p in types}
        comp = next(v for k, v in joined.items() if "M4A" in k)
        vid = next(v for k, v in joined.items() if k.startswith("Video"))
        self.assertEqual(comp, {f"*{e}" for e in COMPRESSED_INPUT_EXTENSIONS})
        self.assertEqual(vid, {f"*{e}" for e in VIDEO_CONTAINER_EXTENSIONS})
        self.assertEqual(types[-1], ("All files", "*.*"))

    def test_classify_input_path_never_rejects(self) -> None:
        c = self.ui.classify_input_path
        for name in ("a.m4a", "b.AAC", "c.ogg", "d.flac", "e.wma", "f.mp4",
                     "g.MKV", "h.wav", "i.mp3", "j.webm", "k.opus"):
            self.assertEqual(c(Path(name)), "supported", name)
        self.assertEqual(c(Path("weird.xyz")), "unknown")
        self.assertEqual(c(Path("noext")), "unknown")

    def test_add_files_accepts_compressed_and_unknown(self) -> None:
        """Run ``AudioMaskApp.add_files`` without constructing a Tk window."""
        app = self.ui.AudioMaskApp.__new__(self.ui.AudioMaskApp)
        app._files = []
        app._refresh_file_box = lambda: None
        logs: list = []
        app.log = logs.append
        files = [self.dir / "song.m4a", self.dir / "clip.mp4",
                 self.dir / "odd.xyz", self.dir / "song.m4a"]
        for f in files[:3]:
            f.write_bytes(b"\0")
        added = app.add_files(files)
        self.assertEqual(added, 3)             # duplicate ignored, none rejected
        self.assertEqual([p.name for p in app._files],
                         ["song.m4a", "clip.mp4", "odd.xyz"])
        self.assertTrue(any("odd.xyz" in m and "FFmpeg" in m for m in logs))
        self.assertFalse(any("unsupported" in m.lower() for m in logs))
        # folders are skipped
        sub = self.dir / "folder"
        sub.mkdir()
        self.assertEqual(app.add_files([sub]), 0)


# --------------------------------------------------------------------------- #
# main.py --selftest (packaging gate, Task F3)
# --------------------------------------------------------------------------- #
class SelftestTests(unittest.TestCase):
    """``main._selftest`` is the gate run by build.bat / build.sh on the frozen
    exe. It must report the FFmpeg backend, pass without FFmpeg (warning only)
    and, when FFmpeg is available, prove the M4A round-trip."""

    @classmethod
    def setUpClass(cls):
        import importlib
        cls.main = importlib.import_module("main")
        cls.ffmpeg = AudioMasker().ffmpeg_path

    def _run(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        log = logging.getLogger("audiomask.test.selftest")
        with redirect_stdout(buf):
            rc = self.main._selftest(log)
        return rc, buf.getvalue()

    def test_selftest_passes_and_reports_backend(self):
        rc, out = self._run()
        self.assertEqual(rc, 0, out)
        self.assertIn("SELFTEST FFmpeg backend:", out)
        self.assertIn("SELFTEST DSP pipeline OK", out)
        self.assertIn("SELFTEST OK:", out)
        if self.ffmpeg:
            self.assertIn("M4A round-trip OK", out)
            self.assertNotIn("[ffmpeg: none]", out)
        else:
            self.assertIn("no FFmpeg backend", out)
            self.assertIn("[ffmpeg: none]", out)

    def test_selftest_without_ffmpeg_is_warning_not_failure(self):
        from core import ffmpeg_locator
        with mock.patch.object(ffmpeg_locator, "find_ffmpeg", return_value=None), \
                mock.patch.object(ffmpeg_locator, "describe",
                                  return_value="FFmpeg backend: NOT FOUND (test)"), \
                mock.patch("shutil.which", return_value=None):
            rc, out = self._run()
        self.assertEqual(rc, 0, out)
        self.assertIn("NOT FOUND (test)", out)
        self.assertIn("no FFmpeg backend", out)
        self.assertIn("[ffmpeg: none]", out)
        self.assertNotIn("M4A round-trip", out)

    def test_selftest_roundtrip_failure_is_exit_3(self):
        if not self.ffmpeg:
            self.skipTest("FFmpeg not available")
        with mock.patch.object(self.main, "_selftest_ffmpeg_roundtrip",
                               side_effect=RuntimeError("boom m4a")):
            rc, out = self._run()
        self.assertEqual(rc, 3)
        self.assertIn("SELFTEST DSP pipeline OK", out)
        self.assertNotIn("SELFTEST OK:", out)

    def test_roundtrip_helper_decodes_m4a(self):
        if not self.ffmpeg:
            self.skipTest("FFmpeg not available")
        import shutil
        masker = AudioMasker()
        n = int(1.0 * SR)
        tone = (0.3 * np.sin(2 * np.pi * 440 * np.arange(n) / SR)).astype(np.float32)
        tmp = Path(tempfile.mkdtemp(prefix="am_rt_"))
        try:
            msg = self.main._selftest_ffmpeg_roundtrip(
                logging.getLogger("audiomask.test"), masker, tone, SR, tmp)
            self.assertIn("M4A round-trip OK", msg)
            self.assertTrue((tmp / "ffmpeg_roundtrip.m4a").is_file())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
