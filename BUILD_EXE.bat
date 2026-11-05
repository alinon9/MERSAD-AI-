@echo off
set "YOLO_AUTOINSTALL=false"
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo   MERSAD AI - Windows Distribution Build Script (PyInstaller)
echo   Mode: --onedir (dist\MERSAD_AI\ folder with models & DLLs)
echo ============================================================

call setup.bat || (
    echo [ERROR] Environment setup failed. Cannot proceed with build.
    pause
    exit /b 1
)

echo [1/5] Running strict installation ^& model verification...
venv\Scripts\python.exe check_install.py --strict || (
    echo.
    echo [ERROR] Fix the FAIL lines above before building the executable.
    pause
    exit /b 1
)

echo [2/5] Running 3 repeated self-test suites to catch concurrency/camera flakes...
for /L %%I in (1,1,3) do (
    venv\Scripts\python.exe -u selftest.py > selftest_build_%%I.log 2>&1 || (
        type selftest_build_%%I.log
        echo [ERROR] Standard self-test run %%I failed - aborting build.
        pause
        exit /b 1
    )
    findstr /C:"SELF-TEST OK" selftest_build_%%I.log >nul || (
        type selftest_build_%%I.log
        echo [ERROR] Self-test run %%I did not confirm success.
        pause
        exit /b 1
    )
)
set MERSAD_BLOCK_SKLEARN=1
venv\Scripts\python.exe -u selftest.py > selftest_build_nosklearn.log 2>&1 || (
    type selftest_build_nosklearn.log
    set MERSAD_BLOCK_SKLEARN=
    echo [ERROR] No-scikit-learn self-test failed - aborting build.
    pause
    exit /b 1
)
set MERSAD_BLOCK_SKLEARN=
findstr /C:"SELF-TEST OK" selftest_build_nosklearn.log >nul || (
    type selftest_build_nosklearn.log
    echo [ERROR] No-scikit-learn run did not confirm success.
    pause
    exit /b 1
)

echo [3/5] Installing pinned PyInstaller (pyinstaller==6.11.1) and running pip check...
venv\Scripts\pip.exe install pyinstaller==6.11.1 -c constraints-win-x64.txt || (
    echo [ERROR] Failed to install pyinstaller==6.11.1.
    pause
    exit /b 1
)
venv\Scripts\python.exe -m pip check || (
    echo [ERROR] pip check reported package conflicts.
    pause
    exit /b 1
)

echo [4/5] Building MERSAD_AI --onedir distribution (logging to build_pyinstaller.log)...
venv\Scripts\pyinstaller.exe --noconfirm --clean --onedir --name MERSAD_AI ^
  --add-data "dashboard.html;." ^
  --add-data "README_AR.md;." ^
  --hidden-import registry ^
  --hidden-import insights ^
  --hidden-import analytics ^
  --hidden-import camera_history ^
  --hidden-import notify ^
  --hidden-import server ^
  --hidden-import openpyxl ^
  --collect-all easyocr ^
  --collect-all ultralytics ^
  --collect-submodules sklearn ^
  mersad_live.py > build_pyinstaller.log 2>&1 || (
    echo [ERROR] PyInstaller build failed. Last lines of build_pyinstaller.log:
    powershell -NoProfile -Command "Get-Content build_pyinstaller.log -Tail 35" 2>nul
    pause
    exit /b 1
)

echo [5/5] Copying verified offline AI models and distribution launchers into dist\MERSAD_AI\ ...
if not exist "dist\MERSAD_AI\MERSAD_AI.exe" (
    echo [ERROR] Build output dist\MERSAD_AI\MERSAD_AI.exe was not created!
    pause
    exit /b 1
)

if exist "models" (
    xcopy /E /I /Y "models" "dist\MERSAD_AI\models" >nul || (
        echo [ERROR] Failed to copy models directory into dist\MERSAD_AI\models.
        pause
        exit /b 1
    )
)

REM Create distribution launcher scripts inside dist\MERSAD_AI\ that run MERSAD_AI.exe directly without Python/venv
(
echo @echo off
echo chcp 65001 ^>nul
echo cd /d "%%~dp0"
echo MERSAD_AI.exe %%*
echo pause
) > "dist\MERSAD_AI\RUN.bat"

(
echo @echo off
echo chcp 65001 ^>nul
echo cd /d "%%~dp0"
echo echo [LAN MODE] Starting MERSAD_AI.exe on 0.0.0.0 for local Wi-Fi access...
echo MERSAD_AI.exe --host 0.0.0.0 %%*
echo pause
) > "dist\MERSAD_AI\RUN_LAN.bat"

(
echo @echo off
echo chcp 65001 ^>nul
echo cd /d "%%~dp0"
echo MERSAD_AI.exe --verify
echo pause
) > "dist\MERSAD_AI\VERIFY_AUDIT.bat"

REM Verify required files exist inside dist\MERSAD_AI\ before declaring success
for %%F in ("dist\MERSAD_AI\MERSAD_AI.exe" "dist\MERSAD_AI\models\yunet.onnx" "dist\MERSAD_AI\models\sface.onnx" "dist\MERSAD_AI\models\yolov8n.pt" "dist\MERSAD_AI\RUN.bat" "dist\MERSAD_AI\RUN_LAN.bat") do (
    if not exist %%F (
        echo [ERROR] Distribution verification failed: missing required file %%F
        pause
        exit /b 1
    )
)

pushd "%TEMP%"
"%~dp0dist\MERSAD_AI\MERSAD_AI.exe" --verify > "%~dp0exe_verify_build.log" 2>&1
set VERIFY_RC=!ERRORLEVEL!
popd
if not "!VERIFY_RC!"=="0" (
    type exe_verify_build.log
    echo [ERROR] Standalone EXE audit verification failed.
    pause
    exit /b 1
)
findstr /C:"Audit chain OK" exe_verify_build.log >nul || (
    type exe_verify_build.log
    echo [ERROR] Standalone EXE did not confirm audit-chain integrity.
    pause
    exit /b 1
)

"%~dp0dist\MERSAD_AI\MERSAD_AI.exe" --verify-models > "%~dp0exe_model_verify.log" 2>&1
set MODEL_VERIFY_RC=!ERRORLEVEL!
if not "!MODEL_VERIFY_RC!"=="0" (
    type exe_model_verify.log
    echo [ERROR] Bundled AI model verification failed after build.
    pause
    exit /b 1
)
type exe_model_verify.log
findstr /C:"All bundled AI models are present and valid." exe_model_verify.log >nul || (
    type exe_model_verify.log
    echo [ERROR] Standalone EXE did not confirm model integrity.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   BUILD COMPLETE ^& VERIFIED: dist\MERSAD_AI\MERSAD_AI.exe
echo   Note: This is an --onedir distribution. Distribute the
echo   ENTIRE dist\MERSAD_AI\ folder (including internal DLLs and
echo   models\) to target Windows x64 machines.
echo ============================================================
pause
exit /b 0
