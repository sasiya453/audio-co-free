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

### Supported input — universal format support (v1.1)

AudioMask Pro ships with a **bundled static FFmpeg** (`bin\ffmpeg.exe`, placed
in `_internal\bin\` of the packaged app). End users do **not** need to install
FFmpeg; the engine finds the bundled copy automatically and falls back to a
system-wide FFmpeg on `PATH` only if the bundled one is missing.

| Category | Extensions | Decoder |
|---|---|---|
| Uncompressed / lossless | `.wav .flac .aiff .aif .w64 .caf .au` … | libsndfile (soundfile) |
| Lossy audio | `.mp3 .ogg .oga .opus` | libsndfile, FFmpeg fallback |
| Compressed audio (needs FFmpeg) | `.m4a .m4b .aac .wma .ac3 .amr .mka .mp2 .ape .tta` … | **bundled FFmpeg** → temp WAV |
| Video containers (audio track extracted) | `.mp4 .mkv .mov .webm .avi .ts .m4v .3gp .flv .wmv` … | **bundled FFmpeg** → temp WAV |

Files with unknown extensions are not rejected — FFmpeg sniffs the container.
The start-up console shows which backend is active, e.g.
`[INFO] FFmpeg backend: Bundled (7.1) -> …\_internal\bin\ffmpeg.exe`.

Output: WAV (16-bit), FLAC, OGG Vorbis, MP3 (when the bundled libsndfile ≥ 1.1 supports it).

![screenshot placeholder](docs/screenshot.png)
*(Screenshot placeholder — drop a PNG at `docs/screenshot.png`.)*

---

## Requirements

| Running the `.exe` | Running / building from source |
|---|---|
| Windows 10 x64 (or 11) | Python 3.10+ **64-bit** |
| ~650 MB disk space for the bundle (incl. ~150 MB FFmpeg) | `pip install -r requirements.txt` |
| **Nothing else** — FFmpeg is bundled | `python tools/fetch_ffmpeg.py` (downloads `bin/ffmpeg(.exe)`), or FFmpeg on `PATH` |

No Python installation and **no FFmpeg installation** are required on the
machine that runs the packaged build.

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

The self-test prints the active FFmpeg backend, runs the full DSP pipeline on a
synthesised tone and — when FFmpeg is available — encodes that tone to `.m4a`
and decodes it back, proving that compressed-format support works on this PC:

```
SELFTEST FFmpeg backend: Bundled (N-1270xx) -> C:\...\AudioMaskPro\_internal\bin\ffmpeg.exe
SELFTEST DSP pipeline OK (1.90s @ 22050 Hz, peak 0.891)
SELFTEST M4A round-trip OK (21.9 kB, 2.00s @ 22050 Hz, peak 0.302)
SELFTEST OK: ...\tone_masked.wav [ffmpeg: Bundled (N-1270xx)]
```

---

## Run from source

```bash
git clone https://github.com/sasiya453/audio-co-free.git
cd audio-co-free
python -m venv .venv
.venv\Scripts\activate          # Windows   (source .venv/bin/activate on POSIX)
pip install -r requirements.txt
python tools/fetch_ffmpeg.py    # optional: bundled FFmpeg into bin/ (else system PATH is used)
python main.py                  # GUI
python main.py --selftest       # headless pipeline + FFmpeg M4A round-trip check
```

Set `AUDIOMASK_DEBUG=1` to enable DEBUG-level logging. Set `AUDIOMASK_FFMPEG`
to the full path of an `ffmpeg` executable to override auto-detection.

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

`build.bat` pipeline:

1. creates `.venv` and installs `requirements.txt`;
2. **fetches the static FFmpeg** (`python tools\fetch_ffmpeg.py --platform win64`
   → `bin\ffmpeg.exe`, skipped when already present) and checks it runs;
3. runs the unit tests;
4. invokes `pyinstaller --noconfirm --clean build.spec`;
5. verifies `dist\AudioMaskPro\_internal\bin\ffmpeg.exe` exists;
6. runs `dist\AudioMaskPro\AudioMaskPro.exe --selftest` **with the system `PATH`
   stripped**, so the build only passes if the *bundled* FFmpeg decodes M4A.

Build details (`build.spec`):

* Bundles `bin/ffmpeg.exe` (+ `bin/FFMPEG_LICENSE.txt`) into `bin/` inside the
  bundle (`_internal\bin\` one-folder, `%TEMP%\_MEIxxxx\bin\` one-file). If the
  binary is missing the spec prints a loud warning but still builds.
* `collect_all` for `customtkinter`, `librosa`, `soundfile`, `soxr`, `lazy_loader`
  (theme JSON files, `libsndfile_x64.dll`, librosa data files).
* Hidden imports for dynamically loaded `scipy.signal/special/fft`, `numba`,
  `llvmlite` and `scikit-learn` (a hard `librosa` dependency).
* Runtime hook `hooks/rthook_numba.py` redirects the numba JIT cache to `%TEMP%`
  so nothing is written inside the read-only bundle. JIT stays **enabled**.
* `upx=False` — UPX corrupts some numpy/scipy DLLs and triggers antivirus heuristics.
* Switches: `ONEFILE=1`, `CONSOLE=1` (environment variables read by the spec).
* Optional icon: place `assets/icon.ico` (Windows) / `assets/icon.png` (POSIX) and rebuild.

Linux/macOS/WSL: `./build.sh [folder|onefile|smoke]` validates the same spec
(fetches the `linux64` FFmpeg build, runs the PATH-stripped frozen self-test).

### Bundled FFmpeg licence note

`tools/fetch_ffmpeg.py` downloads the static builds published by
[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds). The default is the
**GPL** variant (most codecs). If you redistribute AudioMask Pro binaries and
prefer LGPL terms, fetch with `python tools/fetch_ffmpeg.py --lgpl`. The
licence text from the archive is shipped as `_internal\bin\FFMPEG_LICENSE.txt`.
The binary itself (~150 MB) is git-ignored; only `bin/README.md` is committed.

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
| Console shows `[WARN] FFmpeg backend: not found` | The bundled `_internal\bin\ffmpeg.exe` is missing (incomplete copy / antivirus quarantine). Reinstall the whole `AudioMaskPro` folder, or install FFmpeg and add it to `PATH` (`winget install Gyan.FFmpeg`), or set `AUDIOMASK_FFMPEG=C:\path\to\ffmpeg.exe`. |
| `--selftest` fails at *M4A round-trip* | Antivirus blocked `ffmpeg.exe` from executing, or the file is corrupt. Whitelist the folder; rebuild after `del bin\ffmpeg.exe` to re-download. |
| *"Format not recognised"* on `.m4a/.aac/.wma/.mp4` | Only happens when no FFmpeg backend is available — see the two rows above. |
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
python -m unittest discover -s tests      # 102 tests, no display required
```

* `tests/test_engine.py` — DSP stages on synthetic signals, settings validation, I/O error paths.
* `tests/test_ui_logic.py` — logging bootstrap, hardening paths, pure UI helpers incl. the FFmpeg banner (no Tk).
* `tests/test_formats.py` — M4A/AAC/OGG/Opus/FLAC/WMA/MP3/MP4/MKV/MOV/WebM decoding through a
  *bundled-only* FFmpeg (system `PATH` stripped). Skipped when no FFmpeg is available to build fixtures.

---

## Project layout

```
main.py                 entry point (logging, crash guard, --selftest incl. FFmpeg M4A round-trip, launches UI)
core/audio_engine.py    AudioMasker, MaskSettings, probe(), CLI (FFmpeg-first decode for compressed/video)
core/ffmpeg_locator.py  find_ffmpeg(): env -> bundled (_MEIPASS/bin, exe dir) -> repo bin/ -> PATH
core/logging_setup.py   rotating file logging + environment dump
ui/app_ui.py            CustomTkinter application (threaded batch processing, FFmpeg status banner)
bin/                    bundled FFmpeg (git-ignored binary, fetched by tools/fetch_ffmpeg.py)
tools/fetch_ffmpeg.py   downloads a static FFmpeg build (win64 / linux64, --lgpl, --check)
hooks/rthook_numba.py   PyInstaller runtime hook (numba cache redirection)
build.spec              PyInstaller specification (one-folder / one-file, bundles bin/ffmpeg)
build.bat / build.sh    build scripts (Windows / POSIX): deps -> FFmpeg -> tests -> build -> selftest
tests/                  unit tests
handoff.md              session-to-session state for AI agents
```

---

## License

MIT — see `LICENSE` (add the file if you distribute binaries).
