param(
    [string]$GameRoot,
    [string]$Homm3Root,
    [switch]$Repair,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:DetectionCandidates = New-Object "System.Collections.Generic.List[string]"
$script:Homm3DetectionCandidates = New-Object "System.Collections.Generic.List[string]"

function Add-GameRootCandidate($Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $normalized = [System.Environment]::ExpandEnvironmentVariables($Path)
    if (-not $script:DetectionCandidates.Contains($normalized)) {
        [void]$script:DetectionCandidates.Add($normalized)
    }
}

function Add-Homm3RootCandidate($Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $normalized = [System.Environment]::ExpandEnvironmentVariables($Path)
    if (-not $script:Homm3DetectionCandidates.Contains($normalized)) {
        [void]$script:Homm3DetectionCandidates.Add($normalized)
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

function Add-Homm3SteamLibraryCandidates($SteamRoot) {
    if ([string]::IsNullOrWhiteSpace($SteamRoot)) {
        return
    }

    foreach ($folderName in @("Heroes of Might & Magic III - HD Edition", "Heroes of Might and Magic III - HD Edition")) {
        Add-Homm3RootCandidate (Join-Path $SteamRoot (Join-Path "steamapps\common" $folderName))
    }

    $libraryFile = Join-Path $SteamRoot "steamapps\libraryfolders.vdf"
    if (-not (Test-Path -LiteralPath $libraryFile)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $libraryFile -ErrorAction SilentlyContinue) {
        if ($line -match '"path"\s+"([^"]+)"') {
            $libraryPath = $Matches[1] -replace "\\\\", "\"
            foreach ($folderName in @("Heroes of Might & Magic III - HD Edition", "Heroes of Might and Magic III - HD Edition")) {
                Add-Homm3RootCandidate (Join-Path $libraryPath (Join-Path "steamapps\common" $folderName))
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

function Test-Homm3Root($Path) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }

    $hasExe = (Test-Path -LiteralPath (Join-Path $Path "Heroes3.exe")) -or
        (Test-Path -LiteralPath (Join-Path $Path "HD_Launcher.exe")) -or
        (Test-Path -LiteralPath (Join-Path $Path "Might & Magic Heroes III - HD Edition.exe")) -or
        (Test-Path -LiteralPath (Join-Path $Path "Heroes of Might & Magic III - HD Edition.exe"))
    if (-not $hasExe) {
        return $false
    }

    $data = Join-Path $Path "Data"
    $hasCompleteLods = (Test-Path -LiteralPath (Join-Path $data "H3bitmap.lod")) -and
        (Test-Path -LiteralPath (Join-Path $data "H3sprite.lod")) -and
        (Test-Path -LiteralPath (Join-Path $data "H3ab_bmp.lod")) -and
        (Test-Path -LiteralPath (Join-Path $data "H3ab_spr.lod"))
    $hasHdMarkers = (Test-Path -LiteralPath (Join-Path $Path "_HD3_Data")) -or ($Path -match "HD Edition")

    return ($hasCompleteLods -or $hasHdMarkers)
}

function Find-DefaultHomm3Root {
    Add-Homm3RootCandidate (Join-Path $PackageRoot "HoMM 3 Complete")
    Add-Homm3RootCandidate "C:\GOG Games\HoMM 3 Complete"
    Add-Homm3RootCandidate "C:\GOG Games\Heroes of Might and Magic 3 Complete"
    Add-Homm3RootCandidate "C:\Program Files (x86)\GOG Galaxy\Games\HoMM 3 Complete"
    Add-Homm3RootCandidate "C:\Program Files (x86)\GOG Galaxy\Games\Heroes of Might and Magic 3 Complete"
    Add-Homm3RootCandidate "C:\Program Files (x86)\Steam\steamapps\common\Heroes of Might & Magic III - HD Edition"
    Add-Homm3RootCandidate "C:\Program Files (x86)\Steam\steamapps\common\Heroes of Might and Magic III - HD Edition"

    $programFilesX86 = [System.Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $programFiles = [System.Environment]::GetEnvironmentVariable("ProgramFiles")
    if ($programFilesX86) {
        Add-Homm3SteamLibraryCandidates (Join-Path $programFilesX86 "Steam")
    }
    if ($programFiles) {
        Add-Homm3SteamLibraryCandidates (Join-Path $programFiles "Steam")
    }

    foreach ($drive in [System.IO.DriveInfo]::GetDrives()) {
        if (-not $drive.IsReady) {
            continue
        }
        Add-Homm3RootCandidate (Join-Path $drive.RootDirectory.FullName "GOG Games\HoMM 3 Complete")
        Add-Homm3RootCandidate (Join-Path $drive.RootDirectory.FullName "GOG Games\Heroes of Might and Magic 3 Complete")
        Add-Homm3RootCandidate (Join-Path $drive.RootDirectory.FullName "SteamLibrary\steamapps\common\Heroes of Might & Magic III - HD Edition")
        Add-Homm3RootCandidate (Join-Path $drive.RootDirectory.FullName "SteamLibrary\steamapps\common\Heroes of Might and Magic III - HD Edition")
    }

    foreach ($candidate in $script:Homm3DetectionCandidates) {
        if (Test-Homm3Root $candidate) {
            return $candidate
        }
    }
    return $null
}

function Require-Path($Path, $Message) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw $Message
    }
}

function Unblock-Tree($Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
        try { Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue } catch {}
    }
    try { Unblock-File -LiteralPath $Path -ErrorAction SilentlyContinue } catch {}
}

function Write-DoorstopConfig($Path) {
@"
# General options for Unity Doorstop
[General]
enabled = true
target_assembly = BepInEx\core\BepInEx.Unity.IL2CPP.dll
redirect_output_log = false
boot_config_override =
ignore_disable_switch = false

[UnityMono]
dll_search_path_override =
debug_enabled = false
debug_address = 127.0.0.1:10000
debug_suspend = false

[Il2Cpp]
coreclr_path = dotnet\coreclr.dll
corlib_dir = dotnet
"@ | Set-Content -LiteralPath $Path -Encoding ASCII
}

function Get-BytesSha256($Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Copy-Stream($Source, $Destination) {
    $buffer = New-Object byte[] 1048576
    while (($read = $Source.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $Destination.Write($buffer, 0, $read)
    }
}

function Add-ZipPayloadEntry($Zip, $EntryName, $PayloadPath) {
    $entry = $Zip.CreateEntry($EntryName, [System.IO.Compression.CompressionLevel]::Optimal)
    $inStream = [System.IO.File]::OpenRead($PayloadPath)
    try {
        $outStream = $entry.Open()
        try {
            Copy-Stream $inStream $outStream
        }
        finally {
            $outStream.Dispose()
        }
    }
    finally {
        $inStream.Dispose()
    }
}

function Test-CoreOverlay($CoreZipPath) {
    $zip = [System.IO.Compression.ZipFile]::OpenRead($CoreZipPath)
    try {
        $dataEntry = $zip.GetEntry("DB/data.json")
        $fractionEntry = $zip.GetEntry("DB/fractions/7_homm3_stronghold.json")
        if ($null -eq $dataEntry) { throw "Core.zip validation failed: missing DB/data.json." }
        if ($null -eq $fractionEntry) { throw "Core.zip validation failed: missing Stronghold faction file." }

        $reader = New-Object System.IO.StreamReader($dataEntry.Open(), [System.Text.Encoding]::UTF8)
        try {
            $dataJson = $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }
        if ($dataJson -notmatch "homm3_stronghold") {
            throw "Core.zip validation failed: DB/data.json does not contain homm3_stronghold."
        }
    }
    finally {
        $zip.Dispose()
    }
}

function Apply-CoreOverlay($CoreZipPath, $ManifestPath, $PackageRootPath) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if ($manifest.format -ne "hommoe-stronghold-release-overlay-v1") {
        throw "Unsupported Core overlay manifest format: $($manifest.format)"
    }

    $operationsByPath = @{}
    foreach ($op in $manifest.operations) {
        $operationsByPath[$op.path] = $op
    }

    $timestamp = Get-Date -Format yyyyMMdd-HHmmss
    $backup = "$CoreZipPath.backup-installer-$timestamp"
    $tmpZip = "$CoreZipPath.installer-tmp-$timestamp"
    Copy-Item -LiteralPath $CoreZipPath -Destination $backup -Force

    try {
        $src = [System.IO.Compression.ZipFile]::OpenRead($CoreZipPath)
        $dst = [System.IO.Compression.ZipFile]::Open($tmpZip, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            $written = New-Object "System.Collections.Generic.HashSet[string]"
            foreach ($entry in $src.Entries) {
                if ([string]::IsNullOrEmpty($entry.Name)) {
                    continue
                }

                $name = $entry.FullName.Replace("\", "/").TrimStart("/")
                if ($operationsByPath.ContainsKey($name)) {
                    $op = $operationsByPath[$name]
                    $entryStream = $entry.Open()
                    try {
                        $memory = New-Object System.IO.MemoryStream
                        try {
                            Copy-Stream $entryStream $memory
                            $currentHash = Get-BytesSha256 $memory.ToArray()
                        }
                        finally {
                            $memory.Dispose()
                        }
                    }
                    finally {
                        $entryStream.Dispose()
                    }

                    if ($currentHash -ne $op.previousSha256 -and $currentHash -ne $op.sha256) {
                        throw "Core.zip member $name does not match the expected release baseline. Steam may have updated the game; use a matching installer package."
                    }

                    $payload = Join-Path $PackageRootPath ("core_overlay\" + $op.payload.Replace("/", "\"))
                    Require-Path $payload "Overlay payload is missing: $payload"
                    if ((Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash.ToLowerInvariant() -ne $op.sha256) {
                        throw "Overlay payload hash mismatch: $payload"
                    }
                    Add-ZipPayloadEntry $dst $name $payload
                }
                else {
                    $newEntry = $dst.CreateEntry($entry.FullName, [System.IO.Compression.CompressionLevel]::Optimal)
                    $inStream = $entry.Open()
                    try {
                        $outStream = $newEntry.Open()
                        try {
                            Copy-Stream $inStream $outStream
                        }
                        finally {
                            $outStream.Dispose()
                        }
                    }
                    finally {
                        $inStream.Dispose()
                    }
                }
                [void]$written.Add($name)
            }

            foreach ($op in $manifest.operations) {
                if ($written.Contains($op.path)) {
                    continue
                }
                if ($op.operation -ne "add_member") {
                    throw "Expected existing Core.zip member is missing: $($op.path)"
                }
                $payload = Join-Path $PackageRootPath ("core_overlay\" + $op.payload.Replace("/", "\"))
                Require-Path $payload "Overlay payload is missing: $payload"
                Add-ZipPayloadEntry $dst $op.path $payload
            }
        }
        finally {
            $dst.Dispose()
            $src.Dispose()
        }

        Move-Item -LiteralPath $tmpZip -Destination $CoreZipPath -Force
        Test-CoreOverlay $CoreZipPath
        return $backup
    }
    catch {
        if (Test-Path -LiteralPath $tmpZip) {
            Remove-Item -LiteralPath $tmpZip -Force
        }
        if (Test-Path -LiteralPath $backup) {
            Copy-Item -LiteralPath $backup -Destination $CoreZipPath -Force
        }
        throw
    }
}

if (-not $GameRoot) {
    $GameRoot = Find-DefaultGameRoot
}
if (-not $GameRoot) {
    $checked = ($script:DetectionCandidates | ForEach-Object { "  - $_" }) -join [Environment]::NewLine
    throw "Could not auto-detect the game folder. Re-run with -GameRoot ""C:\Path\To\Heroes of Might and Magic Olden Era"". Checked:$([Environment]::NewLine)$checked"
}

if (-not $Homm3Root) {
    $Homm3Root = Find-DefaultHomm3Root
}
if (-not $Homm3Root) {
    $checked = ($script:Homm3DetectionCandidates | ForEach-Object { "  - $_" }) -join [Environment]::NewLine
    throw "Could not find a HoMM3 Complete or HoMM3 HD installation. Choose that folder in the installer, or rerun with -Homm3Root ""C:\Path\To\HoMM3"". Checked:$([Environment]::NewLine)$checked"
}
if (-not (Test-Homm3Root $Homm3Root)) {
    throw "This does not look like a HoMM3 Complete or HoMM3 HD folder: $Homm3Root"
}

$GameRoot = (Resolve-Path -LiteralPath $GameRoot).Path
$Homm3Root = (Resolve-Path -LiteralPath $Homm3Root).Path
$CoreZip = Join-Path $GameRoot "HeroesOldenEra_Data\StreamingAssets\Core.zip"
$PluginTarget = Join-Path $GameRoot "BepInEx\plugins\OfflineUnlockMod"
$PluginPayload = Join-Path $PackageRoot "payload\BepInEx\plugins\OfflineUnlockMod"
$BepInExPayload = Join-Path $PackageRoot "payload\BepInEx"
$RootPayload = Join-Path $PackageRoot "payload\game_root"
$BepInExCfg = Join-Path $GameRoot "BepInEx\config\BepInEx.cfg"
$OverlayManifest = Join-Path $PackageRoot "core_overlay\manifest.json"
$InstallState = Join-Path $GameRoot "BepInEx\plugins\OfflineUnlockMod.install-state.json"

Require-Path (Join-Path $GameRoot "HeroesOldenEra.exe") "This does not look like the release game folder: $GameRoot"
Write-Host "Validated HoMM3 prerequisite: $Homm3Root"
Require-Path $CoreZip "Missing release Core.zip: $CoreZip"
Require-Path $PluginPayload "Installer payload is incomplete: $PluginPayload"
Require-Path (Join-Path $BepInExPayload "core\BepInEx.Unity.IL2CPP.dll") "Installer payload is missing bundled BepInEx IL2CPP core."
Require-Path (Join-Path $RootPayload "dotnet\coreclr.dll") "Installer payload is missing bundled Doorstop CoreCLR runtime."
Require-Path (Join-Path $RootPayload "winhttp.dll") "Installer payload is missing bundled Doorstop winhttp.dll."
Require-Path (Join-Path $RootPayload "doorstop_config.ini") "Installer payload is missing bundled Doorstop config."
Require-Path $OverlayManifest "This package does not yet contain a release-derived Core overlay manifest. This scaffold is not publishable until core_overlay is generated from a known-good Steam release Core.zip."

Copy-Item -LiteralPath (Join-Path $RootPayload "winhttp.dll") -Destination (Join-Path $GameRoot "winhttp.dll") -Force
Copy-Item -LiteralPath (Join-Path $RootPayload "dotnet") -Destination $GameRoot -Recurse -Force
Write-DoorstopConfig (Join-Path $GameRoot "doorstop_config.ini")
if (Test-Path -LiteralPath (Join-Path $RootPayload ".doorstop_version")) {
    Copy-Item -LiteralPath (Join-Path $RootPayload ".doorstop_version") -Destination (Join-Path $GameRoot ".doorstop_version") -Force
}
New-Item -ItemType Directory -Path (Join-Path $GameRoot "BepInEx") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $BepInExPayload "core") -Destination (Join-Path $GameRoot "BepInEx") -Recurse -Force
if (Test-Path -LiteralPath (Join-Path $BepInExPayload "patchers")) {
    Copy-Item -LiteralPath (Join-Path $BepInExPayload "patchers") -Destination (Join-Path $GameRoot "BepInEx") -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $GameRoot "BepInEx\config") -Force | Out-Null
if (-not (Test-Path -LiteralPath $BepInExCfg)) {
    Copy-Item -LiteralPath (Join-Path $BepInExPayload "config\BepInEx.cfg") -Destination $BepInExCfg -Force
}

if (Test-Path -LiteralPath $BepInExCfg) {
    $cfg = Get-Content -LiteralPath $BepInExCfg -Raw
    if ($cfg -match '(?m)^UnityLogListening\s*=') {
        $cfg = $cfg -replace '(?m)^UnityLogListening\s*=.*$', 'UnityLogListening = false'
        Set-Content -LiteralPath $BepInExCfg -Value $cfg -Encoding UTF8
    }
}

Unblock-Tree (Join-Path $GameRoot "winhttp.dll")
Unblock-Tree (Join-Path $GameRoot "BepInEx\core")

Require-Path (Join-Path $GameRoot "winhttp.dll") "Doorstop install failed: winhttp.dll was not copied."
Require-Path (Join-Path $GameRoot "dotnet\coreclr.dll") "Doorstop install failed: dotnet\coreclr.dll was not copied."
Require-Path (Join-Path $GameRoot "BepInEx\core\BepInEx.Unity.IL2CPP.dll") "BepInEx install failed: BepInEx.Unity.IL2CPP.dll was not copied."
$doorstopConfigText = Get-Content -LiteralPath (Join-Path $GameRoot "doorstop_config.ini") -Raw
if ($doorstopConfigText -notmatch '(?m)^enabled\s*=\s*true\s*$' -or $doorstopConfigText -notmatch 'BepInEx\\core\\BepInEx\.Unity\.IL2CPP\.dll') {
    throw "Doorstop config verification failed; BepInEx will not launch."
}

$existingState = $null
if (Test-Path -LiteralPath $InstallState) {
    $existingState = Get-Content -LiteralPath $InstallState -Raw | ConvertFrom-Json
}

if (Test-Path -LiteralPath $PluginTarget) {
    $backup = "$PluginTarget.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Copy-Item -LiteralPath $PluginTarget -Destination $backup -Recurse -Force
    Remove-Item -LiteralPath $PluginTarget -Recurse -Force
}

New-Item -ItemType Directory -Path (Split-Path -Parent $PluginTarget) -Force | Out-Null
Copy-Item -LiteralPath $PluginPayload -Destination (Split-Path -Parent $PluginTarget) -Recurse -Force

$coreBackup = Apply-CoreOverlay $CoreZip $OverlayManifest $PackageRoot
$originalCoreBackup = if ($existingState -and $existingState.originalCoreBackup) { $existingState.originalCoreBackup } else { $coreBackup }

$state = [ordered]@{
    gameRoot = $GameRoot
    installedAt = (Get-Date).ToUniversalTime().ToString("o")
    packageRoot = $PackageRoot
    originalCoreBackup = $originalCoreBackup
    lastCoreSafetyBackup = $coreBackup
    overlayManifest = $OverlayManifest
}
$state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $InstallState -Encoding UTF8

Write-Host "Installed Stronghold mod successfully."
if (-not (Test-Path -LiteralPath (Join-Path $GameRoot "BepInEx\interop\Hex.dll"))) {
    Write-Host "BepInEx was installed, but interop has not been generated yet. Launch the game once; BepInEx will generate it on first start."
}
Write-Host "Original Core.zip backup: $originalCoreBackup"
if ($Repair) {
    Write-Host "Repair mode completed payload and Core overlay refresh."
}
