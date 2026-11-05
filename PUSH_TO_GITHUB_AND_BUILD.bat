@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================================
echo   MERSAD AI V7.1 Stage 15 - Automated GitHub Actions Windows x64 EXE Builder
echo   Target Repository : https://github.com/alinon9/MERSAD-AI-
echo   Workflow File     : .github/workflows/windows-build.yml
echo   Expected Artifact : MERSAD_AI_Windows_x64_Distribution
echo ============================================================================
echo.

REM Configure target repository and workflow parameters (overridable via environment variables)
set "SOURCE_DIR=%~dp0"
if not defined MERSAD_GITHUB_REPO set "MERSAD_GITHUB_REPO=alinon9/MERSAD-AI-"
if not defined MERSAD_REPO_URL set "MERSAD_REPO_URL=https://github.com/%MERSAD_GITHUB_REPO%.git"
if not defined MERSAD_BUILD_BRANCH set "MERSAD_BUILD_BRANCH=release/v7.1-stage15-win-x64"
if not defined MERSAD_WORKFLOW_FILE set "MERSAD_WORKFLOW_FILE=windows-build.yml"
if not defined MERSAD_ARTIFACT_NAME set "MERSAD_ARTIFACT_NAME=MERSAD_AI_Windows_x64_Distribution"
if not defined MERSAD_WORKTREE_DIR set "MERSAD_WORKTREE_DIR=%~dp0.git_build_worktree"
if not defined MERSAD_ARTIFACT_DIR set "MERSAD_ARTIFACT_DIR=%~dp0build_artifacts"
if not defined MERSAD_FINAL_DIR set "MERSAD_FINAL_DIR=%~dp0MERSAD_AI_RELEASE"

REM ============================================================================
REM [1/12] Verify Git and GitHub CLI (gh) are installed
REM ============================================================================
echo [1/12] Checking Git and GitHub CLI ^(gh^) installation...
where git >nul 2>nul
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] Git is not installed or not in PATH.
    echo         Download and install Git for Windows from: https://git-scm.com/download/win
    pause
    exit /b 1
)
where gh >nul 2>nul
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] GitHub CLI ^(gh^) is not installed or not in PATH.
    echo         Install it via: winget install --id GitHub.cli
    echo         Or download from: https://cli.github.com/
    pause
    exit /b 1
)
for /f "delims=" %%V in ('git --version') do echo        Found: %%V
for /f "delims=" %%V in ('gh --version') do (
    echo        Found: %%V
    goto :done_gh_ver
)
:done_gh_ver

REM ============================================================================
REM [2/12] Verify GitHub CLI authentication and permissions (no hardcoded secrets)
REM ============================================================================
echo [2/12] Verifying GitHub CLI authentication ^& permissions...
gh auth status >nul 2>nul
if !ERRORLEVEL! NEQ 0 (
    echo [AUTH] You are not logged in to GitHub CLI. Launching secure interactive login...
    echo        ^(Please select GitHub.com -^> HTTPS -^> Login with a web browser^)
    gh auth login --hostname github.com --git-protocol https --web
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] GitHub CLI authentication failed or was cancelled.
        pause
        exit /b 1
    )
)
gh auth setup-git >nul 2>nul
echo        [OK] Authenticated safely via GitHub CLI credential helper.

REM ============================================================================
REM [3/12] Connect to target GitHub repository & prepare cloned worktree (supports first & repeated runs on existing history)
REM ============================================================================
echo [3/12] Connecting to repository %MERSAD_GITHUB_REPO% and preparing Git worktree...
gh repo view "%MERSAD_GITHUB_REPO%" >nul 2>nul
if !ERRORLEVEL! NEQ 0 (
    echo [REPO] Repository %MERSAD_GITHUB_REPO% was not found or is not accessible yet.
    echo        Attempting to create repository %MERSAD_GITHUB_REPO% on your GitHub account...
    gh repo create "%MERSAD_GITHUB_REPO%" --private --description "MERSAD AI V7.1 Stage 15 Windows x64 Build" >nul 2>nul
    gh repo view "%MERSAD_GITHUB_REPO%" >nul 2>nul
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Could not access or create %MERSAD_GITHUB_REPO%.
        echo         Ensure your GitHub account has access to https://github.com/%MERSAD_GITHUB_REPO%
        echo         or run: set MERSAD_GITHUB_REPO=YOUR_USERNAME/MERSAD-AI- before running this script.
        pause
        exit /b 1
    )
)

