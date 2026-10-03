# AudioMask Pro — Session Handoff

> **Protocol for every agent session:** read this file first → execute ONLY the
> "Next Pending Task" → run tests → commit → update this file → push.
> Do NOT redo completed tasks. Keep sessions short; credits are limited.

---

## Project Snapshot

| Item | Value |
|---|---|
| Repo | https://github.com/sasiya453/audio-co-free |
| Branch | `main` |
| Python | 3.10+ (dev sandbox runs 3.13; keep 3.10-compatible syntax) |
| Deps | see `requirements.txt` (numpy, scipy, librosa, soundfile, soxr, customtkinter, pyinstaller) |
| Run app | `python main.py` (set `AUDIOMASK_DEBUG=1` for debug console) |
| Log file | `%LOCALAPPDATA%\AudioMaskPro\logs\audiomask.log` (Win) / `~/.audiomask/logs/` (other) |
| Tests | `python -m unittest discover -s tests` (**59 tests, ~5 s**, no display needed) |
| CLI smoke | `python -m core.audio_engine song.mp3 -o out -p 1.5 -s 1.05` |
| Headless UI check | `sudo apt-get install -y xvfb && xvfb-run -a python -c "import sys; sys.path.insert(0,'.'); from ui.app_ui import AudioMaskApp; a=AudioMaskApp(); a.update(); a.shutdown(); a.destroy(); print('ok')"` |
| Sandbox setup | `pip install customtkinter` is NOT preinstalled in the sandbox — run `pip install -r requirements.txt` first |

---

## Roadmap Status

| # | Task | Status |
|---|---|---|
| 1 | Core DSP Engine (`core/audio_engine.py`) | ✅ DONE (session 1) |
| 2 | CustomTkinter Desktop UI (`ui/app_ui.py`, `main.py`) | ✅ DONE (session 2) |
| 3 | Logging, hardening, memory cleanup, error popups | ✅ **DONE (session 3)** |
| 4 | PyInstaller `build.spec`, `build.bat`, `README.md` | 🔶 **NEXT — ACTIVE** |

---

## File Manifest (current)

```
main.py                   # entry point: logging bootstrap, thread excepthook, crash popup, launches UI
core/__init__.py
core/audio_engine.py      # AudioMasker + MaskSettings + probe() + CLI   (Task 1, hardened Task 3)
core/logging_setup.py     # configure_logging / log_environment / open_log_folder (Task 3)
ui/__init__.py
ui/app_ui.py              # AudioMaskApp(ctk.CTk) v0.3.0 + pure helpers  (Task 2, hardened Task 3)
tests/__init__.py
tests/test_engine.py      # 31 DSP/engine tests (synthetic signals)
tests/test_ui_logic.py    # 28 tests: logging, hardening paths, UI helpers (no Tk)
requirements.txt
.gitignore
handoff.md
```

---

## Engine API reference (stable)

```python
from core.audio_engine import AudioMasker, MaskSettings, AudioEngineError, \
    AudioLoadError, AudioWriteError, SUPPORTED_INPUT_EXTENSIONS, \
    SUPPORTED_OUTPUT_FORMATS, DEFAULT_MAX_DURATION_S, FFMPEG_HINT

settings = MaskSettings(pitch_semitones=1.0, speed_factor=1.03,
                        bandpass_enabled=True, bandpass_intensity=0.6,
                        reverb_enabled=True, reverb_mix=0.18,
                        output_format="wav").validate()
masker = AudioMasker(max_duration_s=1200)   # .ffmpeg_path = shutil.which("ffmpeg") or None
info   = masker.probe(src)                  # {"duration","sr","channels","format","size"} or AudioLoadError
out    = masker.process_file(src, out_dir, settings, progress_cb=lambda frac, msg: ...)
masker.cancel()                             # thread-safe; raises AudioEngineError("Processing cancelled by user")
```
* Logger names: `audiomask.engine`, `audiomask.ui`, `audiomask.main`, `audiomask.logging`.
* `core.logging_setup.configure_logging(debug=False, console=True) -> Path | None`
  is idempotent and never raises; `active_log_path()` returns the file in use.

