"""
PyInstaller runtime hook: numba / librosa environment for the frozen bundle.

Executed by the bootloader *before* ``main.py``. It must stay dependency-free
(only the standard library) and must never raise.

Why this exists
---------------
* ``librosa`` JIT-compiles helpers with ``numba`` on first use. numba wants to
  write its on-disk cache next to the compiled module, which lives inside the
  read-only ``_internal`` folder of the bundle. Redirecting ``NUMBA_CACHE_DIR``
  to the user's temp directory avoids ``PermissionError`` / silent slowdowns.
* JIT itself must stay enabled (``NUMBA_DISABLE_JIT`` is intentionally *not*
  set) - disabling it makes pitch shifting an order of magnitude slower.
* ``LIBROSA_DATA_DIR`` is pointed at a writable location so the optional
  ``pooch`` example-data registry never tries to create folders in the bundle.
"""
import os
import sys
import tempfile


def _writable_tmp(sub: str) -> str:
    base = os.path.join(tempfile.gettempdir(), "AudioMaskPro", sub)
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:  # noqa: BLE001 - fall back to plain temp dir
        base = tempfile.gettempdir()
    return base


try:
    os.environ.setdefault("NUMBA_CACHE_DIR", _writable_tmp("numba_cache"))
    os.environ.setdefault("LIBROSA_DATA_DIR", _writable_tmp("librosa_data"))
    # Keep BLAS thread pools sane on small machines; the DSP is mostly
    # single-track so oversubscription only adds overhead.
    os.environ.setdefault("OMP_NUM_THREADS", str(min(4, os.cpu_count() or 1)))
    # numba emits noisy warnings when caching is impossible; silence them.
    os.environ.setdefault("NUMBA_DISABLE_PERFORMANCE_WARNINGS", "1")
    if getattr(sys, "frozen", False):
        # Tell our own code it is running from a bundle (used for log messages).
        os.environ.setdefault("AUDIOMASK_FROZEN", "1")
except Exception:  # noqa: BLE001 - never block start-up
    pass
