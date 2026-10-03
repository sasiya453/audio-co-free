# AudioMask Pro

Standalone Windows 10 x64 desktop application for advanced audio DSP
manipulation: time-stretching, high-resolution pitch shifting, structural
frequency masking, micro-reverb room simulation and peak normalisation — all
from a modern dark-mode CustomTkinter interface with a fully non-blocking UI.

> **Disclaimer.** AudioMask Pro is a signal-processing tool. You are solely
> responsible for holding the rights to any audio you process and for complying
> with the terms of service of any platform you upload results to.

---

## What it does

Every input file runs through the same deterministic pipeline
(`core/audio_engine.py → AudioMasker.process_array`):

| # | Stage | Implementation | Purpose |
|---|---|---|---|
| 1 | Time stretch | `librosa.effects.time_stretch` (phase vocoder) | Changes duration without changing pitch |
| 2 | Pitch shift | `librosa.effects.pitch_shift` (soxr HQ resampling) | ±4 semitones, fractional resolution |
| 3 | Bandpass filter | `scipy.signal.butter(4, …, output="sos")` + `sosfilt` | 4th-order Butterworth, blends dry/wet by *intensity* |
| 4 | Micro-reverb | 30 ms delay-line feedback loop (numpy) | Subtle room character / fingerprint smearing |
| 5 | Peak normalise | Scale to −1 dBFS | Guarantees zero digital clipping |

Input: WAV, FLAC, OGG/Opus, AIFF natively; MP3, M4A/AAC, WMA, MP4 via FFmpeg
(auto-detected on `PATH`, optional).
Output: WAV (16-bit), FLAC, OGG Vorbis, MP3 (when the bundled libsndfile ≥ 1.1 supports it).

![screenshot placeholder](docs/screenshot.png)
*(Screenshot placeholder — drop a PNG at `docs/screenshot.png`.)*

---

## Requirements

