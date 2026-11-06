$ErrorActionPreference = "Stop"

# GitHub Windows runners may default to cp1252; force UTF-8 for Python progress output.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Assert-ExitCode([string]$StepName) {
    if ($LASTEXITCODE -ne 0) {
        throw "FATAL [$StepName]: Command failed with exit code $LASTEXITCODE"
    }
}

function Assert-FileExists([string]$FilePath, [long]$MinBytes = 1024) {
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw "FATAL: Required artifact missing: $FilePath"
    }
    $sz = (Get-Item -LiteralPath $FilePath).Length
    if ($sz -lt $MinBytes) {
        throw "FATAL: Required artifact '$FilePath' is too small ($sz bytes < $MinBytes bytes)"
    }
    Write-Host "  [VERIFIED ARTIFACT] $FilePath ($sz bytes)"
}

Write-Host "========================================================================================"
Write-Host "  MERSAD PREVIEW 0.1 — Hardened Windows 10/11 x64 Execution Pipeline (Phases 1 to 5)"
Write-Host "========================================================================================"

# 0. Purge any stale build outputs before starting so old EXEs can NEVER be accepted
Write-Host "[Step 0] Purging stale build, dist, and staging directories..."
foreach ($staleDir in @(
    "MERSAD_AI_Preview_0.1\build",
    "MERSAD_AI_Preview_0.1\dist",
    "MERSAD_LAB_Preview_0.1\build",
    "MERSAD_LAB_Preview_0.1\dist",
    "windows_binaries_staging"
)) {
    if (Test-Path -LiteralPath $staleDir) {
        Remove-Item -LiteralPath $staleDir -Recurse -Force
    }
}

# Verify ISCC.exe (Inno Setup 6) upfront — missing ISCC.exe is an immediate failure
$isccCmd = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($null -ne $isccCmd) {
    $isccPath = $isccCmd.Source
} elseif (Test-Path "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") {
    $isccPath = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
} elseif (Test-Path "${env:ProgramFiles}\Inno Setup 6\ISCC.exe") {
    $isccPath = "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
} else {
    Write-Host "[Setup] ISCC.exe not found in default paths; attempting automatic install via Chocolatey/Winget..."
    $chocoCmd = Get-Command "choco.exe" -ErrorAction SilentlyContinue
    if ($null -ne $chocoCmd) {
        & $chocoCmd.Source install innosetup -y --no-progress
    }
    if (Test-Path "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") {
        $isccPath = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    } elseif (Test-Path "${env:ProgramFiles}\Inno Setup 6\ISCC.exe") {
        $isccPath = "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    } else {
        throw "FATAL: ISCC.exe (Inno Setup 6 Compiler) is not installed or not in PATH. MERSAD_LAB_Setup_x64.exe is mandatory."
    }
}
Write-Host "  [OK] Found Inno Setup Compiler: $isccPath"

if (-not (Test-Path ".venv_final\Scripts\python.exe")) {
    Write-Host "[Setup] Creating isolated Python x64 virtual environment..."
    python -m venv .venv_final
    Assert-ExitCode "python -m venv .venv_final"
}
$py = (Resolve-Path ".venv_final\Scripts\python.exe").Path
$pip = (Resolve-Path ".venv_final\Scripts\pip.exe").Path
$pyinst = Join-Path (Split-Path $py) "pyinstaller.exe"

Write-Host "[Phase 1A] Installing pinned Windows x64 dependencies..."
& $py -m pip install --upgrade pip
Assert-ExitCode "pip upgrade"
& $pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
Assert-ExitCode "pip install CPU torch==2.5.1"
& $pip install -r "MERSAD_AI_Preview_0.1\requirements.txt" -c "MERSAD_AI_Preview_0.1\constraints-win-x64.txt" pyinstaller==6.11.1
Assert-ExitCode "pip install pinned requirements"
& $pip uninstall -y opencv-python-headless
& $pip install --force-reinstall --no-deps opencv-python==4.11.0.86
Assert-ExitCode "enforce GUI opencv-python==4.11.0.86"
& $py "MERSAD_AI_Preview_0.1\check_install.py" --verify-pip-deps
Assert-ExitCode "check_install.py --verify-pip-deps"

Write-Host "[Phase 1B] Downloading 4 AI Models (YuNet, SFace, YOLOv8n, EasyOCR) & Verifying Pinned SHA-256..."
& $py "MERSAD_AI_Preview_0.1\prefetch.py"
Assert-ExitCode "prefetch.py"

