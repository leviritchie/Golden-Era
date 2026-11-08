param(
    [string]$VenvRoot = "",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $VenvRoot) { $VenvRoot = Join-Path $RepoRoot ".venv-procedural-gui" }
if (-not $OutputRoot) { $OutputRoot = Join-Path $RepoRoot "build\procedural_gui" }
$Requirements = Join-Path $PSScriptRoot "requirements.txt"
$Spec = Join-Path $PSScriptRoot "OldenProceduralScenarios.spec"

if (-not (Test-Path -LiteralPath (Join-Path $VenvRoot "Scripts\python.exe"))) {
    py -3.12 -m venv $VenvRoot
}
$Python = Join-Path $VenvRoot "Scripts\python.exe"
& $Python -m pip install --disable-pip-version-check -r $Requirements
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
& $Python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $OutputRoot "dist") `
    --workpath (Join-Path $OutputRoot "work") `
    $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Write-Output (Join-Path $OutputRoot "dist\OldenProceduralScenarios.exe")