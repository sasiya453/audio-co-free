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
| Run app | `python main.py` (set `AUDIOMASK_DEBUG=1` for debug logging) |
| Tests | `python -m unittest tests.test_engine` (31 tests, ~6 s) |
| CLI smoke | `python -m core.audio_engine song.mp3 -o out -p 1.5 -s 1.05` |
| Headless UI check | `sudo apt-get install -y xvfb && xvfb-run -a python -c "import sys; sys.path.insert(0,'.'); from ui.app_ui import AudioMaskApp; a=AudioMaskApp(); a.update(); a.destroy(); print('ok')"` |

---

## Roadmap Status

| # | Task | Status |
|---|---|---|
| 1 | Core DSP Engine (`core/audio_engine.py`) | ✅ DONE (session 1) |
| 2 | CustomTkinter Desktop UI (`ui/app_ui.py`, `main.py`) | ✅ **DONE (session 2)** |
| 3 | Logging, hardening, memory cleanup, error popups | 🔶 **NEXT — ACTIVE** |
| 4 | PyInstaller `build.spec`, `build.bat`, `README.md` | ⬜ pending |

---

## File Manifest (current)

```
main.py                   # entry point: logging setup, frozen-path fix, launches UI
core/__init__.py
core/audio_engine.py      # AudioMasker + MaskSettings + CLI  (Task 1)
ui/__init__.py
ui/app_ui.py              # AudioMaskApp(ctk.CTk)             (Task 2)
tests/__init__.py
tests/test_engine.py      # 31 unit tests, synthetic signals
requirements.txt
.gitignore
handoff.md
```

---

## Task 1 — Engine API reference (unchanged)

```python
from core.audio_engine import AudioMasker, MaskSettings, AudioEngineError, \
    AudioLoadError, AudioWriteError, SUPPORTED_INPUT_EXTENSIONS, SUPPORTED_OUTPUT_FORMATS

settings = MaskSettings(pitch_semitones=1.0, speed_factor=1.03,
                        bandpass_enabled=True, bandpass_intensity=0.6,
                        reverb_enabled=True, reverb_mix=0.18,
                        output_format="wav").validate()
masker = AudioMasker()                   # .ffmpeg_path = shutil.which("ffmpeg") or None
out = masker.process_file(src, out_dir, settings, progress_cb=lambda frac, msg: ...)
masker.cancel()                          # thread-safe flag; raises AudioEngineError("Processing cancelled by user")
```
* Logger names: `audiomask.engine`, `audiomask.ui`, `audiomask.main`.
* `process_file` already does `del audio; gc.collect()` in a `finally`.

## Task 2 — UI summary (what exists now)

`ui/app_ui.py` → `class AudioMaskApp(ctk.CTk)`:
* Panels: header (theme switch) · SOURCE (Browse multi-select, Clear, Output
  folder, file list `CTkTextbox`) · PRIMARY sliders (pitch −4..+4 step 0.1 →
  `+1.00 st`; speed 0.90..1.15 step 0.01 → `x1.030`) · ADVANCED (reverb switch
  + mix slider, bandpass switch + intensity slider, output format wav/flac/ogg,
  Reset) · ACTION (Process, Cancel, per-file + overall progress, `File n / N`
  label) · STATUS CONSOLE (read-only monospace, timestamped, auto-scroll).
* Threading: `_start_processing()` → `threading.Thread(_worker_main, daemon=True)`.
  Worker pushes `(MSG_*, payload)` tuples onto `self._queue`; `_poll_queue()`
  runs every 100 ms via `self.after`. **Worker never touches widgets.**
* Cancel: sets `self._cancel_flag` (Event) + `masker.cancel()`.
* Errors: `AudioEngineError`, `MemoryError`, generic `Exception` caught per
  file in worker → `MSG_FILE_ERROR` → logged; batch summary via `messagebox`.
* `build_settings()` returns validated `MaskSettings` from widget state.
* `_on_close()` asks for confirmation if a batch is running.
* Window 880×800, min 800×720. Palette constants at top of file.

Verified under Xvfb: construction, settings snapshot, 2-file threaded batch
→ FLAC output, missing-file error path, console content. 31 engine tests pass.

---

## 🔶 NEXT PENDING TASK — Task 3: Hardening, Logging & Resource Management

