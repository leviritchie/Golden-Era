# Launch HeroesOE.exe, wait N seconds, force-stop, then print log tails (agent / CI iteration).
# Uses tools/run_playtest_10s.ps1. Default wait is long enough for OfflineLauncherConfig auto-launch + map load.
#
# Usage:
#   powershell.exe -NoProfile -File tools/run_playtest_tail_logs.ps1 -PlaytestRoot "V:\...\Heroes of Might & Magic Olden Era Playtest"
#   powershell.exe -NoProfile -File tools/run_playtest_tail_logs.ps1 -PlaytestRoot "V:\...\" -Seconds 90 -Lines 120
# Default 60s: safe margin for OfflineLauncherConfig auto-launch + map load (with skipIntroCinematics).
param(
	[Parameter(Mandatory = $true)]
	[string] $PlaytestRoot,
	[int] $Seconds = 60,
	[int] $Lines = 100
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$run = Join-Path $here "run_playtest_10s.ps1"
$PlaytestRoot = (Resolve-Path -LiteralPath $PlaytestRoot).Path

if ($Lines -lt 1) { $Lines = 20 }
if ($Seconds -lt 1) { $Seconds = 1 }

Write-Host "=== run_playtest_tail_logs: $Seconds s run ===" -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $run -PlaytestRoot $PlaytestRoot -Seconds $Seconds
$runExit = $LASTEXITCODE

$bepinLog = Join-Path $PlaytestRoot "BepInEx\LogOutput.log"
$errLog = Join-Path $PlaytestRoot "BepInEx\ErrorLog.log"
$player = Join-Path $env:USERPROFILE "AppData\LocalLow\Unfrozen\HeroesOE\Player.log"

function Show-Tail {
	param([string] $Path, [string] $Title)
	Write-Host ""
	Write-Host "=== $Title ===" -ForegroundColor Yellow
	if (-not (Test-Path -LiteralPath $Path)) {
		Write-Host "(missing: $Path)"
		return
	}
	Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue
}

Show-Tail -Path $bepinLog -Title "BepInEx/LogOutput.log (last $Lines lines)"
Show-Tail -Path $errLog -Title "BepInEx/ErrorLog.log (last $Lines lines)"
Show-Tail -Path $player -Title "Player.log (last $Lines lines)"

if ($runExit -ne 0) {
	Write-Host "run_playtest_10s.ps1 exited with $runExit" -ForegroundColor Red
	exit $runExit
}
Write-Host ""
Write-Host "=== done (exit 0) ===" -ForegroundColor Green
exit 0
