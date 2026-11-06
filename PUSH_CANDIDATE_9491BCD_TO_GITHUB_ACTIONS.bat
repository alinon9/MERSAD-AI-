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
echo   نشر الإصدار النهائي المعتمد (MERSAD AI Preview 0.1 ^& MERSAD LAB Preview 0.1)
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

REM 2. استنساخ حزمة التاريخ الجنائي الكامل إلى مجلد عمل نظيف
set "WORK_REPO=%TEMP%\mersad_release_preview01_push_repo"
if exist "%WORK_REPO%" rmdir /s /q "%WORK_REPO%"

git clone "reports_and_logs\mersad_preview_0_1_verifiable_history.bundle" "%WORK_REPO%"
if errorlevel 1 (
    echo [ERROR] تعذّر استنساخ حزمة Git الجنائية reports_and_logs\mersad_preview_0_1_verifiable_history.bundle!
    exit /b 1
)

pushd "%WORK_REPO%"

REM 3. التحقق من عدم المساس بالفرع الرئيسي main
for /f "tokens=*" %%M in ('git rev-parse refs/heads/main 2^>nul') do set "LOCAL_MAIN_SHA=%%M"
if not "!LOCAL_MAIN_SHA!"=="%EXPECTED_MAIN_SHA%" (
    echo [ERROR] بصمة الفرع الرئيسي main ^(!LOCAL_MAIN_SHA!^) لا تطابق البصمة الأصلية غير الممسوسة ^(%EXPECTED_MAIN_SHA%^)!
    popd
    exit /b 1
)

REM 4. التبديل إلى فرع الإصدار النهائي release/mersad-preview-0.1 والتحقق من احتوائه على التزام الكود 25131918
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
echo [INFO] التزام الكود المعتمد ^(v0.1.0-preview-code^): %EXPECTED_AI_CODE_SHA%

REM 5. رفع الفرع release/mersad-preview-0.1 والأوسمة إلى GitHub دون لمس main ودون force-push
git remote set-url origin "%REMOTE_URL%"
echo [INFO] جارٍ رفع الفرع %TARGET_BRANCH% إلى GitHub ^(دون --force ودون المساس بفرع main^)...
git push -u origin "refs/heads/%TARGET_BRANCH%:refs/heads/%TARGET_BRANCH%"
if errorlevel 1 (
    echo [ERROR] فشل رفع الفرع %TARGET_BRANCH% إلى GitHub!
    popd
    exit /b 1
)

git push origin refs/tags/v0.1.0-preview-code refs/tags/rollback-preview01-f66ecea refs/tags/rollback-stable-49e400c refs/tags/rollback-stable-9491bcd refs/tags/rollback-stage15-64b0dde
if errorlevel 1 (
    echo [WARN] تعذّر رفع بعض أوسمة الرجوع الاختيارية، جاري المتابعة...
)

REM 6. التحقق الفعلي من SHA المنشور على GitHub بعد الرفع عبر git ls-remote
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

REM 7. التشغيل اليدوي الصريح لسير العمل عبر workflow_dispatch على الفرع release/mersad-preview-0.1
echo [INFO] جارٍ تشغيل سير العمل %WORKFLOW_FILE% يدوياً ^(workflow_dispatch^) على الفرع %TARGET_BRANCH%...
gh workflow run "%WORKFLOW_FILE%" --ref "%TARGET_BRANCH%" -f run_extended_stress=true
if errorlevel 1 (
    echo [ERROR] فشل تشغيل سير العمل %WORKFLOW_FILE% عبر gh workflow run على الفرع %TARGET_BRANCH%!
    popd
    exit /b 1
)

timeout /t 5 /nobreak >nul
set "RUN_ID="
for /f "tokens=*" %%I in ('gh run list --workflow="%WORKFLOW_FILE%" --branch="%TARGET_BRANCH%" --limit 1 --json databaseId --jq ".[0].databaseId"') do set "RUN_ID=%%I"
if "!RUN_ID!"=="" (
    echo [ERROR] لم يتم العثور على معرّف تشغيل ^(Run ID^) لسير العمل %WORKFLOW_FILE% على الفرع %TARGET_BRANCH%!
    popd
    exit /b 1
)
echo [INFO] تم بدء تشغيل GitHub Actions بنجاح — Run ID: !RUN_ID!
echo [INFO] جارٍ انتظار اكتمال بناء واختبار Windows x64 ^(gh run watch !RUN_ID! --exit-status^)...
gh run watch "!RUN_ID!" --exit-status
if errorlevel 1 (
    echo [ERROR] فشل تنفيذ سير العمل على GitHub Actions ^(Run ID: !RUN_ID!^)! راجع السجلات عبر: gh run view !RUN_ID! --log-failed
    popd
    exit /b 1
)

popd
set "ARTIFACTS_OUT_DIR=%~dp0dist_github_actions_run_!RUN_ID!"
if exist "!ARTIFACTS_OUT_DIR!" rmdir /s /q "!ARTIFACTS_OUT_DIR!"
mkdir "!ARTIFACTS_OUT_DIR!"
echo [INFO] جارٍ تنزيل واستخراج مخرجات Windows الخمسة ^(Artifacts^) إلى: !ARTIFACTS_OUT_DIR!
gh run download "!RUN_ID!" --dir "!ARTIFACTS_OUT_DIR!"
if errorlevel 1 (
    echo [ERROR] تعذّر تنزيل Artifacts للتشغيل !RUN_ID!!
    exit /b 1
)

echo [OK] اكتمل النشر والبناء واستخراج مخرجات Windows الخمسة بنجاح ^(Run ID: !RUN_ID!^)!
exit /b 0