Goal: make the app robust enough to ship. Touch `core/audio_engine.py`,
`ui/app_ui.py`, `main.py`; add `core/logging_setup.py` and `tests/test_ui_logic.py`.

### 3.1 Logging (`core/logging_setup.py`, wire in `main.py`)
- `configure_logging(debug: bool = False) -> Path` → returns log file path.
- Console handler (INFO) + `logging.handlers.RotatingFileHandler`
  (DEBUG, 2 MB × 3 backups) at `%LOCALAPPDATA%\AudioMaskPro\logs\audiomask.log`
  on Windows (`os.environ.get("LOCALAPPDATA")`), fallback `Path.home()/".audiomask"/logs`.
  Create dirs with `mkdir(parents=True, exist_ok=True)`; if that fails fall
  back to console only (never crash on logging).
- Replace `_setup_logging()` in `main.py` with this; log Python version,
  platform, numpy/scipy/librosa/soundfile versions, ffmpeg path at startup.
- Add an "Open log folder" small button in the UI header
  (`os.startfile` on Windows, `xdg-open`/`open` elsewhere, wrapped in try/except).

### 3.2 Engine hardening (`core/audio_engine.py`)
- `load_audio`: reject empty/zero-length audio with `AudioLoadError("File contains no audio")`;
  reject files > configurable `max_duration_s` (default 20 min) with a clear
  message; convert NaN/Inf samples via `np.nan_to_num` after load.
- Wrap FFmpeg fallback: catch `FileNotFoundError`, `subprocess.TimeoutExpired`
  (set `timeout=300`), non-zero return → `AudioLoadError` with a hint
  "Install FFmpeg and add it to PATH to decode MP3/M4A".
- `write_audio`: catch `PermissionError`/`OSError` → `AudioWriteError` with
  the full path; if file is locked, suggest closing the player.
- Add `AudioMasker.probe(path) -> dict` (duration, sr, channels) using
  `soundfile.info` with librosa fallback; used by UI for pre-flight checks.
- Make sure every stage frees intermediates (`del` + the existing `gc.collect()`);
  convert to `np.float32` right after load to halve memory.

### 3.3 UI hardening (`ui/app_ui.py`)
- Pre-flight before starting batch: `probe()` each file; skip & log unreadable
  files; show a `messagebox.askyesno` if some were skipped.
- Warn (askyesno) when output dir == input dir AND output format/suffix would
  overwrite an existing file.
- Check output dir is writable (`os.access(dir, os.W_OK)`) → showerror otherwise.
- Catch `tkinter.TclError` inside `_handle_message` for widgets destroyed
  during shutdown.
- Guard `_poll_queue` re-scheduling after `destroy()` (set `self._closing=True`).
- Add "Open output folder" button enabled after a successful batch.

### 3.4 Tests (`tests/test_ui_logic.py`) — no Tk required
- Test `MaskSettings` round-trip from a fake widget state (factor out
  `settings_from_values(pitch, speed, reverb_on, reverb_mix, bp_on, bp_int, fmt)`
  as a pure function in `ui/app_ui.py` and have `build_settings()` call it).
- Test `configure_logging()` creates a file in a temp dir (monkeypatch
  `LOCALAPPDATA`/`HOME`).
- Test `AudioMasker.probe` and the new `AudioLoadError` paths (empty file,
  NaN samples, too-long duration with `max_duration_s=1`).

### Validation for Task 3
```
python -m py_compile core/*.py ui/*.py main.py
python -m unittest discover -s tests -v
xvfb-run -a python -c "..."   # headless construction check (see Snapshot table)
```

### After Task 3
Commit as `feat(hardening): rotating log files, pre-flight checks, engine error hardening`,
update this file (mark Task 3 done, make Task 4 active with concrete PyInstaller
instructions: hidden imports for `librosa`, `scipy.signal`, `soundfile` + its
`_soundfile_data` DLLs, `customtkinter` assets via `--collect-all customtkinter`,
`numba` cache off, `main.py` entry, `--noconsole`, `build.bat`, `README.md`),
push to `origin main`.

---

## Session Log
| Date | Session | Summary |
|---|---|---|
| 2026-10-03 | 1 | Repo initialised; Task 1 engine + 31 tests implemented, all passing; MP3→WAV CLI smoke test OK. |
| 2026-10-03 | 2 | Task 2 UI (`ui/app_ui.py`, `main.py`) implemented; verified under Xvfb incl. threaded batch + error path; tests green. |
