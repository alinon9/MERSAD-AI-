@echo off
chcp 65001 >nul
cd /d "%~dp0"
call setup.bat || exit /b 1
venv\Scripts\python.exe check_install.py --strict || (echo. & echo Fix the FAIL/MISSING lines above, then run again. & pause & exit /b 1)
echo.
echo [LAN MODE] Starting MERSAD AI on 0.0.0.0 with HTTPS only.
if not defined MERSAD_TLS_CERT (
  echo [SECURITY ERROR] Set MERSAD_TLS_CERT to a valid TLS certificate file.
  pause
  exit /b 2
)
if not defined MERSAD_TLS_KEY (
  echo [SECURITY ERROR] Set MERSAD_TLS_KEY to the matching private key file.
  pause
  exit /b 2
)
if not exist "%MERSAD_TLS_CERT%" (
  echo [SECURITY ERROR] TLS certificate file not found: %MERSAD_TLS_CERT%
  pause
  exit /b 2
)
if not exist "%MERSAD_TLS_KEY%" (
  echo [SECURITY ERROR] TLS private key file not found: %MERSAD_TLS_KEY%
  pause
  exit /b 2
)
if not defined MERSAD_ALLOWED_HOSTS (
  echo [SECURITY ERROR] Set MERSAD_ALLOWED_HOSTS to the exact LAN IP/hostname used by clients.
  pause
  exit /b 2
)
echo [SECURITY] HTTP LAN mode is disabled. TLS and explicit Host allowlisting are required.
echo.
venv\Scripts\python.exe mersad_live.py --host 0.0.0.0 %*
pause
