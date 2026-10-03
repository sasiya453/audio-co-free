"""
AudioMask Pro - Logging configuration
=====================================

Centralised, crash-proof logging bootstrap shared by the GUI entry point
(``main.py``) and the CLI.

* Console handler at INFO (DEBUG when ``debug=True``).
* :class:`logging.handlers.RotatingFileHandler` at DEBUG, 2 MB x 3 backups.
* Log directory resolution (first writable wins):

  1. ``%LOCALAPPDATA%\\AudioMaskPro\\logs`` (Windows)
  2. ``~/.audiomask/logs`` (everything else, or if 1. is unavailable)
  3. system temp dir
  4. console only - logging must *never* crash the application.

Use :func:`configure_logging` once at start-up and :func:`log_environment`
to dump interpreter / library versions into the log for bug reports.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

__all__ = ["configure_logging", "get_log_dir", "log_environment", "LOG_FILE_NAME"]

APP_DIR_NAME = "AudioMaskPro"
LOG_FILE_NAME = "audiomask.log"
MAX_BYTES = 2 * 1024 * 1024  # 2 MB
BACKUP_COUNT = 3

_FILE_FMT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
_CONSOLE_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Third-party loggers that are far too chatty at DEBUG.
_NOISY_LOGGERS = ("numba", "matplotlib", "PIL", "soundfile", "audioread")

# Remembered after the first successful configure_logging() call.
_active_log_path: Optional[Path] = None


def _candidate_dirs() -> list[Path]:
    """Ordered list of directories to try for the log file."""
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / APP_DIR_NAME / "logs")
    try:
        candidates.append(Path.home() / ".audiomask" / "logs")
    except (RuntimeError, KeyError):  # no HOME resolvable
        pass
    candidates.append(Path(tempfile.gettempdir()) / APP_DIR_NAME / "logs")
    return candidates


def get_log_dir(create: bool = True) -> Optional[Path]:
    """
    Return the first usable log directory, creating it when ``create`` is
    True. Returns ``None`` if no candidate is writable.
    """
    for cand in _candidate_dirs():
        try:
            if create:
                cand.mkdir(parents=True, exist_ok=True)
            if cand.is_dir() and os.access(cand, os.W_OK):
                return cand
        except OSError:
            continue
    return None


def active_log_path() -> Optional[Path]:
    """Path of the log file in use (``None`` when console-only)."""
    return _active_log_path


def configure_logging(debug: bool = False,
                      console: bool = True) -> Optional[Path]:
    """
    Install console + rotating-file handlers on the root logger.

    Parameters
    ----------
    debug : bool
        Console verbosity (file handler is always DEBUG).
    console : bool
        Attach a stream handler to stderr. Set False when running frozen
        with ``--noconsole`` *and* stderr is None (PyInstaller windowed mode).

    Returns
    -------
    pathlib.Path | None
        Full path of the log file, or ``None`` if only console logging could
        be configured. This function never raises.
    """
    global _active_log_path

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Idempotent: strip handlers we previously installed (marked attribute).
    for h in list(root.handlers):
        if getattr(h, "_audiomask", False):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass

    # -- console ----------------------------------------------------------
    if console and sys.stderr is not None:
        try:
            ch = logging.StreamHandler(sys.stderr)
            ch.setLevel(logging.DEBUG if debug else logging.INFO)
            ch.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt="%H:%M:%S"))
            ch._audiomask = True  # type: ignore[attr-defined]
            root.addHandler(ch)
        except Exception:  # noqa: BLE001 - never crash on logging
            pass

    # -- rotating file ----------------------------------------------------
    log_path: Optional[Path] = None
    log_dir = get_log_dir(create=True)
    if log_dir is not None:
        try:
            log_path = log_dir / LOG_FILE_NAME
            fh = logging.handlers.RotatingFileHandler(
                str(log_path), maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                encoding="utf-8", delay=False)
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter(_FILE_FMT))
            fh._audiomask = True  # type: ignore[attr-defined]
            root.addHandler(fh)
        except Exception as exc:  # noqa: BLE001
            log_path = None
            logging.getLogger("audiomask.logging").warning(
                "File logging disabled (%s) - console only", exc)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _active_log_path = log_path
    return log_path


def log_environment(logger: Optional[logging.Logger] = None) -> None:
    """Write interpreter, platform and DSP-library versions to the log."""
    log = logger or logging.getLogger("audiomask.main")
    try:
        log.info("Python %s on %s (%s)", platform.python_version(),
                 platform.platform(), platform.machine())
        log.info("Frozen: %s | executable: %s",
                 bool(getattr(sys, "frozen", False)), sys.executable)
        for mod in ("numpy", "scipy", "librosa", "soundfile", "customtkinter"):
            try:
                m = __import__(mod)
                log.info("%s %s", mod, getattr(m, "__version__", "?"))
            except Exception as exc:  # noqa: BLE001
                log.warning("%s: not importable (%s)", mod, exc)
        try:
            import soundfile as sf
            log.info("libsndfile %s", sf.__libsndfile_version__)
        except Exception:  # noqa: BLE001
            pass
        log.info("ffmpeg: %s", shutil.which("ffmpeg") or "not on PATH")
        if _active_log_path:
            log.info("Log file: %s", _active_log_path)
    except Exception:  # noqa: BLE001 - diagnostics must never break startup
        log.debug("log_environment failed", exc_info=True)


def open_log_folder() -> bool:
    """
    Open the log directory in the OS file browser. Returns True on success.
    Safe to call from the UI; never raises.
    """
    import subprocess  # local import keeps module import cheap

    folder = get_log_dir(create=True)
    if folder is None:
        return False
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", str(folder)])  # noqa: S603,S607
        return True
    except Exception:  # noqa: BLE001
        logging.getLogger("audiomask.logging").warning(
            "Could not open log folder %s", folder, exc_info=True)
        return False
