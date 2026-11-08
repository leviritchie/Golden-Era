param(
	[string] $ScratchRoot = 'V:\olden_port_work\golden_era_map_loading\fixtures'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$helperPath = Join-Path $repoRoot 'Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3HeroMapSpriteFrameIndex.cs'
$hookPath = Join-Path $repoRoot 'Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3HeroMapSpriteHook.cs'
$null = New-Item -ItemType Directory -Path $ScratchRoot -Force
$scratchRootFullPath = [IO.Path]::GetFullPath($ScratchRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$testRoot = Join-Path $scratchRootFullPath ('fixture_' + [Guid]::NewGuid().ToString('N'))
$createdRoot = $false

function Assert-True([bool] $Condition, [string] $Message) {
	if (-not $Condition) {
		throw $Message
	}
}

try {
	$null = New-Item -ItemType Directory -Path $testRoot
	$createdRoot = $true
	$spriteRoot = Join-Path $testRoot 'sprites'
	$firstDuplicate = Join-Path $spriteRoot 'a'
	$secondDuplicate = Join-Path $spriteRoot 'z'
	$null = New-Item -ItemType Directory -Path $firstDuplicate -Force
	$null = New-Item -ItemType Directory -Path $secondDuplicate -Force

	for ($group = 0; $group -lt 10; $group++) {
		$frameCount = if ($group -lt 5) { 1 } else { 8 }
		for ($frame = 0; $frame -lt $frameCount; $frame++) {
			$directory = if ($group -eq 0 -and $frame -eq 0) { $firstDuplicate } else { $spriteRoot }
			$name = '{0:D2}_{1:D2}.png' -f $group, $frame
			$null = New-Item -ItemType File -Path (Join-Path $directory $name)
		}
	}
	$null = New-Item -ItemType File -Path (Join-Path $secondDuplicate '00_00.png')
	$null = New-Item -ItemType File -Path (Join-Path $spriteRoot '05_99.png')
	$null = New-Item -ItemType File -Path (Join-Path $spriteRoot 'notes.png')

	$compiledTypes = Add-Type -Path $helperPath -PassThru -WarningAction SilentlyContinue
	$indexType = $compiledTypes | Where-Object FullName -eq 'OfflineUnlockMod.Homm3HeroMapSpriteFrameIndex'
	Assert-True ($null -ne $indexType) 'The frame-index helper did not compile.'
	$create = $indexType.GetMethod('TryCreate', [Reflection.BindingFlags]'Static,NonPublic')
	$lookup = $indexType.GetMethod('TryGetFrame', [Reflection.BindingFlags]'Instance,NonPublic')
	Assert-True ($null -ne $create -and $null -ne $lookup) 'The expected frame-index methods were not found.'

	$createArgs = New-Object object[] 3
	$createArgs[0] = [string] $spriteRoot
	$created = [bool] $create.Invoke($null, $createArgs)
	Assert-True $created ('Frame index creation failed: ' + $createArgs[2])
	$index = $createArgs[1]
	for ($group = 0; $group -lt 10; $group++) {
		$frameCount = if ($group -lt 5) { 1 } else { 8 }
		for ($frame = 0; $frame -lt $frameCount; $frame++) {
			$lookupArgs = New-Object object[] 3
			$lookupArgs[0] = [int] $group
			$lookupArgs[1] = [int] $frame
			$found = [bool] $lookup.Invoke($index, $lookupArgs)
			Assert-True $found ('Missing selected frame {0:D2}_{1:D2}.' -f $group, $frame)
		}
	}

	$duplicateArgs = New-Object object[] 3
	$duplicateArgs[0] = 0
	$duplicateArgs[1] = 0
	$null = $lookup.Invoke($index, $duplicateArgs)
	$expectedDuplicate = [IO.Path]::GetFullPath((Join-Path $firstDuplicate '00_00.png'))
	Assert-True ([string]::Equals([IO.Path]::GetFullPath([string] $duplicateArgs[2]), $expectedDuplicate, [StringComparison]::OrdinalIgnoreCase)) 'Duplicate canonical names no longer select the first path in ordinal-ignore-case sort order.'

	$missingArgs = New-Object object[] 3
	$missingArgs[0] = 5
	$missingArgs[1] = 8
	Assert-True (-not [bool] $lookup.Invoke($index, $missingArgs)) 'An unrequested extra frame was treated as a required walk frame.'

	$missingRootArgs = New-Object object[] 3
	$missingRootArgs[0] = [string] (Join-Path $testRoot 'absent')
	Assert-True (-not [bool] $create.Invoke($null, $missingRootArgs)) 'A missing sprite root was accepted.'
	Assert-True (-not [string]::IsNullOrWhiteSpace([string] $missingRootArgs[2])) 'A missing sprite root failed without a diagnostic.'

	[IO.File]::Delete((Join-Path $spriteRoot '05_07.png'))
	$incompleteArgs = New-Object object[] 3
	$incompleteArgs[0] = [string] $spriteRoot
	Assert-True ([bool] $create.Invoke($null, $incompleteArgs)) ('The incomplete-root index failed unexpectedly: ' + $incompleteArgs[2])
	$missingCanonicalArgs = New-Object object[] 3
	$missingCanonicalArgs[0] = 5
	$missingCanonicalArgs[1] = 7
	Assert-True (-not [bool] $lookup.Invoke($incompleteArgs[1], $missingCanonicalArgs)) 'An extra frame silently substituted for a missing canonical walk frame.'

	$hook = [IO.File]::ReadAllText($hookPath)
	$helper = [IO.File]::ReadAllText($helperPath)
	$indexBuildCalls = [regex]::Matches($hook, 'Homm3HeroMapSpriteFrameIndex\.TryCreate\(root, out var frameIndex, out var indexError\)').Count
	$recursivePngScans = [regex]::Matches($helper, 'Directory\.GetFiles\(root, "\*\.png", SearchOption\.AllDirectories\)').Count
	Assert-True ($indexBuildCalls -eq 1 -and $recursivePngScans -eq 1) 'The active sprite-load path must build one index from one recursive PNG scan.'
	Assert-True (-not $hook.Contains('FindFrameFiles(')) 'The active hook still contains the repeated recursive file-search path.'
	Assert-True ($hook.Contains('private const int WalkFramesPerFacing = 8;')) 'Walk frame count changed unexpectedly.'
	Assert-True ($hook.Contains('new Il2CppStructArray<byte>(bytes)')) 'PNG bytes are not transferred through the bulk IL2CPP array constructor.'
	Assert-True (-not $hook.Contains('il2cppBytes[i] = bytes[i]')) 'The per-byte managed-to-IL2CPP copy loop is still present.'
	Assert-True ($hook.Contains('tex.filterMode = FilterMode.Point;') -and $hook.Contains('tex.wrapMode = TextureWrapMode.Clamp;')) 'Sprite texture sampling modes changed.'

	'OK: helper behavior passed; single-index/bulk-transfer source guards passed.'
}
finally {
	if ($createdRoot) {
		$fullTestRoot = [IO.Path]::GetFullPath($testRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
		$requiredChildPrefix = $scratchRootFullPath + [IO.Path]::DirectorySeparatorChar
		if ($fullTestRoot -eq $scratchRootFullPath -or -not $fullTestRoot.StartsWith($requiredChildPrefix, [StringComparison]::OrdinalIgnoreCase)) {
			throw 'Refusing to remove anything other than this test fixture under the selected scratch root.'
		}
		[IO.Directory]::Delete($fullTestRoot, $true)
	}
}
