param(
  [Parameter(Mandatory = $true)]
  [string]$SourceDir,

  [Parameter(Mandatory = $true)]
  [string]$OutDir,

  [long]$MaxPartBytes = 1900000000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $SourceDir)) {
  throw "SourceDir not found: $SourceDir"
}
if ($MaxPartBytes -le 0) {
  throw "MaxPartBytes must be > 0"
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$exeFiles = @(Get-ChildItem -LiteralPath $SourceDir -File -Filter '*.exe' | Sort-Object Name)
if ($exeFiles.Count -eq 0) {
  throw "No .exe files found under $SourceDir"
}

$manifest = [ordered]@{
  schema = 'golden_era_split_release_assets/v1'
  max_part_bytes = $MaxPartBytes
  generated_utc = (Get-Date).ToUniversalTime().ToString('o')
  assets = @()
}

foreach ($exe in $exeFiles) {
  $length = [long]$exe.Length
  Write-Host ("Splitting {0} ({1:N0} bytes) into <= {2:N0}-byte parts..." -f $exe.Name, $length, $MaxPartBytes)

  $partPaths = @()
  if ($length -le $MaxPartBytes) {
    $dest = Join-Path $OutDir $exe.Name
    Copy-Item -LiteralPath $exe.FullName -Destination $dest -Force
    $partPaths += $dest
  }
  else {
    $partCount = [int][Math]::Ceiling($length / [double]$MaxPartBytes)
    $buffer = New-Object byte[] (1024 * 1024)
    $inputStream = [System.IO.File]::OpenRead($exe.FullName)
    try {
      for ($i = 1; $i -le $partCount; $i++) {
        $partName = '{0}.part{1:D2}' -f $exe.Name, $i
        $partPath = Join-Path $OutDir $partName
        $remaining = [Math]::Min($MaxPartBytes, $length - (($i - 1) * $MaxPartBytes))
        $outputStream = [System.IO.File]::Open($partPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try {
          $written = [long]0
          while ($written -lt $remaining) {
            $toRead = [int][Math]::Min($buffer.Length, $remaining - $written)
            $read = $inputStream.Read($buffer, 0, $toRead)
            if ($read -le 0) {
              throw "Unexpected EOF while writing $partName"
            }
            $outputStream.Write($buffer, 0, $read)
            $written += $read
          }
        }
        finally {
          $outputStream.Dispose()
        }
        $partPaths += $partPath
        Write-Host ("  wrote {0} ({1:N0} bytes)" -f $partName, (Get-Item -LiteralPath $partPath).Length)
      }
    }
    finally {
      $inputStream.Dispose()
    }
  }

  $shaPath = Join-Path $SourceDir ($exe.Name + '.sha256')
  if (-not (Test-Path -LiteralPath $shaPath)) {
    throw "Missing companion hash file: $shaPath"
  }
  $hashDest = Join-Path $OutDir ($exe.Name + '.sha256')
  Copy-Item -LiteralPath $shaPath -Destination $hashDest -Force

  $manifest.assets += [ordered]@{
    output_name = $exe.Name
    sha256_file = ($exe.Name + '.sha256')
    expected_sha256 = ((Get-Content -LiteralPath $shaPath -Raw).Trim().Split(' ')[0]).ToLowerInvariant()
    expected_bytes = $length
    parts = @($partPaths | ForEach-Object { [System.IO.Path]::GetFileName($_) })
  }
}

$joinTemplate = Join-Path $PSScriptRoot 'templates\Join-GoldenEraInstaller.ps1'
if (-not (Test-Path -LiteralPath $joinTemplate)) {
  throw "Missing join template: $joinTemplate"
}
Copy-Item -LiteralPath $joinTemplate -Destination (Join-Path $OutDir 'Join-GoldenEraInstaller.ps1') -Force

$manifestPath = Join-Path $OutDir 'split_assets_manifest.json'
($manifest | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Host "Wrote split assets to $OutDir"
Get-ChildItem -LiteralPath $OutDir -File | Sort-Object Name | ForEach-Object {
  Write-Host ("  {0} ({1:N0} bytes)" -f $_.Name, $_.Length)
}