& $py "MERSAD_AI_Preview_0.1\mersad_live.py" --verify-models
Assert-ExitCode "mersad_live.py --verify-models"

Write-Host "[Phase 1C] Running Real AI Model Inference on MERSAD LAB Frames (--require-real-models)..."
& $py -u "integration\evaluate_ai_models.py" --require-real-models
Assert-ExitCode "evaluate_ai_models.py --require-real-models"

Write-Host "[Phase 2] Verifying Original MERSAD LAB (Commit ed7b8f727243da4878e547f08489af581c83291c) vs Clean-Room LAB..."
# Attempt to fetch build/mersad-lab-exe-20261031 if git origin is configured and reachable; otherwise record Original LAB as BLOCKED without aborting Phase 3B
if (Test-Path ".git") {
    git fetch origin build/mersad-lab-exe-20261031:refs/remotes/origin/mersad-lab-orig 2>$null
    if ($LASTEXITCODE -eq 0) {
        $origSha = (git rev-parse refs/remotes/origin/mersad-lab-orig 2>$null).Trim().ToLower()
        if ($origSha -eq "ed7b8f727243da4878e547f08489af581c83291c") {
            Write-Host "[Phase 2] Restoring Original MERSAD LAB commit ed7b8f727243da4878e547f08489af581c83291c from git remote..."
            git archive refs/remotes/origin/mersad-lab-orig | tar -x -C "MERSAD_LAB_Original_ed7b8f72"
            Set-Content -Path "MERSAD_LAB_Original_ed7b8f72\COMMIT_SHA.txt" -Value $origSha -Encoding ASCII
        }
    }
}
& $py "tools\compare_original_vs_cleanroom_lab.py" --original-source "MERSAD_LAB_Original_ed7b8f72" --cleanroom-dir "MERSAD_LAB_Preview_0.1" --require-cleanroom-pass
Assert-ExitCode "compare_original_vs_cleanroom_lab.py --require-cleanroom-pass (Clean-Room 20/20 PASS verified; Original LAB recorded as PASS or BLOCKED)"

Write-Host "[Phase 3A] Running 232 AI Selftests (Standard + Blocked Sklearn) & 20 LAB Functional/Security Tests..."
& $py -u "MERSAD_AI_Preview_0.1\selftest.py"
Assert-ExitCode "MERSAD AI selftest.py (standard)"
$env:MERSAD_BLOCK_SKLEARN = "1"
try {
    & $py -u "MERSAD_AI_Preview_0.1\selftest.py"
    Assert-ExitCode "MERSAD AI selftest.py (MERSAD_BLOCK_SKLEARN=1)"
} finally {
    Remove-Item Env:\MERSAD_BLOCK_SKLEARN -ErrorAction SilentlyContinue
}
& $py -u "MERSAD_AI_Preview_0.1\verify_integrity.py" --check-models
Assert-ExitCode "MERSAD AI verify_integrity.py --check-models"
& $py -u "MERSAD_LAB_Preview_0.1\test_lab.py"
Assert-ExitCode "MERSAD LAB test_lab.py"

