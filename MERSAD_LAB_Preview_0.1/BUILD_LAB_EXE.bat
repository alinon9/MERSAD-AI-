@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
echo ============================================================================
echo   MERSAD LAB 1.0 (PREVIEW 0.1) — Windows x64 EXE & Portable Builder
echo ============================================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creating isolated Python virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create Python virtual environment. Ensure Python 3.10/3.11 x64 is installed.
        exit /b 1
    )
)

set "PY=.venv\Scripts\python.exe"
set "PIP=.venv\Scripts\pip.exe"

echo [2/5] Installing pinned dependencies (constraints-win-x64.txt)...
"%PIP%" install --upgrade pip
"%PIP%" install -r requirements.txt -c constraints-win-x64.txt pyinstaller==6.10.0
if errorlevel 1 exit /b 1

echo [3/5] Running 20-check functional and security test suite...
"%PY%" -u test_lab.py
if errorlevel 1 (
    echo [ERROR] MERSAD LAB tests failed! Aborting EXE packaging.
    exit /b 1
)

echo [4/5] Building dist\MERSAD_LAB\MERSAD_LAB.exe via PyInstaller...
.venv\Scripts\pyinstaller.exe --noconfirm --clean mersad_lab.spec
if not exist "dist\MERSAD_LAB\MERSAD_LAB.exe" (
    echo [ERROR] MERSAD_LAB.exe was not generated!
    exit /b 1
)

echo [5/5] Verifying MERSAD_LAB.exe --self-check...
"dist\MERSAD_LAB\MERSAD_LAB.exe" --port 0 --self-check
if errorlevel 1 (
    echo [ERROR] MERSAD_LAB.exe self-check failed!
    exit /b 1
)

echo ============================================================================
echo   BUILD SUCCESSFUL: dist\MERSAD_LAB\MERSAD_LAB.exe
echo ============================================================================
exit /b 0
