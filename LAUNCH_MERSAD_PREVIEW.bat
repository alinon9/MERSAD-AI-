@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:MENU
cls
echo ============================================================================
echo   منظومة مرصاد الذكي ومختبر المحاكاة — MERSAD AI — PREVIEW 0.1 (Windows x64)
echo   [نسخة تجريبية موثقة للمعاينة والاختبار ببيانات اصطناعية — ليست للاستخدام الميداني]
echo ============================================================================
echo.
echo   [1] تشغيل مرصاد الذكي بمفرده (MERSAD AI V7.1 — المنفذ 8000)
echo   [2] تشغيل مختبر الكاميرات بمفرده (MERSAD LAB 1.0 — المنفذ 8090)
echo   [3] تشغيل المنظومتين معاً (AI + LAB) مع بث الكاميرا الافتراضية تلقائياً
echo   [4] تشغيل كافة الاختبارات الآلية وفحص التكامل وسلامة الملفات
echo   [5] خروج
echo.
set /p CHOICE="اختر رقم العملية [1-5]: "

if "%CHOICE%"=="1" goto RUN_AI
if "%CHOICE%"=="2" goto RUN_LAB
if "%CHOICE%"=="3" goto RUN_BOTH
if "%CHOICE%"=="4" goto RUN_TESTS
if "%CHOICE%"=="5" exit /b 0
goto MENU

:RUN_AI
echo.
echo [INFO] جارٍ تشغيل MERSAD AI Preview 0.1 على العنوان http://127.0.0.1:8000 ...
pushd "MERSAD_AI_Preview_0.1"
call RUN.bat
popd
pause
goto MENU

:RUN_LAB
echo.
echo [INFO] جارٍ تشغيل MERSAD LAB Preview 0.1 على العنوان http://127.0.0.1:8090 ...
pushd "MERSAD_LAB_Preview_0.1"
call RUN_LAB.bat
popd
pause
goto MENU

:RUN_BOTH
echo.
echo [1/2] تشغيل خادم المختبر MERSAD LAB في نافذة مستقلة (http://127.0.0.1:8090)...
start "MERSAD LAB 1.0 (PREVIEW 0.1)" /D "%~dp0MERSAD_LAB_Preview_0.1" cmd /c RUN_LAB.bat
timeout /t 3 /nobreak >nul
echo [2/2] تشغيل MERSAD AI وربطه بتدفق الكاميرا الافتراضية http://127.0.0.1:8090/stream/cam1.mjpg ...
pushd "MERSAD_AI_Preview_0.1"
if exist "dist\MERSAD_AI\MERSAD_AI.exe" (
    "dist\MERSAD_AI\MERSAD_AI.exe" --source "http://127.0.0.1:8090/stream/cam1.mjpg" --cam LAB_CAM1 --allow-degraded-preview
) else (
    python mersad_live.py --source "http://127.0.0.1:8090/stream/cam1.mjpg" --cam LAB_CAM1 --allow-degraded-preview
)
popd
pause
goto MENU

:RUN_TESTS
echo.
echo [1/4] التحقق من سلامة ملفات MERSAD AI Preview 0.1...
python "MERSAD_AI_Preview_0.1\verify_integrity.py"
echo [2/4] تشغيل اختبارات MERSAD AI (232 اختباراً)...
python -u "MERSAD_AI_Preview_0.1\selftest.py"
echo [3/4] تشغيل اختبارات MERSAD LAB (20 اختباراً)...
python -u "MERSAD_LAB_Preview_0.1\test_lab.py"
echo [4/4] تشغيل اختبارات التكامل بين AI وLAB (12 سيناريو)...
python -u "integration\test_ai_lab_integration.py"
pause
goto MENU
