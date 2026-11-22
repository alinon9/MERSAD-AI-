param(
    [Parameter(Mandatory = $true)][string]$OldArtifactRoot,
    [Parameter(Mandatory = $true)][string]$NewArtifactRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][string]$ApplyScriptPath
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
    source_run = 45037843471
    target_run = 45066828588
    target_commit = "f26379bf18cd49005d85ca0a0279a85b51345291"
    files = @($changed)
    deleted = @($deleted)
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $patchRoot "PATCH_MANIFEST.json") -Encoding utf8
Copy-Item -LiteralPath $ApplyScriptPath -Destination (Join-Path $patchRoot "APPLY_MERSAD_AI_PATCH.ps1") -Force
$readme = @'
MERSAD AI — SciPy Runtime Hotfix
================================
This delta patch updates changed files under MERSAD_AI only. MERSAD LAB and user data are not replaced.

1. Fully extract your original full ZIP to a permanent folder, e.g. C:\MERSAD_PREVIEW_0.1.
2. Confirm MERSAD_AI\MERSAD_AI.exe exists in that folder.
3. Close MERSAD AI.
4. Extract ALL contents of this patch ZIP into the same folder that contains MERSAD_AI.
5. Run APPLY_MERSAD_AI_PATCH.ps1 from PowerShell.

The patch verifies every included file SHA-256 before copying, backs up replaced files under:
%LOCALAPPDATA%\MERSAD_AI\PatchBackups

It then runs --verify-runtime-deps, --verify-models and --verify.
If a check fails, the script attempts to roll back replaced files.
Do not run the program from WinRAR or a temporary Rar$ folder.
'@
Set-Content -LiteralPath (Join-Path $patchRoot "README_AR.txt") -Value $readme -Encoding utf8

$patchFilesBytes = (Get-ChildItem -LiteralPath $patchRoot -Recurse -File | Measure-Object -Property Length -Sum).Sum
$oldBytes = ($oldFiles | Measure-Object -Property Length -Sum).Sum
$newBytes = ($newFiles | Measure-Object -Property Length -Sum).Sum
Write-Host "[DELTA] Old AI files: $($oldFiles.Count); new AI files: $($newFiles.Count)"
Write-Host "[DELTA] Changed/copied files: $($changed.Count); deleted files: $($deleted.Count)"
Write-Host ("[DELTA] Patch content size: {0:N2} MB" -f ($patchFilesBytes / 1MB))
Write-Host ("[DELTA] Old AI folder size: {0:N2} MB; new AI folder size: {1:N2} MB" -f ($oldBytes / 1MB), ($newBytes / 1MB))
