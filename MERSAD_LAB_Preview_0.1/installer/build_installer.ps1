$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location ..

Write-Host "[1/3] Running BUILD_LAB_EXE.bat..."
cmd /c BUILD_LAB_EXE.bat
if ($LASTEXITCODE -ne 0) { throw "BUILD_LAB_EXE.bat failed" }

Write-Host "[2/3] Creating Portable ZIP archive..."
New-Item -ItemType Directory -Force -Path "dist\portable" | Out-Null
Copy-Item -Path "RUN_LAB.bat","README_AR.md","PHASE1_STATUS_AR.md" -Destination "dist\MERSAD_LAB\" -Force
Compress-Archive -Path "dist\MERSAD_LAB\*" -DestinationPath "dist\portable\MERSAD_LAB_Preview_0.1_Portable_x64.zip" -Force

Write-Host "[3/3] Building Windows Installer via Inno Setup (ISCC.exe) if available..."
$iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($null -ne $iscc) {
    & $iscc.Source "installer\mersad_lab_setup.iss"
    Write-Host "Installer built in dist\installer\MERSAD_LAB_Preview_0.1_Setup_x64.exe"
} else {
    Write-Host "ISCC.exe not in PATH; Portable ZIP created at dist\portable\MERSAD_LAB_Preview_0.1_Portable_x64.zip"
}
