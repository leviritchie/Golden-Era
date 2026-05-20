param(
    [string]$ReleaseInputZip = "release_inputs\golden_era_release_payload.zip",
    [string]$OutputRoot = "dist\Golden-Era-Mod",
    [switch]$CreateZip
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ReleaseInputZipPath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $ReleaseInputZip))
$WizardProject = Join-Path $RepoRoot "tools\release_installer\wizard\StrongholdModInstaller.csproj"
$StageRoot = Join-Path $RepoRoot $OutputRoot
$StageFullPath = [System.IO.Path]::GetFullPath($StageRoot)
$DistRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "dist"))

function Require-Path($Path, $Message) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw $Message
    }
}

Require-Path $ReleaseInputZipPath "Release input zip was not found: $ReleaseInputZipPath"
Require-Path $WizardProject "Installer wizard project was not found: $WizardProject"
Require-Path (Join-Path $PSScriptRoot "templates\install.ps1") "Installer script template is missing."
Require-Path (Join-Path $PSScriptRoot "templates\uninstall.ps1") "Uninstaller script template is missing."
Require-Path (Join-Path $PSScriptRoot "templates\README.txt") "README template is missing."

if (-not $StageFullPath.StartsWith($DistRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to stage outside repo dist folder: $StageFullPath"
}

if (Test-Path -LiteralPath $StageFullPath) {
    Remove-Item -LiteralPath $StageFullPath -Recurse -Force
}
New-Item -ItemType Directory -Path $StageFullPath -Force | Out-Null

Expand-Archive -LiteralPath $ReleaseInputZipPath -DestinationPath $StageFullPath -Force

Require-Path (Join-Path $StageFullPath "payload\BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll") "Release inputs are missing OfflineUnlockMod.dll."
Require-Path (Join-Path $StageFullPath "payload\BepInEx\core\BepInEx.Unity.IL2CPP.dll") "Release inputs are missing BepInEx IL2CPP core."
Require-Path (Join-Path $StageFullPath "payload\game_root\dotnet\coreclr.dll") "Release inputs are missing Doorstop CoreCLR runtime."
Require-Path (Join-Path $StageFullPath "payload\game_root\winhttp.dll") "Release inputs are missing Doorstop winhttp.dll."
Require-Path (Join-Path $StageFullPath "core_overlay\manifest.json") "Release inputs are missing the generated Core overlay manifest."

Copy-Item -LiteralPath (Join-Path $PSScriptRoot "templates\install.ps1") -Destination (Join-Path $StageFullPath "install.ps1") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "templates\uninstall.ps1") -Destination (Join-Path $StageFullPath "uninstall.ps1") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "templates\README.txt") -Destination (Join-Path $StageFullPath "README.txt") -Force

& dotnet publish $WizardProject -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:PublishTrimmed=false -p:DebugType=None -p:DebugSymbols=false -o $StageFullPath --nologo
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$version = if ($env:GITHUB_REF_TYPE -eq "tag" -and $env:GITHUB_REF_NAME) { $env:GITHUB_REF_NAME } else { "unknown" }
$inputHash = (Get-FileHash -LiteralPath $ReleaseInputZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$overlayManifest = Get-Content -LiteralPath (Join-Path $StageFullPath "core_overlay\manifest.json") -Raw | ConvertFrom-Json

$manifest = [ordered]@{
    name = "Golden Era Mod"
    pluginVersion = $version
    packageCreatedUtc = (Get-Date).ToUniversalTime().ToString("o")
    overlayBasis = "versioned-release-inputs"
    releaseInputZip = $ReleaseInputZip
    releaseInputZipSha256 = $inputHash
    releaseOverlayGenerated = $true
    includesBepInExBootstrap = $true
    overlayOperationCount = $overlayManifest.operationCount
    notes = @(
        "Installer package assembled from repo release_inputs, not a local Steam install.",
        "Installer targets the Steam release build.",
        "Core overlay and plugin payload may contain multiple HoMM3-inspired faction ports."
    )
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $StageFullPath "manifest.json") -Encoding UTF8

Write-Host "Staged installer package from release inputs: $StageFullPath"
Write-Host "Release input SHA-256: $inputHash"

if ($CreateZip) {
    $zipPath = "$StageFullPath.zip"
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $StageFullPath "*") -DestinationPath $zipPath -Force
    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$zipPath.sha256" -Value "$zipHash  $(Split-Path -Leaf $zipPath)" -Encoding ASCII
    Write-Host "Created package zip: $zipPath"
    Write-Host "Package SHA-256: $zipHash"
}