| Running the `.exe` | Running / building from source |
|---|---|
| Windows 10 x64 (or 11) | Python 3.10+ **64-bit** |
| ~500 MB disk space for the bundle | `pip install -r requirements.txt` |
| *Optional:* [FFmpeg](https://ffmpeg.org/download.html) on `PATH` for MP3/M4A/WMA **input** | Same FFmpeg note applies |

No Python installation is required on the machine that runs the packaged build.

---

## Download & run the executable

1. Grab the latest `AudioMaskPro` folder (or `AudioMaskPro.exe` one-file build) from the project's releases, or build it yourself (below).
2. **One-folder build:** keep the whole `AudioMaskPro\` folder together and launch `AudioMaskPro.exe` inside it.
   **One-file build:** just run `AudioMaskPro.exe` (first start takes a few seconds while it unpacks to `%TEMP%`).
3. Windows SmartScreen may warn about an unsigned app — click *More info → Run anyway*.

Verify the installation headlessly (writes nothing permanent, exit code 0 = OK):

```bat
AudioMaskPro.exe --selftest
```

---

## Run from source

```bash
git clone https://github.com/sasiya453/audio-co-free.git
cd audio-co-free
python -m venv .venv
.venv\Scripts\activate          # Windows   (source .venv/bin/activate on POSIX)
pip install -r requirements.txt
python main.py                  # GUI
python main.py --selftest       # headless pipeline check
```

Set `AUDIOMASK_DEBUG=1` to enable DEBUG-level logging.

Headless CLI (no GUI) is also available:

```bash
python -m core.audio_engine song.mp3 -o out -p 1.5 -s 1.05
```

---

## Build the Windows executable

```bat
build.bat            :: one-folder bundle  -> dist\AudioMaskPro\AudioMaskPro.exe   (recommended)
build.bat onefile    :: single executable  -> dist\AudioMaskPro.exe
build.bat console    :: one-folder bundle that keeps a console window (debugging)
build.bat clean      :: remove build\, dist\, .venv
```

`build.bat` creates `.venv`, installs `requirements.txt`, runs the unit tests,
then invokes `pyinstaller --noconfirm --clean build.spec`.
After building, run `dist\AudioMaskPro\AudioMaskPro.exe --selftest` to confirm
that numba, soxr, libsndfile and scipy all work inside the bundle.

Build details (`build.spec`):

* `collect_all` for `customtkinter`, `librosa`, `soundfile`, `soxr`, `lazy_loader`
  (theme JSON files, `libsndfile_x64.dll`, librosa data files).
* Hidden imports for dynamically loaded `scipy.signal/special/fft`, `numba`,
  `llvmlite` and `scikit-learn` (a hard `librosa` dependency).
* Runtime hook `hooks/rthook_numba.py` redirects the numba JIT cache to `%TEMP%`
  so nothing is written inside the read-only bundle. JIT stays **enabled**.
* `upx=False` — UPX corrupts some numpy/scipy DLLs and triggers antivirus heuristics.
* Switches: `ONEFILE=1`, `CONSOLE=1` (environment variables read by the spec).
* Optional icon: place `assets/icon.ico` (Windows) / `assets/icon.png` (POSIX) and rebuild.

Linux/macOS/WSL: `./build.sh [folder|onefile|smoke]` validates the same spec.

---

## Settings reference

Ranges are enforced by `MaskSettings.validate()`; out-of-range values are clamped.

| Setting | Range | Default | Notes |
|---|---|---|---|
| Pitch (semitones) | −4.0 … +4.0 | 1.0 | Fractional values allowed (0.1 steps in UI) |
| Speed factor | 0.90 … 1.15 | 1.03 | >1 = faster/shorter |
| Bandpass enabled | on/off | on | 4th-order Butterworth |
| Bandpass intensity | 0.0 … 1.0 | 0.6 | Dry/wet blend of the filtered signal |
| Bandpass low / high | Hz | 80 / 14 000 | High is clamped below Nyquist |
| Micro-reverb enabled | on/off | on | |
| Reverb mix | 0.0 … 1.0 | 0.18 | Wet level |
| Reverb delay | 5 … 120 ms | 30 | Delay-line length |
| Reverb feedback | 0.0 … 0.95 | 0.25 | Loop attenuation |
| Normalise peak | −12 … 0 dBFS | −1.0 | Final peak level |
| Output format | wav / flac / ogg / mp3 | wav | |
| Max input duration | — | 20 min | Guard against out-of-memory on huge files |

### Output naming

`<original name>_masked.<fmt>` inside the chosen output folder. If that file
already exists, `_1`, `_2`, … are appended instead of overwriting.

### Logs

| Platform | Location |
|---|---|
| Windows | `%LOCALAPPDATA%\AudioMaskPro\logs\audiomask.log` |
| Linux / macOS | `~/.audiomask/logs/audiomask.log` |

Rotating file (2 MB × 3). The **Open log folder** button in the app header
opens it. The log begins with an environment dump (Python, numpy, scipy,
librosa, soundfile, libsndfile, FFmpeg) — attach it to bug reports.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| *"FFmpeg not found"* when opening MP3/M4A/WMA | Install FFmpeg and add it to `PATH` (`winget install Gyan.FFmpeg`), or convert to WAV/FLAC first. |
| Antivirus flags `AudioMaskPro.exe` | PyInstaller bundles are a common false positive. Build from source yourself with `build.bat`, or whitelist the folder. The build never uses UPX to reduce this risk. |
| *"The output file is locked"* / `PermissionError` | Close the file in your media player / DAW, or pick another output folder. |
| *"Disk full"* | Free space on the output drive; WAV output is ~10 MB per minute of stereo audio. |
| File skipped as *"longer than 20 min"* | Split the file, or raise `max_duration_s` when calling `AudioMasker(...)` from source. |
| Very slow first run | numba compiles its kernels on first use and caches them in `%TEMP%\AudioMaskPro\numba_cache`; later runs are fast. |
| App does not start, no window | Run `AudioMaskPro.exe --selftest` from a terminal and check the log file above. Rebuild with `build.bat console` to see tracebacks. |
| `ModuleNotFoundError` in a freshly built exe | Add the module to `hiddenimports` in `build.spec` and rebuild. |

---

## Tests

```bash
python -m unittest discover -s tests      # 59 tests, no display required
```

* `tests/test_engine.py` — DSP stages on synthetic signals, settings validation, I/O error paths.
* `tests/test_ui_logic.py` — logging bootstrap, hardening paths, pure UI helpers (no Tk).

---

## Project layout

```
main.py                 entry point (logging, crash guard, --selftest, launches UI)
core/audio_engine.py    AudioMasker, MaskSettings, probe(), CLI
core/logging_setup.py   rotating file logging + environment dump
ui/app_ui.py            CustomTkinter application (threaded batch processing)
hooks/rthook_numba.py   PyInstaller runtime hook (numba cache redirection)
build.spec              PyInstaller specification (one-folder / one-file)
build.bat / build.sh    build scripts (Windows / POSIX)
tests/                  unit tests
handoff.md              session-to-session state for AI agents
```

---

## License

MIT — see `LICENSE` (add the file if you distribute binaries).
