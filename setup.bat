@echo off
REM MERSAD AI - Reproducible Environment Setup & Verification Script (Target: Python 3.11 64-bit on Windows x64)
REM Verifies existing venv/.ready against dependency hashes, Python version/arch, installed packages, and AI models.
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    if exist "venv\.ready" (
        venv\Scripts\python.exe check_install.py --verify-ready >nul 2>nul && exit /b 0
        echo [SETUP] Environment or models changed/incomplete - re-validating and updating in place...
    )
)

REM Remove any stale readiness marker before starting installation steps so partial failures never appear ready
if exist "venv\.ready" del /f /q "venv\.ready" >nul 2>nul

REM Resolve compatible 64-bit Python 3.10-3.12 (preferring Python 3.11 64-bit via py launcher so Python 3.13/3.14 in PATH does not break C-extension wheel installation)
set "PYTHON_CMD="
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    for %%V in (3.11-64 3.11 3.12-64 3.12 3.10-64 3.10) do (
        if not defined PYTHON_CMD (
            py -%%V -c "import struct,sys; raise SystemExit(0 if (struct.calcsize('P')*8==64 and sys.version_info[:2] in ((3,10),(3,11),(3,12))) else 1)" >nul 2>nul
            if !ERRORLEVEL! EQU 0 set "PYTHON_CMD=py -%%V"
        )
    )
)
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        python -c "import struct,sys; raise SystemExit(0 if (struct.calcsize('P')*8==64 and sys.version_info[:2] in ((3,10),(3,11),(3,12))) else 1)" >nul 2>nul
        if !ERRORLEVEL! EQU 0 set "PYTHON_CMD=python"
    )
)
if not defined PYTHON_CMD (
    echo [ERROR] Compatible 64-bit Python 3.10-3.12 not found ^(recommended: Python 3.11 64-bit^).
    echo         Note: Python 3.13 / 3.14 are not supported by pinned PyTorch 2.5.1 / OpenCV 4.11 wheels.
    echo         Please install Python 3.11 64-bit from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -c "import struct,sys; raise SystemExit(0 if (struct.calcsize('P')*8==64 and sys.version_info[:2] in ((3,10),(3,11),(3,12))) else 1)" >nul 2>nul
    if !ERRORLEVEL! NEQ 0 (
        echo [SETUP] Existing venv uses an incompatible Python version/architecture - recreating venv with %PYTHON_CMD%...
        rmdir /s /q "venv" >nul 2>nul
    )
)

if not exist "venv\Scripts\python.exe" (
    echo [1/6] Creating Python virtual environment ^(venv^) using %PYTHON_CMD%...
    %PYTHON_CMD% -m venv venv || (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
) else (
    echo [1/6] Using existing virtual environment ^(venv^)...
)

echo [2/6] Upgrading pip and verifying 64-bit Python...
venv\Scripts\python.exe -c "import struct,sys; assert struct.calcsize('P')*8==64 and sys.version_info[:2] in ((3,10),(3,11),(3,12)), '64-bit Python 3.10-3.12 required'; print('Python', sys.version)" || (
    echo [ERROR] 64-bit Python 3.10-3.12 is required ^(recommended: Python 3.11 64-bit^).
    exit /b 1
)
venv\Scripts\python.exe -m pip install --upgrade pip || exit /b 1

REM Default to CPU PyTorch wheels for universal Windows x64 compatibility; if a CUDA wheel is installed, mersad_live.py (--device auto / --gpu) enables GPU automatically (GAP-16)
echo [3/6] Installing pinned PyTorch CPU wheels ^(torch==2.5.1, torchvision==0.20.1^)...
venv\Scripts\pip.exe install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu || exit /b 1

echo [4/6] Installing pinned runtime libraries from requirements.txt...
venv\Scripts\pip.exe install -r requirements.txt -c constraints-win-x64.txt || exit /b 1

echo [5/6] Enforcing full OpenCV GUI support ^(removing headless wheel pulled by easyocr^)...
venv\Scripts\pip.exe uninstall -y opencv-python-headless >nul 2>nul
venv\Scripts\pip.exe install --force-reinstall --no-deps opencv-python==4.11.0.86 || exit /b 1
venv\Scripts\python.exe check_install.py --verify-pip-deps || (
    echo [ERROR] Dependency conflict detected by check_install.py --verify-pip-deps.
    exit /b 1
)

echo [6/6] Downloading and verifying AI models + writing verified venv\.ready stamp...
venv\Scripts\python.exe prefetch.py || exit /b 1
venv\Scripts\python.exe check_install.py --write-ready || (
    echo [ERROR] Final environment and model verification failed.
    exit /b 1
)
exit /b 0
