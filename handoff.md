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
| Version | **1.0.0** (`ui/app_ui.py::APP_VERSION`) — bumping to 1.1.0 at end of FFmpeg upgrade (Task F3) |
| Python | 3.10+ (dev sandbox runs 3.13; keep 3.10-compatible syntax) |
| Deps | see `requirements.txt` (numpy, scipy, librosa, soundfile, soxr, customtkinter, pyinstaller) |
| Run app | `python main.py` (set `AUDIOMASK_DEBUG=1` for debug console) |
| Headless check | `python main.py --selftest` (also works on the frozen exe) |
| Log file | `%LOCALAPPDATA%\AudioMaskPro\logs\audiomask.log` (Win) / `~/.audiomask/logs/` (other) |
| Tests | `python -m unittest discover -s tests` (**93 tests, ~15-40 s**, no display needed; needs `ffmpeg` on PATH to build fixtures, else format tests skip) |
| CLI smoke | `python -m core.audio_engine song.mp3 -o out -p 1.5 -s 1.05` |
| Build (Windows) | `build.bat` → `dist\AudioMaskPro\AudioMaskPro.exe` (`build.bat onefile` / `console` / `clean`) |
| Build (sandbox) | `./build.sh smoke` or `pyinstaller --noconfirm --clean build.spec && dist/AudioMaskPro/AudioMaskPro --selftest` |
| Headless UI check | `sudo apt-get install -y xvfb && xvfb-run -a timeout 20 dist/AudioMaskPro/AudioMaskPro` (exit 124 = started OK) |
| Sandbox setup | `pip install -r requirements.txt` (customtkinter/pyinstaller are NOT preinstalled) |
| Fetch bundled FFmpeg | `python tools/fetch_ffmpeg.py [--platform win64]` → `bin/ffmpeg(.exe)` (git-ignored, ~100 MB) |
| FFmpeg status | `python -c "from core.audio_engine import ffmpeg_status; print(ffmpeg_status())"` |

---

## Roadmap Status

### v1.0 roadmap — ✅ ALL 4 TASKS COMPLETE
| # | Task | Status |
|---|---|---|
| 1 | Core DSP Engine (`core/audio_engine.py`) | ✅ DONE (session 1) |
| 2 | CustomTkinter Desktop UI (`ui/app_ui.py`, `main.py`) | ✅ DONE (session 2) |
| 3 | Logging, hardening, memory cleanup, error popups | ✅ DONE (session 3) |
| 4 | PyInstaller `build.spec`, `build.bat`, `README.md` | ✅ DONE (session 4) |

### Bundled-FFmpeg upgrade (universal format support) — IN PROGRESS
| # | Task | Status |
|---|---|---|
| F1 | Bundled FFmpeg integration + audio loader hardening (`core/ffmpeg_locator.py`, `core/audio_engine.py`, `bin/`, `tools/fetch_ffmpeg.py`, `tests/test_formats.py`) | ✅ **DONE (session 5)** |
| F2 | UI status banner + auto-detection (`ui/app_ui.py`): `[INFO] FFmpeg backend: Bundled/Found`, file dialog accepts all `SUPPORTED_INPUT_EXTENSIONS` | 🔶 **NEXT** |
| F3 | `build.spec` bundles `bin/ffmpeg.exe`; `build.bat` fetches it + runs `--selftest`; bump `APP_VERSION` → 1.1.0; README | ⏳ pending |

---

## File Manifest (current)

```
main.py                   # entry point: logging bootstrap, thread excepthook, crash popup, --selftest, launches UI
core/__init__.py
core/audio_engine.py      # AudioMasker + MaskSettings + probe() + CLI   (Task 1, hardened Task 3, FFmpeg-first decode F1)
core/ffmpeg_locator.py    # find_ffmpeg(): env -> _MEIPASS/bin -> exe dir -> repo bin/ -> PATH; PATH injection; probe (F1)
core/logging_setup.py     # configure_logging / log_environment / open_log_folder (Task 3)
bin/README.md             # bundled FFmpeg folder; ffmpeg(.exe) is git-ignored, fetched by tools/fetch_ffmpeg.py (F1)
tools/fetch_ffmpeg.py     # downloads static BtbN FFmpeg build (win64/linux64) into bin/; --check / --force / --lgpl (F1)
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
tests/test_formats.py     # 34 tests: locator + M4A/AAC/OGG/Opus/FLAC/WMA/MP3/MP4/MKV/MOV/WebM decode via *bundled-only* FFmpeg (F1)
requirements.txt
.gitignore
handoff.md
```

