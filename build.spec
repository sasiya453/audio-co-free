# -*- mode: python ; coding: utf-8 -*-
"""
AudioMask Pro - PyInstaller build specification.

Usage
-----
    pyinstaller --noconfirm --clean build.spec            # one-folder (default)
    set ONEFILE=1 && pyinstaller --noconfirm --clean build.spec   # Windows one-file
    ONEFILE=1 pyinstaller --noconfirm --clean build.spec  # POSIX one-file

Environment switches
--------------------
ONEFILE=1   Produce a single self-extracting executable instead of a folder.
            (Slower start-up: the bundle is unpacked to %TEMP% on every launch.)
CONSOLE=1   Keep a console window (useful for debugging a build).

The spec is cross-platform: it is validated on Linux in the dev sandbox and
used for the real Windows 10 x64 build via ``build.bat``.

Bundled FFmpeg (Task F3)
------------------------
If ``bin/ffmpeg.exe`` (Windows) / ``bin/ffmpeg`` (POSIX) exists it is copied
into the bundle as ``bin/ffmpeg(.exe)`` - i.e. ``dist/AudioMaskPro/_internal/bin/``
for one-folder builds or ``sys._MEIPASS/bin/`` for one-file builds. Both
locations are searched by ``core.ffmpeg_locator.candidate_paths()`` so the
frozen app decodes M4A/AAC/WMA/MP4/MKV... without a system FFmpeg install.
Fetch the binary first with ``python tools/fetch_ffmpeg.py``; a missing binary
only prints a warning (the build still succeeds, but compressed formats will
then require FFmpeg on the user's PATH).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# --------------------------------------------------------------------------- #
# Paths / switches
# --------------------------------------------------------------------------- #
ROOT = Path(SPECPATH).resolve()  # SPECPATH is injected by PyInstaller
APP_NAME = "AudioMaskPro"
ENTRY = str(ROOT / "main.py")
ONEFILE = os.environ.get("ONEFILE", "").strip() in ("1", "true", "yes")
CONSOLE = os.environ.get("CONSOLE", "").strip() in ("1", "true", "yes")

_icon_candidate = ROOT / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.png")
ICON = str(_icon_candidate) if _icon_candidate.is_file() else None

# Bundled FFmpeg: bin/ffmpeg.exe (win) / bin/ffmpeg (posix), fetched by
# tools/fetch_ffmpeg.py. Keep these names in sync with core/ffmpeg_locator.py
# (FFMPEG_EXE_NAME / BUNDLE_DIR_NAME).
FFMPEG_BUNDLE_DIR = "bin"
FFMPEG_EXE_NAME = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
FFMPEG_SRC = ROOT / FFMPEG_BUNDLE_DIR / FFMPEG_EXE_NAME
FFMPEG_LICENSE_SRC = ROOT / FFMPEG_BUNDLE_DIR / "FFMPEG_LICENSE.txt"


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001 - broken optional packages must not kill the build
        return False


# --------------------------------------------------------------------------- #
# Dependency collection
# --------------------------------------------------------------------------- #
datas: list = []
binaries: list = []
hiddenimports: list = []

# Packages that ship data files / native libraries that PyInstaller's static
# analysis misses (theme JSONs, libsndfile, soxr, librosa registry files...).
for _pkg in ("customtkinter", "librosa", "soundfile", "soxr", "lazy_loader"):
    if not _importable(_pkg):
        continue
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# scipy sub-packages that are imported dynamically.
hiddenimports += collect_submodules("scipy.signal")
hiddenimports += collect_submodules("scipy.special")
hiddenimports += collect_submodules("scipy.fft")
hiddenimports += [
    "scipy._lib.messagestream",
    "scipy._cyutility",
    "scipy.sparse.csgraph._validation",
    "scipy.special._cdflib",
    "scipy.special._special_ufuncs",
]

# numba is a hard requirement of librosa (JIT helpers); make sure the whole
# package tree is visible to the analysis.
if _importable("numba"):
    hiddenimports += collect_submodules("numba")
    hiddenimports += ["llvmlite", "llvmlite.binding"]

# scikit-learn is a hard librosa dependency with Cython modules that are
# loaded dynamically.
if _importable("sklearn"):
    hiddenimports += [
        "sklearn", "sklearn.utils._cython_blas", "sklearn.utils._typedefs",
        "sklearn.utils._heap", "sklearn.utils._sorting", "sklearn.utils._vector_sentinel",
        "sklearn.neighbors._partition_nodes", "sklearn.tree._utils",
        "sklearn.metrics._pairwise_distances_reduction._datasets_pair",
        "sklearn.metrics._pairwise_distances_reduction._middle_term_computer",
    ]
    hiddenimports += collect_submodules("sklearn.cluster")
    hiddenimports += collect_submodules("sklearn.feature_extraction")

# --------------------------------------------------------------------------- #
# Bundled FFmpeg (universal format support, Task F3)
# --------------------------------------------------------------------------- #
if FFMPEG_SRC.is_file():
    # (source, dest_dir) -> dest_dir is relative to the bundle root, so the
    # binary ends up at _internal/bin/ffmpeg(.exe) or _MEIPASS/bin/ffmpeg(.exe).
    binaries.append((str(FFMPEG_SRC), FFMPEG_BUNDLE_DIR))
    _size_mb = FFMPEG_SRC.stat().st_size / 1e6
    print(f"[build.spec] Bundling FFmpeg: {FFMPEG_SRC} ({_size_mb:.1f} MB) "
          f"-> {FFMPEG_BUNDLE_DIR}/{FFMPEG_EXE_NAME}")
    if FFMPEG_LICENSE_SRC.is_file():
        datas.append((str(FFMPEG_LICENSE_SRC), FFMPEG_BUNDLE_DIR))
    else:
        print("[build.spec] NOTE: bin/FFMPEG_LICENSE.txt not found - the GPL/LGPL "
              "licence text of the static FFmpeg build will not be shipped.")
else:
    _warn = (
        "\n" + "!" * 78 + "\n"
        f"WARNING: {FFMPEG_BUNDLE_DIR}/{FFMPEG_EXE_NAME} missing - "
        "run  python tools/fetch_ffmpeg.py  before building.\n"
        "         The build will continue, but the packaged app will only decode\n"
        "         M4A/AAC/WMA/MP4/MKV if the END USER has FFmpeg on their PATH.\n"
        + "!" * 78 + "\n"
    )
    print(_warn, file=sys.stderr)
    print(_warn)

# Optional librosa companions - include only when installed.
for _opt in ("pooch", "audioread", "msgpack", "joblib", "decorator",
             "numba.core.typing.cffi_utils", "packaging"):
    if _importable(_opt.split(".")[0]):
        hiddenimports.append(_opt)

# Our own packages (imported via sys.path manipulation in main.py).
hiddenimports += ["core", "core.audio_engine", "core.ffmpeg_locator",
                  "core.logging_setup", "ui", "ui.app_ui"]

# Tk image support used by customtkinter (PIL is a ctk dependency).
hiddenimports += ["PIL", "PIL._tkinter_finder", "PIL.ImageTk", "PIL.Image"]

# De-duplicate while preserving order.
hiddenimports = list(dict.fromkeys(hiddenimports))

# Things we definitely do not need. NOTE: numba MUST NOT be excluded.
excludes = [
    "matplotlib", "IPython", "jupyter", "notebook", "ipykernel",
    "pytest", "tkinter.test",
    "PyQt5", "PyQt6", "PySide2", "PySide6",
    "pandas", "sympy", "cv2", "torch", "tensorflow",
    # NOTE: scikit-learn is a *hard* librosa dependency (librosa.segment) -
    # it must not be excluded.
    # NOTE: do NOT exclude scipy sub-packages - librosa imports scipy.spatial,
    # scipy.ndimage, scipy.interpolate and scipy.stats lazily at runtime.
]

# --------------------------------------------------------------------------- #
# Analysis / bundle
# --------------------------------------------------------------------------- #
block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "hooks" / "rthook_numba.py")],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_exe_common = dict(
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX corrupts some numpy/scipy DLLs and trips AV heuristics
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        exclude_binaries=False,
        runtime_tmpdir=None,
        **_exe_common,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **_exe_common,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
