"""
AudioMask Pro - Core DSP Engine
================================

Headless audio-processing engine. Loads an audio file (MP3 / WAV / FLAC / OGG
and anything else libsndfile or FFmpeg can decode), runs the full masking DSP
chain and writes the result to disk.

Pipeline (in order):
    1. Time stretch        (librosa.effects.time_stretch)
    2. Pitch shift         (librosa.effects.pitch_shift)
    3. Butterworth bandpass (scipy.signal.butter -> sosfilt, 4th order)
    4. Micro-reverb        (short delay-line feedback loop, ~30 ms)
    5. Peak normalisation  (prevents digital clipping)

The engine is UI-agnostic. Progress is reported through an optional callback
``progress_cb(fraction: float, message: str)`` so a GUI can drive a progress
bar from a worker thread without this module importing any GUI code.

Typical use::

    from core.audio_engine import AudioMasker, MaskSettings

    masker = AudioMasker()
    out = masker.process_file(
        "song.mp3",
        "out_dir",
        MaskSettings(pitch_semitones=1.5, speed_factor=1.04),
    )
"""

from __future__ import annotations

import gc
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np

try:
    import soundfile as sf
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "soundfile is required: pip install soundfile"
    ) from exc

try:
    import librosa
    import librosa.effects
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError("librosa is required: pip install librosa") from exc

try:
    from scipy import signal as sps
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError("scipy is required: pip install scipy") from exc


__all__ = [
    "AudioMasker",
    "MaskSettings",
    "AudioEngineError",
    "AudioLoadError",
    "AudioWriteError",
    "SUPPORTED_INPUT_EXTENSIONS",
    "SUPPORTED_OUTPUT_FORMATS",
]

logger = logging.getLogger("audiomask.engine")

# File types we will attempt to open. soundfile covers most; MP3 falls back to
# librosa/audioread or FFmpeg depending on the platform build.
SUPPORTED_INPUT_EXTENSIONS: Tuple[str, ...] = (
    ".wav", ".flac", ".mp3", ".ogg", ".oga", ".opus", ".aiff", ".aif",
    ".m4a", ".aac", ".wma", ".mp4",
)

# Output container -> soundfile subtype. MP3 is only available if the bundled
# libsndfile is >= 1.1.0 (soundfile >= 0.12); we verify at runtime.
SUPPORTED_OUTPUT_FORMATS = {
    "wav": "PCM_16",
    "flac": "PCM_16",
    "ogg": "VORBIS",
    "mp3": "MPEG_LAYER_III",
}

ProgressCallback = Callable[[float, str], None]


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #
class AudioEngineError(Exception):
    """Base class for all engine errors."""


class AudioLoadError(AudioEngineError):
    """Raised when an input file cannot be decoded."""


