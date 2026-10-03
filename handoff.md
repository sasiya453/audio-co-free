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
| Version | **1.1.0** (`ui/app_ui.py::APP_VERSION`) — bundled-FFmpeg release |
| Python | 3.10+ (dev sandbox runs 3.13; keep 3.10-compatible syntax) |
| Deps | see `requirements.txt` (numpy, scipy, librosa, soundfile, soxr, customtkinter, pyinstaller) |
| Run app | `python main.py` (set `AUDIOMASK_DEBUG=1` for debug console) |
| Headless check | `python main.py --selftest` (also works on the frozen exe; prints FFmpeg backend + M4A round-trip) |
| Log file | `%LOCALAPPDATA%\AudioMaskPro\logs\audiomask.log` (Win) / `~/.audiomask/logs/` (other) |
| Tests | `python -m unittest discover -s tests` (**106 tests, ~15-40 s**, no display needed; needs `ffmpeg` (bin/ or PATH) to build fixtures, else format tests skip; `pip install customtkinter` else 9 UI-helper tests skip) |
| CLI smoke | `python -m core.audio_engine song.mp3 -o out -p 1.5 -s 1.05` |
| Build (Windows) | `build.bat` → `dist\AudioMaskPro\AudioMaskPro.exe` (`build.bat onefile` / `console` / `clean`); fetches `bin\ffmpeg.exe`, verifies `_internal\bin\ffmpeg.exe`, runs PATH-stripped `--selftest` |
| Build (sandbox) | `./build.sh smoke` (`SKIP_TESTS=1`, `SKIP_FFMPEG=1` env) or `pyinstaller --noconfirm --clean build.spec && env -i HOME=$HOME PATH=/nonexistent dist/AudioMaskPro/AudioMaskPro --selftest` |
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

### Bundled-FFmpeg upgrade (universal format support) — ✅ ALL 3 TASKS COMPLETE (v1.1.0)
| # | Task | Status |
|---|---|---|
| F1 | Bundled FFmpeg integration + audio loader hardening (`core/ffmpeg_locator.py`, `core/audio_engine.py`, `bin/`, `tools/fetch_ffmpeg.py`, `tests/test_formats.py`) | ✅ **DONE (session 5)** |
| F2 | UI status banner + auto-detection (`ui/app_ui.py`): `[INFO] FFmpeg backend: Bundled/Found`, file dialog accepts all `SUPPORTED_INPUT_EXTENSIONS` | ✅ **DONE (session 6)** |
| F3 | `build.spec` bundles `bin/ffmpeg.exe`; `build.bat`/`build.sh` fetch it + verify + PATH-stripped frozen `--selftest`; `--selftest` M4A round-trip; `APP_VERSION` → 1.1.0; README | ✅ **DONE (session 7)** |

---

## File Manifest (current)

