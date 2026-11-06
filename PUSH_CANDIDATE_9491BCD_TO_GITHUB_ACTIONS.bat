@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "TARGET_BRANCH=release/mersad-preview-0.1"
set "EXPECTED_AI_CODE_SHA=25131918a981ac2ac37923d4c738d9f93cdcbc5b"
set "EXPECTED_LAB_CODE_SHA=e9284356f4d1a8205946d5893121c6f8a2f22012"
set "EXPECTED_MAIN_SHA=25c9e5bba30dc8f921675e12c23a53571be895c1"
set "WORKFLOW_FILE=release-mersad-preview-0.1-windows.yml"
set "REMOTE_URL=https://github.com/alinon9/MERSAD-AI-.git"

echo ========================================================================================
echo   نشر الإصدار النهائي المعتمد وبناء واستخراج مخرجات Windows x64
echo   الفرع المعتمد: %TARGET_BRANCH%
echo   التزام الكود الأساسي لـ MERSAD AI : %EXPECTED_AI_CODE_SHA%
echo   التزام الكود الأساسي لـ MERSAD LAB: %EXPECTED_LAB_CODE_SHA%
echo   الفرع الرئيسي main (غير ممسوس)   : %EXPECTED_MAIN_SHA%
echo ========================================================================================

REM 1. التحقق المسبق الصارم من تثبيت ومصادقة GitHub CLI (gh) قبل البدء
where gh >nul 2>&1
if errorlevel 1 (
    echo [ERROR] أداة GitHub CLI ^(gh^) غير مثبتة على هذا الجهاز!
    echo [ERROR] يتطلب تشغيل سير العمل %WORKFLOW_FILE% عبر workflow_dispatch وجود أداة gh مصادق عليها.
    echo [ERROR] يرجى تثبيت GitHub CLI ^(winget install GitHub.cli^) وتسجيل الدخول عبر ^(gh auth login^) ثم إعادة المحاولة.
    exit /b 1
)

gh auth status >nul 2>&1
if errorlevel 1 (
    echo [ERROR] أداة GitHub CLI ^(gh^) مثبتة ولكنها غير مصادق عليها ^(Unauthenticated^)!
    echo [ERROR] يرجى تنفيذ الأمر: gh auth login للمصادقة مع حساب GitHub قبل تشغيل هذا السكربت.
    exit /b 1
)

REM 2. التحقق من توافق مدخلات workflow_dispatch مع ملف الـ Workflow الفعلي
findstr /C:"run_extended_stress:" ".github\workflows\%WORKFLOW_FILE%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] المدخل run_extended_stress غير معرّف في .github\workflows\%WORKFLOW_FILE%!
    exit /b 1
)

REM 3. استنساخ حزمة التاريخ الجنائي الكامل إلى مجلد عمل نظيف
set "WORK_REPO=%TEMP%\mersad_release_preview01_push_repo"
if exist "%WORK_REPO%" rmdir /s /q "%WORK_REPO%"

git clone "reports_and_logs\mersad_preview_0_1_verifiable_history.bundle" "%WORK_REPO%"
if errorlevel 1 (
    echo [ERROR] تعذّر استنساخ حزمة Git الجنائية reports_and_logs\mersad_preview_0_1_verifiable_history.bundle!
    exit /b 1
)

pushd "%WORK_REPO%"

REM 4. التحقق من عدم المساس بالفرع الرئيسي main
for /f "tokens=*" %%M in ('git rev-parse origin/main 2^>nul') do set "LOCAL_MAIN_SHA=%%M"
if not "!LOCAL_MAIN_SHA!"=="%EXPECTED_MAIN_SHA%" (
    echo [ERROR] بصمة الفرع الرئيسي main ^(!LOCAL_MAIN_SHA!^) لا تطابق البصمة الأصلية غير الممسوسة ^(%EXPECTED_MAIN_SHA%^)!
    popd
    exit /b 1
)

REM 5. التبديل إلى فرع الإصدار النهائي release/mersad-preview-0.1 والتحقق من احتوائه على التزام الكود 25131918
git checkout "%TARGET_BRANCH%"
if errorlevel 1 (
    echo [ERROR] تعذّر التبديل إلى فرع الإصدار النهائي %TARGET_BRANCH%!
    popd
    exit /b 1
)

