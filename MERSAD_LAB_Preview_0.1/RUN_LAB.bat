@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================================
echo   تشغيل مختبر مرصاد — MERSAD LAB 1.0 (PREVIEW 0.1)
echo   العنوان المحلي: http://127.0.0.1:8090
echo ============================================================================
if exist "MERSAD_LAB.exe" (
    start "" http://127.0.0.1:8090
    "MERSAD_LAB.exe" --host 127.0.0.1 --port 8090
    exit /b %ERRORLEVEL%
)
if exist "dist\MERSAD_LAB\MERSAD_LAB.exe" (
    start "" http://127.0.0.1:8090
    "dist\MERSAD_LAB\MERSAD_LAB.exe" --host 127.0.0.1 --port 8090
    exit /b %ERRORLEVEL%
)
python lab_server.py --host 127.0.0.1 --port 8090
