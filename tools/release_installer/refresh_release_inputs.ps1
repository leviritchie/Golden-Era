param(
    [string]$GameRoot = "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era",
    [Parameter(Mandatory = $true)]
    [string]$CleanReleaseCore,
    [string]$OutputZip = "release_inputs\golden_era_release_payload.zip",
    [string]$PluginDllOverride
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StageRoot = Join-Path $RepoRoot "dist\_golden_era_release_input_stage"
$ReleaseCore = Join-Path $GameRoot "HeroesOldenEra_Data\StreamingAssets\Core.zip"
$PluginSource = Join-Path $GameRoot "BepInEx\plugins\OfflineUnlockMod"
$PayloadPlugin = Join-Path $StageRoot "payload\BepInEx\plugins\OfflineUnlockMod"
$PayloadBepInEx = Join-Path $StageRoot "payload\BepInEx"
$PayloadRoot = Join-Path $StageRoot "payload\game_root"
$OverlayDir = Join-Path $StageRoot "core_overlay"
$OutputZipPath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputZip))
$OutputShaPath = "$OutputZipPath.sha256"

function Require-Path($Path, $Message) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw $Message
    }
}

function Test-ExcludedPayloadFile($Path) {
    $name = [System.IO.Path]::GetFileName($Path)
    $lowerName = $name.ToLowerInvariant()
    $lowerPath = $Path.ToLowerInvariant()
    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()

    if ($lowerPath -match "\\__pycache__\\") { return $true }
    if ($lowerPath -match "\\histogram_icons\\") { return $true }
    if ($lowerName -match "backup") { return $true }
    if ($lowerName -match "\.disabled") { return $true }
    if ($extension -in @(".log", ".flag", ".pdb", ".py", ".pyc", ".meta", ".tmp")) { return $true }
    return $false
}

function Copy-FilteredDirectory($Source, $Destination) {
    $sourceRoot = (Resolve-Path -LiteralPath $Source).Path.TrimEnd("\")
    $files = Get-ChildItem -LiteralPath $sourceRoot -Recurse -File -Force
    $copied = 0
    $excluded = 0
    foreach ($file in $files) {
        if (Test-ExcludedPayloadFile $file.FullName) {
            $excluded++
            continue
        }

        $relative = $file.FullName.Substring($sourceRoot.Length).TrimStart("\")
        $target = Join-Path $Destination $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        $copied++
    }
    Write-Host "Copied $copied plugin file(s); excluded $excluded maintainer/build artifact(s)."
}

function Assert-NoForbiddenPayloadFiles($Root) {
    $bad = Get-ChildItem -LiteralPath $Root -Recurse -File -Force | Where-Object {
        Test-ExcludedPayloadFile $_.FullName
    }
    if ($bad) {
        $sample = ($bad | Select-Object -First 20 | ForEach-Object { "  - $($_.FullName)" }) -join [Environment]::NewLine
        throw "Forbidden files reached the release payload:$([Environment]::NewLine)$sample"
    }
}

function Assert-NoPrivateTextLeaks($Root) {
    $textExtensions = @(".json", ".txt", ".cfg", ".ini", ".xml", ".yml", ".yaml", ".md", ".manifest")
    $patterns = @(
        "V:\",
        "C:\Users\levir",
        "Olden Era Playtest Tweak",
        "golden_era_release_repo",
        "CodexSandbox"
    )
    $bad = New-Object "System.Collections.Generic.List[string]"
    Get-ChildItem -LiteralPath $Root -Recurse -File -Force | Where-Object {
        $textExtensions -contains $_.Extension.ToLowerInvariant()
    } | ForEach-Object {
        $text = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue
        if ($null -eq $text) { return }
        foreach ($pattern in $patterns) {
            if ($text.Contains($pattern)) {
                [void]$bad.Add("$($_.FullName) contains $pattern")
                break
            }
        }
    }
    if ($bad.Count -gt 0) {
        $sample = ($bad | Select-Object -First 20 | ForEach-Object { "  - $_" }) -join [Environment]::NewLine
        throw "Private/local path text reached the release payload:$([Environment]::NewLine)$sample"
    }
}

function Remove-DamageHistogramConfig($PluginRoot) {
    $configPath = Join-Path $PluginRoot "config.json"
    if (-not (Test-Path -LiteralPath $configPath)) {
        return
    }

    $json = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $removed = 0
    $properties = @($json.PSObject.Properties | Where-Object {
        $_.Name -eq "damageHistograms" -or $_.Name.StartsWith("damageHistogram", [System.StringComparison]::OrdinalIgnoreCase)
    })
    foreach ($property in $properties) {
        $json.PSObject.Properties.Remove($property.Name)
        $removed++
    }

    if ($removed -gt 0) {
        $json | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $configPath -Encoding UTF8
    }
    Write-Host "Removed $removed damage histogram config key(s) from Golden Era payload config."
}

function Assert-NoDamageHistogramPayload($Root) {
    $badPaths = Get-ChildItem -LiteralPath $Root -Recurse -Force | Where-Object {
        $_.FullName.ToLowerInvariant() -match "\\histogram_icons(\\|$)" -or
        $_.Name -match "DamageHistogramMod"
    }
    if ($badPaths) {
        $sample = ($badPaths | Select-Object -First 20 | ForEach-Object { "  - $($_.FullName)" }) -join [Environment]::NewLine
        throw "Damage histogram payload files reached the Golden Era release payload:$([Environment]::NewLine)$sample"
    }

    $badConfig = Get-ChildItem -LiteralPath $Root -Recurse -File -Filter "config.json" -Force | Where-Object {
        Select-String -LiteralPath $_.FullName -Pattern "damageHistograms|damageHistogram" -Quiet
    }
    if ($badConfig) {
        $sample = ($badConfig | Select-Object -First 20 | ForEach-Object { "  - $($_.FullName)" }) -join [Environment]::NewLine
        throw "Damage histogram config keys reached the Golden Era release payload:$([Environment]::NewLine)$sample"
    }
}

function ConvertTo-SanitizedJsonValue($Value) {
    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [string]) {
        if ($Value -match '^[A-Za-z]:\\' -or
            $Value -match '\\Users\\levir' -or
            $Value -match 'Olden Era Playtest Tweak' -or
            $Value -match 'golden_era_release_repo' -or
            $Value -match 'CodexSandbox') {
            return "<sanitized-local-path>"
        }
        return $Value
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $out = [ordered]@{}
        foreach ($key in $Value.Keys) {
            $out[$key] = ConvertTo-SanitizedJsonValue $Value[$key]
        }
        return $out
    }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $out = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) {
            $out[$property.Name] = ConvertTo-SanitizedJsonValue $property.Value
        }
        return $out
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $array = @()
        foreach ($item in $Value) {
            $array += ConvertTo-SanitizedJsonValue $item
        }
        return $array
    }
    return $Value
}

