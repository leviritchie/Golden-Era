# List .controller assets under an AssetRipper export that look esquire-related.
param(
  [Parameter(Mandatory = $true)][string]$ExportRoot
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $ExportRoot)) { throw "Missing folder: $ExportRoot" }

$assets = Join-Path $ExportRoot "Assets"
if (-not (Test-Path -LiteralPath $assets)) {
  Write-Warning "No Assets subfolder - is this a full Unity export? Root: $ExportRoot"
}

$all = @(Get-ChildItem -LiteralPath $ExportRoot -Recurse -Filter "*.controller" -File -ErrorAction SilentlyContinue)
$hit = @($all | Where-Object { $_.FullName -match "esquire|Esquire|humans|Humans|1Prefabs|pikeman" })

if ($hit.Count -gt 0) {
  Write-Host "Heuristic matches (prefer battle / Humans prefab controllers):"
  $hit | Select-Object FullName, Length | Format-Table -AutoSize
}
else {
  Write-Host "No path matched esquire|Humans|1Prefabs|pikeman. Sample of all .controller files (max 50):"
  $all | Select-Object -First 50 FullName | Format-Table -AutoSize
}