REM Prepare synchronized Git worktree inside %MERSAD_WORKTREE_DIR% by cloning or fetching remote history
REM (Prevents "refusing to merge unrelated histories" when extracted from a fresh ZIP onto an existing repo)
if exist "%MERSAD_WORKTREE_DIR%\.git" (
    echo        Using existing synchronized Git worktree at %MERSAD_WORKTREE_DIR%...
    pushd "%MERSAD_WORKTREE_DIR%"
    git remote set-url origin "%MERSAD_REPO_URL%"
    if !ERRORLEVEL! NEQ 0 (
        popd
        echo [ERROR] Failed to configure remote origin in %MERSAD_WORKTREE_DIR%.
        pause
        exit /b 1
    )
    git fetch origin --prune
    if !ERRORLEVEL! NEQ 0 (
        popd
        echo [ERROR] Failed to fetch from %MERSAD_REPO_URL%. Check network connectivity and permissions.
        pause
        exit /b 1
    )
    popd
) else (
    if exist "%MERSAD_WORKTREE_DIR%" rmdir /s /q "%MERSAD_WORKTREE_DIR%" >nul 2>nul
    echo        Cloning remote repository %MERSAD_REPO_URL% into %MERSAD_WORKTREE_DIR%...
    git clone "%MERSAD_REPO_URL%" "%MERSAD_WORKTREE_DIR%"
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] git clone failed for %MERSAD_REPO_URL%.
        pause
        exit /b 1
    )
)

pushd "%MERSAD_WORKTREE_DIR%"
git config user.name >nul 2>nul || git config user.name "MERSAD AI Builder"
git config user.email >nul 2>nul || git config user.email "mersad-builder@users.noreply.github.com"

REM Detect remote default branch (if repository already has commits)
set "DEFAULT_BRANCH="
for /f "delims=" %%D in ('gh repo view "%MERSAD_GITHUB_REPO%" --json defaultBranchRef --jq ".defaultBranchRef.name" 2^>nul') do (
    if not "%%D"=="" if not "%%D"=="null" set "DEFAULT_BRANCH=%%D"
)
if not defined DEFAULT_BRANCH set "DEFAULT_BRANCH=main"

REM Switch to target build branch on top of existing remote history (avoiding unrelated histories)
git show-ref --verify --quiet "refs/remotes/origin/%MERSAD_BUILD_BRANCH%"
if !ERRORLEVEL! EQU 0 (
    echo        Checking out existing remote build branch origin/%MERSAD_BUILD_BRANCH%...
    git checkout -B "%MERSAD_BUILD_BRANCH%" "origin/%MERSAD_BUILD_BRANCH%"
    if !ERRORLEVEL! NEQ 0 (
        popd
        echo [ERROR] Failed to checkout branch %MERSAD_BUILD_BRANCH% from origin.
        pause
        exit /b 1
    )
    git merge --ff-only "origin/%MERSAD_BUILD_BRANCH%"
    if !ERRORLEVEL! NEQ 0 (
        popd
        echo [ERROR] Local worktree diverged from origin/%MERSAD_BUILD_BRANCH%. Aborting safely without force push.
        pause
        exit /b 1
    )
) else (
    git show-ref --verify --quiet "refs/remotes/origin/%DEFAULT_BRANCH%"
    if !ERRORLEVEL! EQU 0 (
        echo        Creating build branch %MERSAD_BUILD_BRANCH% from remote default branch origin/%DEFAULT_BRANCH%...
        git checkout -B "%MERSAD_BUILD_BRANCH%" "origin/%DEFAULT_BRANCH%"
        if !ERRORLEVEL! NEQ 0 (
            popd
            echo [ERROR] Failed to create branch %MERSAD_BUILD_BRANCH% from origin/%DEFAULT_BRANCH%.
            pause
            exit /b 1
        )
    ) else (
        echo        Remote repository is empty; initializing branch %MERSAD_BUILD_BRANCH%...
        git checkout -B "%MERSAD_BUILD_BRANCH%"
        if !ERRORLEVEL! NEQ 0 (
            popd
            echo [ERROR] Failed to initialize branch %MERSAD_BUILD_BRANCH%.
            pause
            exit /b 1
        )
    )
)

