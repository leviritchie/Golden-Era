# Export HeroesOE_Data to a Unity project tree via AssetRipper's local HTTP API (--headless).
# Requires: dist\AssetRipper.GUI.Free.exe from bootstrap.cmd
param(
  [Parameter(Mandatory = $true)][string]$ArExe,
  [Parameter(Mandatory = $true)][string]$GameDataPath,
  [Parameter(Mandatory = $true)][string]$ExportPath,
  [int]$Port = 17865,
  [int]$StartupWaitSeconds = 120,
  [int]$LoadTimeoutSec = 3600,
  [int]$ExportTimeoutSec = 7200
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ArExe)) { throw "Missing AssetRipper: $ArExe" }
if (-not (Test-Path -LiteralPath $GameDataPath)) { throw "Missing game data folder: $GameDataPath" }

$parent = Split-Path -Parent $ExportPath
if ($parent -and -not (Test-Path -LiteralPath $parent)) {
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
}

$ar = Start-Process -FilePath $ArExe -ArgumentList @("--headless", "--port=$Port") -PassThru -WindowStyle Hidden
if (-not $ar) { throw "Failed to start AssetRipper" }

try {
  $deadline = (Get-Date).AddSeconds($StartupWaitSeconds)
  $ready = $false
  while ((Get-Date) -lt $deadline) {
    try {
      Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2 -MaximumRedirection 5 | Out-Null
      $ready = $true
      break
    }
    catch {
      Start-Sleep -Seconds 1
    }
  }
  if (-not $ready) { throw "AssetRipper did not listen on port $Port within ${StartupWaitSeconds}s" }

  $loadBody = "Path=" + [uri]::EscapeDataString((Resolve-Path -LiteralPath $GameDataPath).Path)
  Write-Host "POST /LoadFolder (this can take many minutes)..."
  Invoke-WebRequest -Uri "http://127.0.0.1:$Port/LoadFolder" -Method Post -Body $loadBody `
    -ContentType "application/x-www-form-urlencoded" -TimeoutSec $LoadTimeoutSec `
    -UseBasicParsing -MaximumRedirection 10 | Out-Null

  $exportBody = "Path=" + [uri]::EscapeDataString($ExportPath) + "&CreateSubfolder=false"
  Write-Host "POST /Export/UnityProject (long run)..."
  Invoke-WebRequest -Uri "http://127.0.0.1:$Port/Export/UnityProject" -Method Post -Body $exportBody `
    -ContentType "application/x-www-form-urlencoded" -TimeoutSec $ExportTimeoutSec `
    -UseBasicParsing -MaximumRedirection 10 | Out-Null

  Write-Host "Export finished: $ExportPath"
}
finally {
  Stop-Process -Id $ar.Id -Force -ErrorAction SilentlyContinue
}