Write-Host "[Phase 3B] Building MERSAD_AI.exe, MERSAD_LAB.exe, Portable ZIPs & MERSAD_LAB_Setup_x64.exe..."
Push-Location "MERSAD_AI_Preview_0.1"
try {
    & $pyinst --noconfirm --clean mersad_ai.spec
    Assert-ExitCode "PyInstaller mersad_ai.spec"
    Copy-Item -Path "models" -Destination "dist\MERSAD_AI\models" -Recurse -Force
    Copy-Item -Path "dashboard.html","README_AR.md","SYSTEM_REQUIREMENTS.txt","verify_integrity.py" -Destination "dist\MERSAD_AI\" -Force
    Set-Content -LiteralPath "dist\MERSAD_AI\RUN.bat" -Encoding utf8 -Value "@echo off`r`nchcp 65001 >nul`r`ncd /d `"%~dp0`"`r`nMERSAD_AI.exe %*`r`npause"
    Set-Content -LiteralPath "dist\MERSAD_AI\RUN_LAN.bat" -Encoding utf8 -Value "@echo off`r`nchcp 65001 >nul`r`ncd /d `"%~dp0`"`r`necho [LAN MODE] Starting MERSAD_AI.exe on 0.0.0.0 for local Wi-Fi access...`r`nMERSAD_AI.exe --host 0.0.0.0 %*`r`npause"
    Set-Content -LiteralPath "dist\MERSAD_AI\VERIFY_AUDIT.bat" -Encoding utf8 -Value "@echo off`r`nchcp 65001 >nul`r`ncd /d `"%~dp0`"`r`nMERSAD_AI.exe --verify || (pause & exit /b 1)`r`nMERSAD_AI.exe --verify-models || (pause & exit /b 1)`r`nMERSAD_AI.exe --readiness-report || (pause & exit /b 1)`r`npause"
    New-Item -ItemType Directory -Force -Path "dist\portable" | Out-Null
    Compress-Archive -Path "dist\MERSAD_AI\*" -DestinationPath "dist\portable\MERSAD_AI_Portable_x64.zip" -Force
} finally {
    Pop-Location
}

Push-Location "MERSAD_LAB_Preview_0.1"
try {
    & $pyinst --noconfirm --clean mersad_lab.spec
    Assert-ExitCode "PyInstaller mersad_lab.spec"
    Copy-Item -Path "index.html","README_AR.md","PHASE1_STATUS_AR.md","RUN_LAB.bat" -Destination "dist\MERSAD_LAB\" -Force
    New-Item -ItemType Directory -Force -Path "dist\portable" | Out-Null
    Compress-Archive -Path "dist\MERSAD_LAB\*" -DestinationPath "dist\portable\MERSAD_LAB_Portable_x64.zip" -Force
    & $isccPath "installer\mersad_lab_setup.iss"
    Assert-ExitCode "ISCC.exe installer\mersad_lab_setup.iss"
} finally {
    Pop-Location
}

Write-Host "[Phase 3C] Verifying Physical Existence of All Mandatory Executables & Portable Packages..."
Assert-FileExists "MERSAD_AI_Preview_0.1\dist\MERSAD_AI\MERSAD_AI.exe" 1000000
Assert-FileExists "MERSAD_LAB_Preview_0.1\dist\MERSAD_LAB\MERSAD_LAB.exe" 1000000
Assert-FileExists "MERSAD_LAB_Preview_0.1\dist\installer\MERSAD_LAB_Setup_x64.exe" 500000
Assert-FileExists "MERSAD_AI_Preview_0.1\dist\portable\MERSAD_AI_Portable_x64.zip" 1000000
Assert-FileExists "MERSAD_LAB_Preview_0.1\dist\portable\MERSAD_LAB_Portable_x64.zip" 500000

Write-Host "[Phase 3D] Testing EXEs in Isolated Path with Arabic Characters & Spaces (Scrubbed PATH)..."
$arabicTestDir = Join-Path $env:TEMP "مسار اختبار مرصاد الذكي Preview 0.1"
if (Test-Path -LiteralPath $arabicTestDir) { Remove-Item -LiteralPath $arabicTestDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path "$arabicTestDir\MERSAD_AI" | Out-Null
New-Item -ItemType Directory -Force -Path "$arabicTestDir\MERSAD_LAB" | Out-Null
Copy-Item -Path "MERSAD_AI_Preview_0.1\dist\MERSAD_AI\*" -Destination "$arabicTestDir\MERSAD_AI\" -Recurse -Force
Copy-Item -Path "MERSAD_LAB_Preview_0.1\dist\MERSAD_LAB\*" -Destination "$arabicTestDir\MERSAD_LAB\" -Recurse -Force

$arabicInstallDir = Join-Path $env:TEMP "تثبيت مختبر مرصاد Preview 0.1"
if (Test-Path -LiteralPath $arabicInstallDir) { Remove-Item -LiteralPath $arabicInstallDir -Recurse -Force }

$savedPath = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
try {
    & "$arabicTestDir\MERSAD_AI\MERSAD_AI.exe" --verify-models
    Assert-ExitCode "MERSAD_AI.exe --verify-models in Arabic path"
    & "$arabicTestDir\MERSAD_AI\MERSAD_AI.exe" --verify
    Assert-ExitCode "MERSAD_AI.exe --verify in Arabic path"
    & "$arabicTestDir\MERSAD_LAB\MERSAD_LAB.exe" --port 0 --self-check
    Assert-ExitCode "MERSAD_LAB.exe --self-check in Arabic path"

    Write-Host "[Phase 3E] Testing Silent Install, Installed EXE Execution, and Silent Uninstall..."
    $setupExe = (Resolve-Path "MERSAD_LAB_Preview_0.1\dist\installer\MERSAD_LAB_Setup_x64.exe").Path
    $instProc = Start-Process -FilePath $setupExe -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$arabicInstallDir`"") -Wait -PassThru
    if ($instProc.ExitCode -ne 0) {
        throw "FATAL: MERSAD_LAB_Setup_x64.exe silent install failed with exit code $($instProc.ExitCode)"
    }
    Assert-FileExists "$arabicInstallDir\MERSAD_LAB.exe" 1000000

    & "$arabicInstallDir\MERSAD_LAB.exe" --port 0 --self-check
    Assert-ExitCode "Installed MERSAD_LAB.exe --self-check"

    Assert-FileExists "$arabicInstallDir\unins000.exe" 50000
    $uninstProc = Start-Process -FilePath "$arabicInstallDir\unins000.exe" -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait -PassThru
    if ($uninstProc.ExitCode -ne 0) {
        throw "FATAL: unins000.exe silent uninstall failed with exit code $($uninstProc.ExitCode)"
    }
    Start-Sleep -Seconds 2
    if (Test-Path -LiteralPath "$arabicInstallDir\MERSAD_LAB.exe") {
        throw "FATAL: Installed MERSAD_LAB.exe was not removed after uninstallation!"
    }
    Write-Host "  [OK] Installer install -> run -> uninstall lifecycle verified in Arabic path with spaces."
} finally {
    $env:PATH = $savedPath
}

