@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "MERSAD_AI.exe" (
    MERSAD_AI.exe --verify || (pause & exit /b 1)
    MERSAD_AI.exe --verify-models || (pause & exit /b 1)
    MERSAD_AI.exe --readiness-report || (pause & exit /b 1)
    pause
    exit /b 0
)
call setup.bat || exit /b 1
venv\Scripts\python.exe mersad_live.py --verify || (pause & exit /b 1)
venv\Scripts\python.exe mersad_live.py --verify-models || (pause & exit /b 1)
venv\Scripts\python.exe mersad_live.py --readiness-report || (pause & exit /b 1)
pause