class AudioWriteError(AudioEngineError):
    """Raised when the processed audio cannot be written."""


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@dataclass
class MaskSettings:
    """
    All tunable parameters for one processing run.

    Attributes
    ----------
    pitch_semitones : float
        Pitch shift in semitones (fractional allowed). Range -4.0 .. +4.0.
    speed_factor : float
        Playback-rate multiplier. >1.0 = faster/shorter. Range 0.90 .. 1.15.
    bandpass_enabled : bool
        Apply the 4th-order Butterworth bandpass filter.
    bandpass_low_hz : float
        Lower cut-off frequency of the bandpass filter.
    bandpass_high_hz : float
        Upper cut-off frequency of the bandpass filter.
    bandpass_intensity : float
        Dry/wet mix for the filter. 0.0 = bypass, 1.0 = fully filtered.
    reverb_enabled : bool
        Apply the micro-reverb feedback delay.
    reverb_delay_ms : float
        Delay-line length in milliseconds (default 30 ms).
    reverb_feedback : float
        Feedback gain (0.0 .. <1.0). Higher = longer tail.
    reverb_mix : float
        Wet/dry mix of the reverb (0.0 .. 1.0).
    normalize_peak_db : float
        Target peak level in dBFS after processing (e.g. -1.0).
    output_format : str
        One of SUPPORTED_OUTPUT_FORMATS keys.
    output_suffix : str
        Text appended to the base filename of the output file.
    """

    pitch_semitones: float = 1.0
    speed_factor: float = 1.03
    bandpass_enabled: bool = True
    bandpass_low_hz: float = 80.0
    bandpass_high_hz: float = 14_000.0
    bandpass_intensity: float = 0.6
    reverb_enabled: bool = True
    reverb_delay_ms: float = 30.0
    reverb_feedback: float = 0.25
    reverb_mix: float = 0.18
    normalize_peak_db: float = -1.0
    output_format: str = "wav"
    output_suffix: str = "_masked"

    # Hard limits used for validation / UI slider bounds.
    LIMITS: dict = field(
        default_factory=lambda: {
            "pitch_semitones": (-4.0, 4.0),
            "speed_factor": (0.90, 1.15),
            "bandpass_intensity": (0.0, 1.0),
            "reverb_feedback": (0.0, 0.95),
            "reverb_mix": (0.0, 1.0),
            "reverb_delay_ms": (5.0, 120.0),
            "normalize_peak_db": (-12.0, 0.0),
        },
        repr=False,
        compare=False,
    )

    def validate(self) -> "MaskSettings":
        """Clamp every numeric field into its legal range and sanity-check
        the remaining fields. Returns ``self`` for chaining."""
        for name, (lo, hi) in self.LIMITS.items():
            val = float(getattr(self, name))
            clamped = min(max(val, lo), hi)
            if clamped != val:
                logger.warning("Setting %s=%s clamped to %s", name, val, clamped)
            setattr(self, name, clamped)

        if self.bandpass_low_hz <= 0:
            self.bandpass_low_hz = 20.0
        if self.bandpass_high_hz <= self.bandpass_low_hz:
            self.bandpass_high_hz = self.bandpass_low_hz * 2.0

        fmt = str(self.output_format).lower().lstrip(".")
        if fmt not in SUPPORTED_OUTPUT_FORMATS:
            logger.warning("Unknown output format %r, falling back to wav", fmt)
            fmt = "wav"
        self.output_format = fmt
        return self

    def to_dict(self) -> dict:
        """Serialisable representation (drops the LIMITS helper)."""
        d = asdict(self)
        d.pop("LIMITS", None)
        return d


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class AudioMasker:
    """
    Stateless DSP processor. One instance can be reused for many files; it
    holds no per-file state apart from a cancellation flag.

    Parameters
    ----------
    target_sr : int | None
        If given, audio is resampled to this rate on load. ``None`` keeps the
        native sample rate of the source file.
    ffmpeg_path : str | None
        Explicit path to an FFmpeg binary used as a decoding fallback for
        formats libsndfile cannot open (notably MP3 on older builds). If
        ``None`` the engine searches ``PATH``.
    """

    #: Progress fractions emitted at each pipeline stage.
    _STAGES = {
        "load": 0.05,
        "stretch": 0.30,
        "pitch": 0.60,
        "filter": 0.72,
        "reverb": 0.84,
        "normalize": 0.90,
        "write": 1.00,
    }

    def __init__(self, target_sr: Optional[int] = None,
                 ffmpeg_path: Optional[str] = None) -> None:
        self.target_sr = target_sr
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        self._cancel_requested = False
        logger.debug("AudioMasker initialised (ffmpeg=%s)", self.ffmpeg_path)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def cancel(self) -> None:
        """Request cancellation of the current ``process_file`` call. The
        pipeline checks the flag between stages."""
        self._cancel_requested = True

    def process_file(
        self,
        input_path: os.PathLike | str,
        output_dir: os.PathLike | str,
        settings: Optional[MaskSettings] = None,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> Path:
        """
        Run the complete pipeline on a single file.

        Parameters
        ----------
        input_path : path-like
            Source audio file.
        output_dir : path-like
            Directory where the processed file is written (created if absent).
        settings : MaskSettings, optional
            Processing parameters. Defaults are used when omitted.
        progress_cb : callable(fraction, message), optional
            Invoked at every stage boundary. Must be thread-safe if called
            from a worker thread (the GUI layer is responsible for marshalling
            to the main thread).

        Returns
        -------
        pathlib.Path
            Path to the written output file.

        Raises
        ------
        AudioLoadError, AudioWriteError, AudioEngineError
        """
        settings = (settings or MaskSettings()).validate()
        self._cancel_requested = False
        in_path = Path(input_path).expanduser().resolve()
        out_dir = Path(output_dir).expanduser().resolve()

        if not in_path.is_file():
            raise AudioLoadError(f"Input file not found: {in_path}")

        logger.info("Processing %s -> %s with %s", in_path.name, out_dir,
                    settings.to_dict())

        audio = None
        try:
            self._report(progress_cb, 0.0, f"Loading {in_path.name}")
            audio, sr = self.load_audio(in_path)
            self._report(progress_cb, self._STAGES["load"],
                         f"Loaded {audio.shape[-1] / sr:.1f}s @ {sr} Hz")

            audio = self.process_array(audio, sr, settings, progress_cb)

            self._check_cancel()
            out_path = self._build_output_path(in_path, out_dir, settings)
            self._report(progress_cb, self._STAGES["normalize"],
                         f"Writing {out_path.name}")
            self.write_audio(out_path, audio, sr, settings.output_format)
            self._report(progress_cb, self._STAGES["write"], "Done")
            logger.info("Wrote %s", out_path)
            return out_path
        finally:
            # Release large buffers eagerly - important when batch processing
            # inside a long-lived desktop app.
            del audio
            gc.collect()

    def process_array(
        self,
        audio: np.ndarray,
        sr: int,
        settings: Optional[MaskSettings] = None,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        """
        Run the DSP chain on an in-memory signal.

        Parameters
        ----------
        audio : np.ndarray
            Shape ``(n_samples,)`` for mono or ``(n_channels, n_samples)``
            for multichannel, float32/float64 in [-1, 1].
        sr : int
            Sample rate in Hz.

        Returns
        -------
        np.ndarray
            Processed float32 array with the same channel layout.
        """
        settings = (settings or MaskSettings()).validate()
        y = np.asarray(audio, dtype=np.float32)
        if y.ndim == 0 or y.size == 0:
            raise AudioEngineError("Audio buffer is empty")
        if y.ndim > 2:
            raise AudioEngineError(f"Unsupported array shape {y.shape}")

        # 1. Time stretch ------------------------------------------------- #
        self._check_cancel()
        if abs(settings.speed_factor - 1.0) > 1e-4:
            self._report(progress_cb, self._STAGES["load"],
                         f"Time-stretching x{settings.speed_factor:.3f}")
            y = self.time_stretch(y, settings.speed_factor)
        self._report(progress_cb, self._STAGES["stretch"], "Time stretch done")

        # 2. Pitch shift -------------------------------------------------- #
        self._check_cancel()
        if abs(settings.pitch_semitones) > 1e-4:
            self._report(progress_cb, self._STAGES["stretch"],
                         f"Pitch-shifting {settings.pitch_semitones:+.2f} st")
            y = self.pitch_shift(y, sr, settings.pitch_semitones)
        self._report(progress_cb, self._STAGES["pitch"], "Pitch shift done")

        # 3. Bandpass ----------------------------------------------------- #
        self._check_cancel()
        if settings.bandpass_enabled and settings.bandpass_intensity > 0:
            self._report(progress_cb, self._STAGES["pitch"],
                         "Applying Butterworth bandpass")
            y = self.bandpass_filter(
                y, sr,
                settings.bandpass_low_hz,
                settings.bandpass_high_hz,
                mix=settings.bandpass_intensity,
            )
        self._report(progress_cb, self._STAGES["filter"], "Filter done")

        # 4. Micro-reverb ------------------------------------------------- #
        self._check_cancel()
        if settings.reverb_enabled and settings.reverb_mix > 0:
            self._report(progress_cb, self._STAGES["filter"],
                         "Rendering micro-reverb")
            y = self.micro_reverb(
                y, sr,
                delay_ms=settings.reverb_delay_ms,
                feedback=settings.reverb_feedback,
                mix=settings.reverb_mix,
            )
        self._report(progress_cb, self._STAGES["reverb"], "Reverb done")

        # 5. Normalise ---------------------------------------------------- #
        self._check_cancel()
        y = self.normalize_peak(y, settings.normalize_peak_db)
        self._report(progress_cb, self._STAGES["normalize"], "Normalised")

        return np.ascontiguousarray(y, dtype=np.float32)

    # ------------------------------------------------------------------ #
    # I/O
    # ------------------------------------------------------------------ #
    def load_audio(self, path: os.PathLike | str) -> Tuple[np.ndarray, int]:
        """
        Decode an audio file to a float32 array.

        Returns ``(audio, sr)`` where ``audio`` is ``(n_samples,)`` for mono
        or ``(n_channels, n_samples)`` otherwise. Tries, in order:
        soundfile -> librosa/audioread -> FFmpeg transcode to temp WAV.
        """
        path = Path(path)
        if path.suffix.lower() not in SUPPORTED_INPUT_EXTENSIONS:
            logger.warning("Unrecognised extension %s - attempting anyway",
                           path.suffix)

        errors = []

        # Attempt 1: libsndfile (fast, handles WAV/FLAC/OGG, MP3 on new builds)
        try:
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
            audio = data.T  # (channels, samples)
            return self._finalise_loaded(audio, sr)
        except Exception as exc:  # noqa: BLE001 - try next decoder
            errors.append(f"soundfile: {exc}")

        # Attempt 2: librosa (may use audioread / ffmpeg under the hood)
        try:
            audio, sr = librosa.load(str(path), sr=None, mono=False)
            return self._finalise_loaded(np.atleast_1d(audio), int(sr))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"librosa: {exc}")

        # Attempt 3: explicit FFmpeg transcode
        if self.ffmpeg_path:
            try:
                audio, sr = self._load_via_ffmpeg(path)
                return self._finalise_loaded(audio, sr)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"ffmpeg: {exc}")
        else:
            errors.append("ffmpeg: binary not found on PATH")

        raise AudioLoadError(
            f"Could not decode '{path.name}'. The file may be corrupt or the "
            f"codec is unsupported. Details: " + " | ".join(errors)
        )

    def write_audio(self, path: os.PathLike | str, audio: np.ndarray,
                    sr: int, fmt: str = "wav") -> Path:
        """Write ``audio`` to ``path`` using soundfile. Creates parent dirs."""
        path = Path(path)
        fmt = fmt.lower().lstrip(".")
        subtype = SUPPORTED_OUTPUT_FORMATS.get(fmt, "PCM_16")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = np.asarray(audio, dtype=np.float32)
            if data.ndim == 2:
                data = data.T  # soundfile expects (samples, channels)
            # Verify the container/subtype pair is supported by this libsndfile
            if not sf.check_format(fmt.upper(), subtype):
                if fmt == "mp3":
                    raise AudioWriteError(
                        "This libsndfile build cannot encode MP3. "
                        "Choose WAV or FLAC output."
                    )
                subtype = None  # let soundfile pick the default
            sf.write(str(path), data, sr, subtype=subtype, format=fmt.upper())
            return path
        except AudioWriteError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AudioWriteError(f"Failed to write '{path}': {exc}") from exc

    # ------------------------------------------------------------------ #
    # DSP primitives (public so they can be unit-tested individually)
    # ------------------------------------------------------------------ #
    @staticmethod
    def time_stretch(y: np.ndarray, rate: float) -> np.ndarray:
        """Phase-vocoder time stretch. ``rate`` > 1 shortens the clip."""
        if rate <= 0:
            raise AudioEngineError("speed_factor must be > 0")
        try:
            return librosa.effects.time_stretch(y, rate=float(rate))
        except Exception as exc:  # noqa: BLE001
            raise AudioEngineError(f"Time stretch failed: {exc}") from exc

    @staticmethod
    def pitch_shift(y: np.ndarray, sr: int, semitones: float,
                    bins_per_octave: int = 48) -> np.ndarray:
        """
        High-resolution pitch shift. ``bins_per_octave=48`` gives quarter-
        semitone granularity so fractional shifts stay precise.
        """
        try:
            return librosa.effects.pitch_shift(
                y,
                sr=int(sr),
                n_steps=float(semitones) * (bins_per_octave / 12.0),
                bins_per_octave=bins_per_octave,
                res_type="soxr_hq",
            )
        except Exception as exc:  # noqa: BLE001
            raise AudioEngineError(f"Pitch shift failed: {exc}") from exc

    @staticmethod
    def bandpass_filter(y: np.ndarray, sr: int, low_hz: float, high_hz: float,
                        order: int = 4, mix: float = 1.0) -> np.ndarray:
        """
        4th-order Butterworth bandpass implemented as second-order sections
        (numerically stable). ``mix`` blends filtered with dry signal.
        """
        nyq = 0.5 * sr
        lo = max(low_hz, 1.0) / nyq
        hi = min(high_hz, nyq * 0.99) / nyq
        if not (0 < lo < hi < 1):
            raise AudioEngineError(
                f"Invalid bandpass range {low_hz}-{high_hz} Hz for sr={sr}")
        try:
            sos = sps.butter(order, [lo, hi], btype="bandpass", output="sos")
            filtered = sps.sosfilt(sos, y, axis=-1).astype(np.float32)
        except Exception as exc:  # noqa: BLE001
            raise AudioEngineError(f"Bandpass filter failed: {exc}") from exc
        mix = float(np.clip(mix, 0.0, 1.0))
        if mix >= 1.0:
            return filtered
        return (mix * filtered + (1.0 - mix) * y).astype(np.float32)

    @staticmethod
    def micro_reverb(y: np.ndarray, sr: int, delay_ms: float = 30.0,
                     feedback: float = 0.25, mix: float = 0.18) -> np.ndarray:
        """
        Comb-filter style room simulation: a single delay line of
        ``delay_ms`` with ``feedback`` gain. Implemented with ``lfilter`` so
        it runs at C speed instead of a Python sample loop.

            w[n] = x[n] + feedback * w[n - D]
            out  = (1 - mix) * x + mix * w[n - D]
        """
        feedback = float(np.clip(feedback, 0.0, 0.95))
        mix = float(np.clip(mix, 0.0, 1.0))
        delay = int(round(sr * delay_ms / 1000.0))
        if delay < 1 or mix <= 0.0:
            return y
        try:
            # Feedback comb: H(z) = z^-D / (1 - fb * z^-D)
            b = np.zeros(delay + 1, dtype=np.float64)
            b[delay] = 1.0
            a = np.zeros(delay + 1, dtype=np.float64)
            a[0] = 1.0
            a[delay] = -feedback
            wet = sps.lfilter(b, a, y, axis=-1).astype(np.float32)
        except Exception as exc:  # noqa: BLE001
            raise AudioEngineError(f"Micro-reverb failed: {exc}") from exc
        return ((1.0 - mix) * y + mix * wet).astype(np.float32)

    @staticmethod
    def normalize_peak(y: np.ndarray, target_db: float = -1.0) -> np.ndarray:
        """Scale so the absolute peak sits at ``target_db`` dBFS. Also strips
        NaN/Inf that could sneak in from upstream numerical issues."""
        y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
        peak = float(np.max(np.abs(y))) if y.size else 0.0
        if peak < 1e-9:
            return y.astype(np.float32)
        target = 10.0 ** (float(target_db) / 20.0)
        return (y * (target / peak)).astype(np.float32)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _finalise_loaded(self, audio: np.ndarray, sr: int) -> Tuple[np.ndarray, int]:
        """Squeeze single-channel to 1-D, optionally resample, cast float32."""
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim == 2 and audio.shape[0] == 1:
            audio = audio[0]
        if audio.size == 0:
            raise AudioLoadError("Decoded audio is empty")
        if self.target_sr and int(sr) != int(self.target_sr):
            audio = librosa.resample(audio, orig_sr=int(sr),
                                     target_sr=int(self.target_sr),
                                     res_type="soxr_hq")
            sr = int(self.target_sr)
        return audio, int(sr)

    def _load_via_ffmpeg(self, path: Path) -> Tuple[np.ndarray, int]:
        """Transcode to a temporary 32-bit float WAV and read it back."""
        tmp_fd, tmp_name = tempfile.mkstemp(suffix=".wav", prefix="amask_")
        os.close(tmp_fd)
        try:
            cmd = [
                self.ffmpeg_path, "-y", "-v", "error",
                "-i", str(path),
                "-vn", "-acodec", "pcm_f32le", tmp_name,
            ]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=600, creationflags=creationflags)
            if proc.returncode != 0:
                raise AudioLoadError(proc.stderr.strip() or "ffmpeg failed")
            data, sr = sf.read(tmp_name, dtype="float32", always_2d=True)
            return data.T, int(sr)
        finally:
            try:
                os.remove(tmp_name)
            except OSError:
                pass

    @staticmethod
    def _build_output_path(in_path: Path, out_dir: Path,
                           settings: MaskSettings) -> Path:
        """``<out_dir>/<stem><suffix>.<fmt>`` with collision avoidance."""
        out_dir.mkdir(parents=True, exist_ok=True)
        base = f"{in_path.stem}{settings.output_suffix}"
        candidate = out_dir / f"{base}.{settings.output_format}"
        n = 1
        while candidate.exists():
            candidate = out_dir / f"{base}_{n}.{settings.output_format}"
            n += 1
        return candidate

    def _check_cancel(self) -> None:
        if self._cancel_requested:
            raise AudioEngineError("Processing cancelled by user")

    @staticmethod
    def _report(cb: Optional[ProgressCallback], frac: float, msg: str) -> None:
        logger.debug("[%3.0f%%] %s", frac * 100, msg)
        if cb is None:
            return
        try:
            cb(float(np.clip(frac, 0.0, 1.0)), msg)
        except Exception:  # noqa: BLE001 - never let UI errors kill DSP
            logger.exception("progress callback raised")