git merge-base --is-ancestor "%EXPECTED_AI_CODE_SHA%" HEAD
if errorlevel 1 (
    echo [ERROR] الفرع %TARGET_BRANCH% لا يتضمن التزام الكود المعتمد %EXPECTED_AI_CODE_SHA%!
    popd
    exit /b 1
)

for /f "tokens=*" %%H in ('git rev-parse HEAD') do set "LOCAL_HEAD_SHA=%%H"
echo [INFO] أحدث التزام محلي ^(HEAD^) على الفرع %TARGET_BRANCH%: !LOCAL_HEAD_SHA!

REM 6. رفع الفرع release/mersad-preview-0.1 والأوسمة إلى GitHub دون لمس main ودون force-push
git remote set-url origin "%REMOTE_URL%"
echo [INFO] جارٍ رفع الفرع %TARGET_BRANCH% إلى GitHub ^(دون force-push ودون المساس بفرع main^)...
git push -u origin "refs/heads/%TARGET_BRANCH%:refs/heads/%TARGET_BRANCH%"
if errorlevel 1 (
    echo [ERROR] فشل رفع الفرع %TARGET_BRANCH% إلى GitHub!
    popd
    exit /b 1
)

git push origin refs/tags/v0.1.0-preview-code refs/tags/rollback-preview01-f66ecea refs/tags/rollback-stable-49e400c refs/tags/rollback-stable-9491bcd refs/tags/rollback-stage15-64b0dde >nul 2>&1

REM 7. التحقق الفعلي من SHA المنشور على GitHub بعد الرفع عبر git ls-remote
set "REMOTE_SHA="
for /f "tokens=1" %%R in ('git ls-remote origin "refs/heads/%TARGET_BRANCH%"') do set "REMOTE_SHA=%%R"
if "!REMOTE_SHA!"=="" (
    echo [ERROR] تعذّر قراءة SHA الفعلي للفرع %TARGET_BRANCH% من GitHub عبر git ls-remote!
    popd
    exit /b 1
)
if /i not "!REMOTE_SHA!"=="!LOCAL_HEAD_SHA!" (
    echo [ERROR] عدم تطابق SHA على GitHub ^(!REMOTE_SHA!^) مع HEAD المحلي ^(!LOCAL_HEAD_SHA!^)!
    popd
    exit /b 1
)
echo [OK] تم التحقق من تطابق SHA الفعلي المنشور على GitHub: !REMOTE_SHA!

REM 8. تسجيل أحدث Run ID سابق قبل إطلاق workflow_dispatch لمنع التقاط أي تشغيل قديم
set "PREV_LATEST_RUN_ID=0"
for /f "tokens=*" %%P in ('gh run list --workflow="%WORKFLOW_FILE%" --branch="%TARGET_BRANCH%" --event=workflow_dispatch --limit 1 --json databaseId --jq ".[0].databaseId // 0" 2^>nul') do set "PREV_LATEST_RUN_ID=%%P"
echo [INFO] أحدث Run ID سابق قبل الإطلاق: !PREV_LATEST_RUN_ID!

REM 9. التشغيل اليدوي الصريح لسير العمل عبر workflow_dispatch على الفرع release/mersad-preview-0.1
echo [INFO] جارٍ إرسال طلب تشغيل سير العمل %WORKFLOW_FILE% ^(workflow_dispatch^) على الفرع %TARGET_BRANCH%...
gh workflow run "%WORKFLOW_FILE%" --ref "%TARGET_BRANCH%" -f run_extended_stress=true
if errorlevel 1 (
    echo [ERROR] فشل تشغيل سير العمل %WORKFLOW_FILE% عبر gh workflow run على الفرع %TARGET_BRANCH%!
    popd
    exit /b 1
)
echo [STATUS] DISPATCHED — تم إرسال طلب workflow_dispatch، وجارٍ انتظار تسجيل التشغيل الجديد المطابق لـ !LOCAL_HEAD_SHA!...

