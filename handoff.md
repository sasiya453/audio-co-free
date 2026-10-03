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
| Tests | `python -m unittest tests.test_engine` (31 tests, ~30 s) |
| CLI smoke | `python -m core.audio_engine song.mp3 -o out -p 1.5 -s 1.05` |

---

## Roadmap Status

| # | Task | Status |
|---|---|---|
| 1 | Core DSP Engine (`core/audio_engine.py`) | ✅ **DONE** |
| 2 | CustomTkinter Desktop UI (`ui/app_ui.py`) | 🔶 **NEXT — ACTIVE** |
| 3 | Logging, hardening, memory cleanup, error popups | ⬜ pending |
| 4 | PyInstaller `build.spec`, `build.bat`, `README.md` | ⬜ pending |

---

## Task 1 — COMPLETED (this session)

### File manifest
```
core/__init__.py
core/audio_engine.py      # AudioMasker + MaskSettings + CLI
tests/__init__.py
tests/test_engine.py      # 31 unit tests, synthetic signals, no fixtures needed
ui/__init__.py            # empty placeholder for Task 2
requirements.txt
.gitignore
handoff.md
```

### Engine API reference (what the UI must call)

```python
from core.audio_engine import AudioMasker, MaskSettings, AudioEngineError, \
    AudioLoadError, AudioWriteError, SUPPORTED_INPUT_EXTENSIONS, SUPPORTED_OUTPUT_FORMATS

settings = MaskSettings(
    pitch_semitones=1.0,      # -4.0 .. +4.0
    speed_factor=1.03,        # 0.90 .. 1.15
    bandpass_enabled=True,
    bandpass_low_hz=80.0,
    bandpass_high_hz=14000.0,
    bandpass_intensity=0.6,   # 0..1 dry/wet
    reverb_enabled=True,
    reverb_delay_ms=30.0,
    reverb_feedback=0.25,     # 0..0.95
    reverb_mix=0.18,          # 0..1
    normalize_peak_db=-1.0,
    output_format="wav",      # wav | flac | ogg | mp3 (mp3 only if libsndfile supports)
    output_suffix="_masked",
)
settings.LIMITS                # dict: field -> (min, max)  — use for slider bounds
settings.validate()            # clamps in place, returns self

masker = AudioMasker(target_sr=None)
out_path = masker.process_file(input_path, output_dir, settings,
                               progress_cb=lambda frac, msg: ...)  # frac 0..1
masker.cancel()                # safe to call from another thread
```

* `progress_cb` is called from whatever thread runs `process_file` — the UI
  must marshal to Tk via `widget.after(0, ...)` or a `queue.Queue`.
* All failures raise `AudioEngineError` subclasses with user-readable messages.
* Logger name: `audiomask.engine`.
* Pipeline order: stretch → pitch → Butterworth SOS bandpass (order 4) →
  comb-filter micro-reverb (lfilter, 30 ms) → peak normalise → write.
* Decoding chain: soundfile → librosa/audioread → FFmpeg temp-WAV fallback.

---

## 🔶 NEXT PENDING TASK — Task 2: Desktop UI (`ui/app_ui.py` + `main.py`)

### Deliverables
1. **`ui/app_ui.py`** — class `AudioMaskApp(customtkinter.CTk)`.
2. **`main.py`** at repo root — entry point: sets `ctk.set_appearance_mode("dark")`,
   builds `AudioMaskApp()`, calls `.mainloop()`. (PyInstaller will target this.)

### UI requirements
- Dark-mode, glassmorphic look: `ctk.set_default_color_theme("dark-blue")`,
  rounded `CTkFrame`s with slight transparency contrast, title "AudioMask Pro".
  Window ~ 820×640, min size set, `ctk.set_widget_scaling` respected.
- **Source section:** "Browse…" → `filedialog.askopenfilenames` (multi-select OK)
  filtered by `SUPPORTED_INPUT_EXTENSIONS`; show selected file list in a
  `CTkTextbox` or `CTkScrollableFrame`. Output dir via `askdirectory`
  (default = same folder as first input).
- **Sliders with live readouts** (bounds from `MaskSettings().LIMITS`):
  - Pitch semitones: -4.0 → +4.0, step 0.1, label shows `+1.50 st`
  - Speed factor: 0.90 → 1.15, step 0.01, label shows `x1.030`
- **Advanced panel** (collapsible or framed):
  - `CTkSwitch` Micro-Reverb on/off + slider Reverb Mix 0–1
  - `CTkSwitch` Bandpass on/off + slider Intensity 0–1
  - `CTkOptionMenu` output format: wav / flac / ogg
- **Process / Cancel buttons.** Process spawns `threading.Thread(daemon=True)`
  that loops over selected files calling `masker.process_file`. Cancel calls
  `masker.cancel()`. Disable controls while running.
- **Progress bar** `CTkProgressBar` (per-file + overall "n / N" label).
- **Status console** `CTkTextbox` (read-only, monospace) — append timestamped
  lines; auto-scroll. Thread-safe via `queue.Queue` drained by `self.after(100, poll)`.
- On error show `tkinter.messagebox.showerror` with the `AudioEngineError` text.
- Keep UI code free of DSP logic — import only from `core.audio_engine`.

### Validation for Task 2
- `python -m py_compile ui/app_ui.py main.py`
- Headless sandbox cannot open Tk windows; validate construction with
  `xvfb-run python -c "import main"` if `xvfb-run` exists, else py_compile only.
- Existing tests must still pass: `python -m unittest tests.test_engine`.

### After Task 2
Commit as `feat(ui): CustomTkinter desktop interface with threaded engine`,
update this file (mark Task 2 done, make Task 3 active with concrete
instructions), push to `origin main`.

---

## Session Log
| Date | Session | Summary |
|---|---|---|
| 2026-10-03 | 1 | Repo initialised; Task 1 engine + 31 tests implemented, all passing; MP3→WAV CLI smoke test OK. |
