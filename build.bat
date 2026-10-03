@echo off
REM ============================================================================
REM  AudioMask Pro - Windows 10 x64 build script
REM
REM  Usage:
REM      build.bat              one-folder bundle  -> dist\AudioMaskPro\AudioMaskPro.exe
REM      build.bat onefile      single executable  -> dist\AudioMaskPro.exe
REM      build.bat console      one-folder bundle with a debug console window
REM      build.bat clean        remove build artefacts and the virtual env
REM
REM  Requirements: Python 3.10+ 64-bit on PATH ("python --version").
REM                Internet access on the first run (pip + FFmpeg download).
REM
REM  Pipeline:
REM      venv -> deps -> fetch bin\ffmpeg.exe -> unit tests -> PyInstaller
REM      -> verify bundled FFmpeg -> run frozen "AudioMaskPro.exe --selftest"
REM ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "ONEFILE="
set "CONSOLE="
if /I "%~1"=="onefile" set "ONEFILE=1"
if /I "%~1"=="console" set "CONSOLE=1"
if /I "%~1"=="clean" goto :clean

echo.
echo === AudioMask Pro build ===
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python was not found on PATH. Install Python 3.10+ ^(64-bit^) from python.org
    echo         and tick "Add python.exe to PATH" in the installer.
    exit /b 1
)

python -c "import sys,struct; sys.exit(0 if (sys.version_info>=(3,10) and struct.calcsize('P')*8==64) else 1)"
if errorlevel 1 (
    echo [ERROR] A 64-bit Python 3.10 or newer is required.
    python --version
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/8] Creating virtual environment .venv ...
    python -m venv .venv || (echo [ERROR] venv creation failed & exit /b 1)
) else (
    echo [1/8] Re-using existing .venv
)

call ".venv\Scripts\activate.bat" || (echo [ERROR] could not activate .venv & exit /b 1)

echo [2/8] Upgrading pip ...
python -m pip install --upgrade pip --quiet

echo [3/8] Installing dependencies ...
pip install -r requirements.txt --quiet || (echo [ERROR] dependency installation failed & exit /b 1)

echo [4/8] Bundled FFmpeg ...
if exist "bin\ffmpeg.exe" (
    echo        bin\ffmpeg.exe already present - skipping download
) else (
    echo        downloading static FFmpeg ^(BtbN win64 build, ~100 MB^) ...
    python tools\fetch_ffmpeg.py --platform win64
    if errorlevel 1 (
        echo [ERROR] Could not fetch FFmpeg. Check your internet connection or copy a
        echo         static ffmpeg.exe into bin\ manually, then re-run build.bat.
        exit /b 1
    )
)
python tools\fetch_ffmpeg.py --check >nul 2>nul
if errorlevel 1 (
    echo [ERROR] bin\ffmpeg.exe is still missing after fetch - aborting.
    exit /b 1
)
"bin\ffmpeg.exe" -version 2>nul | findstr /B /C:"ffmpeg version" >nul
if errorlevel 1 (
    echo [ERROR] bin\ffmpeg.exe does not run ^("ffmpeg -version" failed^).
    echo         Delete bin\ffmpeg.exe and re-run build.bat to download it again.
    exit /b 1
)

echo [5/8] Running unit tests ...
python -m unittest discover -s tests
if errorlevel 1 (
    echo [ERROR] Tests failed - aborting build.
    exit /b 1
)

echo [6/8] Running PyInstaller ...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
pyinstaller --noconfirm --clean build.spec
if errorlevel 1 (
    echo.
    echo [ERROR] BUILD FAILED - see output above.
    exit /b 1
)

echo [7/8] Verifying artefacts ...
if defined ONEFILE (
    set "APP_EXE=dist\AudioMaskPro.exe"
    REM one-file: ffmpeg.exe lives inside the archive and is unpacked to
    REM %TEMP%\_MEIxxxx\bin\ at run time - verified by the selftest below.
) else (
    set "APP_EXE=dist\AudioMaskPro\AudioMaskPro.exe"
    if not exist "dist\AudioMaskPro\_internal\bin\ffmpeg.exe" (
        echo [ERROR] dist\AudioMaskPro\_internal\bin\ffmpeg.exe is missing -
        echo         build.spec did not bundle FFmpeg. Check the spec output above.
        exit /b 1
    )
    echo        bundled FFmpeg: dist\AudioMaskPro\_internal\bin\ffmpeg.exe  OK
    if not exist "dist\AudioMaskPro\_internal\_soundfile_data" (
        echo [WARN]  _internal\_soundfile_data missing - libsndfile may not be bundled.
    )
)
if not exist "%APP_EXE%" (
    echo [ERROR] %APP_EXE% was not produced.
    exit /b 1
)

echo [8/8] Frozen self-test ^(DSP pipeline + bundled FFmpeg M4A round-trip^) ...
REM Hide any system FFmpeg so the selftest proves the *bundled* copy works.
setlocal
set "PATH=%SystemRoot%\System32;%SystemRoot%"
set "AUDIOMASK_FFMPEG="
"%APP_EXE%" --selftest
set "SELFTEST_RC=%ERRORLEVEL%"
endlocal & set "SELFTEST_RC=%SELFTEST_RC%"
if not "%SELFTEST_RC%"=="0" (
    echo.
    echo [ERROR] Frozen self-test FAILED ^(exit %SELFTEST_RC%^).
    echo         Re-run with  build.bat console  to see the traceback, then check
    echo         the "Windows first-run checklist" in handoff.md / README.md.
    exit /b 1
)

echo.
if defined ONEFILE (
    echo Build OK:  dist\AudioMaskPro.exe
) else (
    echo Build OK:  dist\AudioMaskPro\AudioMaskPro.exe
    echo            ^(ship the whole dist\AudioMaskPro folder^)
)
echo            FFmpeg is bundled - end users do NOT need to install it.
echo.
exit /b 0

:clean
echo Removing build\, dist\, __pycache__ and .venv ...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist .venv rmdir /s /q .venv
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
echo Done.  ^(bin\ffmpeg.exe was kept - delete it manually to force a re-download^)
exit /b 0
