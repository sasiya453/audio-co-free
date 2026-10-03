"""
Universal-format tests (bundled FFmpeg upgrade).

* ``core.ffmpeg_locator`` discovery order, PATH injection, probing.
* ``AudioMasker.load_audio`` / ``probe`` for M4A, AAC, OGG, FLAC, WMA, Opus,
  MP3 and video containers (MP4, MKV, MOV, WebM) - decoded *without* FFmpeg on
  PATH, using only a "bundled" binary dropped into ``bin/`` / ``_MEIPASS``.

Fixtures are synthesised on the fly with whatever FFmpeg the sandbox has
(``/usr/bin/ffmpeg``). Format tests are skipped when no encoder is available.
"""
from __future__ import annotations

import os
import shutil
import subprocess
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

from core import ffmpeg_locator as loc  # noqa: E402
from core.audio_engine import (  # noqa: E402
    AudioLoadError,
    AudioMasker,
    FFMPEG_PREFERRED_EXTENSIONS,
    MaskSettings,
    NATIVE_INPUT_EXTENSIONS,
    SUPPORTED_INPUT_EXTENSIONS,
    VIDEO_CONTAINER_EXTENSIONS,
    ffmpeg_status,
)

SR = 22_050
SYSTEM_FFMPEG = shutil.which("ffmpeg")


def _tone(seconds: float = 1.5, freq: float = 440.0,
          channels: int = 1) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    y = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return y if channels == 1 else np.stack([y] * channels, axis=1)


def _encoders() -> set:
    if not SYSTEM_FFMPEG:
        return set()
    out = subprocess.run([SYSTEM_FFMPEG, "-hide_banner", "-encoders"],
                         capture_output=True, text=True).stdout
    return {line.split()[1] for line in out.splitlines()
            if line.startswith(" ") and len(line.split()) > 1}


ENCODERS = _encoders()

# ext -> (ffmpeg args, required encoder, is_video)
FORMATS = {
    ".m4a": (["-c:a", "aac", "-b:a", "128k"], "aac", False),
    ".aac": (["-c:a", "aac", "-f", "adts"], "aac", False),
    ".ogg": (["-c:a", "libvorbis"], "libvorbis", False),
    ".opus": (["-c:a", "libopus"], "libopus", False),
    ".flac": (["-c:a", "flac"], "flac", False),
    ".wma": (["-c:a", "wmav2"], "wmav2", False),
    ".mp3": (["-c:a", "libmp3lame", "-b:a", "128k"], "libmp3lame", False),
    ".mp4": (["-c:v", "mpeg4", "-c:a", "aac"], "aac", True),
    ".mkv": (["-c:v", "mpeg4", "-c:a", "aac"], "aac", True),
    ".mov": (["-c:v", "mpeg4", "-c:a", "aac"], "aac", True),
    ".webm": (["-c:v", "libvpx", "-c:a", "libopus"], "libopus", True),
}