# --------------------------------------------------------------------------- #
# CLI entry point for quick manual testing
# --------------------------------------------------------------------------- #
def _cli() -> int:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="AudioMask Pro DSP engine")
    parser.add_argument("input", help="input audio file")
    parser.add_argument("-o", "--out-dir", default=".", help="output directory")
    parser.add_argument("-p", "--pitch", type=float, default=1.0,
                        help="pitch shift in semitones (-4..4)")
    parser.add_argument("-s", "--speed", type=float, default=1.03,
                        help="speed factor (0.90..1.15)")
    parser.add_argument("--no-bandpass", action="store_true")
    parser.add_argument("--no-reverb", action="store_true")
    parser.add_argument("-f", "--format", default="wav",
                        choices=sorted(SUPPORTED_OUTPUT_FORMATS))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    settings = MaskSettings(
        pitch_semitones=args.pitch,
        speed_factor=args.speed,
        bandpass_enabled=not args.no_bandpass,
        reverb_enabled=not args.no_reverb,
        output_format=args.format,
    )

    def show(frac: float, msg: str) -> None:
        print(f"[{frac * 100:5.1f}%] {msg}")

    try:
        out = AudioMasker().process_file(args.input, args.out_dir, settings, show)
        print(f"Output: {out}")
        return 0
    except AudioEngineError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
