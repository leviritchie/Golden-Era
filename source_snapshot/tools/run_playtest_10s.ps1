# Launch HeroesOE.exe, wait N seconds (default 10), then force-close the process.
# Prevents a forgotten playtest from staying open (BepInEx/Unity in background).
#
# Usage:
#   powershell.exe -NoProfile -File tools/run_playtest_10s.ps1 -PlaytestRoot "V:\path\..."
#   powershell.exe -NoProfile -File tools/run_playtest_10s.ps1 -PlaytestRoot "V:\path\..." -Seconds 30
param(
	[Parameter(Mandatory = $true)]
	[string] $PlaytestRoot,
	[int] $Seconds = 10
)

$ErrorActionPreference = "Stop"
$PlaytestRoot = (Resolve-Path -LiteralPath $PlaytestRoot).Path
$exe = Join-Path $PlaytestRoot "HeroesOE.exe"
if (-not (Test-Path -LiteralPath $exe)) {
	Write-Error "Not found: $exe"
	exit 1
}

Write-Host "Starting: $exe"
$p = Start-Process -FilePath $exe -WorkingDirectory $PlaytestRoot -PassThru
if ($null -eq $p) {
	Write-Error "Start-Process did not return a process."
	exit 1
}

if ($Seconds -lt 1) { $Seconds = 1 }
$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline) {
	Start-Sleep -Milliseconds 200
	$p.Refresh()
	if ($p.HasExited) {
		Write-Host "Process exited on its own (exit $($p.ExitCode))."
		exit 0
	}
}

Get-Process -Name "HeroesOE" -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "Stopped HeroesOE after $Seconds second(s) (PID was $($p.Id))."
exit 0
