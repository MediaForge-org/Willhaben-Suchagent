# Builds a reproducible Windows x86_64 release package.
#
# Must run ON Windows - the PyInstaller runtime bundle is not cross-compiled.
# For a Linux package, run deployment/build-release-linux.sh on Linux.
#
# Does NOT run the test suite and does NOT touch git. Safe to re-run.

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$VersionMatch = Select-String -Path "agent/app/_version.py" -Pattern '__version__ = "([^"]+)"'
$Version = $VersionMatch.Matches[0].Groups[1].Value
$PackageName = "Willhaben-Suchagent-$Version-windows-x86_64"
$OutputDir = Join-Path $RepoRoot "dist-release"
$StageDir = Join-Path $OutputDir $PackageName

Write-Host "Building release $Version for windows-x86_64"
Write-Host ""

Write-Host "== 1/6: Building the Firefox extension =="
Push-Location "extension"
npm ci
npm run build
Pop-Location

Write-Host ""
Write-Host "== 2/6: Packaging extension/dist as an .xpi =="
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$XpiPath = Join-Path $OutputDir "willhaben-suchagent-$Version-firefox.xpi"
if (Test-Path $XpiPath) { Remove-Item $XpiPath }
Compress-Archive -Path "extension/dist/*" -DestinationPath $XpiPath

Write-Host ""
Write-Host "== 3/6: Building the Python runtime with PyInstaller =="
$BuildVenv = Join-Path $RepoRoot ".build-venv"
if (-not (Test-Path $BuildVenv)) {
    py -3 -m venv $BuildVenv
}
& "$BuildVenv\Scripts\pip.exe" install --quiet --upgrade pip
& "$BuildVenv\Scripts\pip.exe" install --quiet -e "$RepoRoot[build]"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "deployment/pyinstaller/build", "deployment/pyinstaller/dist"
Push-Location "deployment/pyinstaller"
& "$BuildVenv\Scripts\pyinstaller.exe" --noconfirm --clean willhaben-suchagent.spec
Pop-Location

Write-Host ""
Write-Host "== 4/6: Assembling the release folder =="
if (Test-Path $StageDir) { Remove-Item -Recurse -Force $StageDir }
New-Item -ItemType Directory -Force -Path (Join-Path $StageDir "extension") | Out-Null
Copy-Item -Recurse "deployment/pyinstaller/dist/runtime" (Join-Path $StageDir "runtime")
Copy-Item "deployment/release-templates/windows/Einrichtung.bat" (Join-Path $StageDir "Einrichtung.bat")
Copy-Item "deployment/release-templates/windows/Willhaben-Suchagent starten.bat" (Join-Path $StageDir "Willhaben-Suchagent starten.bat")
Copy-Item $XpiPath (Join-Path $StageDir "extension/willhaben-suchagent.xpi")
Copy-Item "USER_GUIDE.md" (Join-Path $StageDir "USER_GUIDE.md")
Copy-Item "CHANGELOG.md" (Join-Path $StageDir "CHANGELOG.md")

Write-Host ""
Write-Host "== 5/6: Creating the release archive =="
$ArchivePath = Join-Path $OutputDir "$PackageName.zip"
if (Test-Path $ArchivePath) { Remove-Item $ArchivePath }
Compress-Archive -Path $StageDir -DestinationPath $ArchivePath

Write-Host ""
Write-Host "== 6/6: Writing checksums =="
$Sha256File = Join-Path $OutputDir "SHA256SUMS.windows"
$Lines = @()
$Lines += "$((Get-FileHash $ArchivePath -Algorithm SHA256).Hash.ToLower())  $(Split-Path $ArchivePath -Leaf)"
$Lines += "$((Get-FileHash $XpiPath -Algorithm SHA256).Hash.ToLower())  $(Split-Path $XpiPath -Leaf)"
Set-Content -Path $Sha256File -Value $Lines

Write-Host ""
Write-Host "Done. Release artifacts in ${OutputDir}:"
Write-Host "  $PackageName.zip"
Write-Host "  $(Split-Path $XpiPath -Leaf)"
Write-Host "  SHA256SUMS.windows"