Write-Host "[Phase 4] Running Final Unmocked End-to-End Integration (Real YOLOv8n + Real EasyOCR)..."
& $py -u "integration\test_ai_lab_integration.py" --require-real-models
Assert-ExitCode "test_ai_lab_integration.py --require-real-models"

Write-Host "[Phase 5] Staging Final Binaries & Computing SHA-256..."
New-Item -ItemType Directory -Force -Path "windows_binaries_staging\MERSAD_AI" | Out-Null
New-Item -ItemType Directory -Force -Path "windows_binaries_staging\MERSAD_LAB" | Out-Null
Copy-Item -Path "MERSAD_AI_Preview_0.1\dist\MERSAD_AI\*" -Destination "windows_binaries_staging\MERSAD_AI\" -Recurse -Force
Copy-Item -Path "MERSAD_LAB_Preview_0.1\dist\MERSAD_LAB\*" -Destination "windows_binaries_staging\MERSAD_LAB\" -Recurse -Force
Copy-Item -Path "MERSAD_AI_Preview_0.1\dist\portable\MERSAD_AI_Portable_x64.zip" -Destination "windows_binaries_staging\MERSAD_AI_Portable_x64.zip" -Force
Copy-Item -Path "MERSAD_LAB_Preview_0.1\dist\portable\MERSAD_LAB_Portable_x64.zip" -Destination "windows_binaries_staging\MERSAD_LAB_Portable_x64.zip" -Force
Copy-Item -Path "MERSAD_LAB_Preview_0.1\dist\installer\MERSAD_LAB_Setup_x64.exe" -Destination "windows_binaries_staging\MERSAD_LAB_Setup_x64.exe" -Force

Assert-FileExists "windows_binaries_staging\MERSAD_AI\MERSAD_AI.exe" 1000000
Assert-FileExists "windows_binaries_staging\MERSAD_LAB\MERSAD_LAB.exe" 1000000
Assert-FileExists "windows_binaries_staging\MERSAD_LAB_Setup_x64.exe" 500000
Assert-FileExists "windows_binaries_staging\MERSAD_AI_Portable_x64.zip" 1000000
Assert-FileExists "windows_binaries_staging\MERSAD_LAB_Portable_x64.zip" 500000

Get-ChildItem -Path "windows_binaries_staging" -Recurse -File | ForEach-Object {
    $h = (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash.ToLower()
    $rel = $_.FullName.Substring((Resolve-Path "windows_binaries_staging").Path.Length + 1)
    "$h  $rel"
} | Set-Content -Path "windows_binaries_staging\SHA256SUMS_WINDOWS_EXE.txt" -Encoding UTF8

Write-Host "========================================================================================"
Write-Host "  ALL 5 PHASES COMPLETED AND VERIFIED SUCCESSFULLY ON WINDOWS x64!"
Write-Host "========================================================================================"
