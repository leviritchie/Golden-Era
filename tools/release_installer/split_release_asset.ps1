param(
  [Parameter(Mandatory = $true)]
  [string]$InputFile,

  [Parameter(Mandatory = $true)]
  [string]$OutDir,

  [long]$MaxPartBytes = 1900000000,

  [string]$OutputBaseName = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $InputFile)) {
  throw "InputFile not found: $InputFile"
}
if ($MaxPartBytes -le 0) {
  throw "MaxPartBytes must be > 0"
}

$item = Get-Item -LiteralPath $InputFile
if ([string]::IsNullOrWhiteSpace($OutputBaseName)) {
  $OutputBaseName = $item.Name
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$length = [long]$item.Length
Write-Host ("Splitting {0} ({1:N0} bytes) as {2} into <= {3:N0}-byte parts..." -f $item.Name, $length, $OutputBaseName, $MaxPartBytes)

$partNames = New-Object System.Collections.Generic.List[string]
if ($length -le $MaxPartBytes) {
  $dest = Join-Path $OutDir $OutputBaseName
  Copy-Item -LiteralPath $item.FullName -Destination $dest -Force
  $partNames.Add($OutputBaseName)
  Write-Host ("  wrote {0} ({1:N0} bytes)" -f $OutputBaseName, $length)
}
else {
  $partCount = [int][Math]::Ceiling($length / [double]$MaxPartBytes)
  $buffer = New-Object byte[] (1024 * 1024)
  $inputStream = [System.IO.File]::OpenRead($item.FullName)
  try {
    for ($i = 1; $i -le $partCount; $i++) {
      $partName = '{0}.part{1:D2}' -f $OutputBaseName, $i
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
      $partNames.Add($partName)
      Write-Host ("  wrote {0} ({1:N0} bytes)" -f $partName, (Get-Item -LiteralPath $partPath).Length)
    }
  }
  finally {
    $inputStream.Dispose()
  }
}

$shaSource = "$($item.FullName).sha256"
$expectedSha = $null
if (Test-Path -LiteralPath $shaSource) {
  $expectedSha = ((Get-Content -LiteralPath $shaSource -Raw).Trim().Split(' ')[0]).ToLowerInvariant()
  Copy-Item -LiteralPath $shaSource -Destination (Join-Path $OutDir ($OutputBaseName + '.sha256')) -Force
}
else {
  $expectedSha = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  Set-Content -LiteralPath (Join-Path $OutDir ($OutputBaseName + '.sha256')) -Value "$expectedSha  $OutputBaseName" -Encoding ASCII
}

$manifest = [ordered]@{
  schema = 'golden_era_payload_download/v1'
  payload_base_name = $OutputBaseName
  expected_sha256 = $expectedSha
  expected_bytes = $length
  max_part_bytes = $MaxPartBytes
  parts = @($partNames)
}

$manifestPath = Join-Path $OutDir ($OutputBaseName + '.download-manifest.json')
($manifest | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Host "Wrote split payload assets to $OutDir"
Get-ChildItem -LiteralPath $OutDir -File | Sort-Object Name | ForEach-Object {
  Write-Host ("  {0} ({1:N0} bytes)" -f $_.Name, $_.Length)
}
