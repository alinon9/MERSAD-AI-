@echo off
setlocal EnableExtensions
chcp 65001 >nul
title MERSAD AI - Apply Cumulative Update

echo.
echo ============================================
echo   MERSAD AI - Cumulative Update Installer
echo   Phases 1 + 2 + 3
echo ============================================
echo.
echo Close MERSAD AI completely before continuing.
echo This update preserves models, database, evidence,
echo settings, logs and all other user data.
echo.

set /p "TARGET=Enter the full path to your existing MERSAD_AI folder: "
if not defined TARGET (
  echo [ERROR] No destination was entered.
  pause
  exit /b 1
)
if not exist "%TARGET%\MERSAD_AI.exe" (
  echo [ERROR] MERSAD_AI.exe was not found in:
  echo "%TARGET%"
  pause
  exit /b 1
)
for %%F in ("MERSAD_AI\MERSAD_AI.exe" "MERSAD_AI\MERSAD_Desktop.exe" "MERSAD_AI\dashboard.html" "MERSAD_AI\camera-connect.js") do (
  if not exist "%%~F" (
    echo [ERROR] Patch file missing: %%~F
    pause
    exit /b 1
  )
)
tasklist /FI "IMAGENAME eq MERSAD_AI.exe" 2>nul | find /I "MERSAD_AI.exe" >nul
if not errorlevel 1 (
  echo [ERROR] MERSAD_AI.exe is still running. Close the app and retry.
  pause
  exit /b 1
)
tasklist /FI "IMAGENAME eq MERSAD_Desktop.exe" 2>nul | find /I "MERSAD_Desktop.exe" >nul
if not errorlevel 1 (
  echo [ERROR] MERSAD_Desktop.exe is still running. Close the app and retry.
  pause
  exit /b 1
)

for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%T"
set "BACKUP=%TARGET%\backup_before_cumulative_update_%STAMP%"
mkdir "%BACKUP%" || (
  echo [ERROR] Could not create backup folder.
  pause
  exit /b 1
)

for %%F in (MERSAD_AI.exe MERSAD_Desktop.exe dashboard.html camera-connect.js) do (
  if exist "%TARGET%\%%F" copy /Y "%TARGET%\%%F" "%BACKUP%\%%F" >nul
)
if errorlevel 1 (
  echo [ERROR] Backup failed. No files were replaced.
  pause
  exit /b 1
)

for %%F in (MERSAD_AI.exe MERSAD_Desktop.exe dashboard.html camera-connect.js) do (
  copy /Y "MERSAD_AI\%%F" "%TARGET%\%%F" >nul || (
    echo [ERROR] Failed updating %%F.
    echo Your backup is here: "%BACKUP%"
    pause
    exit /b 1
  )
)

echo.
echo [SUCCESS] Cumulative update installed.
echo Backup: "%BACKUP%"
echo Updated: MERSAD_AI.exe, MERSAD_Desktop.exe, dashboard.html, camera-connect.js
echo Preserved: models, database, evidence, settings and logs.
echo.
pause