---

## Engine API reference (stable)

```python
from core.audio_engine import AudioMasker, MaskSettings, AudioEngineError, \
    AudioLoadError, AudioWriteError, SUPPORTED_INPUT_EXTENSIONS, \
    NATIVE_INPUT_EXTENSIONS, FFMPEG_PREFERRED_EXTENSIONS, \
    VIDEO_CONTAINER_EXTENSIONS, SUPPORTED_OUTPUT_FORMATS, \
    DEFAULT_MAX_DURATION_S, FFMPEG_HINT, ffmpeg_status
from core import ffmpeg_locator   # find_ffmpeg() -> FFmpegInfo(path, source, version) | None
                                  # .label -> "Bundled (7.1)" / "System PATH (6.0)"; describe() -> one-liner

settings = MaskSettings(pitch_semitones=1.0, speed_factor=1.03,
                        bandpass_enabled=True, bandpass_intensity=0.6,
                        reverb_enabled=True, reverb_mix=0.18,
                        output_format="wav").validate()
masker = AudioMasker(max_duration_s=1200)   # .ffmpeg_path (bundled preferred), .ffmpeg_info, .ffmpeg_available
AudioMasker.prefers_ffmpeg("x.m4a")         # True -> FFmpeg tried first (compressed/video containers)
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

## What Task F1 delivered (session 5)

* **`core/ffmpeg_locator.py`** — `find_ffmpeg()` search order: `AUDIOMASK_FFMPEG`
  env → `sys._MEIPASS/{,bin/}ffmpeg(.exe)` → `<exe dir>/{,bin/,_internal/,_internal/bin/}`
  → `<repo>/bin/ffmpeg(.exe)` → `shutil.which("ffmpeg")`. Validates with
  `ffmpeg -version` (cached, thread-safe). On success it **prepends the binary's
  folder to `PATH`** and inserts the exact path into `audioread.ffdec.COMMANDS`,
  so `librosa.load` also uses the bundled copy. `ffmpeg_probe()` parses
  `ffmpeg -i` stderr (duration/sr/channels/codec) — no `ffprobe` shipped.
  `reset_cache()` for re-detection. `describe()` → status line for UI.
* **`core/audio_engine.py`** — extension tables split into `NATIVE_INPUT_EXTENSIONS`
  (libsndfile) and `FFMPEG_PREFERRED_EXTENSIONS` (= compressed `.m4a .aac .wma
  .ac3 .amr …` + video `.mp4 .mkv .mov .webm .avi .ts …`). `load_audio()` uses
  order **ffmpeg → soundfile → librosa** for FFmpeg-preferred files and
  **soundfile → ffmpeg → librosa** otherwise, so `.m4a` never hits libsndfile's
  "Format not recognised". FFmpeg transcode uses `-vn -sn -dn -map 0:a:0? -acodec
  pcm_f32le -f wav` (audio track only from video). Decoder failures are tagged
  (`_decoder_error`) so the loop continues; validation errors (too long / empty)
  still abort immediately. `probe()` and `_enforce_duration_limit()` use the
  FFmpeg probe for compressed files. New: `ffmpeg_status()`, `AudioMasker.ffmpeg_info`,
  `.ffmpeg_available`, `AudioMasker.prefers_ffmpeg()`. CLI prints the backend line.
* **`bin/`** — `README.md` only; `bin/ffmpeg`, `bin/ffmpeg.exe`, `bin/FFMPEG_LICENSE.txt`
  are git-ignored. **`tools/fetch_ffmpeg.py`** downloads the BtbN static build
  (`--platform win64|linux64`, `--lgpl`, `--check`, `--force`) and extracts only
  `ffmpeg(.exe)` + licence.
* **`tests/test_formats.py`** (34) — fixtures encoded with sandbox FFmpeg, then
  decoded with **PATH stripped** and a copy planted as `_MEIPASS/bin/ffmpeg`
  (proves bundled-only operation). Covers `.m4a .aac .ogg .opus .flac .wma .mp3
  .mp4 .mkv .mov .webm`, full pipeline on M4A/MP4, "no FFmpeg anywhere" error
  path, backend fall-through, no-audio-track video, duration guard via probe.
* 93/93 tests green (sandbox has `/usr/bin/ffmpeg`; on a box without it, the
  34 format tests skip). `python -m core.audio_engine t.m4a -o out` works.

---

## 🔶 NEXT PENDING TASK — F2: UI status & FFmpeg auto-detection banner (`ui/app_ui.py`)

1. In `AudioMaskApp.__init__` replace the `if not self.masker.ffmpeg_path:` warning
   (around line 210) with:
   ```python
   info = self.masker.ffmpeg_info
   if self.masker.ffmpeg_available:
       self.log(f"[INFO] FFmpeg backend: {info.label if info else 'Found'} -> {self.masker.ffmpeg_path}")
   else:
       self.log("[WARN] FFmpeg backend: not found - M4A/AAC/WMA/MP4 decoding disabled. "
                "Reinstall the app (bin/ffmpeg.exe) or install FFmpeg.")
   ```
   (`self.log` already prefixes; check how it formats before adding `[INFO]`.)
2. Make the file-open dialog's `filetypes` use `SUPPORTED_INPUT_EXTENSIONS`
   (add an "All media" entry with every extension and separate "Audio"/"Video"
   groups). Grep `filedialog.askopenfilenames` in `ui/app_ui.py`.
3. If the UI filters dropped/selected files by extension, use
   `SUPPORTED_INPUT_EXTENSIONS` (not a hard-coded list) and never reject unknown
   extensions outright — the engine attempts them.
4. `core/logging_setup.py::log_environment` line ~172: replace the
   `shutil.which("ffmpeg")` log with `ffmpeg_locator.describe()`.
5. Add 2-4 tests to `tests/test_ui_logic.py` (pure helpers only, no Tk) and
   extend any existing dialog-filter helper test. Run full suite, commit, update
   this file (mark F2 done, activate F3), push.

### Then F3 (packaging)
* `build.spec`: if `bin/ffmpeg.exe` (win) / `bin/ffmpeg` (posix) exists add it to
  `binaries` as `(path, "bin")` → lands in `_internal/bin/` (one-folder) or
  `_MEIPASS/bin/` (one-file) — both already in the locator search list. Also add
  `bin/FFMPEG_LICENSE.txt` to `datas` when present. Warn loudly (not fail) if missing.
* `build.bat`: call `python tools\fetch_ffmpeg.py --platform win64` before
  PyInstaller; after build run `dist\AudioMaskPro\AudioMaskPro.exe --selftest`
  and fail on non-zero exit. `build.sh`: same with linux64.
* `main.py --selftest`: additionally print `ffmpeg_status()` and, if FFmpeg is
  available, round-trip a synthesized tone through `ffmpeg -> .m4a -> load_audio`.
* Bump `APP_VERSION` to 1.1.0, update README (FFmpeg no longer optional for
  users; bundled), mark F3 done here.

### Windows first-run checklist (do this if the user reports build problems)
1. `build.bat console` → run `dist\AudioMaskPro\AudioMaskPro.exe --selftest` and read the traceback.
2. Typical fixes: add module to `hiddenimports` in `build.spec`; if
   `libsndfile_x64.dll` is missing check `dist\AudioMaskPro\_internal\_soundfile_data\`;
   if Tk themes are missing confirm `_internal\customtkinter\assets\themes\*.json` exists.
3. Keep `upx=False`. Keep numba JIT enabled.

### Future ideas (prioritised)
1. **Presets** — save/load `MaskSettings` as JSON (`%LOCALAPPDATA%\AudioMaskPro\presets\`), preset dropdown in UI.
2. **Drag-and-drop** input files (`tkinterdnd2`; add to `collect_all` in spec).
3. **MP3 / M4A output guaranteed** — bundled FFmpeg is now always available: fall back to `ffmpeg -i out.wav -b:a 192k out.mp3` when `sf.check_format("MP3")` fails; add `m4a` output option.
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
| 2026-10-03 | 5 | **F1 bundled FFmpeg**: `core/ffmpeg_locator.py`, FFmpeg-first decode order in `core/audio_engine.py`, extended extension tables (video containers), `bin/` + `tools/fetch_ffmpeg.py`, `tests/test_formats.py` (34). 93/93 tests; M4A/MP4 decode verified with system PATH stripped. |
| 2026-10-03 | 4 | Task 4 packaging: `build.spec`, `hooks/rthook_numba.py`, `build.bat`, `build.sh`, `README.md`, `main.py --selftest`, v1.0.0. Fixed 3 spec issues (PyInstaller alias conflict, scipy.spatial, sklearn). Frozen Linux build starts under Xvfb and passes `--selftest`; 59/59 tests. **Roadmap complete.** |