REM Check for any unresolved merge conflict markers before overlaying files
git diff --name-only --diff-filter=U | findstr /R "." >nul 2>nul
if !ERRORLEVEL! EQU 0 (
    popd
    echo [ERROR] Unresolved merge conflicts detected in %MERSAD_WORKTREE_DIR%. Stopping safely.
    pause
    exit /b 1
)
popd

REM ============================================================================
REM [4/12] Copy updated Stage 15 files into worktree without deleting existing repo files
REM ============================================================================
echo [4/12] Verifying and overlaying updated Stage 15 files into worktree ^(preserving existing repo files^)...
for %%R in ("mersad_live.py" "server.py" "registry.py" "insights.py" "analytics.py" "camera_history.py" "notify.py" "check_install.py" "prefetch.py" "selftest.py" "dashboard.html" "mersad_ai.spec" "requirements.txt" "constraints-win-x64.txt" "setup.bat" "BUILD_EXE.bat" "RUN.bat" "RUN_LAN.bat" "CHECK.bat" "VERIFY_AUDIT.bat" "PUSH_TO_GITHUB_AND_BUILD.bat" "BUILD_REPORT.md" "START_HERE_AR.md" ".github\workflows\windows-build.yml") do (
    if not exist "%SOURCE_DIR%%%~R" (
        echo [ERROR] Essential Stage 15 file %%~R is missing from %SOURCE_DIR%! Aborting.
        pause
        exit /b 1
    )
)

mkdir "%MERSAD_WORKTREE_DIR%\.github\workflows" >nul 2>nul
copy /Y "%SOURCE_DIR%.github\workflows\windows-build.yml" "%MERSAD_WORKTREE_DIR%\.github\workflows\windows-build.yml" >nul
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] Failed to copy .github\workflows\windows-build.yml into worktree.
    pause
    exit /b 1
)

for %%E in (py html spec txt bat md) do (
    for %%F in ("%SOURCE_DIR%*.%%E") do (
        copy /Y "%%~fF" "%MERSAD_WORKTREE_DIR%\%%~nxF" >nul
        if !ERRORLEVEL! NEQ 0 (
            echo [ERROR] Failed to copy %%~nxF into worktree.
            pause
            exit /b 1
        )
    )
)

if exist "%SOURCE_DIR%.gitignore" (
    copy /Y "%SOURCE_DIR%.gitignore" "%MERSAD_WORKTREE_DIR%\.gitignore" >nul
) else if not exist "%MERSAD_WORKTREE_DIR%\.gitignore" (
    (
        echo __pycache__/
        echo *.pyc
        echo venv/
        echo build/
        echo dist/
        echo .git_build_worktree/
        echo build_artifacts/
        echo MERSAD_AI_RELEASE/
        echo eval_uploads/
        echo evidence/
        echo evidence_archive/
        echo *.db
        echo *.db-wal
        echo *.db-shm
        echo *.ipclock
        echo *.log
        echo .mersad_hmac.key
        echo .mersad_secrets.json
        echo .tg_listener_*.lock
    ) > "%MERSAD_WORKTREE_DIR%\.gitignore"
)
echo        [OK] Stage 15 files overlaid cleanly without deleting any existing repository files.

