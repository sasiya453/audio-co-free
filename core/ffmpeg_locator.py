"""
AudioMask Pro - FFmpeg discovery
================================

Finds an FFmpeg executable so compressed formats (MP3 / M4A / AAC / WMA /
OGG / Opus) and video containers (MP4 / MKV / MOV / WebM ...) can be decoded
even when the end user has *not* installed FFmpeg system-wide.

Search order (first hit wins)
-----------------------------
1. ``AUDIOMASK_FFMPEG`` environment variable (explicit file path).
2. Bundled binary next to the frozen application:
   ``sys._MEIPASS/ffmpeg(.exe)``, ``sys._MEIPASS/bin/ffmpeg(.exe)``,
   ``<exe dir>/ffmpeg(.exe)``, ``<exe dir>/bin/ffmpeg(.exe)``.
3. Repository checkout: ``<project root>/bin/ffmpeg(.exe)``.
4. Anything called ``ffmpeg`` on the system ``PATH``.

Once a binary is located :func:`register_ffmpeg` prepends its folder to
``PATH`` (process-local) so third-party code that shells out to a bare
``"ffmpeg"`` command - notably ``audioread`` used by ``librosa.load`` -
transparently uses the bundled copy as well.

The module is import-safe: it never raises and never spawns a process at
import time. Version probing is lazy and cached.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

__all__ = [
    "FFmpegInfo",
    "FFMPEG_ENV_VAR",
    "FFMPEG_EXE_NAME",
    "BUNDLE_DIR_NAME",
    "candidate_paths",
    "find_ffmpeg",
    "register_ffmpeg",
    "ffmpeg_version",
    "ffmpeg_probe",
    "reset_cache",
    "describe",
]

logger = logging.getLogger("audiomask.ffmpeg")

#: Environment variable that forces a specific FFmpeg binary.
FFMPEG_ENV_VAR = "AUDIOMASK_FFMPEG"
#: Platform specific executable name.
FFMPEG_EXE_NAME = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
#: Sub-folder (relative to project root / bundle root) holding the binary.
BUNDLE_DIR_NAME = "bin"
#: Seconds allowed for ``ffmpeg -version`` / ``ffmpeg -i`` probes.
PROBE_TIMEOUT_S = 15

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

_lock = threading.Lock()
_cached: Optional["FFmpegInfo"] = None
_cache_valid = False
_registered_dirs: set = set()
_audioread_original_cmds: Optional[tuple] = None


@dataclass(frozen=True)
class FFmpegInfo:
    """Where FFmpeg was found and how."""

    path: str
    #: ``"env"`` | ``"bundled"`` | ``"project"`` | ``"path"``
    source: str
    version: str = ""

    @property
    def is_bundled(self) -> bool:
        return self.source in ("bundled", "project")

    @property
    def label(self) -> str:
        """Short human readable label for status lines."""
        pretty = {"env": "Env override", "bundled": "Bundled",
                  "project": "Bundled (bin/)", "path": "System PATH"}
        base = pretty.get(self.source, self.source)
        return f"{base}" + (f" ({self.version})" if self.version else "")


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _bundle_roots() -> Iterator[Path]:
    """Directories that may contain a bundled binary (deduplicated)."""
    seen = set()
    roots: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    for r in roots:
        for d in (r, r / BUNDLE_DIR_NAME, r / "_internal",
                  r / "_internal" / BUNDLE_DIR_NAME):
            key = str(d)
            if key not in seen:
                seen.add(key)
                yield d


def candidate_paths() -> List[tuple]:
    """
    Ordered list of ``(source, Path)`` candidates that will be checked by
    :func:`find_ffmpeg`. Exposed for diagnostics and tests.
    """
    cands: List[tuple] = []
    env = os.environ.get(FFMPEG_ENV_VAR, "").strip().strip('"')
    if env:
        cands.append(("env", Path(env)))
    for d in _bundle_roots():
        cands.append(("bundled", d / FFMPEG_EXE_NAME))
    cands.append(("project", _PROJECT_ROOT / BUNDLE_DIR_NAME / FFMPEG_EXE_NAME))
    if os.name != "nt":
        # Allow a Windows-named binary dropped into bin/ on POSIX dev boxes
        # to be *ignored* gracefully, but also accept a plain "ffmpeg".
        cands.append(("project", _PROJECT_ROOT / BUNDLE_DIR_NAME / "ffmpeg"))
    return cands


def _is_executable(p: Path) -> bool:
    try:
        if not p.is_file():
            return False
        if os.name == "nt":
            # Windows has no exec bit; require an executable extension
            return p.suffix.lower() in (".exe", ".bat", ".cmd", ".com")
        return os.access(str(p), os.X_OK)
    except OSError:
        return False


def find_ffmpeg(use_cache: bool = True, probe_version: bool = True
                ) -> Optional[FFmpegInfo]:
    """
    Locate FFmpeg. Returns :class:`FFmpegInfo` or ``None``.

    Parameters
    ----------
    use_cache : bool
        Reuse the result of a previous successful lookup.
    probe_version : bool
        Run ``ffmpeg -version`` once to capture the version string.
    """
    global _cached, _cache_valid
    with _lock:
        if use_cache and _cache_valid:
            return _cached

        info: Optional[FFmpegInfo] = None
        for source, p in candidate_paths():
            if _is_executable(p):
                info = FFmpegInfo(path=str(p), source=source)
                break
            if source == "env":
                logger.warning("%s=%s does not point to an executable file",
                               FFMPEG_ENV_VAR, p)

        if info is None:
            found = shutil.which("ffmpeg")
            if found:
                info = FFmpegInfo(path=found, source="path")

        if info is not None and probe_version:
            ver = ffmpeg_version(info.path)
            if ver is None:
                logger.warning("FFmpeg at %s did not respond to -version; "
                               "ignoring it", info.path)
                info = None
            else:
                info = FFmpegInfo(path=info.path, source=info.source,
                                  version=ver)

        if info is not None:
            _register_locked(info.path)
            logger.info("FFmpeg backend: %s -> %s", info.label, info.path)
        else:
            logger.warning("FFmpeg not found (bundled or PATH); compressed "
                           "formats will rely on libsndfile only")

        _cached, _cache_valid = info, True
        return info


def reset_cache() -> None:
    """Forget the cached lookup and undo the ``audioread`` registration
    (tests / "re-detect" after the user installs FFmpeg). ``PATH`` entries
    added earlier are left in place - they are harmless."""
    global _cached, _cache_valid, _audioread_original_cmds
    with _lock:
        _cached, _cache_valid = None, False
        _registered_dirs.clear()
        if _audioread_original_cmds is not None:
            try:  # pragma: no cover - optional package
                import audioread.ffdec as _ffdec
                _ffdec.COMMANDS = _audioread_original_cmds
            except Exception:  # noqa: BLE001
                pass
            _audioread_original_cmds = None


# --------------------------------------------------------------------------- #
# PATH injection
# --------------------------------------------------------------------------- #
def _register_locked(ffmpeg_path: str) -> None:
    folder = str(Path(ffmpeg_path).resolve().parent)
    if folder in _registered_dirs:
        return
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if folder not in parts:
        os.environ["PATH"] = folder + (os.pathsep + current if current else "")
        logger.debug("Prepended %s to PATH for audioread/librosa", folder)
    _registered_dirs.add(folder)
    # audioread (used by librosa.load) tries these command names in order.
    global _audioread_original_cmds
    try:  # pragma: no cover - depends on optional package
        import audioread.ffdec as _ffdec
        cmds = tuple(_ffdec.COMMANDS)
        if _audioread_original_cmds is None:
            _audioread_original_cmds = cmds
        if ffmpeg_path not in cmds:
            _ffdec.COMMANDS = (ffmpeg_path,) + cmds
    except Exception:  # noqa: BLE001
        pass


def register_ffmpeg(ffmpeg_path: str) -> None:
    """Prepend the folder of ``ffmpeg_path`` to ``PATH`` (idempotent) and
    tell ``audioread`` about the exact binary."""
    with _lock:
        _register_locked(ffmpeg_path)


# --------------------------------------------------------------------------- #
# Probing helpers
# --------------------------------------------------------------------------- #
def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ffmpeg_version(ffmpeg_path: str) -> Optional[str]:
    """Return e.g. ``"7.1"`` / ``"N-118000-g1234"`` or ``None`` on failure."""
    try:
        proc = subprocess.run(  # noqa: S603
            [ffmpeg_path, "-version"], capture_output=True, text=True,
            timeout=PROBE_TIMEOUT_S, creationflags=_no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    first = (proc.stdout or proc.stderr or "").strip().splitlines()
    if not first:
        return None
    m = re.search(r"ffmpeg version\s+(\S+)", first[0])
    return m.group(1) if m else first[0][:40]


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_AUDIO_RE = re.compile(
    r"Stream #\d+:\d+(?:\[[^\]]*\])?(?:\([^)]*\))?:\s*Audio:\s*([^,]+),"
    r"\s*(\d+)\s*Hz,\s*([^,]+)")


def ffmpeg_probe(ffmpeg_path: str, media_path: os.PathLike | str
                 ) -> Optional[dict]:
    """
    Lightweight metadata probe using ``ffmpeg -i`` (no ``ffprobe`` needed).

    Returns ``{"duration": float, "sr": int, "channels": int,
    "codec": str}`` or ``None`` when the file has no decodable audio stream.
    Never raises.
    """
    try:
        proc = subprocess.run(  # noqa: S603
            [ffmpeg_path, "-hide_banner", "-nostdin", "-i", str(media_path)],
            capture_output=True, text=True, errors="replace",
            timeout=PROBE_TIMEOUT_S, creationflags=_no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    text = proc.stderr or ""
    m_dur = _DUR_RE.search(text)
    m_aud = _AUDIO_RE.search(text)
    if not m_aud:
        return None
    duration = 0.0
    if m_dur:
        h, m, s = m_dur.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    layout = m_aud.group(3).strip().lower()
    if layout.startswith("mono"):
        channels = 1
    elif layout.startswith("stereo"):
        channels = 2
    else:
        m_ch = re.match(r"(\d+)(?:\.(\d+))?\s*(?:channels)?", layout)
        if m_ch:
            channels = int(m_ch.group(1)) + int(m_ch.group(2) or 0)
        else:
            channels = 0
    return {
        "duration": float(duration),
        "sr": int(m_aud.group(2)),
        "channels": channels,
        "codec": m_aud.group(1).strip().split(" ")[0],
    }


def describe() -> str:
    """One-line status for logs / UI console."""
    info = find_ffmpeg()
    if info is None:
        return "FFmpeg backend: NOT FOUND (bundled binary missing and not on PATH)"
    return f"FFmpeg backend: {info.label} -> {info.path}"
