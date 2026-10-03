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
    echo [1/5] Creating virtual environment .venv ...
    python -m venv .venv || (echo [ERROR] venv creation failed & exit /b 1)
) else (
    echo [1/5] Re-using existing .venv
)

call ".venv\Scripts\activate.bat" || (echo [ERROR] could not activate .venv & exit /b 1)

echo [2/5] Upgrading pip ...
python -m pip install --upgrade pip --quiet

echo [3/5] Installing dependencies ...
pip install -r requirements.txt --quiet || (echo [ERROR] dependency installation failed & exit /b 1)

echo [4/5] Running unit tests ...
python -m unittest discover -s tests
if errorlevel 1 (
    echo [ERROR] Tests failed - aborting build.
    exit /b 1
)

echo [5/5] Running PyInstaller ...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
pyinstaller --noconfirm --clean build.spec
if errorlevel 1 (
    echo.
    echo [ERROR] BUILD FAILED - see output above.
    exit /b 1
)

echo.
if defined ONEFILE (
    echo Build OK:  dist\AudioMaskPro.exe
) else (
    echo Build OK:  dist\AudioMaskPro\AudioMaskPro.exe
    echo            ^(ship the whole dist\AudioMaskPro folder^)
)
echo.
exit /b 0

:clean
echo Removing build\, dist\, __pycache__ and .venv ...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist .venv rmdir /s /q .venv
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
echo Done.
exit /b 0
