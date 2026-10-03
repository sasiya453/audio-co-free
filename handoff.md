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
| Version | **1.0.0** (`ui/app_ui.py::APP_VERSION`) |
| Python | 3.10+ (dev sandbox runs 3.13; keep 3.10-compatible syntax) |
| Deps | see `requirements.txt` (numpy, scipy, librosa, soundfile, soxr, customtkinter, pyinstaller) |
| Run app | `python main.py` (set `AUDIOMASK_DEBUG=1` for debug console) |
| Headless check | `python main.py --selftest` (also works on the frozen exe) |
| Log file | `%LOCALAPPDATA%\AudioMaskPro\logs\audiomask.log` (Win) / `~/.audiomask/logs/` (other) |
| Tests | `python -m unittest discover -s tests` (**59 tests, ~10-30 s**, no display needed) |
| CLI smoke | `python -m core.audio_engine song.mp3 -o out -p 1.5 -s 1.05` |
| Build (Windows) | `build.bat` → `dist\AudioMaskPro\AudioMaskPro.exe` (`build.bat onefile` / `console` / `clean`) |
| Build (sandbox) | `./build.sh smoke` or `pyinstaller --noconfirm --clean build.spec && dist/AudioMaskPro/AudioMaskPro --selftest` |
| Headless UI check | `sudo apt-get install -y xvfb && xvfb-run -a timeout 20 dist/AudioMaskPro/AudioMaskPro` (exit 124 = started OK) |
| Sandbox setup | `pip install -r requirements.txt` (customtkinter/pyinstaller are NOT preinstalled) |

---

## Roadmap Status — ✅ ALL 4 TASKS COMPLETE

| # | Task | Status |
|---|---|---|
| 1 | Core DSP Engine (`core/audio_engine.py`) | ✅ DONE (session 1) |
| 2 | CustomTkinter Desktop UI (`ui/app_ui.py`, `main.py`) | ✅ DONE (session 2) |
| 3 | Logging, hardening, memory cleanup, error popups | ✅ DONE (session 3) |
| 4 | PyInstaller `build.spec`, `build.bat`, `README.md` | ✅ **DONE (session 4)** |

---

## File Manifest (current)

