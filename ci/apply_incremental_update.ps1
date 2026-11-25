param([Parameter(Mandatory=$true)][string]$InstallDir)
$ErrorActionPreference = "Stop"
$InstallDir = (Resolve-Path -LiteralPath $InstallDir).Path
if (-not (Test-Path -LiteralPath (Join-Path $InstallDir "MERSAD_AI.exe") -PathType Leaf)) { throw "MERSAD_AI.exe not found in InstallDir." }
$files = @("MERSAD_AI.exe","MERSAD_Desktop.exe","dashboard.html","camera-connect.js","purify.min.js","dompurify-guard.js","LICENSE_DOMPURIFY.txt","RUN.bat","RUN_BACKEND.bat")
$manifest = Join-Path $PSScriptRoot "SHA256SUMS_UPDATE.txt"
foreach ($line in Get-Content -LiteralPath $manifest) {
  if ($line -notmatch '^([0-9a-fA-F]{64})\s+(.+)$') { throw "Invalid manifest row: $line" }
  $expected=$Matches[1].ToLowerInvariant(); $name=$Matches[2].Trim()
  if ($name -notin $files) { throw "Unexpected update file: $name" }
  $actual=(Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name) -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $expected) { throw "SHA-256 mismatch: $name" }
}
foreach ($name in $files) { if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $name) -PathType Leaf)) { throw "Missing payload: $name" } }
$backup=Join-Path $InstallDir ("_backup_before_update_"+(Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($name in $files) { $p=Join-Path $InstallDir $name; if (Test-Path -LiteralPath $p) { Copy-Item -LiteralPath $p -Destination (Join-Path $backup $name) -Force } }
try {
  foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $InstallDir $name) -Force }
  Write-Host "Update applied. Backup saved at: $backup" -ForegroundColor Green
} catch {
  foreach ($name in $files) { $saved=Join-Path $backup $name; if (Test-Path -LiteralPath $saved) { Copy-Item -LiteralPath $saved -Destination (Join-Path $InstallDir $name) -Force } }
  throw
}