REM 10. حلقة استقصاء ذكية (Polling) للتحقق من ظهور Run ID جديد يطابق Workflow + workflow_dispatch + الفرع + LOCAL_HEAD_SHA
set "RUN_ID="
for /L %%A in (1,1,24) do (
    if "!RUN_ID!"=="" (
        timeout /t 5 /nobreak >nul
        for /f "tokens=*" %%I in ('gh run list --workflow="%WORKFLOW_FILE%" --branch="%TARGET_BRANCH%" --event=workflow_dispatch --limit 10 --json databaseId^,headSha^,event^,headBranch --jq ".[] | select(.event == \"workflow_dispatch\" and .headBranch == \"%TARGET_BRANCH%\" and .headSha == \"!LOCAL_HEAD_SHA!\" and (.databaseId > !PREV_LATEST_RUN_ID!)) | .databaseId" 2^>nul') do (
            if "!RUN_ID!"=="" set "RUN_ID=%%I"
        )
        if "!RUN_ID!"=="" (
            echo [POLL %%A/24] في انتظار ظهور تشغيل workflow_dispatch جديد للالتزام !LOCAL_HEAD_SHA!...
        )
    )
)

if "!RUN_ID!"=="" (
    echo [ERROR] لم يظهر تشغيل workflow_dispatch جديد يطابق الالتزام !LOCAL_HEAD_SHA! على الفرع %TARGET_BRANCH% بعد 120 ثانية!
    popd
    exit /b 1
)
echo [OK] تم التحقق من Run ID الجديد المطابق للالتزام !LOCAL_HEAD_SHA!: !RUN_ID!

REM 11. مراقبة اكتمال التشغيل والتحقق من نجاح جميع المهام (Jobs)
echo [INFO] جارٍ انتظار اكتمال بناء واختبار Windows x64 ^(gh run watch !RUN_ID! --exit-status^)...
gh run watch "!RUN_ID!" --exit-status
if errorlevel 1 (
    echo [ERROR] فشل تنفيذ سير العمل على GitHub Actions ^(Run ID: !RUN_ID!^)! راجع السجلات عبر: gh run view !RUN_ID! --log-failed
    popd
    exit /b 1
)

set "FAILED_JOBS="
for /f "tokens=*" %%J in ('gh run view "!RUN_ID!" --json conclusion^,jobs --jq "if .conclusion != \"success\" or ([.jobs[] | select(.conclusion != \"success\")] | length > 0) then \"FAILED\" else \"OK\" end"') do set "FAILED_JOBS=%%J"
if not "!FAILED_JOBS!"=="OK" (
    echo [ERROR] فشل أحد الـ Jobs داخل التشغيل !RUN_ID!!
    popd
    exit /b 1
)

popd
set "ARTIFACTS_OUT_DIR=%~dp0dist_github_actions_run_!RUN_ID!"
if exist "!ARTIFACTS_OUT_DIR!" rmdir /s /q "!ARTIFACTS_OUT_DIR!"
mkdir "!ARTIFACTS_OUT_DIR!"
echo [INFO] جارٍ تنزيل واستخراج Artifacts الخاصة بـ Run ID !RUN_ID! إلى: !ARTIFACTS_OUT_DIR!
gh run download "!RUN_ID!" --dir "!ARTIFACTS_OUT_DIR!"
if errorlevel 1 (
    echo [ERROR] تعذّر تنزيل Artifacts للتشغيل !RUN_ID!!
    exit /b 1
)

REM 12. التحقق الصارم من وجود الملفات الخمسة المطلوبة وحساب بصمات SHA-256 لكل ملف
python tools\deploy_and_run_github_actions.py --verify-downloaded-artifacts "!ARTIFACTS_OUT_DIR!" --run-id "!RUN_ID!"
if errorlevel 1 (
    echo [ERROR] فشل التحقق من اكتمال الملفات التنفيذية الخمسة أو حساب بصماتها في !ARTIFACTS_OUT_DIR!!
    exit /b 1
)

echo [STATUS] PASS — اكتمل البناء والتحقق من الملفات الخمسة وبصمات SHA-256 بنجاح ^(Run ID: !RUN_ID!^)!
exit /b 0
