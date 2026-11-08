@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================================
echo   بناء الحزمة الكاملة لنظام Windows 10/11 x64 — MERSAD AI — PREVIEW 0.1
echo   (يفوض التنفيذ إلى BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1 الصارم)
echo ============================================================================

powershell -ExecutionPolicy Bypass -File "%~dp0BUILD_AND_VERIFY_FINAL_WINDOWS_RELEASE.ps1"
if errorlevel 1 (
    echo [ERROR] فشلت إحدى مراحل البناء أو التحقق الصارم!
    exit /b 1
)

echo [SUCCESS] اكتمل بناء وفحص MERSAD_AI.exe و MERSAD_LAB.exe و MERSAD_LAB_Setup_x64.exe بنجاح!
exit /b 0
