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
echo "[1/4] Python: $($PY --version)"
$PY -m pip install -q -r requirements.txt

echo "[2/4] Unit tests"
$PY -m unittest discover -s tests

echo "[3/4] PyInstaller"
rm -rf build dist
$PY -m PyInstaller --noconfirm --clean build.spec

echo "[4/4] Artefact check"
if [[ -n "${ONEFILE:-}" ]]; then
  BIN="dist/AudioMaskPro"
else
  BIN="dist/AudioMaskPro/AudioMaskPro"
  ls dist/AudioMaskPro/_internal/_soundfile_data/ >/dev/null \
    && echo "  libsndfile bundled: ok"
fi
[[ -x "$BIN" ]] || { echo "binary missing: $BIN"; exit 1; }
echo "  Build OK: $BIN ($(du -sh "$(dirname "$BIN")" | cut -f1))"

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