function Sanitize-JsonTextPayloads($Root) {
    $patterns = @(
        "V:\",
        "C:\Users\levir",
        "Olden Era Playtest Tweak",
        "golden_era_release_repo",
        "CodexSandbox"
    )
    $changed = 0
    Get-ChildItem -LiteralPath $Root -Recurse -File -Filter "*.json" -Force | ForEach-Object {
        $text = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue
        if ($null -eq $text) { return }
        $hasPrivatePath = $false
        foreach ($pattern in $patterns) {
            if ($text.Contains($pattern)) {
                $hasPrivatePath = $true
                break
            }
        }
        if (-not $hasPrivatePath) { return }

        try {
            $json = $text | ConvertFrom-Json
            $sanitized = ConvertTo-SanitizedJsonValue $json
            $sanitized | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $_.FullName -Encoding UTF8
            $changed++
        }
        catch {
            throw "Could not sanitize JSON path leaks in $($_.FullName): $($_.Exception.Message)"
        }
    }
    Write-Host "Sanitized $changed JSON file(s) containing local build paths."
}

Require-Path (Join-Path $GameRoot "HeroesOldenEra.exe") "Release game executable was not found under: $GameRoot"
Require-Path $PluginSource "Deployed plugin folder was not found: $PluginSource"
Require-Path $ReleaseCore "Modded release Core.zip was not found: $ReleaseCore"
Require-Path $CleanReleaseCore "Clean release Core.zip was not found: $CleanReleaseCore"
Require-Path (Join-Path $GameRoot "BepInEx\core\BepInEx.Unity.IL2CPP.dll") "BepInEx IL2CPP core was not found under: $GameRoot"
Require-Path (Join-Path $GameRoot "dotnet\coreclr.dll") "Doorstop CoreCLR runtime was not found under: $GameRoot"
Require-Path (Join-Path $GameRoot "winhttp.dll") "Doorstop winhttp.dll was not found under: $GameRoot"
Require-Path (Join-Path $GameRoot "doorstop_config.ini") "Doorstop config was not found under: $GameRoot"