REM ============================================================================
REM [5/12] Verify .github/workflows/windows-build.yml exists at repository root
REM ============================================================================
echo [5/12] Verifying .github\workflows\windows-build.yml in repository worktree...
if not exist "%MERSAD_WORKTREE_DIR%\.github\workflows\windows-build.yml" (
    echo [ERROR] Workflow file .github\workflows\windows-build.yml is missing in worktree!
    pause
    exit /b 1
)
findstr /C:"workflow_dispatch" "%MERSAD_WORKTREE_DIR%\.github\workflows\windows-build.yml" >nul 2>nul
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] .github\workflows\windows-build.yml does not contain workflow_dispatch trigger!
    pause
    exit /b 1
)
findstr /C:"windows-latest" "%MERSAD_WORKTREE_DIR%\.github\workflows\windows-build.yml" >nul 2>nul
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] .github\workflows\windows-build.yml does not target runs-on: windows-latest!
    pause
    exit /b 1
)
echo        [OK] .github\workflows\windows-build.yml verified.

REM ============================================================================
REM [6/12] Safely commit & push updates to build branch (and register workflow on default branch if needed, NEVER force-pushing)
REM ============================================================================
echo [6/12] Committing and safely pushing to branch %MERSAD_BUILD_BRANCH% ^(no force push^)...
pushd "%MERSAD_WORKTREE_DIR%"
git add .github/workflows/windows-build.yml *.py *.html *.spec *.txt *.bat *.md .gitignore >nul 2>nul

set "NEW_COMMIT_PUSHED=0"
git diff --cached --quiet
if !ERRORLEVEL! NEQ 0 (
    git commit -m "chore(stage15): update Windows x64 PyInstaller EXE build & CI workflow"
    if !ERRORLEVEL! NEQ 0 (
        popd
        echo [ERROR] Git commit failed on branch %MERSAD_BUILD_BRANCH%.
        pause
        exit /b 1
    )
    set "NEW_COMMIT_PUSHED=1"
) else (
    echo        [INFO] Working tree matches latest commit on %MERSAD_BUILD_BRANCH%.
)

for /f "delims=" %%H in ('git rev-parse HEAD') do set "LOCAL_HEAD_SHA=%%H"
echo        Target Commit SHA: !LOCAL_HEAD_SHA!

REM Check whether remote branch already points to LOCAL_HEAD_SHA
set "REMOTE_BRANCH_SHA="
for /f "tokens=1" %%R in ('git ls-remote origin "refs/heads/%MERSAD_BUILD_BRANCH%" 2^>nul') do set "REMOTE_BRANCH_SHA=%%R"
if /I not "!REMOTE_BRANCH_SHA!"=="!LOCAL_HEAD_SHA!" (
    git push -u origin "%MERSAD_BUILD_BRANCH%"
    if !ERRORLEVEL! NEQ 0 (
        popd
        echo [ERROR] Failed to push branch %MERSAD_BUILD_BRANCH% to %MERSAD_REPO_URL%.
        echo         Remote may have new commits or branch protection. Pull/merge first; force-push is strictly disabled.
        pause
        exit /b 1
    )
    set "NEW_COMMIT_PUSHED=1"
) else (
    echo        [INFO] Remote branch %MERSAD_BUILD_BRANCH% is already at commit !LOCAL_HEAD_SHA!.
)