```
main.py                   # entry point: logging bootstrap, thread excepthook, crash popup, --selftest, launches UI
core/__init__.py
core/audio_engine.py      # AudioMasker + MaskSettings + probe() + CLI   (Task 1, hardened Task 3)
core/logging_setup.py     # configure_logging / log_environment / open_log_folder (Task 3)
ui/__init__.py
ui/app_ui.py              # AudioMaskApp(ctk.CTk) v1.0.0 + pure helpers  (Task 2, hardened Task 3)
hooks/rthook_numba.py     # PyInstaller runtime hook: NUMBA_CACHE_DIR/LIBROSA_DATA_DIR -> %TEMP% (Task 4)
build.spec                # PyInstaller spec, one-folder default; ONEFILE=1 / CONSOLE=1 env switches (Task 4)
build.bat                 # Windows build: venv -> deps -> tests -> pyinstaller (Task 4)
build.sh                  # POSIX spec validation incl. Xvfb smoke (Task 4)
README.md                 # user + developer documentation (Task 4)
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

---

## What Task 4 delivered (session 4)

* **`build.spec`** — cross-platform. `collect_all` for `customtkinter`, `librosa`,
  `soundfile`, `soxr`, `lazy_loader`; hidden imports for `scipy.signal/special/fft`,
  `numba` (+`llvmlite`), **`sklearn`** (hard librosa dependency via `librosa.segment`),
  `pooch`/`audioread`/`msgpack`/`joblib` when installed; `upx=False`; icon picked up
  from `assets/icon.ico` (win) / `assets/icon.png` if present; `ONEFILE=1` and
  `CONSOLE=1` env switches.
* **Lessons learned (do not regress):**
  * Do **not** put `distutils`, `setuptools`, `wheel`, `unittest`, `test` in `excludes` —
    PyInstaller 6.x aliases them internally and aborts with `ValueError: Target module … already imported`.
  * Do **not** exclude any `scipy.*` sub-package or `sklearn` — librosa imports
    `scipy.spatial`, `scipy.ndimage`, `scipy.interpolate`, `scipy.stats`, `sklearn` lazily.
  * `collect_all("soundfile")` bundles `_internal/_soundfile_data/libsndfile_*` correctly.
* **`hooks/rthook_numba.py`** — redirects numba JIT cache + librosa data dir to
  `%TEMP%\AudioMaskPro\…`; JIT stays enabled; sets `AUDIOMASK_FROZEN=1`.
* **`main.py --selftest`** — synthesises a tone, runs full pipeline, verifies finite
  output ≤ 0 dBFS; exit 0/3. Works inside the frozen exe (no display needed).
* **`build.bat`** (venv → pip → unittest → pyinstaller; `onefile`/`console`/`clean`)
  and **`build.sh`** (`folder`/`onefile`/`smoke`).
* **`README.md`** — full user/developer docs; `APP_VERSION` bumped to 1.0.0.
* **Validation performed in sandbox (Linux):** build OK (~460 MB one-folder),
  frozen GUI starts under Xvfb (`AudioMask Pro v1.0.0 ready.`), frozen `--selftest`
  passes (`peak 0.891`, 1.90 s @ 22050 Hz), 59/59 tests green.
* **Not yet validated:** an actual Windows 10 build (sandbox is Linux-only).
  The spec is platform-agnostic; the first Windows run should simply be
  `build.bat` then `dist\AudioMaskPro\AudioMaskPro.exe --selftest`.

---

## 🔶 NEXT PENDING TASK — none mandatory. Roadmap complete.

If a new session is started, pick from the **Future ideas** below in priority
order, or act on user feedback from the first real Windows build.

### Windows first-run checklist (do this if the user reports build problems)
1. `build.bat console` → run `dist\AudioMaskPro\AudioMaskPro.exe --selftest` and read the traceback.
2. Typical fixes: add module to `hiddenimports` in `build.spec`; if
   `libsndfile_x64.dll` is missing check `dist\AudioMaskPro\_internal\_soundfile_data\`;
   if Tk themes are missing confirm `_internal\customtkinter\assets\themes\*.json` exists.
3. Keep `upx=False`. Keep numba JIT enabled.

### Future ideas (prioritised)
1. **Presets** — save/load `MaskSettings` as JSON (`%LOCALAPPDATA%\AudioMaskPro\presets\`), preset dropdown in UI.
2. **Drag-and-drop** input files (`tkinterdnd2`; add to `collect_all` in spec).
3. **MP3 output guaranteed** — detect libsndfile MPEG support at start-up; fall back to bundled FFmpeg encode (`ffmpeg -i out.wav -b:a 192k out.mp3`) if unavailable.
4. **Batch parallelism** — `concurrent.futures.ThreadPoolExecutor(max_workers=2)` for multi-file jobs; keep progress aggregation thread-safe via the existing queue.
5. **Waveform preview** — before/after mini waveform drawn on a `CTkCanvas` (numpy decimation; no matplotlib).
6. **i18n** — move UI strings to `ui/strings.py` dict; add language switch.
7. **Code signing / release CI** — GitHub Actions `windows-latest` job running `build.bat` and uploading `dist\` as an artifact; `LICENSE` file (MIT).
8. **Icon** — add `assets/icon.ico` (256×256 multi-res); spec already picks it up.

### Validation for any future change
```
python -m py_compile build.spec main.py hooks/*.py core/*.py ui/*.py
python -m unittest discover -s tests
pyinstaller --noconfirm --clean build.spec && dist/AudioMaskPro/AudioMaskPro --selftest
```

---

## Session Log
| Date | Session | Summary |
|---|---|---|
| 2026-10-03 | 1 | Repo initialised; Task 1 engine + 31 tests implemented, all passing; MP3→WAV CLI smoke test OK. |
| 2026-10-03 | 2 | Task 2 UI (`ui/app_ui.py`, `main.py`) implemented; verified under Xvfb incl. threaded batch + error path; tests green. |
| 2026-10-03 | 3 | Task 3 hardening: `core/logging_setup.py`, engine `probe()`/duration/NaN/FFmpeg/write error paths, UI pre-flight + log/output buttons + safe shutdown, `tests/test_ui_logic.py` (28). 59/59 tests pass; Xvfb batch + `main.py` start-up log verified. |
| 2026-10-03 | 4 | Task 4 packaging: `build.spec`, `hooks/rthook_numba.py`, `build.bat`, `build.sh`, `README.md`, `main.py --selftest`, v1.0.0. Fixed 3 spec issues (PyInstaller alias conflict, scipy.spatial, sklearn). Frozen Linux build starts under Xvfb and passes `--selftest`; 59/59 tests. **Roadmap complete.** |
