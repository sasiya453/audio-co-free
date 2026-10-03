#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# AudioMask Pro - POSIX build / spec-validation script (Linux, macOS, WSL).
#
# The shipping target is Windows 10 x64 (use build.bat there). This script
# exists so the PyInstaller spec can be validated in CI / the dev sandbox.
#
#   ./build.sh            one-folder bundle  -> dist/AudioMaskPro/AudioMaskPro
#   ./build.sh onefile    single executable  -> dist/AudioMaskPro
#   ./build.sh smoke      build, then launch the binary headless for 15 s
#
# Pipeline: deps -> fetch bin/ffmpeg -> tests -> PyInstaller -> artefact check
#           -> frozen "--selftest" with PATH stripped (proves bundled FFmpeg)
# Env: SKIP_TESTS=1 skips the unit tests, SKIP_FFMPEG=1 skips the download.
# ----------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-folder}"
case "$MODE" in
  onefile) export ONEFILE=1 ;;
  folder|smoke) ;;
  *) echo "usage: $0 [folder|onefile|smoke]"; exit 2 ;;
esac

PY="${PYTHON:-python3}"
echo "[1/6] Python: $($PY --version)"
$PY -m pip install -q -r requirements.txt

echo "[2/6] Bundled FFmpeg"
if [[ -z "${SKIP_FFMPEG:-}" ]]; then
  if [[ -x bin/ffmpeg ]]; then
    echo "  bin/ffmpeg already present - skipping download"
  else
    case "$(uname -s)" in
      Linux)  $PY tools/fetch_ffmpeg.py --platform linux64 ;;
      *)      echo "  no static source for $(uname -s); copy an ffmpeg binary into bin/ manually" ;;
    esac
  fi
  if [[ -x bin/ffmpeg ]]; then
    bin/ffmpeg -version | head -n1 | grep -q '^ffmpeg version' \
      && echo "  bin/ffmpeg runs: $(bin/ffmpeg -version | head -n1 | cut -d' ' -f1-3)"
  else
    echo "  WARNING: bin/ffmpeg missing - packaged app will need FFmpeg on the user's PATH"
  fi
fi

echo "[3/6] Unit tests"
if [[ -z "${SKIP_TESTS:-}" ]]; then
  $PY -m unittest discover -s tests
else
  echo "  skipped (SKIP_TESTS=1)"
fi

echo "[4/6] PyInstaller"
rm -rf build dist
$PY -m PyInstaller --noconfirm --clean build.spec

echo "[5/6] Artefact check"
if [[ -n "${ONEFILE:-}" ]]; then
  BIN="dist/AudioMaskPro"
else
  BIN="dist/AudioMaskPro/AudioMaskPro"
  ls dist/AudioMaskPro/_internal/_soundfile_data/ >/dev/null \
    && echo "  libsndfile bundled: ok"
  if [[ -x bin/ffmpeg ]]; then
    [[ -x dist/AudioMaskPro/_internal/bin/ffmpeg ]] \
      || { echo "  bundled FFmpeg missing: dist/AudioMaskPro/_internal/bin/ffmpeg"; exit 1; }
    echo "  bundled FFmpeg: dist/AudioMaskPro/_internal/bin/ffmpeg  ok"
  fi
fi
[[ -x "$BIN" ]] || { echo "binary missing: $BIN"; exit 1; }
echo "  Build OK: $BIN ($(du -sh "$(dirname "$BIN")" | cut -f1))"

echo "[6/6] Frozen self-test (system PATH stripped -> must use bundled FFmpeg)"
set +e
env -i HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" PATH=/nonexistent "$BIN" --selftest; rc=$?
set -e
if [[ $rc -ne 0 ]]; then echo "  selftest FAILED (exit $rc)"; exit 1; fi
echo "  selftest OK"

if [[ "$MODE" == "smoke" ]]; then
  echo "Headless smoke start (15 s) ..."
  if command -v xvfb-run >/dev/null; then
    set +e
    xvfb-run -a timeout 15 "$BIN"; rc=$?
    set -e
    # 124 = killed by timeout after a clean start, 0 = app closed itself
    if [[ $rc -eq 124 || $rc -eq 0 ]]; then echo "  smoke OK (exit $rc)"; else
      echo "  smoke FAILED (exit $rc)"; exit 1; fi
  else
    echo "  xvfb-run not available - skipped"
  fi
fi