REM Safely ensure .github/workflows/windows-build.yml is registered on the repository's default branch
REM so GitHub registers workflow_dispatch, WITHOUT overwriting default branch files or bypassing branch protection.
set "WORKFLOW_ON_DEFAULT=0"
git fetch origin "%DEFAULT_BRANCH%" >nul 2>nul
if !ERRORLEVEL! EQU 0 (
    git cat-file -e "origin/%DEFAULT_BRANCH%:.github/workflows/%MERSAD_WORKFLOW_FILE%" 2>nul
    if !ERRORLEVEL! EQU 0 (
        set "WORKFLOW_ON_DEFAULT=1"
        echo        [OK] Workflow %MERSAD_WORKFLOW_FILE% is already registered on default branch ^(%DEFAULT_BRANCH%^).
    ) else (
        echo        [INFO] Registering .github/workflows/%MERSAD_WORKFLOW_FILE% on default branch ^(%DEFAULT_BRANCH%^) via safe single-file commit...
        git checkout -B "_register_wf_%DEFAULT_BRANCH%" "origin/%DEFAULT_BRANCH%" >nul 2>nul
        if !ERRORLEVEL! EQU 0 (
            mkdir ".github\workflows" >nul 2>nul
            copy /Y "%SOURCE_DIR%.github\workflows\windows-build.yml" ".github\workflows\windows-build.yml" >nul
            git add ".github/workflows/windows-build.yml" >nul 2>nul
            git commit -m "ci: register windows-build.yml workflow on default branch for workflow_dispatch" >nul 2>nul
            git push origin "_register_wf_%DEFAULT_BRANCH%:refs/heads/%DEFAULT_BRANCH%" >nul 2>nul
            if !ERRORLEVEL! EQU 0 (
                set "WORKFLOW_ON_DEFAULT=1"
                echo        [OK] Registered %MERSAD_WORKFLOW_FILE% on default branch ^(%DEFAULT_BRANCH%^) without altering other files.
            ) else (
                echo        [INFO] Default branch ^(%DEFAULT_BRANCH%^) is protected; build will rely on push trigger on %MERSAD_BUILD_BRANCH%.
            )
            git checkout "%MERSAD_BUILD_BRANCH%" >nul 2>nul
            git branch -D "_register_wf_%DEFAULT_BRANCH%" >nul 2>nul
        )
    )
)
popd

REM ============================================================================
REM [7/12] Locate or trigger GitHub Actions run for exact commit !LOCAL_HEAD_SHA! (preventing duplicate runs & stale run selection)
REM ============================================================================
echo [7/12] Resolving GitHub Actions run for commit !LOCAL_HEAD_SHA! on branch %MERSAD_BUILD_BRANCH%...
set "RUN_ID="

REM If a push just occurred, wait briefly to see if the push trigger already started a run for LOCAL_HEAD_SHA
if "!NEW_COMMIT_PUSHED!"=="1" (
    echo        Checking for push-triggered workflow run matching commit !LOCAL_HEAD_SHA!...
    for /L %%P in (1,1,6) do (
        if not defined RUN_ID (
            for /f "delims=" %%I in ('gh run list --repo "%MERSAD_GITHUB_REPO%" --workflow "%MERSAD_WORKFLOW_FILE%" --branch "%MERSAD_BUILD_BRANCH%" --limit 10 --json databaseId^,headSha^,status^,conclusion --jq ".[] | select(.headSha == \"!LOCAL_HEAD_SHA!\" and (.status != \"completed\" or .conclusion == \"success\")) | .databaseId" 2^>nul') do (
                if not defined RUN_ID if not "%%I"=="" if not "%%I"=="null" set "RUN_ID=%%I"
            )
            if not defined RUN_ID timeout /t 3 /nobreak >nul
        )
    )
)