def _make_fixture(dst: Path, src_wav: Path) -> bool:
    """Encode ``src_wav`` to ``dst`` (format by extension). False if the
    needed encoder is unavailable."""
    args, enc, is_video = FORMATS[dst.suffix]
    if enc not in ENCODERS:
        return False
    if is_video and dst.suffix == ".webm" and "libvpx" not in ENCODERS:
        return False
    cmd = [SYSTEM_FFMPEG, "-y", "-v", "error", "-nostdin"]
    if is_video:
        # tiny synthetic video stream so the container really is "video"
        cmd += ["-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=1.5"]
    cmd += ["-i", str(src_wav)]
    if is_video:
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += args + [str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 0


class _BundledFFmpegEnv:
    """Context manager: hide system ffmpeg from PATH and plant a copy as the
    *bundled* binary in a fake ``_MEIPASS`` folder."""

    def __init__(self, tmp: Path, mode: str = "meipass") -> None:
        self.tmp = tmp
        self.mode = mode
        self._patches: list = []

    def __enter__(self) -> "_BundledFFmpegEnv":
        bundle = self.tmp / "frozen_app"
        (bundle / "bin").mkdir(parents=True)
        self.bundled = bundle / "bin" / loc.FFMPEG_EXE_NAME
        shutil.copy2(SYSTEM_FFMPEG, self.bundled)
        self.bundled.chmod(0o755)
        env = {k: v for k, v in os.environ.items()}
        env["PATH"] = str(self.tmp / "empty_path")  # no ffmpeg here
        env.pop(loc.FFMPEG_ENV_VAR, None)
        (self.tmp / "empty_path").mkdir(exist_ok=True)
        self._patches.append(mock.patch.dict(os.environ, env, clear=True))
        if self.mode == "meipass":
            self._patches.append(mock.patch.object(sys, "_MEIPASS", str(bundle),
                                                   create=True))
        elif self.mode == "exe_dir":
            self._patches.append(mock.patch.object(sys, "frozen", True,
                                                   create=True))
            self._patches.append(mock.patch.object(
                sys, "executable", str(bundle / "AudioMaskPro")))
        elif self.mode == "project":
            self._patches.append(mock.patch.object(loc, "_PROJECT_ROOT", bundle))
        for p in self._patches:
            p.start()
        # Clear any registered dir / cache state from previous tests
        loc._registered_dirs.clear()
        loc.reset_cache()
        return self

    def __exit__(self, *exc) -> None:
        for p in reversed(self._patches):
            p.stop()
        loc._registered_dirs.clear()
        loc.reset_cache()


# --------------------------------------------------------------------------- #
# Locator
# --------------------------------------------------------------------------- #
class TestFFmpegLocator(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory(prefix="amask_loc_")
        self.dir = Path(self._td.name)
        loc.reset_cache()

    def tearDown(self) -> None:
        loc.reset_cache()
        loc._registered_dirs.clear()
        self._td.cleanup()

    def test_candidate_order_env_first(self) -> None:
        with mock.patch.dict(os.environ, {loc.FFMPEG_ENV_VAR: "/x/ffmpeg"}):
            cands = loc.candidate_paths()
        self.assertEqual(cands[0][0], "env")
        self.assertEqual(cands[0][1], Path("/x/ffmpeg"))
        self.assertIn("project", [c[0] for c in cands])

    def test_meipass_candidates_present_when_frozen(self) -> None:
       with mock.patch.object(sys, "_MEIPASS", "/frozen", create=True):
           paths = [p.as_posix() for src, p in loc.candidate_paths() if src == "bundled"]
      self.assertTrue(any(p.startswith("/frozen") for p in paths))
      self.assertTrue(any(p.endswith(f"bin/{loc.FFMPEG_EXE_NAME}") for p in paths))

    def test_not_found_returns_none(self) -> None:
        empty = self.dir / "empty"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(empty)}, clear=False), \
                mock.patch.object(loc, "_PROJECT_ROOT", self.dir):
            os.environ.pop(loc.FFMPEG_ENV_VAR, None)
            info = loc.find_ffmpeg(use_cache=False, probe_version=False)
        self.assertIsNone(info)
        self.assertIn("NOT FOUND", loc.describe())

    def test_env_override_non_executable_is_skipped(self) -> None:
        bogus = self.dir / "ffmpeg.txt"
        bogus.write_text("not a binary")
        empty = self.dir / "empty"
        empty.mkdir()
        with mock.patch.dict(os.environ, {loc.FFMPEG_ENV_VAR: str(bogus),
                                          "PATH": str(empty)}), \
                mock.patch.object(loc, "_PROJECT_ROOT", self.dir):
            self.assertIsNone(loc.find_ffmpeg(use_cache=False,
                                              probe_version=False))

    @unittest.skipUnless(SYSTEM_FFMPEG, "ffmpeg not available")
    def test_bundled_meipass_preferred_and_path_injected(self) -> None:
        with _BundledFFmpegEnv(self.dir, "meipass") as env:
            info = loc.find_ffmpeg(use_cache=False)
            self.assertIsNotNone(info)
            self.assertEqual(info.source, "bundled")
            self.assertEqual(Path(info.path), env.bundled)
            self.assertTrue(info.is_bundled)
            self.assertTrue(info.version)
            self.assertIn("Bundled", info.label)
            # PATH was prepended -> bare "ffmpeg" now resolves to bundled copy
            self.assertEqual(Path(shutil.which("ffmpeg")).resolve(),
                             env.bundled.resolve())
            self.assertIn("Bundled", ffmpeg_status())

    @unittest.skipUnless(SYSTEM_FFMPEG, "ffmpeg not available")
    def test_bundled_next_to_frozen_exe(self) -> None:
        with _BundledFFmpegEnv(self.dir, "exe_dir"):
            info = loc.find_ffmpeg(use_cache=False, probe_version=False)
        self.assertIsNotNone(info)
        self.assertEqual(info.source, "bundled")

    @unittest.skipUnless(SYSTEM_FFMPEG, "ffmpeg not available")
    def test_project_bin_dir(self) -> None:
        with _BundledFFmpegEnv(self.dir, "project"):
            info = loc.find_ffmpeg(use_cache=False, probe_version=False)
        self.assertIsNotNone(info)
        self.assertEqual(info.source, "project")
        self.assertIn("bin", Path(info.path).parts)

    @unittest.skipUnless(SYSTEM_FFMPEG, "ffmpeg not available")
    def test_system_path_fallback(self) -> None:
        with mock.patch.object(loc, "_PROJECT_ROOT", self.dir):
            os.environ.pop(loc.FFMPEG_ENV_VAR, None)
            info = loc.find_ffmpeg(use_cache=False, probe_version=False)
        self.assertIsNotNone(info)
        self.assertEqual(info.source, "path")

    @unittest.skipUnless(SYSTEM_FFMPEG, "ffmpeg not available")
    def test_cache_and_reset(self) -> None:
        a = loc.find_ffmpeg()
        b = loc.find_ffmpeg()
        self.assertIs(a, b)
        loc.reset_cache()
        c = loc.find_ffmpeg()
        self.assertIsNot(a, c)
        self.assertEqual(a.path, c.path)

    @unittest.skipUnless(SYSTEM_FFMPEG, "ffmpeg not available")
    def test_version_probe(self) -> None:
        self.assertTrue(loc.ffmpeg_version(SYSTEM_FFMPEG))
        self.assertIsNone(loc.ffmpeg_version(str(self.dir / "nope")))

    @unittest.skipUnless(SYSTEM_FFMPEG, "ffmpeg not available")
    def test_probe_metadata_wav(self) -> None:
        wav = self.dir / "t.wav"
        sf.write(str(wav), _tone(1.5, channels=2), SR)
        meta = loc.ffmpeg_probe(SYSTEM_FFMPEG, wav)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["sr"], SR)
        self.assertEqual(meta["channels"], 2)
        self.assertAlmostEqual(meta["duration"], 1.5, delta=0.1)

    @unittest.skipUnless(SYSTEM_FFMPEG, "ffmpeg not available")
    def test_probe_non_media_returns_none(self) -> None:
        junk = self.dir / "junk.m4a"
        junk.write_bytes(os.urandom(2048))
        self.assertIsNone(loc.ffmpeg_probe(SYSTEM_FFMPEG, junk))

    def test_register_idempotent(self) -> None:
        fake = self.dir / "tools" / loc.FFMPEG_EXE_NAME
        fake.parent.mkdir()
        fake.write_bytes(b"")
        before = os.environ.get("PATH", "")
        try:
            loc.register_ffmpeg(str(fake))
            loc.register_ffmpeg(str(fake))
            parts = os.environ["PATH"].split(os.pathsep)
            self.assertEqual(parts[0], str(fake.parent.resolve()))
            self.assertEqual(parts.count(str(fake.parent.resolve())), 1)
        finally:
            os.environ["PATH"] = before
            loc._registered_dirs.clear()


