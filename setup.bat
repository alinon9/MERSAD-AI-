@echo off
REM MERSAD AI - Reproducible Environment Setup & Verification Script (Target: Python 3.11 64-bit on Windows x64)
REM Verifies existing venv/.ready against dependency hashes, Python version/arch, installed packages, and AI models.
cd /d "%~dp0"

where python >nul 2>nul || (
    echo [ERROR] Python not found in PATH. Install Python 3.11 64-bit from python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

if exist "venv\Scripts\python.exe" (
    if exist "venv\.ready" (
        venv\Scripts\python.exe check_install.py --verify-ready >nul 2>nul && exit /b 0
        echo [SETUP] Environment or models changed/incomplete - re-validating and updating in place...
    )
)

REM Remove any stale readiness marker before starting installation steps so partial failures never appear ready
if exist "venv\.ready" del /f /q "venv\.ready" >nul 2>nul

if not exist "venv\Scripts\python.exe" (
    echo [1/6] Creating Python virtual environment ^(venv^)...
    python -m venv venv || (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
) else (
    echo [1/6] Using existing virtual environment ^(venv^)...
)

echo [2/6] Upgrading pip and verifying 64-bit Python...
venv\Scripts\python.exe -c "import struct,sys; assert struct.calcsize('P')*8==64, '64-bit Python required'; print('Python', sys.version)" || (
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
