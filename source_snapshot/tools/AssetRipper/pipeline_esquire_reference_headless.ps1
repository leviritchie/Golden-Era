# Headless pipeline: AssetRipper bootstrap (optional) -> export HeroesOE_Data -> copy stock battle controller into Unity Reference.
param(
  [string]$ToolsRipperRoot = $PSScriptRoot,
  [string]$GameDataPath = "V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data",
  [string]$ExportPath = "",
  [string]$UnityProject = "C:\Users\<user>\oldenera_factions",
  [string]$ReferenceRelative = "Assets\CustomUnits\esquire\Reference",
  [switch]$SkipBootstrap,
  [switch]$SkipExport,
  [switch]$ForceExport,
  [switch]$RunUnityRebuild,
  [string]$UnityExe = "$env:ProgramFiles\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe",
  [string]$CustomPrefabPipeline = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ExportPath)) {
  $ExportPath = Join-Path $ToolsRipperRoot "..\reference\assetripper_olden_demo_unity"
}
$ExportPath = [System.IO.Path]::GetFullPath($ExportPath)

if ([string]::IsNullOrWhiteSpace($CustomPrefabPipeline)) {
  $CustomPrefabPipeline = Join-Path $ToolsRipperRoot "..\custom_prefab_pipeline"
}
$CustomPrefabPipeline = [System.IO.Path]::GetFullPath($CustomPrefabPipeline)

$arExe = Join-Path $ToolsRipperRoot "dist\AssetRipper.GUI.Free.exe"

if (-not $SkipBootstrap) {
  Write-Host "=== bootstrap.cmd ==="
  $boot = Join-Path $ToolsRipperRoot "bootstrap.cmd"
  $p = Start-Process -FilePath $boot -WorkingDirectory $ToolsRipperRoot -Wait -NoNewWindow -PassThru
  if ($p.ExitCode -ne 0) { throw "bootstrap.cmd failed with exit $($p.ExitCode)" }
}

if (-not (Test-Path -LiteralPath $arExe)) { throw "AssetRipper missing after bootstrap: $arExe" }

$assetsMarker = Join-Path $ExportPath "Assets"
$doExport = -not $SkipExport -and ($ForceExport -or -not (Test-Path -LiteralPath $assetsMarker))

if ($doExport) {
  if (-not (Test-Path -LiteralPath $GameDataPath)) { throw "Game data not found: $GameDataPath" }
  Write-Host "=== export_heroesoe_unity_project (long) ==="
  & (Join-Path $ToolsRipperRoot "export_heroesoe_unity_project.ps1") `
    -ArExe $arExe -GameDataPath $GameDataPath -ExportPath $ExportPath
}
else {
  Write-Host "Skipping export (existing export or -SkipExport). Using: $ExportPath"
}

Write-Host "=== select_and_copy_esquire_stock_controller ==="
& (Join-Path $ToolsRipperRoot "select_and_copy_esquire_stock_controller.ps1") `
  -ExportRoot $ExportPath -UnityProjectRoot $UnityProject -ReferenceRelative $ReferenceRelative

if ($RunUnityRebuild) {
  if (-not (Test-Path -LiteralPath $UnityExe)) { throw "Unity editor not found: $UnityExe (edit -UnityExe)" }
  $bundleCmd = Join-Path $CustomPrefabPipeline "build_esquire_bundle.cmd"
  if (-not (Test-Path -LiteralPath $bundleCmd)) { throw "Missing $bundleCmd" }
  Write-Host "=== build_esquire_bundle.cmd ==="
  $bp = Start-Process -FilePath $bundleCmd -WorkingDirectory $CustomPrefabPipeline -Wait -NoNewWindow -PassThru
  if ($bp.ExitCode -ne 0) { throw "build_esquire_bundle.cmd failed with exit $($bp.ExitCode)" }
}

Write-Host "Pipeline finished."
