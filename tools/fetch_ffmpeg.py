#!/usr/bin/env python3
"""
Fetch a static FFmpeg build into ``bin/`` so it can be bundled by PyInstaller.

Usage
-----
    python tools/fetch_ffmpeg.py            # auto-detect platform
    python tools/fetch_ffmpeg.py --platform win64   # cross-fetch for Windows
    python tools/fetch_ffmpeg.py --check    # exit 0 if bin/ffmpeg(.exe) exists
    python tools/fetch_ffmpeg.py --force    # re-download even if present

Sources (static, self-contained, no DLL dependencies):
    * win64  : BtbN/FFmpeg-Builds "ffmpeg-master-latest-win64-gpl.zip"
               (GPL build; LGPL variant via --lgpl)
    * linux64: BtbN/FFmpeg-Builds "ffmpeg-master-latest-linux64-gpl.tar.xz"

Only ``ffmpeg(.exe)`` is kept (ffprobe/ffplay are discarded) - the engine
uses ``ffmpeg -i`` for probing so ffprobe is not needed. The licence file
shipped inside the archive is stored next to it as ``bin/FFMPEG_LICENSE.txt``.

The binary is deliberately git-ignored (≈100-150 MB). CI / ``build.bat`` run
this script before PyInstaller.
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "bin"

_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
SOURCES = {
    "win64": {
        "gpl": _BASE + "ffmpeg-master-latest-win64-gpl.zip",
        "lgpl": _BASE + "ffmpeg-master-latest-win64-lgpl.zip",
        "exe": "ffmpeg.exe",
    },
    "linux64": {
        "gpl": _BASE + "ffmpeg-master-latest-linux64-gpl.tar.xz",
        "lgpl": _BASE + "ffmpeg-master-latest-linux64-lgpl.tar.xz",
        "exe": "ffmpeg",
    },
}


def detect_platform() -> str:
    if sys.platform.startswith("win"):
        return "win64"
    if sys.platform.startswith("linux"):
        return "linux64"
    raise SystemExit(f"No static FFmpeg source configured for {sys.platform}; "
                     "install FFmpeg manually and copy it into bin/.")


def target_exe(platform: str) -> Path:
    return BIN_DIR / SOURCES[platform]["exe"]


def _progress(done: int, total: int) -> None:
    if total > 0:
        pct = done * 100 // total
        sys.stdout.write(f"\r  downloading... {done / 1e6:6.1f} / "
                         f"{total / 1e6:6.1f} MB ({pct:3d}%)")
    else:
        sys.stdout.write(f"\r  downloading... {done / 1e6:6.1f} MB")
    sys.stdout.flush()


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "AudioMaskPro/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            _progress(done, total)
    sys.stdout.write("\n")


def _extract_member(archive: Path, exe_name: str, out_exe: Path) -> None:
    """Pull ``bin/<exe_name>`` and ``LICENSE*`` out of a zip or tar.xz."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    license_out = BIN_DIR / "FFMPEG_LICENSE.txt"
    found = False
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                base = name.rsplit("/", 1)[-1]
                if base == exe_name and "/bin/" in name:
                    with zf.open(name) as src, open(out_exe, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found = True
                elif base.upper().startswith("LICENSE") and name.count("/") == 1:
                    license_out.write_bytes(zf.read(name))
    else:
        with tarfile.open(archive, "r:*") as tf:
            for m in tf.getmembers():
                base = m.name.rsplit("/", 1)[-1]
                if base == exe_name and "/bin/" in m.name and m.isfile():
                    src = tf.extractfile(m)
                    with open(out_exe, "wb") as dst:
                        shutil.copyfileobj(src, dst)  # type: ignore[arg-type]
                    found = True
                elif base.upper().startswith("LICENSE") and m.isfile() \
                        and m.name.count("/") == 1:
                    license_out.write_bytes(tf.extractfile(m).read())  # type: ignore[union-attr]
    if not found:
        raise SystemExit(f"{exe_name} not found inside {archive.name}")
    if os.name != "nt":
        out_exe.chmod(out_exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
                      | stat.S_IXOTH)


def verify(exe: Path) -> str:
    """Return the version line, or raise SystemExit. Skipped when the binary
    targets a different OS (e.g. win64 fetched on Linux)."""
    import subprocess
    if (exe.suffix == ".exe") != (os.name == "nt"):
        return "(cross-platform binary - not executed here)"
    out = subprocess.run([str(exe), "-version"], capture_output=True,
                         text=True, timeout=30)
    if out.returncode != 0:
        raise SystemExit(f"{exe} failed to run:\n{out.stderr}")
    return out.stdout.splitlines()[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--platform", choices=sorted(SOURCES),
                    help="target platform (default: auto)")
    ap.add_argument("--lgpl", action="store_true", help="use LGPL build")
    ap.add_argument("--force", action="store_true", help="re-download")
    ap.add_argument("--check", action="store_true",
                    help="only report whether bin/ffmpeg exists")
    ap.add_argument("--url", help="override download URL")
    args = ap.parse_args(argv)

    platform = args.platform or detect_platform()
    exe = target_exe(platform)

    if args.check:
        if exe.is_file():
            print(f"OK  {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
            return 0
        print(f"MISSING {exe}")
        return 1

    if exe.is_file() and not args.force:
        print(f"Already present: {exe} ({exe.stat().st_size / 1e6:.1f} MB) "
              f"- use --force to re-download")
        print(" ", verify(exe))
        return 0

    url = args.url or SOURCES[platform]["lgpl" if args.lgpl else "gpl"]
    print(f"Fetching FFmpeg ({platform}) from\n  {url}")
    with tempfile.TemporaryDirectory(prefix="ffmpeg_dl_") as td:
        archive = Path(td) / url.rsplit("/", 1)[-1]
        download(url, archive)
        print(f"  extracting {SOURCES[platform]['exe']} -> {exe}")
        _extract_member(archive, SOURCES[platform]["exe"], exe)
    print(" ", verify(exe))
    print(f"Done. {exe} ({exe.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
