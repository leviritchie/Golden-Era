param(
	[string]$GameRoot = "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era",
	[string]$ProjectRoot = $PSScriptRoot,
	[int]$Tail = 500
)

$ErrorActionPreference = "Continue"

function Write-Section {
	param([string]$Title)
	Write-Host ""
	Write-Host "== $Title =="
}

function Show-Item {
	param([string]$Path)
	if (Test-Path -LiteralPath $Path) {
		Get-Item -LiteralPath $Path | Select-Object FullName, Length, LastWriteTime | Format-List
	} else {
		Write-Host "Missing: $Path"
	}
}

$bepInExRoot = Join-Path $GameRoot "BepInEx"
$pluginRoot = Join-Path $bepInExRoot "plugins\OfflineUnlockMod"
$logPath = Join-Path $bepInExRoot "LogOutput.log"
$errorLogPath = Join-Path $bepInExRoot "ErrorLog.log"
$interopHex = Join-Path $bepInExRoot "interop\Hex.dll"
$metadata = Join-Path $GameRoot "HeroesOldenEra_Data\il2cpp_data\Metadata\global-metadata.dat"
$gameAssembly = Join-Path $GameRoot "GameAssembly.dll"
$pluginDll = Join-Path $pluginRoot "OfflineUnlockMod.dll"
$importJson = Join-Path $pluginRoot "homm3_import.json"

Write-Section "Game And Interop"
Show-Item (Join-Path $GameRoot "HeroesOldenEra.exe")
Show-Item $gameAssembly
Show-Item $metadata
Show-Item $interopHex
Show-Item $pluginDll

Write-Section "Import Json"
if (Test-Path -LiteralPath $importJson) {
	try {
		$json = Get-Content -LiteralPath $importJson -Raw | ConvertFrom-Json
		$count = if ($json.entries) { @($json.entries).Count } else { 0 }
		Write-Host "Parsed homm3_import.json entries: $count"
	} catch {
		Write-Host "Failed to parse homm3_import.json with PowerShell JSON parser:"
		Write-Host $_.Exception.Message
	}
} else {
	Write-Host "Missing: $importJson"
}

if (!(Test-Path -LiteralPath $logPath)) {
	Write-Section "Log"
	Write-Host "Missing: $logPath"
	exit 0
}

$log = Get-Content -LiteralPath $logPath -Tail $Tail

Write-Section "Build Markers"
$log | Select-String -Pattern "BepInEx 6|Detected outdated interop|Loading \[HeroesOE Offline Unlock|Mod DLL probe: build=|Launcher config:|Chainloader startup complete" | ForEach-Object { $_.Line }

Write-Section "Hook Registration Summary"
$log | Select-String -Pattern "registered .*patch|0 .*patch|hooks skipped|map slice|visual slice|release Stronghold Custom Game integration" | ForEach-Object { $_.Line }

Write-Section "Failures"
$failurePatterns = @(
	"method not found",
	"type not found",
	"patch failed",
	"Failed to patch",
	"failed to parse",
	"could not parse",
	"no homm3_import.json entries",
	"not found:",
	"MissingMethodException",
	"NullReferenceException",
	"ArgumentException"
)
$pattern = ($failurePatterns | ForEach-Object { [Regex]::Escape($_) }) -join "|"
$log | Select-String -Pattern $pattern -CaseSensitive:$false | ForEach-Object { $_.Line }

Write-Section "Custom Game Candidate Drift"
$log | Select-String -Pattern "ReleaseCustomGameUiProbe.*(method not found|method shape not found|candidate|patched|integration patch)" | ForEach-Object { $_.Line }

Write-Section "ErrorLog Tail"
if (Test-Path -LiteralPath $errorLogPath) {
	Get-Content -LiteralPath $errorLogPath -Tail 120
} else {
	Write-Host "Missing: $errorLogPath"
}

Write-Section "Next Static Trace Anchors"
Write-Host "1. If interop regenerated, rebuild the mod against $interopHex."
Write-Host "2. Replace exact obfuscated method names with signature/field-shape matching for any hook family that registered 0 patches."
Write-Host "3. For Custom Game, BhFraction element is String, Sprite, Boolean, Boolean; BhHero element is String, Boolean, Boolean, Action<T>."
Write-Host "4. Avoid direct JToken casts under IL2CPP Newtonsoft; use Type checks plus ToString()/parsing helpers."