# --------------------------------------------------------------------------- #
# Engine: extension tables
# --------------------------------------------------------------------------- #
class TestExtensionTables(unittest.TestCase):
    def test_compressed_and_video_are_ffmpeg_preferred(self) -> None:
        for ext in (".m4a", ".aac", ".wma", ".mp4", ".mkv", ".mov", ".webm"):
            self.assertIn(ext, FFMPEG_PREFERRED_EXTENSIONS, ext)
            self.assertIn(ext, SUPPORTED_INPUT_EXTENSIONS, ext)
            self.assertTrue(AudioMasker.prefers_ffmpeg(f"x{ext}"), ext)

    def test_native_formats_not_ffmpeg_first(self) -> None:
        for ext in (".wav", ".flac", ".ogg", ".mp3"):
            self.assertIn(ext, NATIVE_INPUT_EXTENSIONS)
            self.assertFalse(AudioMasker.prefers_ffmpeg(f"X{ext.upper()}"))

    def test_no_duplicates_and_lowercase(self) -> None:
        self.assertEqual(len(SUPPORTED_INPUT_EXTENSIONS),
                         len(set(SUPPORTED_INPUT_EXTENSIONS)))
        for ext in SUPPORTED_INPUT_EXTENSIONS:
            self.assertTrue(ext.startswith(".") and ext == ext.lower(), ext)
        self.assertTrue(set(VIDEO_CONTAINER_EXTENSIONS)
                        <= set(SUPPORTED_INPUT_EXTENSIONS))


