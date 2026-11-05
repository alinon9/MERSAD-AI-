@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1"
if errorlevel 1 (
    echo.
    echo [FAILED] فشلت إحدى مراحل البناء أو التحقق على Windows x64! راجع الرسائل أعلاه.
    pause
    exit /b 1
)
echo.
echo [SUCCESS] اكتملت جميع المراحل الخمس بنجاح في المجلد windows_binaries_staging\
pause
exit /b 0
