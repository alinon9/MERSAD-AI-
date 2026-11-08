@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if "%MERSAD_DEPLOY_BRANCH%"=="" (
    set "TARGET_BRANCH=fix/preview-0.1-postbuild-42273598736"
) else (
    set "TARGET_BRANCH=%MERSAD_DEPLOY_BRANCH%"
)
if not "%~1"=="" set "TARGET_BRANCH=%~1"

set "EXPECTED_AI_PREFLIGHT_PARENT_SHA=05f29af416c4a28ddf59c291819584d1a416d570"
set "EXPECTED_AI_CODE_SHA=edaf651321ec9ea6ba613e3ab1630bc16b11b9d5"
set "EXPECTED_AI_PREV_FIX_SHA=d965d71317e3506e5dce9d316dc81cb8ae45e43b"
set "EXPECTED_AI_RELEASE_BASE_SHA=25131918a981ac2ac37923d4c738d9f93cdcbc5b"
set "EXPECTED_LAB_CODE_SHA=748ac0158761812a6fff63ff6fe626b9df8c252b"
set "EXPECTED_LAB_RELEASE_BASE_SHA=e9284356f4d1a8205946d5893121c6f8a2f22012"
set "EXPECTED_MAIN_SHA=25c9e5bba30dc8f921675e12c23a53571be895c1"
set "WORKFLOW_FILE=release-mersad-preview-0.1-windows.yml"
set "REMOTE_URL=https://github.com/alinon9/MERSAD-AI-.git"

echo ========================================================================================
echo   نشر الإصدار النهائي المعتمد وبناء واستخراج مخرجات Windows x64 ^(Push-Triggered Single-Run CI^)
echo   الفرع المستهدف ^(Configurable^)     : %TARGET_BRANCH%
echo   التزام Preflight الأب ^(v0.1.2^)    : %EXPECTED_AI_PREFLIGHT_PARENT_SHA%
echo   التزام الكود الموحد لـ MERSAD AI   : %EXPECTED_AI_CODE_SHA% ^(سلف: %EXPECTED_AI_PREV_FIX_SHA% / %EXPECTED_AI_RELEASE_BASE_SHA%^)
echo   التزام الكود الموحد لـ MERSAD LAB  : %EXPECTED_LAB_CODE_SHA% ^(سلف: %EXPECTED_LAB_RELEASE_BASE_SHA%^)
echo   الفرع الرئيسي main ^(غير ممسوس^)   : %EXPECTED_MAIN_SHA%
echo ========================================================================================

REM 1. التحقق المسبق الصارم من تثبيت ومصادقة GitHub CLI (gh) قبل البدء
where gh >nul 2>&1
if errorlevel 1 (
    echo [ERROR] أداة GitHub CLI ^(gh^) غير مثبتة على هذا الجهاز!
    echo [ERROR] يتطلب رصد ومتابعة تشغيل سير العمل %WORKFLOW_FILE% وتنزيل Artifacts وجود أداة gh مصادق عليها.
    echo [ERROR] يرجى تثبيت GitHub CLI ^(winget install GitHub.cli^) وتسجيل الدخول عبر ^(gh auth login^) ثم إعادة المحاولة.
    exit /b 1
)

gh auth status >nul 2>&1
if errorlevel 1 (
    echo [ERROR] أداة GitHub CLI ^(gh^) مثبتة ولكنها غير مصادق عليها ^(Unauthenticated^)!
    echo [ERROR] يرجى تنفيذ الأمر: gh auth login للمصادقة مع حساب GitHub قبل تشغيل هذا السكربت.
    exit /b 1
)

