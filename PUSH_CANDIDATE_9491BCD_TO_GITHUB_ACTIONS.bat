@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ========================================================================================
echo   رفع فرع الإصدار المرشح (Commit 9491bcd0d610c51ce76b599591db5c9f0b84cd44) إلى GitHub
echo   وتشغيل سير عمل البناء والاختبار على Windows x64 دون تعديل الفرع الرئيسي main
echo ========================================================================================

set "WORK_REPO=%TEMP%\mersad_candidate_push_repo"
if exist "%WORK_REPO%" rmdir /s /q "%WORK_REPO%"

git clone "reports_and_logs\mersad_preview_0_1_verifiable_history.bundle" "%WORK_REPO%"
if errorlevel 1 (
    echo [ERROR] تعذّر استنساخ حزمة Git المرفقة!
    exit /b 1
)

pushd "%WORK_REPO%"
git checkout preview/mersad-ai-lab-0.1-20261105
if errorlevel 1 (
    echo [ERROR] تعذّر التبديل إلى الفرع المرشح preview/mersad-ai-lab-0.1-20261105!
    popd
    exit /b 1
)

git remote set-url origin https://github.com/alinon9/MERSAD-AI-.git
echo [INFO] جارٍ دفع الفرع المرشح preview/mersad-ai-lab-0.1-20261105 إلى GitHub (دون لمس main ودون force-push)...
git push -u origin preview/mersad-ai-lab-0.1-20261105
if errorlevel 1 (
    echo [ERROR] تعذّر رفع الفرع إلى GitHub. تأكد من تسجيل الدخول في Git أو gh auth login.
    popd
    exit /b 1
)

where gh >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] تشغيل سير العمل release-mersad-preview-0.1-windows.yml عبر GitHub CLI...
    gh workflow run release-mersad-preview-0.1-windows.yml --ref preview/mersad-ai-lab-0.1-20261105
    if errorlevel 1 (
        echo [ERROR] تعذّر تشغيل سير العمل عبر gh workflow run!
        popd
        exit /b 1
    )
)
popd
echo [OK] تم رفع الفرع المرشح بنجاح دون المساس بفرع main!
pause
exit /b 0