if (Test-Path -LiteralPath $StageRoot) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $PayloadPlugin -Force | Out-Null
New-Item -ItemType Directory -Path $PayloadRoot -Force | Out-Null
New-Item -ItemType Directory -Path $OverlayDir -Force | Out-Null

Copy-FilteredDirectory $PluginSource $PayloadPlugin
Remove-DamageHistogramConfig $PayloadPlugin
if ($PluginDllOverride) {
    Require-Path $PluginDllOverride "Plugin DLL override was not found: $PluginDllOverride"
    Copy-Item -LiteralPath $PluginDllOverride -Destination (Join-Path $PayloadPlugin "OfflineUnlockMod.dll") -Force
}

Copy-Item -LiteralPath (Join-Path $GameRoot "BepInEx\core") -Destination $PayloadBepInEx -Recurse -Force
if (Test-Path -LiteralPath (Join-Path $GameRoot "BepInEx\patchers")) {
    Copy-Item -LiteralPath (Join-Path $GameRoot "BepInEx\patchers") -Destination $PayloadBepInEx -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $PayloadBepInEx "config") -Force | Out-Null
$sourceBepInExCfg = Join-Path $GameRoot "BepInEx\config\BepInEx.cfg"
if (Test-Path -LiteralPath $sourceBepInExCfg) {
    $cfg = Get-Content -LiteralPath $sourceBepInExCfg -Raw
    $cfg = $cfg -replace '(?m)^UnityLogListening\s*=.*$', 'UnityLogListening = false'
    Set-Content -LiteralPath (Join-Path $PayloadBepInEx "config\BepInEx.cfg") -Value $cfg -Encoding UTF8
}
else {
    Set-Content -LiteralPath (Join-Path $PayloadBepInEx "config\BepInEx.cfg") -Value "UnityLogListening = false" -Encoding UTF8
}

Copy-Item -LiteralPath (Join-Path $GameRoot "winhttp.dll") -Destination $PayloadRoot -Force
Copy-Item -LiteralPath (Join-Path $GameRoot "dotnet") -Destination $PayloadRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $GameRoot "doorstop_config.ini") -Destination $PayloadRoot -Force
if (Test-Path -LiteralPath (Join-Path $GameRoot ".doorstop_version")) {
    Copy-Item -LiteralPath (Join-Path $GameRoot ".doorstop_version") -Destination $PayloadRoot -Force
}

& python (Join-Path $PSScriptRoot "export_release_core_overlay.py") `
    --vanilla-core (Resolve-Path -LiteralPath $CleanReleaseCore).Path `
    --modded-core (Resolve-Path -LiteralPath $ReleaseCore).Path `
    --out-dir $OverlayDir `
    --force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Require-Path (Join-Path $PayloadPlugin "OfflineUnlockMod.dll") "Release payload is missing OfflineUnlockMod.dll."
Require-Path (Join-Path $PayloadPlugin "custom_factions") "Release payload is missing custom_factions manifests."
Require-Path (Join-Path $PayloadPlugin "homm3_import.json") "Release payload is missing homm3_import.json."
Require-Path (Join-Path $PayloadPlugin "homm3_bundles") "Release payload is missing homm3_bundles."
Require-Path (Join-Path $PayloadBepInEx "core\BepInEx.Unity.IL2CPP.dll") "Release payload is missing BepInEx IL2CPP core."
Require-Path (Join-Path $PayloadRoot "dotnet\coreclr.dll") "Release payload is missing Doorstop CoreCLR runtime."
Require-Path (Join-Path $OverlayDir "manifest.json") "Release payload is missing Core overlay manifest."

Sanitize-JsonTextPayloads $StageRoot
Assert-NoForbiddenPayloadFiles $StageRoot
Assert-NoDamageHistogramPayload $StageRoot
Assert-NoPrivateTextLeaks $StageRoot

if (Test-Path -LiteralPath $OutputZipPath) {
    Remove-Item -LiteralPath $OutputZipPath -Force
}
if (Test-Path -LiteralPath $OutputShaPath) {
    Remove-Item -LiteralPath $OutputShaPath -Force
}
New-Item -ItemType Directory -Path (Split-Path -Parent $OutputZipPath) -Force | Out-Null

Compress-Archive -Path (Join-Path $StageRoot "*") -DestinationPath $OutputZipPath -Force
$zipHash = (Get-FileHash -LiteralPath $OutputZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $OutputShaPath -Value "$zipHash  $(Split-Path -Leaf $OutputZipPath)" -Encoding ASCII

Write-Host "Wrote release input zip: $OutputZipPath"
Write-Host "Release input SHA-256: $zipHash"