REM If no run was triggered by push (e.g. re-running on an already-pushed commit), trigger via workflow_dispatch
if defined RUN_ID (
    echo        [OK] Push-triggered run detected ^(Run ID: !RUN_ID!^) for commit !LOCAL_HEAD_SHA! — skipping duplicate workflow_dispatch.
) else (
    echo        Triggering manual workflow_dispatch run on branch %MERSAD_BUILD_BRANCH% for commit !LOCAL_HEAD_SHA!...
    gh workflow run "%MERSAD_WORKFLOW_FILE%" --repo "%MERSAD_GITHUB_REPO%" --ref "%MERSAD_BUILD_BRANCH%"
    if !ERRORLEVEL! NEQ 0 (
        echo [WARN] workflow_dispatch command returned non-zero; polling for active run matching commit !LOCAL_HEAD_SHA!...
    )
    for /L %%A in (1,1,15) do (
        if not defined RUN_ID (
            timeout /t 4 /nobreak >nul
            for /f "delims=" %%I in ('gh run list --repo "%MERSAD_GITHUB_REPO%" --workflow "%MERSAD_WORKFLOW_FILE%" --branch "%MERSAD_BUILD_BRANCH%" --limit 10 --json databaseId^,headSha^,status --jq ".[] | select(.headSha == \"!LOCAL_HEAD_SHA!\" and .status != \"completed\") | .databaseId" 2^>nul') do (
                if not defined RUN_ID if not "%%I"=="" if not "%%I"=="null" set "RUN_ID=%%I"
            )
            if not defined RUN_ID (
                for /f "delims=" %%I in ('gh run list --repo "%MERSAD_GITHUB_REPO%" --workflow "%MERSAD_WORKFLOW_FILE%" --branch "%MERSAD_BUILD_BRANCH%" --limit 5 --json databaseId^,headSha^,conclusion --jq ".[] | select(.headSha == \"!LOCAL_HEAD_SHA!\" and .conclusion == \"success\") | .databaseId" 2^>nul') do (
                    if not defined RUN_ID if not "%%I"=="" if not "%%I"=="null" set "RUN_ID=%%I"
                )
            )
        )
    )
)

if not defined RUN_ID (
    echo [ERROR] Could not find an active or successful GitHub Actions run for commit !LOCAL_HEAD_SHA! on branch %MERSAD_BUILD_BRANCH%.
    echo         Verify GitHub Actions is enabled at: https://github.com/%MERSAD_GITHUB_REPO%/actions
    pause
    exit /b 1
)
echo        [OK] Bound strictly to Run ID: !RUN_ID! ^(Commit SHA: !LOCAL_HEAD_SHA!^)
echo        Run URL: https://github.com/%MERSAD_GITHUB_REPO%/actions/runs/!RUN_ID!

REM ============================================================================
REM [8/12] Watch build progress until completion
REM ============================================================================
echo [8/12] Monitoring GitHub Actions Windows x64 build in real time ^(Run ID: !RUN_ID!^)...
gh run watch "!RUN_ID!" --repo "%MERSAD_GITHUB_REPO%" --exit-status
set "WATCH_RC=!ERRORLEVEL!"

REM ============================================================================
REM [9/12] Detect build success or failure and verify Run headSha
REM ============================================================================
echo [9/12] Verifying final workflow conclusion and commit integrity...
set "RUN_CONCLUSION="
set "RUN_HEAD_SHA="
for /f "delims=" %%C in ('gh run view "!RUN_ID!" --repo "%MERSAD_GITHUB_REPO%" --json conclusion --jq ".conclusion" 2^>nul') do set "RUN_CONCLUSION=%%C"
for /f "delims=" %%S in ('gh run view "!RUN_ID!" --repo "%MERSAD_GITHUB_REPO%" --json headSha --jq ".headSha" 2^>nul') do set "RUN_HEAD_SHA=%%S"

if !WATCH_RC! NEQ 0 (
    echo [ERROR] GitHub Actions build failed ^(Run ID: !RUN_ID!, conclusion: !RUN_CONCLUSION!^).
    echo         Inspect failure logs via: gh run view !RUN_ID! --repo %MERSAD_GITHUB_REPO% --log-failed
    pause
    exit /b 1
)
if /I not "!RUN_CONCLUSION!"=="success" (
    echo [ERROR] GitHub Actions run did not succeed ^(conclusion: !RUN_CONCLUSION!^).
    pause
    exit /b 1
)
if /I not "!RUN_HEAD_SHA!"=="!LOCAL_HEAD_SHA!" (
    echo [ERROR] Run headSha ^(!RUN_HEAD_SHA!^) does not match expected commit ^(!LOCAL_HEAD_SHA!^)!
    pause
    exit /b 1
)
echo        [OK] Build succeeded on Windows Runner ^(Run ID: !RUN_ID!, SHA: !RUN_HEAD_SHA!^).

