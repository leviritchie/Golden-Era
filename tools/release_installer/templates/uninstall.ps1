param(
    [string]$GameRoot
)

$ErrorActionPreference = "Stop"
Write-Warning "uninstall.ps1 is a legacy unpacked-package reference. The supported public installer is the single self-extracting GoldenEraModInstaller EXE, which removes only its side-by-side target copy."
$script:DetectionCandidates = New-Object "System.Collections.Generic.List[string]"

function Add-GameRootCandidate($Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $normalized = [System.Environment]::ExpandEnvironmentVariables($Path)
    if (-not $script:DetectionCandidates.Contains($normalized)) {
        [void]$script:DetectionCandidates.Add($normalized)
    }
}

function Add-SteamLibraryCandidates($SteamRoot) {
    if ([string]::IsNullOrWhiteSpace($SteamRoot)) {
        return
    }
    Add-GameRootCandidate (Join-Path $SteamRoot "steamapps\common\Heroes of Might and Magic Olden Era")

    $libraryFile = Join-Path $SteamRoot "steamapps\libraryfolders.vdf"
    if (-not (Test-Path -LiteralPath $libraryFile)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $libraryFile -ErrorAction SilentlyContinue) {
        if ($line -match '"path"\s+"([^"]+)"') {
            $libraryPath = $Matches[1] -replace "\\\\", "\"
            Add-GameRootCandidate (Join-Path $libraryPath "steamapps\common\Heroes of Might and Magic Olden Era")
        }
    }

    $steamApps = Join-Path $SteamRoot "steamapps"
    if (Test-Path -LiteralPath $steamApps) {
        Get-ChildItem -LiteralPath $steamApps -Filter "appmanifest_*.acf" -ErrorAction SilentlyContinue | ForEach-Object {
            $text = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue
            if ($text -and $text -match "Heroes of Might" -and $text -match "Olden Era" -and $text -match '"installdir"\s+"([^"]+)"') {
                Add-GameRootCandidate (Join-Path $steamApps (Join-Path "common" $Matches[1]))
            }
        }
    }
}

function Find-DefaultGameRoot {
    Add-GameRootCandidate "C:\Program Files (x86)\Steam\steamapps\common\Heroes of Might and Magic Olden Era"

    $programFilesX86 = [System.Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $programFiles = [System.Environment]::GetEnvironmentVariable("ProgramFiles")
    if ($programFilesX86) {
        Add-SteamLibraryCandidates (Join-Path $programFilesX86 "Steam")
    }
    if ($programFiles) {
        Add-SteamLibraryCandidates (Join-Path $programFiles "Steam")
    }

    foreach ($registryPath in @("HKCU:\Software\Valve\Steam", "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam", "HKLM:\SOFTWARE\Valve\Steam")) {
        try {
            $steamRoot = (Get-ItemProperty -LiteralPath $registryPath -ErrorAction Stop).InstallPath
            Add-SteamLibraryCandidates $steamRoot
        }
        catch {
        }
    }

    foreach ($drive in [System.IO.DriveInfo]::GetDrives()) {
        if (-not $drive.IsReady) {
            continue
        }
        Add-GameRootCandidate (Join-Path $drive.RootDirectory.FullName "SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era")
    }

    foreach ($candidate in $script:DetectionCandidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate "HeroesOldenEra.exe")) {
            return $candidate
        }
    }
    return $null
}

if (-not $GameRoot) {
    $GameRoot = Find-DefaultGameRoot
}
if (-not $GameRoot) {
    $checked = ($script:DetectionCandidates | ForEach-Object { "  - $_" }) -join [Environment]::NewLine
    throw "Could not auto-detect the game folder. Re-run with -GameRoot ""C:\Path\To\Heroes of Might and Magic Olden Era"". Checked:$([Environment]::NewLine)$checked"
}

$GameRoot = (Resolve-Path -LiteralPath $GameRoot).Path
$PluginTarget = Join-Path $GameRoot "BepInEx\plugins\OfflineUnlockMod"
$CoreZip = Join-Path $GameRoot "HeroesOldenEra_Data\StreamingAssets\Core.zip"
$InstallState = Join-Path $GameRoot "BepInEx\plugins\OfflineUnlockMod.install-state.json"

if (Test-Path -LiteralPath $PluginTarget) {
    Remove-Item -LiteralPath $PluginTarget -Recurse -Force
    Write-Host "Removed plugin folder: $PluginTarget"
}

$backupToRestore = $null
if (Test-Path -LiteralPath $InstallState) {
    $state = Get-Content -LiteralPath $InstallState -Raw | ConvertFrom-Json
    if ($state.originalCoreBackup -and (Test-Path -LiteralPath $state.originalCoreBackup)) {
        $backupToRestore = Get-Item -LiteralPath $state.originalCoreBackup
    }
}

if (-not $backupToRestore) {
    $backupToRestore = Get-ChildItem -LiteralPath (Split-Path -Parent $CoreZip) -Filter "Core.zip.backup-installer-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime |
        Select-Object -First 1
}

if ($backupToRestore) {
    Copy-Item -LiteralPath $backupToRestore.FullName -Destination $CoreZip -Force
    Write-Host "Restored Core.zip backup: $($backupToRestore.Name)"
    if (Test-Path -LiteralPath $InstallState) {
        Remove-Item -LiteralPath $InstallState -Force
    }
}
else {
    Write-Host "No installer-created Core.zip backup was found. Plugin files were removed only."
}
