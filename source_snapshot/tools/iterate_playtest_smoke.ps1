# Repeated launch + BepInEx log validation. See tools/run_playtest_10s.ps1 and verify_esquire_interop/check_bepinex_log.ps1.
#
# Examples:
#   3x 10s + BepInEx check each round
#   powershell.exe -NoProfile -File tools/iterate_playtest_smoke.ps1 -PlaytestRoot "V:\...\Heroes of Might & Magic Olden Era Playtest"
#   5x 8s, then 30s deep load + Player.log [Config] db is loaded
#   powershell.exe -NoProfile -File tools/iterate_playtest_smoke.ps1 -PlaytestRoot "V:\...\" -Rounds 5 -Seconds 8 -DeepLoadSeconds 30
# Optional: -AllowBhAppStartIl2CppNre  (see check_bepinex_log.ps1; BepInEx can spam Il2CppInterop NRE on BhAppStartScript::Update)
param(
	[Parameter(Mandatory = $true)]
	[string] $PlaytestRoot,
	[int] $Rounds = 3,
	[int] $Seconds = 10,
	[int] $DeepLoadSeconds = 0,
	[switch] $AllowBhAppStartIl2CppNre
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$run = Join-Path $here "run_playtest_10s.ps1"
$check = Join-Path (Join-Path $here "verify_esquire_interop") "check_bepinex_log.ps1"
$PlaytestRoot = (Resolve-Path -LiteralPath $PlaytestRoot).Path

if ($Rounds -lt 0) { $Rounds = 0 }
if ($Seconds -lt 1) { $Seconds = 1 }
if ($DeepLoadSeconds -lt 0) { $DeepLoadSeconds = 0 }

# Child scripts use `exit` -- run each in a separate powershell process so this file does not terminate early.
$ps = "powershell.exe"
$checkSplat = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $check, "-PlaytestRoot", $PlaytestRoot)
if ($AllowBhAppStartIl2CppNre) { $checkSplat += "-AllowBhAppStartIl2CppNre" }
$failed = $false
for ($i = 1; $i -le $Rounds; $i++) {
	Write-Host "=== Round $i / $Rounds ($Seconds s) ===" -ForegroundColor Cyan
	& $ps -NoProfile -ExecutionPolicy Bypass -File $run -PlaytestRoot $PlaytestRoot -Seconds $Seconds
	if ($LASTEXITCODE -ne 0) { $failed = $true; break }
	& $ps @checkSplat
	if ($LASTEXITCODE -ne 0) { $failed = $true; break }
}

if (-not $failed -and $DeepLoadSeconds -ge 1) {
	Write-Host "=== Deep load ($DeepLoadSeconds s) + Player.log ===" -ForegroundColor Cyan
	& $ps -NoProfile -ExecutionPolicy Bypass -File $run -PlaytestRoot $PlaytestRoot -Seconds $DeepLoadSeconds
	if ($LASTEXITCODE -ne 0) { $failed = $true }
	if (-not $failed) {
		& $ps @checkSplat
		if ($LASTEXITCODE -ne 0) { $failed = $true }
	}
	if (-not $failed) {
		$player = Join-Path $env:USERPROFILE "AppData\LocalLow\Unfrozen\HeroesOE\Player.log"
		if (-not (Test-Path -LiteralPath $player)) {
			Write-Error "Player.log not found: $player"
			exit 1
		}
		$tail = Get-Content -LiteralPath $player -Tail 4000 -ErrorAction SilentlyContinue
		$raw = if ($null -ne $tail) { ($tail -join "`n") } else { [string]::Empty }
		if ($raw -notmatch "\[Config\]\s*db is loaded") {
			Write-Error "Player.log in last 4000 lines has no line matching '[Config] db is loaded' (deep load may need a longer -DeepLoadSeconds)."
			$failed = $true
		} else {
			Write-Host "Player.log: OK ([Config] db is loaded in recent tail)"
		}
	}
}

if ($failed) {
	Write-Host "iterate_playtest_smoke: FAILED" -ForegroundColor Red
	exit 1
}
Write-Host "iterate_playtest_smoke: all rounds OK" -ForegroundColor Green
exit 0