REM ============================================================================
REM [10/12] Automatically download the build Artifact to a local directory
REM ============================================================================
echo [10/12] Downloading artifact %MERSAD_ARTIFACT_NAME% into %MERSAD_ARTIFACT_DIR%...
if exist "%MERSAD_ARTIFACT_DIR%" rmdir /s /q "%MERSAD_ARTIFACT_DIR%" >nul 2>nul
mkdir "%MERSAD_ARTIFACT_DIR%"
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] Could not create artifact download directory %MERSAD_ARTIFACT_DIR%.
    pause
    exit /b 1
)
gh run download "!RUN_ID!" --repo "%MERSAD_GITHUB_REPO%" --name "%MERSAD_ARTIFACT_NAME%" --dir "%MERSAD_ARTIFACT_DIR%"
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] Failed to download artifact %MERSAD_ARTIFACT_NAME% from run !RUN_ID!.
    pause
    exit /b 1
)
echo        [OK] Artifact downloaded to: %MERSAD_ARTIFACT_DIR%

REM ============================================================================
REM [11/12] Extract/stage the package and verify all required files, models, and DLLs
REM ============================================================================
echo [11/12] Staging final runnable distribution folder at %MERSAD_FINAL_DIR%\MERSAD_AI ...
if exist "%MERSAD_FINAL_DIR%\MERSAD_AI" rmdir /s /q "%MERSAD_FINAL_DIR%\MERSAD_AI" >nul 2>nul
mkdir "%MERSAD_FINAL_DIR%\MERSAD_AI" >nul 2>nul

if exist "%MERSAD_ARTIFACT_DIR%\MERSAD_AI\MERSAD_AI.exe" (
    xcopy /E /I /Y "%MERSAD_ARTIFACT_DIR%\MERSAD_AI" "%MERSAD_FINAL_DIR%\MERSAD_AI" >nul
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to stage files from %MERSAD_ARTIFACT_DIR%\MERSAD_AI
        pause
        exit /b 1
    )
) else if exist "%MERSAD_ARTIFACT_DIR%\dist\MERSAD_AI\MERSAD_AI.exe" (
    xcopy /E /I /Y "%MERSAD_ARTIFACT_DIR%\dist\MERSAD_AI" "%MERSAD_FINAL_DIR%\MERSAD_AI" >nul
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to stage files from %MERSAD_ARTIFACT_DIR%\dist\MERSAD_AI
        pause
        exit /b 1
    )
) else if exist "%MERSAD_ARTIFACT_DIR%\MERSAD_AI.exe" (
    xcopy /E /I /Y "%MERSAD_ARTIFACT_DIR%" "%MERSAD_FINAL_DIR%\MERSAD_AI" >nul
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to stage files from %MERSAD_ARTIFACT_DIR%
        pause
        exit /b 1
    )
) else (
    for %%Z in ("%MERSAD_ARTIFACT_DIR%\*.zip") do (
        powershell -NoProfile -Command "Expand-Archive -LiteralPath '%%~fZ' -DestinationPath '%MERSAD_FINAL_DIR%\MERSAD_AI' -Force"
        if !ERRORLEVEL! NEQ 0 (
            echo [ERROR] Failed to extract archive %%~fZ
            pause
            exit /b 1
        )
    )
)

