param(
    [Parameter(Mandatory = $true)][string]$OldArtifactRoot,
    [Parameter(Mandatory = $true)][string]$NewArtifactRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][string]$ApplyScriptPath,
    [long]$SourceRunId = 45066828588,
    [long]$TargetRunId = 0,
    [string]$TargetCommit = ""
)
$ErrorActionPreference = "Stop"
$oldAi = Join-Path $OldArtifactRoot "MERSAD_AI"
$newAi = Join-Path $NewArtifactRoot "MERSAD_AI"
if (-not (Test-Path -LiteralPath (Join-Path $oldAi "MERSAD_AI.exe") -PathType Leaf)) { throw "Old artifact does not contain MERSAD_AI.exe" }
if (-not (Test-Path -LiteralPath (Join-Path $newAi "MERSAD_AI.exe") -PathType Leaf)) { throw "New artifact does not contain MERSAD_AI.exe" }

if (Test-Path -LiteralPath $OutputRoot) { Remove-Item -LiteralPath $OutputRoot -Recurse -Force }
$patchRoot = Join-Path $OutputRoot "MERSAD_AI_PATCH"
$patchFiles = Join-Path $patchRoot "PATCH_FILES\MERSAD_AI"
New-Item -ItemType Directory -Force -Path $patchFiles | Out-Null

$changed = [Collections.Generic.List[object]]::new()
$newFiles = @(Get-ChildItem -LiteralPath $newAi -Recurse -Force -File)
$oldFiles = @(Get-ChildItem -LiteralPath $oldAi -Recurse -Force -File)
foreach ($newFile in $newFiles) {
    $rel = [IO.Path]::GetRelativePath($newAi, $newFile.FullName).Replace('\', '/')
    $oldPath = Join-Path $oldAi ($rel.Replace('/', '\'))
    $copyIt = -not (Test-Path -LiteralPath $oldPath -PathType Leaf)
    if (-not $copyIt) {
        $newHash = (Get-FileHash -LiteralPath $newFile.FullName -Algorithm SHA256).Hash
        $oldHash = (Get-FileHash -LiteralPath $oldPath -Algorithm SHA256).Hash
        $copyIt = $newHash -ne $oldHash
    }
    if ($copyIt) {
        $target = Join-Path $patchFiles ($rel.Replace('/', '\'))
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $newFile.FullName -Destination $target -Force
        $digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
        $changed.Add([pscustomobject]@{ path = $rel; sha256 = $digest })
    }
}
$deleted = [Collections.Generic.List[string]]::new()
foreach ($oldFile in $oldFiles) {
    $rel = [IO.Path]::GetRelativePath($oldAi, $oldFile.FullName).Replace('\', '/')
    if (-not (Test-Path -LiteralPath (Join-Path $newAi ($rel.Replace('/', '\'))) -PathType Leaf)) { $deleted.Add($rel) }
}
if ($changed.Count -eq 0 -and $deleted.Count -eq 0) { throw "No AI files differ between old and fixed artifacts; refusing to publish an empty patch." }

$manifest = [ordered]@{
    schema = "mersad_ai_delta_patch_v1"
    source_run = $SourceRunId
    target_run = $TargetRunId
    target_commit = $TargetCommit
    files = @($changed)
    deleted = @($deleted)
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $patchRoot "PATCH_MANIFEST.json") -Encoding utf8
Copy-Item -LiteralPath $ApplyScriptPath -Destination (Join-Path $patchRoot "APPLY_MERSAD_AI_PATCH.ps1") -Force
$readme = @'
مرصاد AI — تحديث صغير للبرنامج
================================
هذه الرقعة تحدّث ملفات MERSAD_AI فقط. لا تستبدل MERSAD_LAB ولا قاعدة بياناتك ولا ملفات الأدلة.

1. أغلق مرصاد AI بالكامل.
2. فك ضغط محتويات هذه الرقعة داخل المجلد الذي يحتوي مجلد MERSAD_AI.
3. انقر مرتين على APPLY_MERSAD_AI_PATCH.bat.
4. انتظر حتى تظهر رسالة نجاح الفحوصات.

قبل الاستبدال، يتحقق المثبّت من SHA-256 لكل ملف، ويحفظ نسخة احتياطية من الملفات المستبدلة داخل:
%LOCALAPPDATA%\MERSAD_AI\PatchBackups

ثم ينفذ فحوصات المكتبات والنماذج وسلسلة التدقيق. إذا فشل أي فحص، يحاول استعادة الملفات السابقة تلقائياً.
لا تشغّل البرنامج من داخل WinRAR أو مجلد مؤقت.
'@
Set-Content -LiteralPath (Join-Path $patchRoot "README_AR.txt") -Value $readme -Encoding utf8

$launcher = @'
@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0APPLY_MERSAD_AI_PATCH.ps1"
if errorlevel 1 (
  echo.
  echo Patch failed. See the message above.
  pause
  exit /b 1
)
echo.
echo MERSAD AI update completed successfully.
pause
'@
Set-Content -LiteralPath (Join-Path $patchRoot "APPLY_MERSAD_AI_PATCH.bat") -Value $launcher -Encoding ASCII

$patchFilesBytes = (Get-ChildItem -LiteralPath $patchRoot -Recurse -File | Measure-Object -Property Length -Sum).Sum
$oldBytes = ($oldFiles | Measure-Object -Property Length -Sum).Sum
$newBytes = ($newFiles | Measure-Object -Property Length -Sum).Sum
Write-Host "[DELTA] Old AI files: $($oldFiles.Count); new AI files: $($newFiles.Count)"
Write-Host "[DELTA] Changed/copied files: $($changed.Count); deleted files: $($deleted.Count)"
Write-Host ("[DELTA] Patch content size: {0:N2} MB" -f ($patchFilesBytes / 1MB))
Write-Host ("[DELTA] Old AI folder size: {0:N2} MB; new AI folder size: {1:N2} MB" -f ($oldBytes / 1MB), ($newBytes / 1MB))
