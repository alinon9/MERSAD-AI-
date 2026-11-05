@echo off
chcp 65001 >nul
cd /d "%~dp0"
call setup.bat || exit /b 1
venv\Scripts\python.exe check_install.py --strict || (echo. & echo Fix the FAIL/MISSING lines above, then run again. & pause & exit /b 1)
venv\Scripts\python.exe mersad_live.py %*
pause
