param(
    [string]$ReleaseInputZip = "release_inputs\golden_era_release_payload.zip",
    [string]$OutputRoot = "dist\local-test",
    [string]$PackageVersion = "",
    [string]$InstallerNameSuffix = "",
    [ValidateSet("", "true", "false")]
    [string]$Homm3UseUpscaledHeroPortraits = "",
    [ValidateSet("Embedded", "Download")]
    [string]$PayloadMode = "Download",
    [string]$GitHubOwner = "leviritchie",
    [string]$GitHubRepo = "Golden-Era",
    [string]$PayloadBaseName = "",
    [long]$MaxPartBytes = 1900000000,
    [switch]$CreateZip
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ReleaseInputZipPath = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $ReleaseInputZip))
$ReleaseInputShaPath = "$ReleaseInputZipPath.sha256"
$WizardProject = Join-Path $RepoRoot "tools\release_installer\wizard\StrongholdModInstaller.csproj"
$StageRoot = Join-Path $RepoRoot $OutputRoot
$StageFullPath = [System.IO.Path]::GetFullPath($StageRoot)
$DistRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot "dist"))
$AssembleScript = Join-Path $PSScriptRoot "assemble_release_input.ps1"

Add-Type -AssemblyName System.IO.Compression.FileSystem

function Require-Path($Path, $Message) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw $Message
    }
}

function Require-ZipEntry($Zip, $EntryName, $Message) {
    $normalized = $EntryName.Replace("/", "\")
    $entry = $Zip.Entries | Where-Object { $_.FullName -eq $EntryName -or $_.FullName -eq $normalized } | Select-Object -First 1
    if ($null -eq $entry) {
        throw $Message
    }
}

function Convert-VersionForAssembly($Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return "0.0.0"
    }

    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith("v")) {
        $trimmed = $trimmed.Substring(1)
    }
    $match = [regex]::Match($trimmed, "^\d+(\.\d+){0,3}")
    if (-not $match.Success) {
        return "0.0.0"
    }

    $parts = $match.Value.Split(".")
    while ($parts.Count -lt 3) {
        $parts += "0"
    }
    return ($parts | Select-Object -First 4) -join "."
}

