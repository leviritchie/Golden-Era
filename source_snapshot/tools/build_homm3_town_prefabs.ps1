param(
	[string]$UnityExe = "C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe",
	[string]$ProjectPath,
	[string]$PluginPayloadRoot,
	[string]$OutputRoot,
	[string]$DeployRoot
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $ProjectPath) {
	$ProjectPath = Join-Path $repoRoot "tmp\unity_homm3_town_prefab_builder_minimal2"
}
if (-not $PluginPayloadRoot) {
	$PluginPayloadRoot = Join-Path $repoRoot "Heroes of Might & Magic Olden Era Playtest\BepInEx\plugins\OfflineUnlockMod"
}
if (-not $OutputRoot) {
	$OutputRoot = Join-Path $PluginPayloadRoot "homm3_town_prefabs"
}

$townSourceRoot = Join-Path $PluginPayloadRoot "homm3_runtime_assets\town_scene_refs"
$unityBuilderSource = Join-Path $repoRoot "tools\unity\Homm3TownPrefabBundleBuilder.cs"
$unityBuilderDest = Join-Path $ProjectPath "Assets\Editor\Homm3TownPrefabBundleBuilder.cs"
$assetRoot = Join-Path $ProjectPath "Assets\Generated"
$textureRoot = Join-Path $assetRoot "Homm3TownPrefabTextures"
$manifestPath = Join-Path $assetRoot "Homm3TownPrefabBuildManifest.tsv"
$buildOutput = Join-Path $ProjectPath "BuildOutput"
$logPath = Join-Path $ProjectPath "homm3_town_prefab_build.log"

if (-not (Test-Path $UnityExe)) {
	throw "Unity executable not found: $UnityExe"
}
if (-not (Test-Path $townSourceRoot)) {
	throw "Town scene source root not found: $townSourceRoot"
}
if (-not (Test-Path $unityBuilderSource)) {
	throw "Unity builder source not found: $unityBuilderSource"
}

New-Item -ItemType Directory -Force -Path $ProjectPath, (Join-Path $ProjectPath "Assets\Editor"), $assetRoot, $textureRoot, $buildOutput, $OutputRoot, (Join-Path $ProjectPath "Packages"), (Join-Path $ProjectPath "ProjectSettings") | Out-Null
$minimalPackageManifest = @"
{
  "dependencies": {
    "com.unity.ugui": "2.0.0",
    "com.unity.modules.assetbundle": "1.0.0",
    "com.unity.modules.imageconversion": "1.0.0",
    "com.unity.modules.ui": "1.0.0"
  }
}
"@
[System.IO.File]::WriteAllText((Join-Path $ProjectPath "Packages\manifest.json"), $minimalPackageManifest, (New-Object System.Text.UTF8Encoding($false)))

$projectVersionPath = Join-Path $ProjectPath "ProjectSettings\ProjectVersion.txt"
if (-not (Test-Path $projectVersionPath)) {
	Set-Content -Path $projectVersionPath -Value "m_EditorVersion: 6000.0.66f2`nm_EditorVersionWithRevision: 6000.0.66f2 (b20bc5da3050)" -Encoding UTF8
}

Copy-Item -Force -Path $unityBuilderSource -Destination $unityBuilderDest

if (Test-Path $textureRoot) {
	Remove-Item -Recurse -Force -LiteralPath $textureRoot
}
if (Test-Path (Join-Path $assetRoot "Homm3TownPrefabs")) {
	Remove-Item -Recurse -Force -LiteralPath (Join-Path $assetRoot "Homm3TownPrefabs")
}
New-Item -ItemType Directory -Force -Path $textureRoot | Out-Null

function Sanitize-LayerId([string]$sid) {
	if ([string]::IsNullOrEmpty($sid)) {
		return "unknown"
	}
	return -join ($sid.ToCharArray() | ForEach-Object {
		if ([char]::IsLetterOrDigit($_)) { $_ } else { '_' }
	})
}

function Get-JsonProperties($obj) {
	if ($null -eq $obj) {
		return @()
	}
	return $obj.PSObject.Properties
}

function Resolve-Placement($placementsById, [string]$layerId, [int]$level) {
	foreach ($candidate in @("${layerId}_${level}", "${layerId}_lvl${level}", $layerId)) {
		if ($placementsById.ContainsKey($candidate)) {
			return $placementsById[$candidate]
		}
	}
	return $null
}

function Resolve-TexturePath([string]$layerDir, $placement, [string]$layerId, [int]$level) {
	if (-not $placement -or -not $placement.sprite) {
		throw "Placement for layer ${layerId} level ${level} is missing explicit sprite metadata"
	}
	$candidate = Join-Path $layerDir $placement.sprite
	if (-not (Test-Path $candidate)) {
		throw "Explicit sprite for layer ${layerId} level ${level} is missing: $($placement.sprite)"
	}
	return (Resolve-Path $candidate).Path
}

