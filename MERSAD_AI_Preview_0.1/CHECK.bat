@echo off
chcp 65001 >nul
cd /d "%~dp0"
call setup.bat || exit /b 1
venv\Scripts\python.exe selftest.py || (pause & exit /b 1)
venv\Scripts\python.exe check_install.py --camera || (pause & exit /b 1)
pause
