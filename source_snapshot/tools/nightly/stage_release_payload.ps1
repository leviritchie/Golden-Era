<#
.SYNOPSIS
  Stages the full Golden Era release payload (the folder that becomes golden_era_release_payload.zip)
  for the nightly lane, then runs every payload gate. Writes no zip and never deploys.

.DESCRIPTION
  This is the v0.1.319 release recipe as a parameterised script. It started as
  tools/release_installer/refresh_official_deobf_release_inputs.ps1 plus the one-off deltas the
  v0.1.319 release applied by hand:
    - Clean Core pin: Steam build 25672315 (depot 3105441 manifest 7750145598966689713).
    - homm3ImportPreviewHooks and homm3ReleaseMapSquadVisualController keep their installed values.
    - Bug reporting keeps the installed values (user-approved 2026-10-05). The gate asserts only the
      shape: modBugReporting=true and an Apps Script /exec endpoint. No endpoint is stored here.
    - OldenAiSim.dll is scrubbed as well as OfflineUnlockMod.dll.
    - Owned-skinned coverage: an import entry whose battle and map prefabs are both
      .../OwnedSkinned/owned_skinned.prefab counts as covered when homm3_bundles/<bundleName> and
      its .manifest are staged. This was approved for the 17 3D-only HoMM3 neutrals.
  Fixes for stager gaps found in v0.1.319:
    - Leftover filters: *.pre<digits|_>*, *.bak_*, *.force_*, *.npz and .foldercache. These are
      excluded on copy, and anything that still reaches the stage is pruned and counted.
    - JSON sanitising also catches JSON-escaped and forward-slash paths ("C:\\Users\\...", "C:/...")
      and paths embedded inside longer strings. tools/nightly/payload_leaks.py does this.
    - Leak gate: payload_leaks.py scan fails on any absolute local path, local username, email address
      or secret in text files and in the two first-party DLLs.

  Inputs are read only: the Golden Era install (plugin folder, BepInEx core, Doorstop, modded
  Core.zip, Unity data, StreamingAssets) and the clean Core.zip from the 25672315 mirror.
  The only file taken from the build of -Ref is the plugin DLL (-PluginDllOverride). Everything else
  is the content deployed to the Golden Era install, which is what the release recipe ships.

  Exit codes: 0 = pass; 30 = staging or a payload gate failed; 40 = the sanitizer/leak gate failed;
  2 = bad arguments.