$rows = New-Object System.Collections.Generic.List[string]
$copyMap = @{}
$fractions = Get-ChildItem -Path $townSourceRoot -Directory | Where-Object { $_.Name -like "homm3_*" } | Sort-Object Name
foreach ($fractionDir in $fractions) {
	$fraction = $fractionDir.Name
	$layerDir = Join-Path $fractionDir.FullName "layers"
	$positionsPath = Join-Path $layerDir "positions.json"
	$mapPath = Join-Path $layerDir "building_layer_map.json"
	if (-not (Test-Path $positionsPath) -or -not (Test-Path $mapPath)) {
		throw "Missing town layer metadata for ${fraction}"
	}

	$positionsJson = Get-Content -Raw -Path $positionsPath | ConvertFrom-Json
	$mapJson = Get-Content -Raw -Path $mapPath | ConvertFrom-Json
	$placementsById = @{}
	foreach ($layer in $positionsJson.layers) {
		$placementsById[$layer.id] = $layer
	}

	$entries = @{}
	foreach ($sidProp in Get-JsonProperties $mapJson.levels) {
		foreach ($levelProp in Get-JsonProperties $sidProp.Value) {
			$level = [int]$levelProp.Name
			$layerId = [string]$levelProp.Value
			$entries["${layerId}`t${level}"] = @{ LayerId = $layerId; Level = $level }
		}
	}

	foreach ($sidProp in Get-JsonProperties $mapJson.buildingLayerIds) {
		$sid = $sidProp.Name
		if ($mapJson.levels -and ($mapJson.levels.PSObject.Properties.Name -contains $sid)) {
			continue
		}
		$layerId = [string]$sidProp.Value
		$entries["${layerId}`t1"] = @{ LayerId = $layerId; Level = 1 }
	}

	foreach ($entry in $entries.Values) {
		$layerId = [string]$entry.LayerId
		$level = [int]$entry.Level
		$placement = Resolve-Placement $placementsById $layerId $level
		if ($null -eq $placement) {
			throw "No placement for ${fraction} layer ${layerId} level ${level}"
		}
		$texturePath = Resolve-TexturePath $layerDir $placement $layerId $level
		if (-not $texturePath) {
			throw "No texture for ${fraction} layer ${layerId} level ${level}"
		}

		$objectName = "OfflineUnlockStrongholdTownLayer_{0}_{1}" -f (Sanitize-LayerId $layerId), $level
		$textureName = Split-Path -Leaf $texturePath
		$assetTextureDir = Join-Path $textureRoot $fraction
		New-Item -ItemType Directory -Force -Path $assetTextureDir | Out-Null
		$assetTexturePath = Join-Path $assetTextureDir $textureName
		if (-not $copyMap.ContainsKey($assetTexturePath)) {
			Copy-Item -Force -Path $texturePath -Destination $assetTexturePath
			$copyMap[$assetTexturePath] = $true
		}

		$unityTexturePath = ("Assets/Generated/Homm3TownPrefabTextures/{0}/{1}" -f $fraction, $textureName).Replace("\", "/")
		$rows.Add(("{0}`t{1}`t{2}" -f $fraction, $objectName, $unityTexturePath))
	}
}

Set-Content -Path $manifestPath -Value ($rows | Sort-Object -Unique) -Encoding UTF8

$buildArgs = "-batchmode -nographics -quit -projectPath `"$ProjectPath`" -executeMethod OfflineUnlockModTools.Homm3TownPrefabBundleBuilder.Build -homm3TownPrefabOutput `"$buildOutput`" -logFile `"$logPath`""
$buildProcess = Start-Process -FilePath $UnityExe -ArgumentList $buildArgs -Wait -PassThru -WindowStyle Hidden
if ($buildProcess.ExitCode -ne 0) {
	throw "Unity town prefab bundle build failed with exit code $($buildProcess.ExitCode). See $logPath"
}

$builtBundle = Join-Path $buildOutput "homm3_town_prefabs"
if (-not (Test-Path $builtBundle)) {
	throw "Built town prefab bundle missing: $builtBundle"
}

Copy-Item -Force -Path $builtBundle -Destination (Join-Path $OutputRoot "homm3_town_prefabs")
Copy-Item -Force -Path $manifestPath -Destination (Join-Path $OutputRoot "Homm3TownPrefabBuildManifest.tsv")

if ($DeployRoot) {
	$deployOutput = Join-Path $DeployRoot "BepInEx\plugins\OfflineUnlockMod\homm3_town_prefabs"
	New-Item -ItemType Directory -Force -Path $deployOutput | Out-Null
	Copy-Item -Force -Path $builtBundle -Destination (Join-Path $deployOutput "homm3_town_prefabs")
    Copy-Item -Force -Path $manifestPath -Destination (Join-Path $deployOutput "Homm3TownPrefabBuildManifest.tsv")
}

Write-Host ("Generated HoMM3 town prefab bundle: {0} entries, output {1}" -f $rows.Count, (Join-Path $OutputRoot "homm3_town_prefabs"))




