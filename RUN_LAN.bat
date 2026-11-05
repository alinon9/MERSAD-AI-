@echo off
chcp 65001 >nul
cd /d "%~dp0"
call setup.bat || exit /b 1
echo.
echo [LAN MODE] Starting MERSAD AI on 0.0.0.0 so phones/tablets on the same Wi-Fi can connect.
echo [SECURITY WARNING] The access token travels over plain HTTP on your local Wi-Fi. Use only on a trusted network.
echo.
venv\Scripts\python mersad_live.py --host 0.0.0.0 %*
pause