#>
[CmdletBinding()]
param(
    [string] $GameRoot = 'V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era',
    [Parameter(Mandatory)] [string] $CleanReleaseCore,
    [Parameter(Mandatory)] [string] $StageRoot,
    [Parameter(Mandatory)] [string] $ToolsDir,
    [Parameter(Mandatory)] [string] $PluginDllOverride,
    [string] $ReportPath,
    [string[]] $LeakTerm = @()
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$LeakTerm = @($LeakTerm | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
$python = (Get-Command python -ErrorAction Stop).Source
$LeakTool = Join-Path $here 'payload_leaks.py'

$ReleaseCore = Join-Path $GameRoot 'HeroesOldenEra_Data\StreamingAssets\Core.zip'
$PluginSource = Join-Path $GameRoot 'BepInEx\plugins\OfflineUnlockMod'
$PayloadPlugin = Join-Path $StageRoot 'payload\BepInEx\plugins\OfflineUnlockMod'
$PayloadBepInEx = Join-Path $StageRoot 'payload\BepInEx'
$PayloadRoot = Join-Path $StageRoot 'payload\game_root'
$PayloadUnity = Join-Path $StageRoot 'payload\unity_data'
$PayloadMetadata = Join-Path $StageRoot 'payload\il2cpp_metadata'
$PayloadStreaming = Join-Path $StageRoot 'payload\streaming_assets'
$OverlayDir = Join-Path $StageRoot 'core_overlay'
$LiveParityStager = Join-Path $ToolsDir 'stage_golden_era_live_parity_payload.py'

# Steam build 25672315 clean Core.zip (depot 3105441 manifest 7750145598966689713).
$PinnedCleanCoreSha256 = 'f11b90c19aae60908a4d503e639f2abf7a02c5d706cdb072879ef9773812d954'
$PinnedCleanCoreBytes = [int64]12962693

$ReleaseCandidateFalseConfigKeys = @(
    'portSmokeProfile',
    'esquirePikemanDiagnostics',
    'esquirePikemanUnityErrorCorrelator',
    'esquirePikemanSpawnerReflectionProbe',
    'homm3ReleaseBattleUiDiagnostics',
    'homm3SkeletalNecromancyProbe',
    'strongholdAbilityPanelProbes',
    'releaseCustomGameUiProbes',
    'homm3UiInspector',
    'homm3LiveProbeWorkbench'
)
$BugReportEndpointShape = '^https://script\.google\.com/macros/s/[A-Za-z0-9_-]{20,}/exec$'

$report = [ordered]@{ schema = 'nightly_stage_report.v1'; status = 'fail'; steps = [ordered]@{} }
function Save-Report {
    if ($ReportPath) { $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReportPath -Encoding utf8 }
}
function Fail([int] $code, [string] $message) {
    $report.error = $message
    $report.exitCode = $code
    Save-Report
    Write-Host "NIGHTLY STAGE: FAIL ($message)"
    exit $code
}
function Require-Path($Path, $Message) {
    if (-not (Test-Path -LiteralPath $Path)) { throw $Message }
}
Add-Type -AssemblyName System.IO.Compression.FileSystem

# ---- file filters -------------------------------------------------------------------------------
# Maintainer leftovers seen in v0.1.319 and removed by hand there.
function Test-LeftoverFile([string] $Path) {
    $name = [IO.Path]::GetFileName($Path).ToLowerInvariant()
    if ($name -match '\.pre[0-9_]') { return $true }          # *.pre25672315_*, *.pre_ocean_*
    if ($name -match '\.bak_') { return $true }               # config.json.bak_*, building_layer_map.json.bak_*
    if ($name -match '\.force_') { return $true }             # *.force_win_game_pending
    if ($name.EndsWith('.npz')) { return $true }              # homm3_town_scene_meshes/scene3d/*/*.npz
    if ($name -eq '.foldercache' -or $name.EndsWith('.foldercache')) { return $true }
    return $false
}

function Test-ExcludedPayloadFile($Path) {
    $name = [System.IO.Path]::GetFileName($Path)
    $lowerName = $name.ToLowerInvariant()
    $lowerPath = $Path.ToLowerInvariant()
    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()

    if (Test-LeftoverFile $Path) { return $true }
    if ($lowerPath -match "\\__pycache__\\") { return $true }
    if ($lowerPath -match "\\live_probe") { return $true }
    if ($lowerPath -match "\\ai_driver_bridge(\\|$|\.)") { return $true }
    if ($lowerPath -match "\\homm3_lab(\\|$|\.)") { return $true }
    if ($lowerPath -match "\\histogram_icons\\") { return $true }
    if ($lowerPath -match "\\dll_backups\\") { return $true }
    if ($lowerName -match "backup") { return $true }
    if ($lowerName -match "\.bak($|-|_|\.)") { return $true }
    if ($lowerName -match "\.disabled") { return $true }
    if ($lowerName -match "^perf_compare") { return $true }
    if ($lowerName -match "_disabled_") { return $true }
    if ($extension -in @(".log", ".flag", ".pdb", ".py", ".pyc", ".meta", ".tmp", ".md", ".txt")) { return $true }
    return $false
}

function Copy-FilteredDirectory($Source, $Destination) {
    $sourceRoot = (Resolve-Path -LiteralPath $Source).Path.TrimEnd("\")
    $copied = 0; $excluded = 0; $leftovers = 0
    foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Force) {
        if (Test-ExcludedPayloadFile $file.FullName) {
            $excluded++
            if (Test-LeftoverFile $file.FullName) { $leftovers++ }
            continue
        }
        $relative = $file.FullName.Substring($sourceRoot.Length).TrimStart("\")
        $target = Join-Path $Destination $relative
        [void](New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force)
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        $copied++
    }
    Write-Host "Copied $copied plugin file(s); excluded $excluded maintainer/runtime artifact(s), $leftovers of them leftovers."
    return [ordered]@{ copied = $copied; excluded = $excluded; leftoversExcluded = $leftovers }
}

function Copy-Homm3RuntimeLabAssets($SourcePluginRoot, $DestinationPluginRoot) {
    $sourceLab = Join-Path $SourcePluginRoot "homm3_lab"
    Require-Path $sourceLab "Golden Era payload source is missing homm3_lab runtime assets: $sourceLab"
    $destLab = Join-Path $DestinationPluginRoot "homm3_lab"
    $copied = 0
    foreach ($unitDir in Get-ChildItem -LiteralPath $sourceLab -Directory -Force) {
        foreach ($runtimeDir in @("Generated", "extracted_battle", "extracted_map")) {
            $sourceRuntime = Join-Path $unitDir.FullName $runtimeDir
            if (-not (Test-Path -LiteralPath $sourceRuntime)) { continue }
            $sourceRoot = (Resolve-Path -LiteralPath $sourceRuntime).Path.TrimEnd("\")
            foreach ($f in Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Force) {
                if ($f.Extension.ToLowerInvariant() -ne '.json') { continue }
                $relative = $f.FullName.Substring($sourceRoot.Length).TrimStart("\")
                $relativeLower = $relative.ToLowerInvariant()
                if ($relativeLower -match "(^|\\)(backup|.*backup.*|.*\.disabled.*)(\\|$)" -or
                    $relativeLower -match "\.bak($|\\|_)" -or
                    $relativeLower -match "\.disabled($|\\)" -or
                    (Test-LeftoverFile $f.FullName)) {
                    continue
                }
                $target = Join-Path (Join-Path $destLab $unitDir.Name) (Join-Path $runtimeDir $relative)
                [void](New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force)
                Copy-Item -LiteralPath $f.FullName -Destination $target -Force
                $copied++
            }
        }
    }
    if ($copied -le 0) { throw "No homm3_lab runtime assets were copied from: $sourceLab" }
    Write-Host "Copied $copied homm3_lab runtime metadata file(s)."
    return $copied
}

function Set-JsonBool($Json, $Name, [bool]$Value) {
    if ($Json.PSObject.Properties.Name -contains $Name) { $Json.$Name = $Value }
    else { Add-Member -InputObject $Json -MemberType NoteProperty -Name $Name -Value $Value }
}

function Set-PluginReleaseConfig($PluginRoot) {
    $configPath = Join-Path $PluginRoot "config.json"
    Require-Path $configPath "Release payload is missing config.json."
    $json = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json -DateKind String
    foreach ($prop in @($json.PSObject.Properties)) {
        if ($prop.Value -is [bool] -and $prop.Name -match '(?i)(diagnostic|probe|inspector|liveProbeWorkbench)') {
            $prop.Value = $false
        }
    }
    Set-JsonBool $json "releaseSafeProfile" $true
    Set-JsonBool $json "autoLaunchOnMenu" $false
    Set-JsonBool $json "releaseSafeAutoLaunchOnMenu" $false
    foreach ($key in $ReleaseCandidateFalseConfigKeys) {
        if ($json.PSObject.Properties.Name -contains $key) { $json.$key = $false }
    }
    # Bug reporting keeps the installed (user-approved) values; only its shape is asserted.
    if (-not ($json.modBugReporting -eq $true -and [string]$json.modBugReportingEndpoint -match $BugReportEndpointShape)) {
        throw "Staged config bug-report settings are not the approved shape (modBugReporting=true and an Apps Script /exec endpoint)."
    }
    $json | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $configPath -Encoding UTF8
}

function Set-PayloadBepInExConfig($GameRoot, $PayloadBepInExRoot) {
    [void](New-Item -ItemType Directory -Path (Join-Path $PayloadBepInExRoot "config") -Force)
    $sourceBepInExCfg = Join-Path $GameRoot "BepInEx\config\BepInEx.cfg"
    $targetBepInExCfg = Join-Path $PayloadBepInExRoot "config\BepInEx.cfg"
    if (Test-Path -LiteralPath $sourceBepInExCfg) {
        $cfg = Get-Content -LiteralPath $sourceBepInExCfg -Raw
        if ($cfg -match '(?m)^UnityLogListening\s*=') { $cfg = $cfg -replace '(?m)^UnityLogListening\s*=.*$', 'UnityLogListening = false' }
        else { $cfg = $cfg.TrimEnd() + [Environment]::NewLine + "UnityLogListening = false" + [Environment]::NewLine }
        Set-Content -LiteralPath $targetBepInExCfg -Value $cfg -Encoding UTF8
    }
    else {
        Set-Content -LiteralPath $targetBepInExCfg -Value "UnityLogListening = false" -Encoding UTF8
    }
}

# BepInEx names its Unity base library zip after the game's Unity version ({VERSION}.zip, e.g.
# 6000.0.66.zip). Shipping it in unity-libs means the first launch never has to download it
# from UnityBaseLibrariesSource, which can stall forever behind a firewall or network filter.
function Get-UnityBaseLibsZipName($GameRoot) {
    $fv = (Get-Item -LiteralPath (Join-Path $GameRoot "UnityPlayer.dll")).VersionInfo.FileVersion
    if ($fv -notmatch '^(\d+)\.(\d+)\.(\d+)') { throw "Cannot read the Unity version from UnityPlayer.dll (FileVersion '$fv')." }
    return "$($Matches[1]).$($Matches[2]).$($Matches[3]).zip"
}

function Copy-PayloadUnityBaseLibs($GameRoot, $PayloadBepInExRoot) {
    $name = Get-UnityBaseLibsZipName $GameRoot
    $source = Join-Path $GameRoot "BepInEx\unity-libs\$name"
    Require-Path $source "BepInEx unity-libs zip for the game's Unity version was not found: $source"
    $target = Join-Path $PayloadBepInExRoot "unity-libs"
    [void](New-Item -ItemType Directory -Path $target -Force)
    Copy-Item -LiteralPath $source -Destination (Join-Path $target $name) -Force
    return $name
}

function Assert-NoForbiddenPayloadFiles($Root) {
    $bad = Get-ChildItem -LiteralPath $Root -Recurse -File -Force | Where-Object {
        $lowerPath = $_.FullName.ToLowerInvariant()
        $lowerName = $_.Name.ToLowerInvariant()
        $extension = $_.Extension.ToLowerInvariant()
        if ($lowerPath -match "\\homm3_lab\\") {
            if ($lowerName -match "backup" -or $lowerName -match "\.bak($|-|_)" -or $lowerName -match "\.disabled" -or
                $lowerPath -match "\\__pycache__\\" -or $lowerPath -match "\\live_probe" -or
                $lowerPath -match "\\ai_driver_bridge(\\|$|\.)" -or (Test-LeftoverFile $_.FullName)) {
                return $true
            }
            return -not ($extension -eq ".json" -and
                ($lowerPath -match "\\generated\\" -or $lowerPath -match "\\extracted_battle\\" -or $lowerPath -match "\\extracted_map\\"))
        }
        Test-ExcludedPayloadFile $_.FullName
    }
    if ($bad) {
        $sample = ($bad | Select-Object -First 20 | ForEach-Object { "  - $($_.FullName)" }) -join [Environment]::NewLine
        throw "Forbidden files reached the release payload:$([Environment]::NewLine)$sample"
    }
}

function Assert-CleanCoreHasNoHomm3Payload($CoreZip) {
    $zip = [System.IO.Compression.ZipFile]::OpenRead($CoreZip)
    try {
        $bad = @($zip.Entries | Where-Object { $_.FullName -match '(?i)homm3_|h3_|hero_homm3_|fraction_law_homm3_' } | Select-Object -First 20)
        if ($bad.Count -gt 0) {
            throw "Clean Core.zip appears to contain Golden Era payload entries: $(($bad | ForEach-Object FullName) -join ', ')"
        }
    }
    finally { $zip.Dispose() }
}

function Assert-PinnedCleanCore($CoreZip) {
    $item = Get-Item -LiteralPath $CoreZip
    $actualHash = (Get-FileHash -LiteralPath $CoreZip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([int64]$item.Length -ne $PinnedCleanCoreBytes -or $actualHash -ne $PinnedCleanCoreSha256) {
        throw "CleanReleaseCore is not the pinned build 25672315 Core.zip (expected $PinnedCleanCoreSha256 / $PinnedCleanCoreBytes bytes, got $actualHash / $($item.Length) bytes): $CoreZip"
    }
}

function Assert-OverlayMatchesPinnedCleanCore($OverlayManifestPath) {
    Require-Path $OverlayManifestPath "Overlay manifest was not found: $OverlayManifestPath"
    $manifest = Get-Content -LiteralPath $OverlayManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json -DateKind String
    if ([string]$manifest.vanillaCore.sha256 -ne $PinnedCleanCoreSha256 -or [int64]$manifest.vanillaCore.size -ne $PinnedCleanCoreBytes) {
        throw "Exported core_overlay vanillaCore does not match the pinned build 25672315 Core.zip ($($manifest.vanillaCore.sha256) / $($manifest.vanillaCore.size))."
    }
    return @($manifest.operations).Count
}

function Assert-DllHasNoDebugProvenance($DllPath) {
    $latin1 = [System.Text.Encoding]::GetEncoding("iso-8859-1").GetString([System.IO.File]::ReadAllBytes($DllPath))
    foreach ($pattern in @("\.pdb", "Homm3LiveProbeWorkbench", "live_probe_bridge", "volatile_load_probe_assembly",
            "volatile_compile", "volatile_global_ui_setter_patch", "set_primitive_component_field",
            "invoke_allowlisted_method", "C:\\Users\\<user>", "V:\\", "Olden Era Playtest Tweak", "Golden Era",
            "golden_era_release_repo", "CodexSandbox")) {
        if ($latin1 -match $pattern) { throw "Release DLL contains debug/private provenance pattern '$pattern': $DllPath" }
    }
}

function Get-Homm3ImportLabSid($Entry, $PropertyName) {
    if ($null -eq $Entry -or -not ($Entry.PSObject.Properties.Name -contains $PropertyName)) { return $null }
    $value = [string]$Entry.$PropertyName
    if ([string]::IsNullOrWhiteSpace($value)) { return $null }
    $match = [regex]::Match($value.Replace('\', '/'), '/homm3_lab/([^/]+)/')
    if (-not $match.Success) { return $null }
    return $match.Groups[1].Value
}

function Test-Homm3ImportBundleManifestCoverage($PayloadPlugin, $BundleName, $LabSid, [bool]$MapVisual) {
    if ([string]::IsNullOrWhiteSpace($BundleName) -or [string]::IsNullOrWhiteSpace($LabSid)) { return $false }
    $manifestPath = Join-Path (Join-Path $PayloadPlugin "homm3_bundles") "$BundleName.manifest"
    if (-not (Test-Path -LiteralPath $manifestPath)) { return $false }
    $text = Get-Content -LiteralPath $manifestPath -Raw
    $labRoot = "Assets/CustomUnits/homm3_lab/$LabSid/"
    if ($MapVisual) {
        return $text.Contains($labRoot + "map.prefab") -and $text.Contains($labRoot + "Generated/MapBillboard/Materials/map_frame_")
    }
    return $text.Contains($labRoot + "battle.prefab") -and $text.Contains($labRoot + "Generated/BillboardAnim/Materials/homm3_frame_")
}

function Test-OwnedSkinnedCoverage($PayloadPlugin, $Entry, $BundleName) {
    # Approved for v0.1.319 (3D-only neutrals): both prefabs are the owned-skinned prefab and the bundle ships.
    $suffix = '/OwnedSkinned/owned_skinned.prefab'
    foreach ($prop in 'battlePrefabAssetPath', 'mapPrefabAssetPath') {
        if (-not ($Entry.PSObject.Properties.Name -contains $prop)) { return $false }
        if (-not ([string]$Entry.$prop).Replace('\', '/').EndsWith($suffix, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    }
    if ([string]::IsNullOrWhiteSpace($BundleName)) { return $false }
    $bundle = Join-Path (Join-Path $PayloadPlugin 'homm3_bundles') $BundleName
    return (Test-Path -LiteralPath $bundle) -and (Test-Path -LiteralPath "$bundle.manifest")
}

function Assert-Homm3ImportSidecarCoverage($PayloadPlugin) {
    $import = Get-Content -LiteralPath (Join-Path $PayloadPlugin "homm3_import.json") -Raw | ConvertFrom-Json -DateKind String
    $entries = @($import.entries)
    if ($entries.Count -le 0) { throw "Release payload homm3_import.json contains no entries." }
    $missing = New-Object System.Collections.Generic.List[string]
    $ownedSkinned = 0
    foreach ($entry in $entries) {
        $entryLabel = if ($entry.PSObject.Properties.Name -contains "sid" -and -not [string]::IsNullOrWhiteSpace([string]$entry.sid)) { [string]$entry.sid } else { "<unknown import entry>" }
        $bundleName = if ($entry.PSObject.Properties.Name -contains "bundleName") { [string]$entry.bundleName } else { "" }
        $entryMissing = New-Object System.Collections.Generic.List[string]
        if ([string]::IsNullOrWhiteSpace($bundleName)) { $entryMissing.Add("${entryLabel}: missing bundleName") }
        elseif (-not (Test-Path -LiteralPath (Join-Path (Join-Path $PayloadPlugin "homm3_bundles") $bundleName))) { $entryMissing.Add("${bundleName}: missing homm3_bundles/$bundleName") }

        $battleLabSid = Get-Homm3ImportLabSid $entry "battlePrefabAssetPath"
        if ([string]::IsNullOrWhiteSpace($battleLabSid)) { $entryMissing.Add("${entryLabel}: missing or malformed battlePrefabAssetPath homm3_lab SID") }
        elseif (-not (Test-Path -LiteralPath (Join-Path $PayloadPlugin "homm3_lab\$battleLabSid\Generated\BillboardAnim\array_battle_manifest.json")) -and
            -not (Test-Homm3ImportBundleManifestCoverage $PayloadPlugin $bundleName $battleLabSid $false)) {
            $entryMissing.Add("${bundleName}/${battleLabSid}: missing Generated/BillboardAnim/array_battle_manifest.json")
        }
        $mapLabSid = Get-Homm3ImportLabSid $entry "mapPrefabAssetPath"
        if ([string]::IsNullOrWhiteSpace($mapLabSid)) { $entryMissing.Add("${entryLabel}: missing or malformed mapPrefabAssetPath homm3_lab SID") }
        elseif (-not (Test-Path -LiteralPath (Join-Path $PayloadPlugin "homm3_lab\$mapLabSid\Generated\MapBillboard\array_map_manifest.json")) -and
            -not (Test-Homm3ImportBundleManifestCoverage $PayloadPlugin $bundleName $mapLabSid $true)) {
            $entryMissing.Add("${bundleName}/${mapLabSid}: missing Generated/MapBillboard/array_map_manifest.json")
        }
        if ($entryMissing.Count -gt 0) {
            if (Test-OwnedSkinnedCoverage $PayloadPlugin $entry $bundleName) { $ownedSkinned++ }
            else { foreach ($m in $entryMissing) { $missing.Add($m) } }
        }
    }
    if ($missing.Count -gt 0) {
        throw "Release payload is missing bundle/manifest coverage for imported HoMM3 units:$([Environment]::NewLine)$(($missing | Select-Object -First 30) -join [Environment]::NewLine)"
    }
    return [ordered]@{ entries = $entries.Count; coveredByOwnedSkinnedBundle = $ownedSkinned }
}

function Assert-ReleaseInputClean {
    foreach ($req in @(
            @((Join-Path $PayloadPlugin "OfflineUnlockMod.dll"), "OfflineUnlockMod.dll"),
            @((Join-Path $PayloadPlugin "custom_factions"), "custom_factions manifests"),
            @((Join-Path $PayloadPlugin "homm3_import.json"), "homm3_import.json"),
            @((Join-Path $PayloadPlugin "homm3_bundles"), "homm3_bundles"),
            @((Join-Path $PayloadPlugin "homm3_lab"), "homm3_lab runtime sidecars"),
            @((Join-Path $PayloadBepInEx "core\BepInEx.Unity.IL2CPP.dll"), "BepInEx IL2CPP core"),
            @((Join-Path $PayloadBepInEx ("unity-libs\" + (Get-UnityBaseLibsZipName $GameRoot))), "BepInEx unity-libs base library zip"),
            @((Join-Path $PayloadRoot "dotnet\coreclr.dll"), "Doorstop CoreCLR runtime"),
            @((Join-Path $PayloadRoot "winhttp.dll"), "Doorstop winhttp.dll"),
            @((Join-Path $OverlayDir "manifest.json"), "Core overlay manifest"),
            @((Join-Path $PayloadUnity "resources.assets"), "unity_data/resources.assets"),
            @((Join-Path $PayloadUnity "globalgamemanagers"), "unity_data/globalgamemanagers"),
            @((Join-Path $PayloadMetadata "global-metadata.dat"), "il2cpp_metadata/global-metadata.dat"),
            @((Join-Path $PayloadStreaming "maps\Story_maps"), "streaming_assets/maps/Story_maps"),
            @((Join-Path $PayloadStreaming "video"), "streaming_assets/video"))) {
        Require-Path $req[0] "Release payload is missing $($req[1])."
    }
    $config = Get-Content -LiteralPath (Join-Path $PayloadPlugin "config.json") -Raw | ConvertFrom-Json -DateKind String
    if (-not (($config.PSObject.Properties.Name -contains "releaseSafeProfile") -and $config.releaseSafeProfile)) { throw "Release payload config did not set releaseSafeProfile=true." }
    foreach ($key in @("autoLaunchOnMenu", "releaseSafeAutoLaunchOnMenu") + $ReleaseCandidateFalseConfigKeys) {
        if (($config.PSObject.Properties.Name -contains $key) -and $config.$key) { throw "Release payload config still has $key=true." }
    }
    if (-not ($config.modBugReporting -eq $true -and [string]$config.modBugReportingEndpoint -match $BugReportEndpointShape)) {
        throw "Release payload bug-report settings are not the approved shape."
    }
    $cfgText = Get-Content -LiteralPath (Join-Path $PayloadBepInEx "config\BepInEx.cfg") -Raw
    if ($cfgText -notmatch '(?m)^UnityLogListening\s*=\s*false\s*$') { throw "Release payload BepInEx.cfg did not set UnityLogListening=false." }
    $lab = Join-Path $PayloadPlugin "homm3_lab"
    if (@(Get-ChildItem -LiteralPath $lab -Recurse -File -Filter "array_battle_manifest.json" -Force).Count -le 0) { throw "homm3_lab sidecars contain no array_battle_manifest.json files." }
    if (@(Get-ChildItem -LiteralPath $lab -Recurse -File -Filter "array_map_manifest.json" -Force).Count -le 0) { throw "homm3_lab sidecars contain no array_map_manifest.json files." }
    $coverage = Assert-Homm3ImportSidecarCoverage $PayloadPlugin
    Assert-DllHasNoDebugProvenance (Join-Path $PayloadPlugin "OfflineUnlockMod.dll")
    if (Test-Path -LiteralPath (Join-Path $PayloadPlugin "OldenAiSim.dll")) { Assert-DllHasNoDebugProvenance (Join-Path $PayloadPlugin "OldenAiSim.dll") }
    return $coverage
}

function Timed([string] $name, [scriptblock] $body) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $result = & $body
    $sw.Stop()
    $report.steps[$name] = [ordered]@{ seconds = [Math]::Round($sw.Elapsed.TotalSeconds, 1); result = $result }
    Write-Host ("[stage] {0}: {1:N1}s" -f $name, $sw.Elapsed.TotalSeconds)
}

# ---- preconditions ------------------------------------------------------------------------------
$StageRoot = [IO.Path]::GetFullPath($StageRoot)
if (-not (Test-Path -LiteralPath $LiveParityStager)) { Fail 2 "no live-parity stager under -ToolsDir $ToolsDir" }
if (-not (Test-Path -LiteralPath $LeakTool)) { Fail 2 "missing $LeakTool" }
try {
    Require-Path (Join-Path $GameRoot "HeroesOldenEra.exe") "Game executable was not found under: $GameRoot"
    Require-Path $PluginSource "Deployed plugin folder was not found: $PluginSource"
    Require-Path $ReleaseCore "Modded Core.zip was not found: $ReleaseCore"
    Require-Path $CleanReleaseCore "Clean Core.zip was not found: $CleanReleaseCore"
    Require-Path $PluginDllOverride "Plugin DLL override was not found: $PluginDllOverride"
    foreach ($rel in 'BepInEx\core\BepInEx.Unity.IL2CPP.dll', 'dotnet\coreclr.dll', 'winhttp.dll', 'doorstop_config.ini') {
        Require-Path (Join-Path $GameRoot $rel) "$rel was not found under: $GameRoot"
    }
    Timed 'cleanCorePin' { Assert-PinnedCleanCore $CleanReleaseCore; Assert-CleanCoreHasNoHomm3Payload $CleanReleaseCore; 'ok' }
}
catch { Fail 30 $_.Exception.Message }

# ---- stage ----------------------------------------------------------------------------------------
try {
    if (Test-Path -LiteralPath $StageRoot) { Remove-Item -LiteralPath $StageRoot -Recurse -Force }
    foreach ($d in $PayloadPlugin, $PayloadRoot, $OverlayDir) { [void](New-Item -ItemType Directory -Path $d -Force) }

    Timed 'plugin' { Copy-FilteredDirectory $PluginSource $PayloadPlugin }
    Timed 'homm3Lab' { Copy-Homm3RuntimeLabAssets $PluginSource $PayloadPlugin }
    Timed 'config' { Set-PluginReleaseConfig $PayloadPlugin; 'ok' }
    Copy-Item -LiteralPath $PluginDllOverride -Destination (Join-Path $PayloadPlugin "OfflineUnlockMod.dll") -Force
    Timed 'dllScrub' {
        $out = @()
        foreach ($dllName in 'OfflineUnlockMod.dll', 'OldenAiSim.dll') {
            $dll = Join-Path $PayloadPlugin $dllName
            if (-not (Test-Path -LiteralPath $dll)) { continue }
            $o = & $python (Join-Path $ToolsDir 'scrub_release_candidate_dll.py') --dll $dll 2>&1
            if ($LASTEXITCODE -ne 0) { throw "scrub_release_candidate_dll.py failed for ${dllName}: $($o -join ' ')" }
            $out += "${dllName}: $(($o | Select-Object -Last 1))"
        }
        $out
    }
    Timed 'bepinexDoorstop' {
        Copy-Item -LiteralPath (Join-Path $GameRoot "BepInEx\core") -Destination $PayloadBepInEx -Recurse -Force
        if (Test-Path -LiteralPath (Join-Path $GameRoot "BepInEx\patchers")) {
            Copy-Item -LiteralPath (Join-Path $GameRoot "BepInEx\patchers") -Destination $PayloadBepInEx -Recurse -Force
        }
        Set-PayloadBepInExConfig $GameRoot $PayloadBepInEx
        [void](Copy-PayloadUnityBaseLibs $GameRoot $PayloadBepInEx)
        Copy-Item -LiteralPath (Join-Path $GameRoot "winhttp.dll") -Destination $PayloadRoot -Force
        Copy-Item -LiteralPath (Join-Path $GameRoot "dotnet") -Destination $PayloadRoot -Recurse -Force
        Copy-Item -LiteralPath (Join-Path $GameRoot "doorstop_config.ini") -Destination $PayloadRoot -Force
        if (Test-Path -LiteralPath (Join-Path $GameRoot ".doorstop_version")) {
            Copy-Item -LiteralPath (Join-Path $GameRoot ".doorstop_version") -Destination $PayloadRoot -Force
        }
        'ok'
    }
    Timed 'coreOverlay' {
        $o = & $python (Join-Path $ToolsDir 'export_official_deobf_release_core_overlay.py') `
            --vanilla-core (Resolve-Path -LiteralPath $CleanReleaseCore).Path `
            --modded-core (Resolve-Path -LiteralPath $ReleaseCore).Path `
            --out-dir $OverlayDir `
            --allowed-deleted-member "generator/content_pools/template_maneuvers_pools copy.json" `
            --force 2>&1
        if ($LASTEXITCODE -ne 0) { throw "core overlay export failed: $(($o | Select-Object -Last 5) -join ' ')" }
        [ordered]@{ operations = (Assert-OverlayMatchesPinnedCleanCore (Join-Path $OverlayDir "manifest.json")) }
    }
    Timed 'liveParity' {
        $o = & $python $LiveParityStager --game-root $GameRoot --stage-root $StageRoot 2>&1
        if ($LASTEXITCODE -ne 0) { throw "live-parity stager failed: $(($o | Select-Object -Last 5) -join ' ')" }
        @($o | Where-Object { "$_" -match '^(OK|PASS|staged streaming_assets)' } | ForEach-Object { "$_" })
    }
    Timed 'leftoverPrune' {
        # Belt and braces: StreamingAssets comes through the Python stager, which has its own filter.
        $pruned = @(Get-ChildItem -LiteralPath $StageRoot -Recurse -File -Force | Where-Object { Test-LeftoverFile $_.FullName })
        foreach ($f in $pruned) { Remove-Item -LiteralPath $f.FullName -Force }
        [ordered]@{ count = $pruned.Count; files = @($pruned | Select-Object -First 50 | ForEach-Object { $_.FullName.Substring($StageRoot.Length + 1) }) }
    }
}
catch { Fail 30 $_.Exception.Message }

# ---- sanitize + leak gate ---------------------------------------------------------------------------
$leakJson = if ($ReportPath) { [IO.Path]::ChangeExtension($ReportPath, '.leaks.json') } else { Join-Path (Split-Path $StageRoot) 'stage.leaks.json' }
try {
    Timed 'sanitizeJson' {
        $o = & $python $LeakTool fix --root $StageRoot --report "$leakJson.fix" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "payload_leaks.py fix failed: $(($o | Select-Object -Last 5) -join ' ')" }
        Get-Content -LiteralPath "$leakJson.fix" -Raw | ConvertFrom-Json -DateKind String
    }
}
catch { Fail 40 $_.Exception.Message }

try {
    Timed 'forbiddenFiles' { Assert-NoForbiddenPayloadFiles $StageRoot; 'ok' }
    Timed 'releaseInputClean' { Assert-ReleaseInputClean }
    Timed 'liveParityValidate' {
        $o = & $python $LiveParityStager --game-root $GameRoot --stage-root $StageRoot --validate-only 2>&1
        if ($LASTEXITCODE -ne 0) { throw "live-parity validate failed: $(($o | Select-Object -Last 5) -join ' ')" }
        'ok'
    }
}
catch { Fail 30 $_.Exception.Message }

try {
    Timed 'leakScan' {
        $termArgs = @(); foreach ($t in $LeakTerm) { if ($t) { $termArgs += @('--term', $t) } }
        $o = & $python $LeakTool scan --root $StageRoot --report $leakJson @termArgs 2>&1
        $code = $LASTEXITCODE
        $scan = Get-Content -LiteralPath $leakJson -Raw | ConvertFrom-Json -DateKind String
        if ($code -ne 0) { throw "leak scan found $($scan.hitCount) hit(s); first: $(($scan.hits | Select-Object -First 5 | ForEach-Object { "$($_.file) [$($_.rule)]" }) -join '; ')" }
        [ordered]@{ filesScanned = $scan.filesScanned; bytesScanned = $scan.bytesScanned; hits = $scan.hitCount }
    }
}
catch { Fail 40 $_.Exception.Message }

$bytes = (Get-ChildItem -LiteralPath $StageRoot -Recurse -File -Force | Measure-Object Length -Sum)
$report.stageBytes = [int64]$bytes.Sum
$report.stageFiles = $bytes.Count
$report.status = 'pass'
$report.exitCode = 0
Save-Report
Write-Host ("NIGHTLY STAGE: PASS {0:N0} files, {1:N0} bytes" -f $bytes.Count, $bytes.Sum)
exit 0