```
main.py                   # entry point: logging bootstrap, thread excepthook, crash popup, --selftest (DSP + FFmpeg M4A round-trip, F3), launches UI
core/__init__.py
core/audio_engine.py      # AudioMasker + MaskSettings + probe() + CLI   (Task 1, hardened Task 3, FFmpeg-first decode F1)
core/ffmpeg_locator.py    # find_ffmpeg(): env -> _MEIPASS/bin -> exe dir -> repo bin/ -> PATH; PATH injection; probe (F1)
core/logging_setup.py     # configure_logging / log_environment / open_log_folder (Task 3)
bin/README.md             # bundled FFmpeg folder; ffmpeg(.exe) is git-ignored, fetched by tools/fetch_ffmpeg.py (F1)
tools/fetch_ffmpeg.py     # downloads static BtbN FFmpeg build (win64/linux64) into bin/; --check / --force / --lgpl (F1)
ui/__init__.py
ui/app_ui.py              # AudioMaskApp(ctk.CTk) v1.1.0 + pure helpers  (Task 2, hardened Task 3, FFmpeg banner + universal dialog F2)
hooks/rthook_numba.py     # PyInstaller runtime hook: NUMBA_CACHE_DIR/LIBROSA_DATA_DIR -> %TEMP% (Task 4)
build.spec                # PyInstaller spec, one-folder default; ONEFILE=1 / CONSOLE=1 env switches; bundles bin/ffmpeg(.exe) -> bin/ (Task 4, F3)
build.bat                 # Windows build: venv -> deps -> fetch ffmpeg -> tests -> pyinstaller -> verify -> frozen selftest (Task 4, F3)
build.sh                  # POSIX equivalent incl. PATH-stripped frozen selftest + Xvfb smoke (Task 4, F3)
README.md                 # user + developer documentation (Task 4, FFmpeg bundling docs F3)
tests/__init__.py
tests/test_engine.py      # 31 DSP/engine tests (synthetic signals)
tests/test_ui_logic.py    # 41 tests: logging, hardening paths, UI helpers incl. FFmpeg banner / dialog filetypes / add_files (no Tk), main._selftest (F3)
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

## What Task F2 delivered (session 6)

* **`ui/app_ui.py`** — new pure helpers (Tk-free, unit-tested):
  * `ffmpeg_status_line(masker) -> (message, available)` →
    `"[INFO] FFmpeg backend: Bundled (7.1) -> …\_internal\bin\ffmpeg.exe"` /
    `"[INFO] FFmpeg backend: System PATH (6.0) -> /usr/bin/ffmpeg"` /
    `"[INFO] FFmpeg backend: Found -> <explicit path>"` /
    `"[WARN] FFmpeg backend: not found - M4A/AAC/WMA/MP4 decoding disabled. Reinstall the app (bin/ffmpeg.exe) or install FFmpeg and add it to PATH."`
  * `build_file_dialog_filetypes()` — Tk `filetypes` built from the engine
    tables: **"All media (audio + video)"** (default, every
    `SUPPORTED_INPUT_EXTENSIONS`), "Audio - uncompressed / lossless"
    (`NATIVE_INPUT_EXTENSIONS`), "Audio - compressed (M4A, AAC, WMA ...)"
    (`COMPRESSED_INPUT_EXTENSIONS`), "Video (audio track extracted)"
    (`VIDEO_CONTAINER_EXTENSIONS`), "All files".
  * `classify_input_path(path) -> "supported" | "unknown"` — informational only.
* `AudioMaskApp.__init__` now calls `_log_ffmpeg_status()` (old "FFmpeg not
  found on PATH" note removed); when available it also logs
  `Universal input enabled: WAV/FLAC/OGG/MP3 plus M4A, AAC, WMA, Opus and video containers (MP4/MKV/MOV/WebM).`
* New `AudioMaskApp.add_files(paths) -> int` shared by `_pick_files` (and any
  future drag-and-drop): **never rejects by extension** — unknown extensions
  get a console hint and are still queued (engine/FFmpeg sniffs the container);
  folders are skipped; duplicates ignored.
* **`core/logging_setup.py::log_environment`** logs `ffmpeg_locator.describe()`
  (falls back to `shutil.which` only if the locator import fails).
* **Tests:** +9 in `tests/test_ui_logic.py` (banner variants, dialog filetypes
  cover every supported ext incl. `.m4a .aac .wma .ogg .flac .mp4 .mkv`,
  classify, `add_files` without a Tk window, `log_environment` emits
  `FFmpeg backend:`). **102/102 green.**
* **Verified under Xvfb:** console shows
  `[INFO] FFmpeg backend: System PATH (7.1.5…) -> /usr/bin/ffmpeg` and, with
  `PATH` emptied inside the process, the `[WARN] … not found` line.

---

## What Task F3 delivered (session 7)

* **`build.spec`** — new `FFMPEG_SRC = ROOT/bin/ffmpeg(.exe)`; when present it is
  appended to `binaries` as `(path, "bin")` (→ `_internal/bin/` one-folder,
  `_MEIPASS/bin/` one-file — both in `ffmpeg_locator.candidate_paths()`), and
  `bin/FFMPEG_LICENSE.txt` goes to `datas` as `(path, "bin")`. Missing binary →
  loud `WARNING: bin/ffmpeg(.exe) missing - run python tools/fetch_ffmpeg.py`
  on stdout+stderr, build continues. `core.ffmpeg_locator` added to hiddenimports.
* **`build.bat`** — 8 steps: venv → pip → deps → **fetch `bin\ffmpeg.exe`**
  (`tools\fetch_ffmpeg.py --platform win64`, skipped if present; `--check` +
  `ffmpeg -version` sanity) → tests → PyInstaller → verify
  `dist\AudioMaskPro\_internal\bin\ffmpeg.exe` (one-folder) → run the frozen
  `--selftest` with `PATH=%SystemRoot%\System32;%SystemRoot%` and
  `AUDIOMASK_FFMPEG=` cleared (proves the *bundled* copy works), `exit /b 1` on failure.
  `clean` keeps `bin\ffmpeg.exe`.
* **`build.sh`** — same pipeline for POSIX (`linux64`), frozen selftest via
  `env -i HOME=… PATH=/nonexistent`; `SKIP_TESTS=1` / `SKIP_FFMPEG=1` switches.
* **`main.py --selftest`** — prints `SELFTEST FFmpeg backend: …` (from
  `ffmpeg_status()`), runs the DSP pipeline, then if `masker.ffmpeg_available`
  calls `_selftest_ffmpeg_roundtrip()`: `tone.wav -> ffmpeg -c:a aac -> .m4a ->
  AudioMasker.load_audio` and checks duration ±0.25 s, finite, peak ≥ 0.05.
  Round-trip failure → exit 3. No FFmpeg at all → `SELFTEST WARNING … [ffmpeg: none]`,
  still exit 0 (DSP build is valid, just not universal). `_emit()` helper handles
  `sys.stdout is None` under `--noconsole`.
* **`APP_VERSION = "1.1.0"`**; **README** rewritten sections: supported-input
  table (native / lossy / compressed / video), "no FFmpeg install needed",
  selftest sample output, build pipeline, BtbN GPL/`--lgpl` licence note,
  troubleshooting rows for missing bundled FFmpeg, 102→106 tests, project layout.
* **Tests:** +4 `SelftestTests` in `tests/test_ui_logic.py` (backend reported,
  no-FFmpeg = warning not failure, round-trip failure = exit 3, helper decodes M4A).
  **106/106 green.**
* **Sandbox validation (Linux):** `tools/fetch_ffmpeg.py --platform linux64` →
  `bin/ffmpeg` 175 MB (BtbN `N-127054`); `pyinstaller build.spec` prints
  `[build.spec] Bundling FFmpeg …`; `dist/AudioMaskPro/_internal/bin/{ffmpeg,FFMPEG_LICENSE.txt}`
  present (631 MB total); `env -i PATH=/nonexistent dist/AudioMaskPro/AudioMaskPro --selftest`
  → `SELFTEST FFmpeg backend: Bundled (N-127054…) -> …/_internal/bin/ffmpeg`,
  `M4A round-trip OK`, exit 0; frozen GUI under Xvfb with PATH stripped logs
  `[INFO] FFmpeg backend: Bundled …` + `Universal input enabled …`, `v1.1.0 ready.`
* **Not yet validated:** an actual Windows 10 run of `build.bat` (sandbox is Linux-only).
  Expected first Windows run: `build.bat` → downloads ~100 MB zip → build →
  `[8/8] Frozen self-test` prints `Bundled`.

---

## 🔶 NEXT PENDING TASK — none scheduled

The bundled-FFmpeg upgrade is complete. Pick from **Future ideas** below only if
the user asks; otherwise respond to Windows build feedback using the checklist.

### Windows first-run checklist (do this if the user reports build problems)
1. `build.bat console` → run `dist\AudioMaskPro\AudioMaskPro.exe --selftest` and read the traceback.
2. Typical fixes: add module to `hiddenimports` in `build.spec`; if
   `libsndfile_x64.dll` is missing check `dist\AudioMaskPro\_internal\_soundfile_data\`;
   if Tk themes are missing confirm `_internal\customtkinter\assets\themes\*.json` exists.
3. FFmpeg specific: if `[7/8]` says `_internal\bin\ffmpeg.exe is missing` the spec
   did not see `bin\ffmpeg.exe` — check `[build.spec] Bundling FFmpeg` line in the
   PyInstaller output. If `[8/8]` fails at *M4A round-trip* with `WinError 5` /
   antivirus, whitelist `dist\`. If the BtbN download URL changes, update
   `SOURCES` in `tools/fetch_ffmpeg.py`.
4. Keep `upx=False`. Keep numba JIT enabled.

### Future ideas (prioritised)
1. **Presets** — save/load `MaskSettings` as JSON (`%LOCALAPPDATA%\AudioMaskPro\presets\`), preset dropdown in UI.
2. **Drag-and-drop** input files (`tkinterdnd2`; add to `collect_all` in spec).
3. **MP3 / M4A output guaranteed** — bundled FFmpeg is now always available: fall back to `ffmpeg -i out.wav -b:a 192k out.mp3` when `sf.check_format("MP3")` fails; add `m4a` output option.
3b. **Smaller bundle** — the BtbN GPL build is ~150 MB; a custom-trimmed static FFmpeg (audio-only demuxers/decoders, `--disable-everything --enable-decoder=aac,mp3,…`) would be ~15 MB. Alternatively `--lgpl` is slightly smaller.
3c. **GitHub Actions `windows-latest` CI** running `build.bat` would close the "not validated on Windows" gap.
4. **Batch parallelism** — `concurrent.futures.ThreadPoolExecutor(max_workers=2)` for multi-file jobs; keep progress aggregation thread-safe via the existing queue.
5. **Waveform preview** — before/after mini waveform drawn on a `CTkCanvas` (numpy decimation; no matplotlib).
6. **i18n** — move UI strings to `ui/strings.py` dict; add language switch.
7. **Code signing / release CI** — GitHub Actions `windows-latest` job running `build.bat` and uploading `dist\` as an artifact; `LICENSE` file (MIT).
8. **Icon** — add `assets/icon.ico` (256×256 multi-res); spec already picks it up.

### Validation for any future change
```
python -m py_compile build.spec main.py hooks/*.py core/*.py ui/*.py tools/*.py
python -m unittest discover -s tests
python tools/fetch_ffmpeg.py --check || python tools/fetch_ffmpeg.py --platform linux64
pyinstaller --noconfirm --clean build.spec
env -i HOME=$HOME TMPDIR=/tmp PATH=/nonexistent dist/AudioMaskPro/AudioMaskPro --selftest   # must say "Bundled"
```

---

## Session Log
| Date | Session | Summary |
|---|---|---|
| 2026-10-03 | 1 | Repo initialised; Task 1 engine + 31 tests implemented, all passing; MP3→WAV CLI smoke test OK. |
| 2026-10-03 | 2 | Task 2 UI (`ui/app_ui.py`, `main.py`) implemented; verified under Xvfb incl. threaded batch + error path; tests green. |
| 2026-10-03 | 3 | Task 3 hardening: `core/logging_setup.py`, engine `probe()`/duration/NaN/FFmpeg/write error paths, UI pre-flight + log/output buttons + safe shutdown, `tests/test_ui_logic.py` (28). 59/59 tests pass; Xvfb batch + `main.py` start-up log verified. |
| 2026-10-03 | 7 | **F3 packaging**: `build.spec` bundles `bin/ffmpeg(.exe)`+licence into `bin/`; `build.bat`/`build.sh` fetch FFmpeg, verify `_internal/bin/ffmpeg`, run PATH-stripped frozen `--selftest`; `main.py --selftest` prints backend + M4A round-trip (exit 3 on failure); `APP_VERSION` 1.1.0; README. +4 tests (106/106). Frozen Linux build verified `Bundled` with PATH stripped. **FFmpeg upgrade complete.** |
| 2026-10-03 | 6 | **F2 UI banner**: `ffmpeg_status_line` / `build_file_dialog_filetypes` / `classify_input_path` / `AudioMaskApp.add_files` in `ui/app_ui.py`; `log_environment` uses locator; +9 tests (102/102). Xvfb verified `[INFO] FFmpeg backend: …` and `[WARN]` paths. |
| 2026-10-03 | 5 | **F1 bundled FFmpeg**: `core/ffmpeg_locator.py`, FFmpeg-first decode order in `core/audio_engine.py`, extended extension tables (video containers), `bin/` + `tools/fetch_ffmpeg.py`, `tests/test_formats.py` (34). 93/93 tests; M4A/MP4 decode verified with system PATH stripped. |
| 2026-10-03 | 4 | Task 4 packaging: `build.spec`, `hooks/rthook_numba.py`, `build.bat`, `build.sh`, `README.md`, `main.py --selftest`, v1.0.0. Fixed 3 spec issues (PyInstaller alias conflict, scipy.spatial, sklearn). Frozen Linux build starts under Xvfb and passes `--selftest`; 59/59 tests. **Roadmap complete.** |