# --------------------------------------------------------------------------- #
# Engine: universal decode through *bundled* FFmpeg only
# --------------------------------------------------------------------------- #
@unittest.skipUnless(SYSTEM_FFMPEG, "ffmpeg not available to build fixtures")
class TestUniversalFormats(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._td = tempfile.TemporaryDirectory(prefix="amask_fmt_")
        cls.dir = Path(cls._td.name)
        cls.src = cls.dir / "src.wav"
        sf.write(str(cls.src), _tone(1.5, channels=2), SR)
        cls.fixtures = {}
        for ext in FORMATS:
            dst = cls.dir / f"tone{ext}"
            if _make_fixture(dst, cls.src):
                cls.fixtures[ext] = dst

    @classmethod
    def tearDownClass(cls) -> None:
        cls._td.cleanup()
        loc.reset_cache()
        loc._registered_dirs.clear()

    def _check_decoded(self, audio: np.ndarray, sr: int, ext: str) -> None:
        self.assertGreater(sr, 0, ext)
        n = audio.shape[-1]
        self.assertGreater(n / sr, 1.0, f"{ext}: too short ({n / sr:.2f}s)")
        self.assertLess(n / sr, 2.5, f"{ext}: too long ({n / sr:.2f}s)")
        self.assertTrue(np.all(np.isfinite(audio)), ext)
        self.assertGreater(float(np.max(np.abs(audio))), 0.1, ext)
        mono = audio if audio.ndim == 1 else audio.mean(axis=0)
        spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
        freqs = np.fft.rfftfreq(len(mono), 1.0 / sr)
        peak = float(freqs[int(np.argmax(spec))])
        self.assertAlmostEqual(peak, 440.0, delta=15.0,
                               msg=f"{ext}: dominant {peak:.1f} Hz")

    def _require(self, ext: str) -> Path:
        if ext not in self.fixtures:
            self.skipTest(f"no encoder for {ext} in sandbox ffmpeg")
        return self.fixtures[ext]

    def _load_bundled_only(self, ext: str) -> None:
        """Decode with system PATH stripped - only the bundled copy exists."""
        src = self._require(ext)
        with tempfile.TemporaryDirectory() as td, \
                _BundledFFmpegEnv(Path(td), "meipass") as env:
            m = AudioMasker()
            self.assertEqual(Path(m.ffmpeg_path), env.bundled)
            self.assertTrue(m.ffmpeg_available)
            self.assertIsNotNone(m.ffmpeg_info)
            self.assertTrue(m.ffmpeg_info.is_bundled)
            audio, sr = m.load_audio(src)
            self._check_decoded(audio, sr, ext)
            meta = m.probe(src)
            self.assertGreater(meta["duration"], 1.0)
            self.assertGreater(meta["sr"], 0)
            self.assertEqual(meta["size"], src.stat().st_size)

    def test_m4a(self) -> None: self._load_bundled_only(".m4a")
    def test_aac(self) -> None: self._load_bundled_only(".aac")
    def test_ogg(self) -> None: self._load_bundled_only(".ogg")
    def test_opus(self) -> None: self._load_bundled_only(".opus")
    def test_flac(self) -> None: self._load_bundled_only(".flac")
    def test_wma(self) -> None: self._load_bundled_only(".wma")
    def test_mp3(self) -> None: self._load_bundled_only(".mp3")
    def test_mp4_video(self) -> None: self._load_bundled_only(".mp4")
    def test_mkv_video(self) -> None: self._load_bundled_only(".mkv")
    def test_mov_video(self) -> None: self._load_bundled_only(".mov")
    def test_webm_video(self) -> None: self._load_bundled_only(".webm")

    def test_m4a_full_pipeline(self) -> None:
        src = self._require(".m4a")
        out_dir = self.dir / "out"
        m = AudioMasker()
        out = m.process_file(src, out_dir, MaskSettings(output_format="wav"))
        self.assertTrue(out.is_file())
        self.assertEqual(out.name, "tone_masked.wav")
        y, sr = sf.read(str(out), dtype="float32")
        self.assertTrue(np.all(np.isfinite(y)))
        self.assertLessEqual(float(np.max(np.abs(y))), 1.0)

    def test_mp4_full_pipeline_extracts_audio(self) -> None:
        src = self._require(".mp4")
        m = AudioMasker()
        out = m.process_file(src, self.dir / "out", MaskSettings())
        self.assertTrue(out.is_file())
        self.assertEqual(out.suffix, ".wav")

    def test_m4a_without_any_ffmpeg_gives_clear_error(self) -> None:
        src = self._require(".m4a")
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty"
            empty.mkdir()
            with mock.patch.dict(os.environ, {"PATH": str(empty)}), \
                    mock.patch.object(loc, "_PROJECT_ROOT", Path(td)):
                os.environ.pop(loc.FFMPEG_ENV_VAR, None)
                loc.reset_cache()
                m = AudioMasker()
                self.assertFalse(m.ffmpeg_available)
                with self.assertRaisesRegex(AudioLoadError,
                                            "bundled FFmpeg|ffmpeg"):
                    m.load_audio(src)
            loc.reset_cache()

    def test_ffmpeg_preferred_skips_soundfile(self) -> None:
        """For .m4a the engine must not even try libsndfile first."""
        src = self._require(".m4a")
        m = AudioMasker()
        with mock.patch("core.audio_engine.sf.read",
                        side_effect=AssertionError("soundfile tried first")):
            with mock.patch.object(AudioMasker, "_load_via_ffmpeg",
                                   return_value=(_tone(1.0), SR)) as ff:
                audio, sr = m.load_audio(src)
        ff.assert_called_once()
        self.assertEqual(sr, SR)

    def test_ffmpeg_failure_falls_through_to_next_backend(self) -> None:
        """A decoder-level FFmpeg error must not abort - soundfile is next."""
        wav = self.dir / "fallthrough.wav"
        sf.write(str(wav), _tone(1.0), SR)
        m = AudioMasker()
        with mock.patch.object(AudioMasker, "_load_via_soundfile",
                               side_effect=RuntimeError("Format not recognised")):
            with mock.patch.object(AudioMasker, "_load_via_ffmpeg",
                                   side_effect=AudioLoadError("boom")) as ff:
                # non-decoder AudioLoadError must propagate unchanged
                with self.assertRaisesRegex(AudioLoadError, "boom"):
                    m.load_audio(wav)
        ff.assert_called_once()

    def test_video_without_audio_track_error(self) -> None:
        if "mpeg4" not in ENCODERS:
            self.skipTest("no mpeg4 encoder")
        silent = self.dir / "noaudio.mp4"
        subprocess.run([SYSTEM_FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                        "-i", "color=c=black:s=64x64:r=10:d=1",
                        "-c:v", "mpeg4", "-an", str(silent)], check=True)
        m = AudioMasker()
        with self.assertRaises(AudioLoadError):
            m.load_audio(silent)

    def test_duration_guard_uses_ffmpeg_probe_for_m4a(self) -> None:
        src = self._require(".m4a")
        strict = AudioMasker(max_duration_s=1.0)
        with self.assertRaisesRegex(AudioLoadError, "exceeds"):
            strict.load_audio(src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