REM 2. التحقق من أن ملف الـ Workflow يعتمد محفز push فقط دون workflow_dispatch المزدوج
findstr /C:"push:" ".github\workflows\%WORKFLOW_FILE%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] المحفز push غير معرّف في .github\workflows\%WORKFLOW_FILE%!
    exit /b 1
)
findstr /C:"workflow_dispatch:" ".github\workflows\%WORKFLOW_FILE%" >nul 2>&1
if not errorlevel 1 (
    echo [ERROR] ملف .github\workflows\%WORKFLOW_FILE% لا يزال يحتوي على workflow_dispatch مما يسبب ازدواجية التشغيل!
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

REM 5. التبديل إلى الفرع المستهدف والتحقق من نظافة شجرة العمل وسلالة الالتزامات المعتمدة
git checkout "%TARGET_BRANCH%"
if errorlevel 1 (
    echo [ERROR] تعذّر التبديل إلى الفرع المستهدف %TARGET_BRANCH%!
    popd
    exit /b 1
)

set "DIRTY_TREE="
for /f "tokens=*" %%S in ('git status --porcelain 2^>nul') do set "DIRTY_TREE=%%S"
if not "!DIRTY_TREE!"=="" (
    echo [ERROR] شجرة العمل غير نظيفة قبل الرفع: !DIRTY_TREE!
    popd
    exit /b 1
)

if /i "%TARGET_BRANCH%"=="fix/preview-0.1-postbuild-42273598736" (
    git merge-base --is-ancestor "%EXPECTED_AI_PREFLIGHT_PARENT_SHA%" HEAD
    if errorlevel 1 (
        echo [ERROR] الفرع %TARGET_BRANCH% لا ينحدر من التزام Preflight المعتمد %EXPECTED_AI_PREFLIGHT_PARENT_SHA%!
        popd
        exit /b 1
    )
    git merge-base --is-ancestor "%EXPECTED_AI_CODE_SHA%" HEAD
    if errorlevel 1 (
        echo [ERROR] الفرع %TARGET_BRANCH% لا يتضمن التزام الكود الموحد %EXPECTED_AI_CODE_SHA%!
        popd
        exit /b 1
    )
    git merge-base --is-ancestor "%EXPECTED_AI_PREV_FIX_SHA%" HEAD
    if errorlevel 1 (
        echo [ERROR] الفرع %TARGET_BRANCH% لا يتضمن التزام الإصلاح %EXPECTED_AI_PREV_FIX_SHA%!
        popd
        exit /b 1
    )
)

git merge-base --is-ancestor "%EXPECTED_AI_RELEASE_BASE_SHA%" HEAD
if errorlevel 1 (
    echo [ERROR] الفرع %TARGET_BRANCH% لا يتضمن التزام الكود الأساسي %EXPECTED_AI_RELEASE_BASE_SHA%!
    popd
    exit /b 1
)

for /f "tokens=*" %%H in ('git rev-parse HEAD') do set "LOCAL_HEAD_SHA=%%H"
echo [INFO] أحدث التزام محلي ^(HEAD^) على الفرع %TARGET_BRANCH%: !LOCAL_HEAD_SHA!

git remote set-url origin "%REMOTE_URL%"

REM 6. تسجيل جميع Run IDs السابقة قبل تنفيذ git push لمنع التقاط أي تشغيل تاريخي سابق
set "PREV_RUN_IDS_JSON=[]"
for /f "tokens=*" %%P in ('gh run list --workflow="%WORKFLOW_FILE%" --limit 30 --json databaseId --jq "[.[].databaseId]" 2^>nul') do set "PREV_RUN_IDS_JSON=%%P"
echo [STATUS] PREFLIGHT_PASS — اجتازت جميع فحوصات ما قبل النشر، وسُجلت المعرفات السابقة: !PREV_RUN_IDS_JSON!

REM 7. رفع الفرع المستهدف مرة واحدة إلى GitHub (المحفز الوحيد لسير العمل عبر event=push) دون لمس main ودون force-push
echo [INFO] جارٍ رفع الفرع %TARGET_BRANCH% إلى GitHub لإطلاق بناء Windows CI تلقائياً عبر محفز push فقط ^(دون أي استدعاء يدوي مزدوج^)...
git push -u origin "refs/heads/%TARGET_BRANCH%:refs/heads/%TARGET_BRANCH%"
if errorlevel 1 (
    echo [ERROR] فشل رفع الفرع %TARGET_BRANCH% إلى GitHub!
    popd
    exit /b 1
)

git push origin refs/tags/v0.1.2-windows-ci-preflight-ready refs/tags/v0.1.1-postbuild-reconciled-code refs/tags/v0.1.0-preview-code refs/tags/rollback-preview01-f66ecea refs/tags/rollback-stable-49e400c refs/tags/rollback-stable-9491bcd refs/tags/rollback-stage15-64b0dde >nul 2>&1

REM 8. التحقق الفعلي من SHA المنشور على GitHub بعد الرفع عبر git ls-remote
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
echo [STATUS] PUSH_COMPLETED — تم التحقق من تطابق SHA الفعلي المنشور على GitHub: !REMOTE_SHA!

REM 9. حلقة استقصاء ذكية (Polling) للتحقق من ظهور تشغيل واحد فقط يطابق Workflow + event=="push" + الفرع + LOCAL_HEAD_SHA وغير موجود في PREV_RUN_IDS_JSON
set "RUN_ID="
set "MATCH_COUNT=0"
for /L %%A in (1,1,24) do (
    if "!RUN_ID!"=="" (
        timeout /t 5 /nobreak >nul
        for /f "tokens=*" %%C in ('gh run list --workflow="%WORKFLOW_FILE%" --branch="%TARGET_BRANCH%" --event=push --limit 30 --json databaseId^,headSha^,event^,headBranch --jq "[.[] | select(.event == \"push\" and .headBranch == \"%TARGET_BRANCH%\" and (.headSha | ascii_downcase) == (\"!LOCAL_HEAD_SHA!\" | ascii_downcase) and ((.databaseId as $id | !PREV_RUN_IDS_JSON! | index($id)) == null))] | length" 2^>nul') do (
            set "MATCH_COUNT=%%C"
        )
        if !MATCH_COUNT! GTR 1 (
            echo [STATUS] DUPLICATE_RUN_DETECTED — تم رصد !MATCH_COUNT! تشغيلات متزامنة لنفس الالتزام !LOCAL_HEAD_SHA! على الفرع %TARGET_BRANCH%! إيقاف فوري.
            popd
            exit /b 1
        )
        if "!MATCH_COUNT!"=="1" (
            for /f "tokens=*" %%I in ('gh run list --workflow="%WORKFLOW_FILE%" --branch="%TARGET_BRANCH%" --event=push --limit 30 --json databaseId^,headSha^,event^,headBranch --jq "[.[] | select(.event == \"push\" and .headBranch == \"%TARGET_BRANCH%\" and (.headSha | ascii_downcase) == (\"!LOCAL_HEAD_SHA!\" | ascii_downcase) and ((.databaseId as $id | !PREV_RUN_IDS_JSON! | index($id)) == null))][0].databaseId" 2^>nul') do (
                set "RUN_ID=%%I"
            )
        )
        if "!RUN_ID!"=="" (
            echo [POLL %%A/24] في انتظار ظهور تشغيل push جديد للالتزام !LOCAL_HEAD_SHA!...
        )
    )
)

if "!RUN_ID!"=="" (
    echo [STATUS] RUN_TIMEOUT — لم يظهر تشغيل push جديد يطابق الالتزام !LOCAL_HEAD_SHA! على الفرع %TARGET_BRANCH% بعد 120 ثانية!
    popd
    exit /b 1
)
echo [STATUS] RUN_DISCOVERED — تم اكتشاف تشغيل push الجديد المطابق للالتزام !LOCAL_HEAD_SHA!: !RUN_ID!

REM 10. مراقبة اكتمال التشغيل والتحقق من نجاح جميع المهام (Jobs)
echo [STATUS] RUN_IN_PROGRESS — جارٍ متابعة بناء واختبار Windows x64 ^(gh run watch !RUN_ID! --exit-status^)...
gh run watch "!RUN_ID!" --exit-status
if errorlevel 1 (
    echo [STATUS] RUN_FAILED — فشل تنفيذ سير العمل على GitHub Actions ^(Run ID: !RUN_ID!^)! راجع السجلات عبر: gh run view !RUN_ID! --log-failed
    popd
    exit /b 1
)

set "FAILED_JOBS="
for /f "tokens=*" %%J in ('gh run view "!RUN_ID!" --json conclusion^,jobs --jq "if .conclusion != \"success\" or ([.jobs[] | select(.conclusion != \"success\")] | length > 0) then \"FAILED\" else \"OK\" end"') do set "FAILED_JOBS=%%J"
if not "!FAILED_JOBS!"=="OK" (
    echo [STATUS] RUN_FAILED — فشل أحد الـ Jobs داخل التشغيل !RUN_ID!!
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
    echo [STATUS] RUN_FAILED — تعذّر تنزيل Artifacts للتشغيل !RUN_ID!!
    exit /b 1
)

REM 11. التحقق الصارم من وجود الملفات الخمسة المطلوبة وحساب بصمات SHA-256 لكل ملف
python tools\deploy_and_run_github_actions.py --verify-downloaded-artifacts "!ARTIFACTS_OUT_DIR!" --run-id "!RUN_ID!"
if errorlevel 1 (
    echo [STATUS] RUN_FAILED — فشل التحقق من اكتمال الملفات التنفيذية الخمسة أو حساب بصماتها في !ARTIFACTS_OUT_DIR!!
    exit /b 1
)

echo [STATUS] ARTIFACTS_VERIFIED — تم التحقق من وجود جميع ملفات البناء الخمسة وحساب بصماتها SHA-256.
echo [STATUS] PASS — اكتمل البناء والتحقق من الملفات الخمسة وبصمات SHA-256 بنجاح ^(Run ID: !RUN_ID!^)!
exit /b 0
