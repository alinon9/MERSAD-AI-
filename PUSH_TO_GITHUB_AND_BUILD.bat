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
    if /I not "%~1"=="--local-verify" (
        if not "%~1"=="%ALLOWED_DEPLOY_BRANCH%" (
            echo [ERROR] BRANCH_NOT_IN_ALLOWLIST: CLI branch argument "%~1" is not in ALLOWED_DEPLOY_BRANCHES ^("%ALLOWED_DEPLOY_BRANCH%"^).
            exit /b 3
        )
        set "TARGET_BRANCH=%~1"
    )
)

echo ========================================================================================
echo   MERSAD AI V7.1 ^& MERSAD LAB 1.0 — Preview 0.1
echo   Remediated Cloud Deployment Wrapper ^(Closes BUG-46 ^& BUG-49^)
echo   Target Repository  : https://github.com/alinon9/MERSAD-AI-
echo   Allowlisted Branch : %TARGET_BRANCH%
echo   Central Controller : tools\deploy_and_run_github_actions.py
echo   Security Guarantee : Direct git push, workflow_dispatch triggers, default-branch
echo                        modifications, and silenced errors are strictly disabled.
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
    echo [ERROR] Compatible Python interpreter ^(python or py -3^) was not found in PATH!
    exit /b 2
)

if /I "%~1"=="--local-verify" (
    echo [LOCAL-VERIFY] Running offline integrity and build-configuration verification...
    !PY_CMD! -u "%~dp0verify_integrity.py"
    set "VERIFY_RC=!ERRORLEVEL!"
    if !VERIFY_RC! NEQ 0 (
        echo [ERROR] verify_integrity.py failed with exit code !VERIFY_RC!.
        exit /b !VERIFY_RC!
    )
    !PY_CMD! -u "%~dp0check_install.py"
    set "CHK_RC=!ERRORLEVEL!"
    if !CHK_RC! NEQ 0 (
        echo [ERROR] check_install.py failed with exit code !CHK_RC!.
        exit /b !CHK_RC!
    )
    echo [OK] Local integrity and build configuration verified. To build locally on Windows, run BUILD_EXE.bat.
    exit /b 0
)

if exist "%~dp0..\tools\deploy_and_run_github_actions.py" (
    !PY_CMD! -u "%~dp0..\tools\deploy_and_run_github_actions.py" --live --branch "%TARGET_BRANCH%"
    set "DEPLOY_EXIT_CODE=!ERRORLEVEL!"
) else if exist "%~dp0tools\deploy_and_run_github_actions.py" (
    !PY_CMD! -u "%~dp0tools\deploy_and_run_github_actions.py" --live --branch "%TARGET_BRANCH%"
    set "DEPLOY_EXIT_CODE=!ERRORLEVEL!"
) else (
    echo [ERROR] CENTRAL_CONTROLLER_NOT_FOUND: tools\deploy_and_run_github_actions.py is missing.
    echo         Standalone deployment from an isolated MERSAD_AI_Preview_0.1 subdirectory is disabled ^(BUG-46^).
    echo         Run deployment from the unified repository root or run BUILD_EXE.bat for local offline builds.
    exit /b 4
)

if !DEPLOY_EXIT_CODE! NEQ 0 (
    echo [ERROR] Central deployment controller exited with non-zero code: !DEPLOY_EXIT_CODE!
    exit /b !DEPLOY_EXIT_CODE!
)

echo [OK] Central deployment and verification controller completed successfully ^(Exit Code: 0^).
exit /b 0
