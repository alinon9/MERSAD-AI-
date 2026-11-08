$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location ..

Write-Host "[0/4] Purging stale build and dist directories..."
foreach ($stale in @("build", "dist")) {
    if (Test-Path -LiteralPath $stale) {
        Remove-Item -LiteralPath $stale -Recurse -Force
    }
}

$iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($null -ne $iscc) {
    $isccPath = $iscc.Source
} elseif (Test-Path "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") {
    $isccPath = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
} elseif (Test-Path "${env:ProgramFiles}\Inno Setup 6\ISCC.exe") {
    $isccPath = "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
} else {
    throw "FATAL: ISCC.exe (Inno Setup 6) is required to build MERSAD_LAB_Setup_x64.exe."
}

Write-Host "[1/4] Running BUILD_LAB_EXE.bat..."
cmd /c BUILD_LAB_EXE.bat
if ($LASTEXITCODE -ne 0) { throw "BUILD_LAB_EXE.bat failed with exit code $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath "dist\MERSAD_LAB\MERSAD_LAB.exe" -PathType Leaf)) {
    throw "FATAL: dist\MERSAD_LAB\MERSAD_LAB.exe was not produced!"
}

Write-Host "[2/4] Creating Portable ZIP archive (MERSAD_LAB_Portable_x64.zip)..."
New-Item -ItemType Directory -Force -Path "dist\portable" | Out-Null
Copy-Item -Path "RUN_LAB.bat","README_AR.md","PHASE1_STATUS_AR.md" -Destination "dist\MERSAD_LAB\" -Force
Compress-Archive -Path "dist\MERSAD_LAB\*" -DestinationPath "dist\portable\MERSAD_LAB_Portable_x64.zip" -Force
if (-not (Test-Path -LiteralPath "dist\portable\MERSAD_LAB_Portable_x64.zip" -PathType Leaf)) {
    throw "FATAL: dist\portable\MERSAD_LAB_Portable_x64.zip was not produced!"
}

Write-Host "[3/4] Building Windows Installer (MERSAD_LAB_Setup_x64.exe) via Inno Setup..."
& $isccPath "installer\mersad_lab_setup.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC.exe failed with exit code $LASTEXITCODE" }
if (-not (Test-Path -LiteralPath "dist\installer\MERSAD_LAB_Setup_x64.exe" -PathType Leaf)) {
    throw "FATAL: dist\installer\MERSAD_LAB_Setup_x64.exe was not produced!"
}

Write-Host "[4/4] Verifying Silent Install -> Run -> Uninstall in Arabic path with spaces..."
$testInstDir = Join-Path $env:TEMP "اختبار مثبت مختبر مرصاد Preview 0.1"
if (Test-Path -LiteralPath $testInstDir) { Remove-Item -LiteralPath $testInstDir -Recurse -Force }
$setupFile = (Resolve-Path "dist\installer\MERSAD_LAB_Setup_x64.exe").Path
$p1 = Start-Process -FilePath $setupFile -ArgumentList @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/DIR=`"$testInstDir`"") -Wait -PassThru
if ($p1.ExitCode -ne 0) { throw "Silent install failed ($($p1.ExitCode))" }
if (-not (Test-Path -LiteralPath "$testInstDir\MERSAD_LAB.exe")) { throw "Installed MERSAD_LAB.exe not found" }
& "$testInstDir\MERSAD_LAB.exe" --port 0 --self-check
if ($LASTEXITCODE -ne 0) { throw "Installed MERSAD_LAB.exe --self-check failed ($LASTEXITCODE)" }
$p2 = Start-Process -FilePath "$testInstDir\unins000.exe" -ArgumentList @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART") -Wait -PassThru
if ($p2.ExitCode -ne 0) { throw "Silent uninstall failed ($($p2.ExitCode))" }
Start-Sleep -Seconds 2
if (Test-Path -LiteralPath "$testInstDir\MERSAD_LAB.exe") { throw "MERSAD_LAB.exe remained after uninstall!" }
Write-Host "Installer built and verified at dist\installer\MERSAD_LAB_Setup_x64.exe"
