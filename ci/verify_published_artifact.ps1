param(
  [Parameter(Mandatory = $true)]
  [string]$ArtifactRoot
)

$ErrorActionPreference = "Stop"
$root = $ArtifactRoot
$manifest = Join-Path $root "SHA256SUMS_WINDOWS_FINAL.txt"
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
  throw "Published artifact is missing SHA256SUMS_WINDOWS_FINAL.txt"
}

$rootFull = [IO.Path]::GetFullPath($root).TrimEnd('\') + '\'
$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$manifestLines = @(Get-Content -LiteralPath $manifest | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
if ($manifestLines.Count -lt 100) {
  throw "Published SHA-256 manifest is unexpectedly small: $($manifestLines.Count) entries"
}

foreach ($line in $manifestLines) {
  $manifestMatch = [regex]::Match($line, '^([A-Fa-f0-9]{64})\s{2}(.+)')
  if (-not $manifestMatch.Success -or $manifestMatch.Length -ne $line.Length) {
    throw "Malformed SHA-256 manifest row: $line"
  }
  $expected = $manifestMatch.Groups[1].Value.ToLowerInvariant()
  $relative = $manifestMatch.Groups[2].Value.Trim().Replace('\', '/')
  if (-not $seen.Add($relative)) {
    throw "Duplicate path in SHA-256 manifest: $relative"
  }
  $relativeForJoin = $relative.Replace('/', '\')
  $fullPath = [IO.Path]::GetFullPath((Join-Path $root $relativeForJoin))
  if (-not $fullPath.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Path traversal detected in SHA-256 manifest: $relative"
  }
  if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
    throw "Published artifact is missing a manifest-listed file: $relative"
  }
  $actual = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $expected) {
    throw "SHA-256 mismatch for published file: $relative"
  }
}

$actualFiles = @(Get-ChildItem -LiteralPath $root -Recurse -Force -File | Where-Object {
  -not [string]::Equals($_.FullName, $manifest, [StringComparison]::OrdinalIgnoreCase)
})
foreach ($file in $actualFiles) {
  $relative = [IO.Path]::GetRelativePath($rootFull.TrimEnd('\'), $file.FullName).Replace('\', '/')
  if (-not $seen.Contains($relative)) {
    throw "Unmanifested file found in published artifact: $relative"
  }
}
if ($actualFiles.Count -ne $seen.Count) {
  throw "Manifest/file-count mismatch: manifest=$($seen.Count), extracted=$($actualFiles.Count)"
}
Write-Host "[ARTIFACT] SHA-256 verified for $($seen.Count) files; no missing, changed, or unmanifested files."

$allFiles = @(Get-ChildItem -LiteralPath $root -Recurse -Force -File)
$trustedModels = @($allFiles | Where-Object { $_.Name -eq ".trusted_models.json" })
$sklearnDlls = @($allFiles | Where-Object {
  ($_.Name -eq "msvcp140.dll" -or $_.Name -eq "vcomp140.dll") -and
  $_.FullName -match '[\\/]+sklearn[\\/]+\.libs[\\/]+'
})
if ($trustedModels.Count -lt 1) {
  throw "The hidden trusted-model metadata file .trusted_models.json is absent from the published artifact"
}
foreach ($dllName in @("msvcp140.dll", "vcomp140.dll")) {
  if (@($sklearnDlls | Where-Object { $_.Name -eq $dllName }).Count -lt 1) {
    throw "The sklearn runtime DLL is missing from sklearn\.libs: $dllName"
  }
}
Write-Host "[ARTIFACT] Found .trusted_models.json and both sklearn\.libs runtime DLLs."

$aiExe = Join-Path $root "MERSAD_AI\MERSAD_AI.exe"
$desktopExe = Join-Path $root "MERSAD_AI\MERSAD_Desktop.exe"
$labExe = Join-Path $root "MERSAD_LAB\MERSAD_LAB.exe"
$installer = Join-Path $root "Installers_and_Portable\MERSAD_LAB_Setup_x64.exe"
$aiPortableZip = Join-Path $root "Installers_and_Portable\MERSAD_AI_Portable_x64.zip"
$labPortableZip = Join-Path $root "Installers_and_Portable\MERSAD_LAB_Portable_x64.zip"
foreach ($required in @($aiExe, $desktopExe, $labExe, $installer, $aiPortableZip, $labPortableZip)) {
  if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
    throw "Required published release component is missing: $required"
  }
}

& $desktopExe --self-test
if ($LASTEXITCODE -ne 0) { throw "Published MERSAD_Desktop.exe --self-test failed ($LASTEXITCODE)" }
& $aiExe --verify-models
if ($LASTEXITCODE -ne 0) { throw "Published MERSAD_AI.exe --verify-models failed ($LASTEXITCODE)" }
& $aiExe --verify
if ($LASTEXITCODE -ne 0) { throw "Published MERSAD_AI.exe --verify failed ($LASTEXITCODE)" }
& $labExe --port 0 --self-check
if ($LASTEXITCODE -ne 0) { throw "Published MERSAD_LAB.exe --self-check failed ($LASTEXITCODE)" }

$portableRoot = Join-Path $env:RUNNER_TEMP "mersad-published-portable-check"
$aiPortable = Join-Path $portableRoot "MERSAD_AI"
$labPortable = Join-Path $portableRoot "MERSAD_LAB"
New-Item -ItemType Directory -Force -Path $aiPortable, $labPortable | Out-Null
Expand-Archive -LiteralPath $aiPortableZip -DestinationPath $aiPortable -Force
Expand-Archive -LiteralPath $labPortableZip -DestinationPath $labPortable -Force
$portableAiExe = Join-Path $aiPortable "MERSAD_AI.exe"
$portableLabExe = Join-Path $labPortable "MERSAD_LAB.exe"
if (-not (Test-Path -LiteralPath $portableAiExe -PathType Leaf)) { throw "AI Portable ZIP does not contain MERSAD_AI.exe at its root" }
if (-not (Test-Path -LiteralPath $portableLabExe -PathType Leaf)) { throw "LAB Portable ZIP does not contain MERSAD_LAB.exe at its root" }
& $portableAiExe --verify-models
if ($LASTEXITCODE -ne 0) { throw "Published AI Portable --verify-models failed ($LASTEXITCODE)" }
& $portableAiExe --verify
if ($LASTEXITCODE -ne 0) { throw "Published AI Portable --verify failed ($LASTEXITCODE)" }
& $portableLabExe --port 0 --self-check
if ($LASTEXITCODE -ne 0) { throw "Published LAB Portable --self-check failed ($LASTEXITCODE)" }

$installDir = Join-Path $env:RUNNER_TEMP "تثبيت حزمة مرصاد المنشورة 0.1"
$installArg = '/DIR="' + $installDir + '"'
$installProcess = Start-Process -FilePath $installer -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", $installArg) -Wait -PassThru
if ($installProcess.ExitCode -ne 0) { throw "Published LAB installer failed ($($installProcess.ExitCode))" }
$installedLab = Join-Path $installDir "MERSAD_LAB.exe"
$uninstaller = Join-Path $installDir "unins000.exe"
if (-not (Test-Path -LiteralPath $installedLab -PathType Leaf)) { throw "Published installer did not install MERSAD_LAB.exe" }
if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) { throw "Published installer did not create unins000.exe" }
& $installedLab --port 0 --self-check
if ($LASTEXITCODE -ne 0) { throw "Installed published LAB --self-check failed ($LASTEXITCODE)" }
$uninstallProcess = Start-Process -FilePath $uninstaller -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait -PassThru
if ($uninstallProcess.ExitCode -ne 0) { throw "Published LAB uninstall failed ($($uninstallProcess.ExitCode))" }
if (Test-Path -LiteralPath $installedLab) { throw "Published LAB uninstall left MERSAD_LAB.exe behind" }

Write-Host "[ACCEPTANCE] Downloaded artifact hashes, hidden files, AI/LAB binaries, both Portable ZIPs, and installer install/run/uninstall all passed."