## What Task 3 delivered (session 3)

* **Logging:** rotating file handler (2 MB × 3) with LOCALAPPDATA → `~/.audiomask` →
  temp → console-only fallback chain; start-up environment dump (Python, numpy,
  scipy, librosa, soundfile, libsndfile, ffmpeg); `threading.excepthook` wired to the log.
* **Engine:** `max_duration_s` guard (default 20 min, checked via `sf.info` before decode
  and again after), 0-byte / zero-length / NaN-Inf / bad-sr rejection, float32 cast on
  load, `MemoryError` → `AudioLoadError`/`AudioEngineError`, FFmpeg fallback catches
  `FileNotFoundError` / `TimeoutExpired(300 s)` / non-zero exit with install hint,
  `write_audio` distinguishes `PermissionError` (locked file hint) and ENOSPC (disk full),
  per-stage buffer swap + `gc.collect()` in `process_array`.
* **UI:** pre-flight (`dir_is_writable`, `probe()` each file → skip list + askyesno,
  `find_overwrite_conflicts` warning), "Open log folder" header button, "Open output"
  button enabled after a successful batch, `_closing` flag + `after_cancel` + `TclError`
  guards, `shutdown()` joins the worker (2 s) and drains the queue; `main.py` calls it.
* **Tests:** `tests/test_ui_logic.py` (28) — all 59 pass; UI batch verified under Xvfb
  (good + corrupt file → 1 FLAC written, skip prompt shown, buttons toggled, clean shutdown).

---

## 🔶 NEXT PENDING TASK — Task 4: PyInstaller packaging, `build.bat`, `README.md`

Goal: a clean Windows 10 x64 build that runs on a machine with **no Python**.
Deliverables: `build.spec`, `build.bat`, `README.md`, small tweaks listed below.
Only Linux is available in the sandbox — write the spec/scripts, validate them
with `pyinstaller build.spec` on Linux (it should produce `dist/AudioMaskPro/`
and the binary should start under Xvfb), and document the Windows steps.

### 4.1 `build.spec` (one-folder build is the default; one-file is optional)
```python
# key facts gathered in session 3
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules
datas, binaries, hiddenimports = [], [], []
for pkg in ("customtkinter", "librosa", "soundfile", "soxr"):
    d, b, h = collect_all(pkg); datas += d; binaries += b; hiddenimports += h
hiddenimports += collect_submodules("scipy.signal") + collect_submodules("scipy.special") \
              + ["scipy._lib.messagestream", "scipy.sparse.csgraph._validation",
                 "sklearn.utils._cython_blas"]  # last one only if importable; wrap in try
excludes = ["matplotlib", "IPython", "jupyter", "notebook", "pytest", "tkinter.test",
            "PyQt5", "PySide2", "pandas"]  # numba MUST stay (librosa needs it)
```
* `soundfile` ships `_soundfile_data/libsndfile_x86_64.so` (Linux) /
  `libsndfile_x64.dll` (Windows) — `collect_all("soundfile")` grabs it; verify it
  lands in `dist/AudioMaskPro/_internal/_soundfile_data/`.
* `librosa` needs `util/example_data/registry.txt` + `core/intervals.msgpack` —
  `collect_all("librosa")` includes them (watch for `lazy_loader` stub files).
