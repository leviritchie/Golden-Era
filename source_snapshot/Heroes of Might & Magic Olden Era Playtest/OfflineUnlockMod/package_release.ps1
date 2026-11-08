# Builds Release and zips a public distribution: plugin DLL, deps, README, config example.
# Run:  .\package_release.ps1
# Or:   powershell -ExecutionPolicy Bypass -File package_release.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$verLine = Select-String -Path (Join-Path $root "Plugin.cs") -Pattern 'const string PluginVersion = "([^"]+)"' | Select-Object -First 1
if (-not $verLine) { throw "Could not read PluginVersion from Plugin.cs" }
$ver = $verLine.Matches[0].Groups[1].Value
Write-Host "Plugin version: $ver"

# Skip copying into the live game folder (often locked); output in bin\Release is enough for the zip.
& dotnet build -c Release -p:DeployPluginToGame=false
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$bin = Join-Path $root "bin\Release\netstandard2.1"
$dll = Join-Path $bin "OfflineUnlockMod.dll"
$deps = Join-Path $bin "OfflineUnlockMod.deps.json"
if (-not (Test-Path $dll)) { throw "Missing build output: OfflineUnlockMod.dll" }
if (-not (Test-Path $deps)) { throw "Missing build output: OfflineUnlockMod.deps.json" }

$outDir = Join-Path $root "dist_package"
$pluginDir = Join-Path $outDir "BepInEx\plugins\OfflineUnlockMod"
Remove-Item -Recurse -Force $outDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $pluginDir -Force | Out-Null
Copy-Item -Force $dll $pluginDir
Copy-Item -Force $deps $pluginDir
Copy-Item -Force (Join-Path $root "publish\config.json.example") $pluginDir
Copy-Item -Recurse -Force (Join-Path $root "histogram_icons") $pluginDir
Copy-Item -Recurse -Force (Join-Path $root "homm3_runtime_assets") $pluginDir
Copy-Item -Recurse -Force (Join-Path $root "homm3_town_prefabs") $pluginDir
Copy-Item -Force (Join-Path $root "publish\README-INSTALL.txt") $outDir

$zipName = "HeroesOE-DamageHistogram-v$ver.zip"
$zipPath = Join-Path $root $zipName
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path (Join-Path $outDir "*") -DestinationPath $zipPath
Remove-Item -Recurse -Force $outDir

Write-Host "Created: $zipPath"
Get-Item $zipPath | Format-List Name, Length, LastWriteTime