REM Strictly verify all required distribution files, models, sidecars, and launchers exist
for %%F in (
    "%MERSAD_FINAL_DIR%\MERSAD_AI\MERSAD_AI.exe"
    "%MERSAD_FINAL_DIR%\MERSAD_AI\models\yunet.onnx"
    "%MERSAD_FINAL_DIR%\MERSAD_AI\models\sface.onnx"
    "%MERSAD_FINAL_DIR%\MERSAD_AI\models\yolov8n.pt"
    "%MERSAD_FINAL_DIR%\MERSAD_AI\models\yolov8n.pt.sha256"
    "%MERSAD_FINAL_DIR%\MERSAD_AI\models\.trusted_models.json"
    "%MERSAD_FINAL_DIR%\MERSAD_AI\RUN.bat"
    "%MERSAD_FINAL_DIR%\MERSAD_AI\RUN_LAN.bat"
    "%MERSAD_FINAL_DIR%\MERSAD_AI\VERIFY_AUDIT.bat"
) do (
    if not exist %%F (
        echo [ERROR] Final distribution verification failed: missing required file %%F
        pause
        exit /b 1
    )
)

REM Verify EasyOCR .pth weights (>= 2 files) and bundled native DLLs/PYDs exist inside MERSAD_AI_RELEASE\MERSAD_AI
set "PTH_COUNT=0"
for %%P in ("%MERSAD_FINAL_DIR%\MERSAD_AI\models\easyocr\*.pth") do set /a PTH_COUNT+=1
if !PTH_COUNT! LSS 2 (
    echo [ERROR] Final distribution verification failed: found !PTH_COUNT! EasyOCR .pth files in %MERSAD_FINAL_DIR%\MERSAD_AI\models\easyocr ^(expected ^>= 2^).
    pause
    exit /b 1
)

set "DLL_COUNT=0"
for /f "delims=" %%D in ('dir /s /b "%MERSAD_FINAL_DIR%\MERSAD_AI\*.dll" 2^>nul') do set /a DLL_COUNT+=1
if !DLL_COUNT! LSS 5 (
    echo [ERROR] Final distribution verification failed: bundled DLLs missing in %MERSAD_FINAL_DIR%\MERSAD_AI ^(found !DLL_COUNT! DLLs^).
    pause
    exit /b 1
)
echo        [OK] Distribution structure verified ^(!DLL_COUNT! DLLs and !PTH_COUNT! EasyOCR weights present^).

REM ============================================================================
REM [12/12] Run post-extraction verification on MERSAD_AI.exe and strictly check exit codes
REM ============================================================================
echo [12/12] Executing post-extraction verification on %MERSAD_FINAL_DIR%\MERSAD_AI\MERSAD_AI.exe...
"%MERSAD_FINAL_DIR%\MERSAD_AI\MERSAD_AI.exe" --verify-models
set "VERIFY_MODELS_RC=!ERRORLEVEL!"
if !VERIFY_MODELS_RC! NEQ 0 (
    echo [ERROR] Post-extraction verification FAILED: MERSAD_AI.exe --verify-models exited with code !VERIFY_MODELS_RC!.
    pause
    exit /b !VERIFY_MODELS_RC!
)

"%MERSAD_FINAL_DIR%\MERSAD_AI\MERSAD_AI.exe" --verify
set "VERIFY_AUDIT_RC=!ERRORLEVEL!"
if !VERIFY_AUDIT_RC! NEQ 0 (
    echo [ERROR] Post-extraction verification FAILED: MERSAD_AI.exe --verify exited with code !VERIFY_AUDIT_RC!.
    pause
    exit /b !VERIFY_AUDIT_RC!
)

echo.
echo ============================================================================
echo   SUCCESS! MERSAD AI V7.1 Stage 15 Windows x64 Distribution is VERIFIED:
echo   Final EXE Path   : %MERSAD_FINAL_DIR%\MERSAD_AI\MERSAD_AI.exe
echo   Standard Launch  : %MERSAD_FINAL_DIR%\MERSAD_AI\RUN.bat
echo   LAN / Wi-Fi Mode : %MERSAD_FINAL_DIR%\MERSAD_AI\RUN_LAN.bat
echo   Audit ^& Models   : %MERSAD_FINAL_DIR%\MERSAD_AI\VERIFY_AUDIT.bat
echo ============================================================================
pause
exit /b 0
