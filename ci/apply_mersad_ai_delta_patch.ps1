$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$patchRoot = $PSScriptRoot
$aiRoot = Join-Path $patchRoot "MERSAD_AI"
$patchFilesRoot = Join-Path $patchRoot "PATCH_FILES\MERSAD_AI"
$manifestPath = Join-Path $patchRoot "PATCH_MANIFEST.json"

if (-not (Test-Path -LiteralPath (Join-Path $aiRoot "MERSAD_AI.exe") -PathType Leaf)) {
    throw "Could not find the existing MERSAD_AI folder beside this patch script. Extract the patch into the folder that contains the old MERSAD_AI folder."
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "PATCH_MANIFEST.json is missing." }
if (-not (Test-Path -LiteralPath $patchFilesRoot -PathType Container)) { throw "PATCH_FILES\MERSAD_AI is missing." }
if (Get-Process -Name "MERSAD_AI" -ErrorAction SilentlyContinue) {
    throw "MERSAD_AI is still running. Close its console and dashboard, then run the patch again."
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema -ne "mersad_ai_delta_patch_v1") { throw "Unsupported patch manifest schema." }
$aiRootFull = [IO.Path]::GetFullPath($aiRoot).TrimEnd('\') + '\'
$patchRootFull = [IO.Path]::GetFullPath($patchFilesRoot).TrimEnd('\') + '\'
$backupBase = $env:LOCALAPPDATA
if ([string]::IsNullOrWhiteSpace($backupBase)) { $backupBase = $env:TEMP }
$backupRoot = Join-Path $backupBase ("MERSAD_AI\PatchBackups\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

$rollback = [Collections.Generic.List[object]]::new()
try {
    foreach ($item in @($manifest.files)) {
        $rel = [string]$item.path
        if ([string]::IsNullOrWhiteSpace($rel) -or [IO.Path]::IsPathRooted($rel) -or $rel -match '(^|[\\/])\.\.([\\/]|$)') {
            throw "Unsafe path in patch manifest: $rel"
        }
        $src = [IO.Path]::GetFullPath((Join-Path $patchFilesRoot ($rel.Replace('/', '\'))))
        $dst = [IO.Path]::GetFullPath((Join-Path $aiRoot ($rel.Replace('/', '\'))))
        if (-not $src.StartsWith($patchRootFull, [StringComparison]::OrdinalIgnoreCase)) { throw "Patch source escapes PATCH_FILES: $rel" }
        if (-not $dst.StartsWith($aiRootFull, [StringComparison]::OrdinalIgnoreCase)) { throw "Destination escapes MERSAD_AI: $rel" }
        if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { throw "Patch file is missing: $rel" }
        $actualHash = (Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne ([string]$item.sha256).ToLowerInvariant()) { throw "Patch SHA-256 mismatch: $rel" }
    }

    foreach ($item in @($manifest.files)) {
        $rel = [string]$item.path
        $src = Join-Path $patchFilesRoot ($rel.Replace('/', '\'))
        $dst = Join-Path $aiRoot ($rel.Replace('/', '\'))
        $existed = Test-Path -LiteralPath $dst -PathType Leaf
        $backup = $null
        if ($existed) {
            $backup = Join-Path $backupRoot ($rel.Replace('/', '\'))
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
            Copy-Item -LiteralPath $dst -Destination $backup -Force
        }
        $rollback.Add([pscustomobject]@{ Destination = $dst; Backup = $backup; Existed = $existed })
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }

    foreach ($relValue in @($manifest.deleted)) {
        $rel = [string]$relValue
        if ([string]::IsNullOrWhiteSpace($rel) -or [IO.Path]::IsPathRooted($rel) -or $rel -match '(^|[\\/])\.\.([\\/]|$)') {
            throw "Unsafe delete path in patch manifest: $rel"
        }
        $dst = [IO.Path]::GetFullPath((Join-Path $aiRoot ($rel.Replace('/', '\'))))
        if (-not $dst.StartsWith($aiRootFull, [StringComparison]::OrdinalIgnoreCase)) { throw "Delete path escapes MERSAD_AI: $rel" }
        if (Test-Path -LiteralPath $dst -PathType Leaf) {
            $backup = Join-Path $backupRoot ($rel.Replace('/', '\'))
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
            Copy-Item -LiteralPath $dst -Destination $backup -Force
            $rollback.Add([pscustomobject]@{ Destination = $dst; Backup = $backup; Existed = $true })
            Remove-Item -LiteralPath $dst -Force
        }
    }

    # --verify-models regenerates the trusted-model manifest during its self-check.
    # Preserve its pre-verification state so a later failure can restore it as well.
    $trustedModelsPath = Join-Path $aiRoot "models\.trusted_models.json"
    if (Test-Path -LiteralPath $trustedModelsPath -PathType Leaf) {
        $trustedModelsBackup = Join-Path $backupRoot "_preverification\models\.trusted_models.json"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $trustedModelsBackup) | Out-Null
        Copy-Item -LiteralPath $trustedModelsPath -Destination $trustedModelsBackup -Force
        $rollback.Add([pscustomobject]@{
            Destination = $trustedModelsPath
            Backup = $trustedModelsBackup
            Existed = $true
        })
    }

    Push-Location $aiRoot
    try {
        & (Join-Path $aiRoot "MERSAD_AI.exe") --verify-runtime-deps
        if ($LASTEXITCODE -ne 0) { throw "SciPy/scikit-learn runtime verification failed ($LASTEXITCODE)" }
        & (Join-Path $aiRoot "MERSAD_AI.exe") --verify-models
        if ($LASTEXITCODE -ne 0) { throw "Bundled model verification failed ($LASTEXITCODE)" }
        & (Join-Path $aiRoot "MERSAD_AI.exe") --verify
        if ($LASTEXITCODE -ne 0) { throw "Audit database verification failed ($LASTEXITCODE)" }
    } finally { Pop-Location }

    Write-Host "[PATCH] MERSAD AI patch installed and all runtime checks passed."
    Write-Host "[PATCH] Replaced files backed up at: $backupRoot"
}
catch {
    Write-Error $_
    for ($i = $rollback.Count - 1; $i -ge 0; $i--) {
        $entry = $rollback[$i]
        try {
            if ($entry.Existed -and $entry.Backup -and (Test-Path -LiteralPath $entry.Backup -PathType Leaf)) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $entry.Destination) | Out-Null
                Copy-Item -LiteralPath $entry.Backup -Destination $entry.Destination -Force
            } elseif (-not $entry.Existed -and (Test-Path -LiteralPath $entry.Destination -PathType Leaf)) {
                Remove-Item -LiteralPath $entry.Destination -Force
            }
        } catch { Write-Warning "Rollback could not restore $($entry.Destination): $_" }
    }
    throw "Patch failed; rollback was attempted. Backup folder: $backupRoot"
}
