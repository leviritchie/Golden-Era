# Resolve the stock *battle* AnimatorController from AssetRipper export (Esquire.prefab -> runtime controller -> base controller).
param(
  [Parameter(Mandatory = $true)][string]$ExportRoot,
  [Parameter(Mandatory = $true)][string]$UnityProjectRoot,
  [Parameter(Mandatory = $false)][string]$ReferenceRelative = "Assets\CustomUnits\esquire\Reference",
  [string]$TargetFileName = "StockEsquireBattle.controller"
)

$ErrorActionPreference = "Stop"

function Build-MetaGuidIndex {
  param([string]$Root)
  $map = @{}
  Get-ChildItem -LiteralPath $Root -Recurse -Filter "*.meta" -File -ErrorAction SilentlyContinue | ForEach-Object {
    try {
      foreach ($line in [System.IO.File]::ReadLines($_.FullName)) {
        if ($line -match '^\s*guid:\s*([a-f0-9]{32})\s*$') {
          $map[$matches[1]] = $_.FullName
          break
        }
      }
    }
    catch { }
  }
  return $map
}

function Get-AssetPathFromMeta {
  param([string]$MetaPath)
  if ($MetaPath -match '\.meta$') {
    return $MetaPath.Substring(0, $MetaPath.Length - 5)
  }
  return $null
}

function Get-GuidFromPrefabAnimator {
  param([string]$PrefabPath)
  $text = [System.IO.File]::ReadAllText($PrefabPath)
  if ($text -notmatch '(?ms)Animator:.*?m_Controller:\s*\{[^}]*guid:\s*([a-f0-9]{32})') {
    return $null
  }
  return $matches[1]
}

function Get-BaseControllerGuidFromOverride {
  param([string]$OverridePath)
  $text = [System.IO.File]::ReadAllText($OverridePath)
  if ($text -notmatch 'AnimatorOverrideController:') { return $null }
  if ($text -notmatch 'm_Controller:\s*\{[^}]*guid:\s*([a-f0-9]{32})') { return $null }
  return $matches[1]
}

if (-not (Test-Path -LiteralPath $ExportRoot)) { throw "Export root not found: $ExportRoot" }
if (-not (Test-Path -LiteralPath $UnityProjectRoot)) { throw "Unity project not found: $UnityProjectRoot" }

$exportProject = Join-Path $ExportRoot "ExportedProject"
if (-not (Test-Path -LiteralPath $exportProject)) { $exportProject = $ExportRoot }

$battlePrefab = Get-ChildItem -LiteralPath $exportProject -Recurse -Filter "Esquire.prefab" -File -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match '[\\/]1prefabs[\\/]Esquire\.prefab$' } |
  Select-Object -First 1

if (-not $battlePrefab) {
  throw "Could not find battle prefab ExportedProject/.../1prefabs/Esquire.prefab under $ExportRoot"
}

Write-Host "Battle prefab: $($battlePrefab.FullName)"

$animGuid = Get-GuidFromPrefabAnimator $battlePrefab.FullName
if (-not $animGuid) { throw "No Animator m_Controller guid in Esquire.prefab" }

Write-Host "Animator runtime asset guid: $animGuid"

$metaIndex = Build-MetaGuidIndex $exportProject
if (-not $metaIndex.ContainsKey($animGuid)) {
  throw "No .meta for guid $animGuid (index $( $metaIndex.Count ) metas)."
}

$runtimeAsset = Get-AssetPathFromMeta $metaIndex[$animGuid]
if (-not (Test-Path -LiteralPath $runtimeAsset)) {
  throw "Asset missing for guid $animGuid : $runtimeAsset"
}

Write-Host "Runtime controller asset: $runtimeAsset"

$baseGuid = $null
if ($runtimeAsset -match '\.overrideController$') {
  $baseGuid = Get-BaseControllerGuidFromOverride $runtimeAsset
  if (-not $baseGuid) { throw "Could not read m_Controller from override: $runtimeAsset" }
  Write-Host "Base AnimatorController guid (from override): $baseGuid"
}
else {
  $baseGuid = $animGuid
}

if (-not $metaIndex.ContainsKey($baseGuid)) {
  throw "No .meta for base guid $baseGuid"
}

$srcController = Get-AssetPathFromMeta $metaIndex[$baseGuid]
if (-not ($srcController -match '\.controller$')) {
  throw "Expected .controller for base guid, got: $srcController"
}
if (-not (Test-Path -LiteralPath $srcController)) {
  throw "Missing base controller file: $srcController"
}

Write-Host "Stock base AnimatorController: $srcController"

$refDir = Join-Path $UnityProjectRoot $ReferenceRelative
New-Item -ItemType Directory -Path $refDir -Force | Out-Null

$destController = Join-Path $refDir $TargetFileName
$srcMeta = $srcController + ".meta"
$destMeta = $destController + ".meta"

if (Test-Path -LiteralPath $destController) { Remove-Item -LiteralPath $destController -Force }
if (Test-Path -LiteralPath $destMeta) { Remove-Item -LiteralPath $destMeta -Force }

Copy-Item -LiteralPath $srcController -Destination $destController -Force
if (Test-Path -LiteralPath $srcMeta) {
  Copy-Item -LiteralPath $srcMeta -Destination $destMeta -Force
}

# Stock controller references etalon AnimationClips by GUID; Unity needs those assets in the project.
$etalonSrc = Join-Path $exportProject "Assets\Resources\units\_system\etalon"
$etalonDest = Join-Path $refDir "etalon"
if (Test-Path -LiteralPath $etalonSrc) {
  if (Test-Path -LiteralPath $etalonDest) {
    Remove-Item -LiteralPath $etalonDest -Recurse -Force
  }
  Copy-Item -LiteralPath $etalonSrc -Destination $etalonDest -Recurse
  Write-Host "Copied etalon dependency folder -> $etalonDest"
}
else {
  Write-Warning "etalon folder missing (controller motions may be broken): $etalonSrc"
}

Write-Host "Copied -> $destController"
Write-Host "Done."