* Add a runtime hook `hooks/rthook_numba.py` setting
  `os.environ.setdefault("NUMBA_CACHE_DIR", tempfile.gettempdir())` and
  `NUMBA_DISABLE_JIT` **unset** (JIT must stay on; just redirect the cache so it
  doesn't try to write into the read-only bundle).
* `EXE(..., name="AudioMaskPro", console=False, icon="assets/icon.ico" if exists else None,
  upx=False)`; `COLLECT(...)` for the one-folder bundle. Entry script: `main.py`.
* `main.py` already handles `sys.frozen` / `_MEIPASS` and `sys.stderr is None`.
* Keep spec cross-platform: branch on `sys.platform` only for the icon.

### 4.2 `build.bat` (Windows) + `build.sh` (sandbox validation)
```
@echo off
setlocal
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
rmdir /s /q build dist 2>nul
pyinstaller --noconfirm --clean build.spec
if errorlevel 1 (echo BUILD FAILED & exit /b 1)
echo Build OK: dist\AudioMaskPro\AudioMaskPro.exe
```
* Optional `--onefile` variant: add a second spec or a `set ONEFILE=1` switch read
  via `os.environ` inside `build.spec`.
* `.gitignore` already ignores `build/`, `dist/`, `*.spec`? → **check**: the spec
  must be committed, so remove `*.spec` from `.gitignore` if present.

### 4.3 Sandbox validation of the spec (Linux)
```
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean build.spec
ls dist/AudioMaskPro/_internal/_soundfile_data/
xvfb-run -a timeout 20 dist/AudioMaskPro/AudioMaskPro ; echo exit=$?   # expect 124 (killed by timeout) with no traceback
# headless engine smoke through the frozen bundle:
python -c "import numpy as np, soundfile as sf; sf.write('t.wav', 0.3*np.sin(np.arange(22050)*2*np.pi*440/22050), 22050)"
```
If the frozen binary throws `ModuleNotFoundError`, add the module to
`hiddenimports` and rebuild. Common offenders: `scipy.special._cdflib`,
`sklearn` (not needed — exclude), `pooch` (librosa optional), `lazy_loader`.

### 4.4 `README.md`
Sections: What it does (pipeline table) · Screenshot placeholder · Requirements
(Windows 10 x64, optional FFmpeg for MP3/M4A input) · Download/Run the .exe ·
Run from source (`pip install -r requirements.txt && python main.py`) · Build
(`build.bat`) · Settings reference (ranges from `MaskSettings.LIMITS`) · Output
naming (`<name>_masked.<fmt>`, `_1`, `_2` on collision) · Logs location ·
Troubleshooting (FFmpeg missing, antivirus false positives on PyInstaller
binaries, "file is locked", long files > 20 min) · Tests · License (MIT unless
the user specifies otherwise) · Disclaimer (user is responsible for rights
to processed audio).

### 4.5 Housekeeping
* Bump `APP_VERSION` in `ui/app_ui.py` to `1.0.0`.
* Add `assets/icon.ico` only if a real icon is provided; otherwise leave `icon=None`.
* Append `pyinstaller` validation command to the Snapshot table above.

### Validation for Task 4
```
python -m py_compile build.spec main.py core/*.py ui/*.py
python -m unittest discover -s tests
pyinstaller --noconfirm --clean build.spec && xvfb-run -a timeout 20 dist/AudioMaskPro/AudioMaskPro
```

### After Task 4
Commit as `build(pyinstaller): add build.spec, build.bat and README for Windows 10 x64`,
mark Task 4 done here (roadmap complete), add a "Future ideas" section
(presets JSON, drag-and-drop, MP3 output via bundled FFmpeg, i18n), push to `origin main`.

---

## Session Log
| Date | Session | Summary |
|---|---|---|
| 2026-10-03 | 1 | Repo initialised; Task 1 engine + 31 tests implemented, all passing; MP3→WAV CLI smoke test OK. |
| 2026-10-03 | 2 | Task 2 UI (`ui/app_ui.py`, `main.py`) implemented; verified under Xvfb incl. threaded batch + error path; tests green. |
| 2026-10-03 | 3 | Task 3 hardening: `core/logging_setup.py`, engine `probe()`/duration/NaN/FFmpeg/write error paths, UI pre-flight + log/output buttons + safe shutdown, `tests/test_ui_logic.py` (28). 59/59 tests pass; Xvfb batch + `main.py` start-up log verified. |