function Copy-Stream($Source, $Destination) {
    $buffer = New-Object byte[] 81920
    while (($read = $Source.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $Destination.Write($buffer, 0, $read)
    }
}

function Set-JsonBooleanProperty($Json, $Name, [bool]$Value) {
    $property = $Json.PSObject.Properties[$Name]
    if ($null -eq $property) {
        Add-Member -InputObject $Json -MemberType NoteProperty -Name $Name -Value $Value
    }
    else {
        $Json.$Name = $Value
    }
}

function New-ReleaseInputVariantZip($SourceZipPath, $DestinationZipPath, [bool]$UseUpscaledHeroPortraits) {
    $configEntryName = "payload/BepInEx/plugins/OfflineUnlockMod/config.json"
    $configWasRewritten = $false

    if (Test-Path -LiteralPath $DestinationZipPath) {
        Remove-Item -LiteralPath $DestinationZipPath -Force
    }

    $sourceZip = [System.IO.Compression.ZipFile]::OpenRead($SourceZipPath)
    try {
        $destinationZip = [System.IO.Compression.ZipFile]::Open($DestinationZipPath, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            foreach ($entry in $sourceZip.Entries) {
                $newEntry = $destinationZip.CreateEntry($entry.FullName, [System.IO.Compression.CompressionLevel]::Optimal)
                $normalized = $entry.FullName.Replace("\", "/")
                if ($normalized -eq $configEntryName) {
                    $reader = [System.IO.StreamReader]::new($entry.Open(), [System.Text.Encoding]::UTF8)
                    try {
                        $jsonText = $reader.ReadToEnd()
                    }
                    finally {
                        $reader.Dispose()
                    }

                    $json = $jsonText | ConvertFrom-Json
                    Set-JsonBooleanProperty $json "homm3UseUpscaledHeroPortraits" $UseUpscaledHeroPortraits
                    $newJsonText = ($json | ConvertTo-Json -Depth 100)
                    $writer = [System.IO.StreamWriter]::new($newEntry.Open(), [System.Text.UTF8Encoding]::new($false))
                    try {
                        $writer.Write($newJsonText)
                    }
                    finally {
                        $writer.Dispose()
                    }
                    $configWasRewritten = $true
                }
                else {
                    $sourceStream = $entry.Open()
                    try {
                        $destinationStream = $newEntry.Open()
                        try {
                            Copy-Stream $sourceStream $destinationStream
                        }
                        finally {
                            $destinationStream.Dispose()
                        }
                    }
                    finally {
                        $sourceStream.Dispose()
                    }
                }
            }
        }
        finally {
            $destinationZip.Dispose()
        }
    }
    finally {
        $sourceZip.Dispose()
    }

    if (-not $configWasRewritten) {
        throw "Release input payload is missing OfflineUnlockMod config.json; cannot create portrait variant."
    }
}

Require-Path $AssembleScript "Release-input assembler was not found: $AssembleScript"
& powershell -ExecutionPolicy Bypass -File $AssembleScript `
    -ReleaseInputsDir (Split-Path -Parent $ReleaseInputZipPath) `
    -OutputZipName (Split-Path -Leaf $ReleaseInputZipPath)
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Require-Path $ReleaseInputZipPath "Release input zip was not found: $ReleaseInputZipPath"
Require-Path $ReleaseInputShaPath "Release input checksum was not found: $ReleaseInputShaPath"
Require-Path $WizardProject "Installer wizard project was not found: $WizardProject"

if (-not $StageFullPath.StartsWith($DistRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to stage outside repo dist folder: $StageFullPath"
}

$expected = (Get-Content -LiteralPath $ReleaseInputShaPath).Split(" ")[0].Trim().ToLowerInvariant()
$actual = (Get-FileHash -LiteralPath $ReleaseInputZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    throw "release input checksum mismatch: expected $expected actual $actual"
}

if ([string]::IsNullOrWhiteSpace($PackageVersion)) {
    if ($env:GITHUB_REF_TYPE -eq "tag" -and $env:GITHUB_REF_NAME) {
        $PackageVersion = $env:GITHUB_REF_NAME
    }
    else {
        $PackageVersion = "local-test"
    }
}

if (Test-Path -LiteralPath $StageFullPath) {
    Remove-Item -LiteralPath $StageFullPath -Recurse -Force
}
New-Item -ItemType Directory -Path $StageFullPath -Force | Out-Null

$EffectiveReleaseInputZipPath = $ReleaseInputZipPath
$payloadShaForFooter = $actual
if ($PayloadMode -eq "Embedded" -and $Homm3UseUpscaledHeroPortraits -ne "") {
    $variantRoot = Join-Path $DistRoot "_release_input_variants"
    New-Item -ItemType Directory -Path $variantRoot -Force | Out-Null
    $variantSuffix = $InstallerNameSuffix
    if ([string]::IsNullOrWhiteSpace($variantSuffix)) {
        $variantSuffix = "-portrait-variant"
    }
    $variantName = "golden_era_release_payload-$PackageVersion$variantSuffix.zip"
    $variantName = ($variantName -replace '[<>:"/\\|?*]', '_')
    $EffectiveReleaseInputZipPath = Join-Path $variantRoot $variantName
    $useUpscaled = $Homm3UseUpscaledHeroPortraits -eq "true"
    New-ReleaseInputVariantZip $ReleaseInputZipPath $EffectiveReleaseInputZipPath $useUpscaled
    $payloadShaForFooter = (Get-FileHash -LiteralPath $EffectiveReleaseInputZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
elseif ($PayloadMode -eq "Download" -and $Homm3UseUpscaledHeroPortraits -eq "") {
    throw "Download payload mode requires -Homm3UseUpscaledHeroPortraits true|false so the thin installer can apply the portrait SKU."
}

$zip = [System.IO.Compression.ZipFile]::OpenRead($EffectiveReleaseInputZipPath)
try {
    Require-ZipEntry $zip "payload/BepInEx/plugins/OfflineUnlockMod/OfflineUnlockMod.dll" "Release inputs are missing OfflineUnlockMod.dll."
    Require-ZipEntry $zip "payload/BepInEx/core/BepInEx.Unity.IL2CPP.dll" "Release inputs are missing BepInEx IL2CPP core."
    Require-ZipEntry $zip "payload/game_root/dotnet/coreclr.dll" "Release inputs are missing Doorstop CoreCLR runtime."
    Require-ZipEntry $zip "payload/game_root/winhttp.dll" "Release inputs are missing Doorstop winhttp.dll."
    Require-ZipEntry $zip "payload/unity_data/resources.assets" "Release inputs are missing unity_data/resources.assets."
    Require-ZipEntry $zip "payload/unity_data/globalgamemanagers" "Release inputs are missing unity_data/globalgamemanagers."
    Require-ZipEntry $zip "payload/il2cpp_metadata/global-metadata.dat" "Release inputs are missing il2cpp_metadata/global-metadata.dat."
    Require-ZipEntry $zip "core_overlay/manifest.json" "Release inputs are missing the generated Core overlay manifest."
    $hasStoryMaps = @($zip.Entries | Where-Object {
        $_.FullName.Replace("\", "/") -like "payload/streaming_assets/maps/Story_maps/*"
    }).Count -gt 0
    if (-not $hasStoryMaps) {
        throw "Release inputs are missing streaming_assets/maps/Story_maps content."
    }
    $hasVideo = @($zip.Entries | Where-Object {
        $_.FullName.Replace("\", "/") -like "payload/streaming_assets/video/*"
    }).Count -gt 0
    if (-not $hasVideo) {
        throw "Release inputs are missing streaming_assets/video content."
    }
}
finally {
    $zip.Dispose()
}

$assemblyVersion = Convert-VersionForAssembly $PackageVersion
& dotnet publish $WizardProject `
    -c Release `
    -r win-x64 `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:PublishTrimmed=false `
    -p:DebugType=None `
    -p:DebugSymbols=false `
    -p:Version="$assemblyVersion" `
    -p:AssemblyVersion="$assemblyVersion" `
    -p:FileVersion="$assemblyVersion" `
    -p:InformationalVersion="$PackageVersion" `
    -o $StageFullPath `
    --nologo
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$rawExePath = Join-Path $StageFullPath "GoldenEraModInstaller.exe"
$installerName = "GoldenEraModInstaller-$PackageVersion$InstallerNameSuffix.exe"
$installerName = ($installerName -replace '[<>:"/\\|?*]', '_')
$installerPath = Join-Path $StageFullPath $installerName
Move-Item -LiteralPath $rawExePath -Destination $installerPath -Force

if ($PayloadMode -eq "Embedded") {
    $payloadLength = (Get-Item -LiteralPath $EffectiveReleaseInputZipPath).Length
    $installerStream = [System.IO.File]::Open($installerPath, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $payloadStream = [System.IO.File]::OpenRead($EffectiveReleaseInputZipPath)
        try {
            $payloadStream.CopyTo($installerStream)
        }
        finally {
            $payloadStream.Dispose()
        }

        $hashBytes = [System.Text.Encoding]::ASCII.GetBytes($payloadShaForFooter)
        if ($hashBytes.Length -ne 64) {
            throw "Release input SHA-256 footer must be 64 ASCII bytes."
        }
        $lengthBytes = [System.BitConverter]::GetBytes([int64]$payloadLength)
        $magicBytes = [System.Text.Encoding]::ASCII.GetBytes("GERAPKG1")
        $installerStream.Write($hashBytes, 0, $hashBytes.Length)
        $installerStream.Write($lengthBytes, 0, $lengthBytes.Length)
        $installerStream.Write($magicBytes, 0, $magicBytes.Length)
    }
    finally {
        $installerStream.Dispose()
    }
}
elseif ($PayloadMode -eq "Download") {
    if ([string]::IsNullOrWhiteSpace($PayloadBaseName)) {
        $PayloadBaseName = "golden_era_release_payload-$PackageVersion.zip"
        $PayloadBaseName = ($PayloadBaseName -replace '[<>:"/\\|?*]', '_')
    }

    $payloadLength = [long](Get-Item -LiteralPath $ReleaseInputZipPath).Length
    $partNames = New-Object System.Collections.Generic.List[string]
    if ($payloadLength -le $MaxPartBytes) {
        $partNames.Add($PayloadBaseName) | Out-Null
    }
    else {
        $partCount = [int][Math]::Ceiling($payloadLength / [double]$MaxPartBytes)
        for ($i = 1; $i -le $partCount; $i++) {
            $partNames.Add(("{0}.part{1:D2}" -f $PayloadBaseName, $i)) | Out-Null
        }
    }

    $useUpscaled = $Homm3UseUpscaledHeroPortraits -eq "true"
    $downloadManifest = [ordered]@{
        schema = "golden_era_payload_download/v1"
        githubOwner = $GitHubOwner
        githubRepo = $GitHubRepo
        releaseTag = $PackageVersion
        payloadBaseName = $PayloadBaseName
        expectedSha256 = $actual
        expectedBytes = $payloadLength
        parts = @($partNames)
        homm3UseUpscaledHeroPortraits = $useUpscaled
    }

    $json = ($downloadManifest | ConvertTo-Json -Depth 8 -Compress)
    $jsonBytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $installerStream = [System.IO.File]::Open($installerPath, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $installerStream.Write($jsonBytes, 0, $jsonBytes.Length)
        $lengthBytes = [System.BitConverter]::GetBytes([int64]$jsonBytes.Length)
        $magicBytes = [System.Text.Encoding]::ASCII.GetBytes("GERADL01")
        if ($magicBytes.Length -ne 8) {
            throw "Download footer magic must be exactly 8 ASCII bytes."
        }
        $installerStream.Write($lengthBytes, 0, $lengthBytes.Length)
        $installerStream.Write($magicBytes, 0, $magicBytes.Length)
    }
    finally {
        $installerStream.Dispose()
    }

    $manifestOut = Join-Path $StageFullPath ($installerName + ".download-manifest.json")
    ($downloadManifest | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $manifestOut -Encoding utf8
    Write-Host "Appended GitHub download manifest ($($jsonBytes.Length) bytes) for $PayloadBaseName"
}
else {
    throw "Unknown PayloadMode: $PayloadMode"
}

$exeHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$installerPath.sha256" -Value "$exeHash  $(Split-Path -Leaf $installerPath)" -Encoding ASCII

Write-Host "Created installer ($PayloadMode): $installerPath"
Write-Host "Installer SHA-256: $exeHash"
Write-Host "Release input SHA-256: $actual"
Write-Host "Installer size: $((Get-Item -LiteralPath $installerPath).Length) bytes"
if ($Homm3UseUpscaledHeroPortraits -ne "") {
    Write-Host "homm3UseUpscaledHeroPortraits override: $Homm3UseUpscaledHeroPortraits"
}

if ($CreateZip) {
    Write-Warning "-CreateZip is deprecated and ignored."
}
