@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "ALLOWED_DEPLOY_BRANCH=fix/preview-0.1-postbuild-42273598736"
set "TARGET_BRANCH=%ALLOWED_DEPLOY_BRANCH%"

if defined MERSAD_DEPLOY_BRANCH (
    if not "!MERSAD_DEPLOY_BRANCH!"=="!ALLOWED_DEPLOY_BRANCH!" (
        echo [ERROR] BRANCH_NOT_IN_ALLOWLIST: MERSAD_DEPLOY_BRANCH="!MERSAD_DEPLOY_BRANCH!" is not in ALLOWED_DEPLOY_BRANCHES ^("!ALLOWED_DEPLOY_BRANCH!"^).
        exit /b 3
    )
)
if defined MERSAD_BUILD_BRANCH (
    if not "!MERSAD_BUILD_BRANCH!"=="!ALLOWED_DEPLOY_BRANCH!" (
        echo [ERROR] BRANCH_NOT_IN_ALLOWLIST: MERSAD_BUILD_BRANCH="!MERSAD_BUILD_BRANCH!" is not in ALLOWED_DEPLOY_BRANCHES ^("!ALLOWED_DEPLOY_BRANCH!"^).
        exit /b 3
    )
)
if not "%~1"=="" (
    if not "%~1"=="%ALLOWED_DEPLOY_BRANCH%" (
        echo [ERROR] BRANCH_NOT_IN_ALLOWLIST: CLI branch argument "%~1" is not in ALLOWED_DEPLOY_BRANCHES ^("%ALLOWED_DEPLOY_BRANCH%"^).
        exit /b 3
    )
    set "TARGET_BRANCH=%~1"
)

echo ========================================================================================
echo   MERSAD AI ^& MERSAD LAB — Preview 0.1
echo   واجهة التشغيل الموحدة للنشر والتحقق عبر المتحكم المركزي ^(tools\deploy_and_run_github_actions.py^)
echo   الفرع المسموح حصرياً ^(Allowlisted Branch^): %TARGET_BRANCH%
echo   ملاحظة أمنية: لا ينفذ هذا الملف أي git push مباشر أو دفع للأوسمة ^(Tags^) أو إخفاء للأخطاء؛
echo   يتم فرض قائمة الفروع المسموحة ^(Allowlist^) وتفويض جميع فحوصات Preflight للمتحكم المركزي.
echo ========================================================================================

set "PY_CMD="
where python >nul 2>nul
if !ERRORLEVEL! EQU 0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        set "PY_CMD=py -3"
    )
)

if "!PY_CMD!"=="" (
    echo [ERROR] تعذّر العثور على مفسر Python ^(python أو py -3^) في مسار النظام PATH!
    exit /b 2
)

!PY_CMD! -u "%~dp0tools\deploy_and_run_github_actions.py" --live --branch "%TARGET_BRANCH%"
set "DEPLOY_EXIT_CODE=!ERRORLEVEL!"
if !DEPLOY_EXIT_CODE! NEQ 0 (
    echo [ERROR] توقف المتحكم المركزي للنشر برمز خروج غير صفري: !DEPLOY_EXIT_CODE!
    exit /b !DEPLOY_EXIT_CODE!
)

echo [OK] اكتمل تنفيذ المتحكم المركزي للنشر والتحقق بنجاح ^(Exit Code: 0^).
exit /b 0
