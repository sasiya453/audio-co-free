# bin/ — bundled FFmpeg

AudioMask Pro decodes M4A / AAC / WMA / MP3 and the audio track of MP4 / MKV /
MOV / WebM through a **bundled static FFmpeg** so end users never have to
install FFmpeg themselves.

The binary itself (~100-150 MB) is **not committed to git**. Fetch it before
building:

```
python tools/fetch_ffmpeg.py                  # auto-detect (win64 on Windows)
python tools/fetch_ffmpeg.py --platform win64 # explicit
python tools/fetch_ffmpeg.py --check          # verify presence
```

Expected layout after fetching:

```
bin/
  ffmpeg.exe          (Windows)   or   ffmpeg (Linux)
  FFMPEG_LICENSE.txt  licence text shipped with the static build
  README.md           this file
```

Discovery order used by `core/ffmpeg_locator.py` at runtime:

1. `AUDIOMASK_FFMPEG` env var
2. `sys._MEIPASS/ffmpeg.exe`, `sys._MEIPASS/bin/ffmpeg.exe`, `<exe dir>/ffmpeg.exe`, `<exe dir>/bin/ffmpeg.exe` (frozen app)
3. `<repo>/bin/ffmpeg.exe` (source checkout)
4. `ffmpeg` on the system `PATH`

Source of the static builds: https://github.com/BtbN/FFmpeg-Builds (GPL by
default, `--lgpl` for the LGPL variant).
