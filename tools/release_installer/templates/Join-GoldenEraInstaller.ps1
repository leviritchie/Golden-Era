#Requires -Version 5.1
<#
.SYNOPSIS
  Joins Golden Era installer .partNN files into a runnable .exe and verifies SHA-256.

.DESCRIPTION
  Download every matching part into the same folder as this script, then run:

    powershell -ExecutionPolicy Bypass -File .\Join-GoldenEraInstaller.ps1

  Or join one specific installer:

    powershell -ExecutionPolicy Bypass -File .\Join-GoldenEraInstaller.ps1 `
      -InstallerName GoldenEraModInstaller-v0.1.307-standard-portraits.exe
#>
param(
  [string]$InstallerName = '',
  [string]$PartsDir = $PSScriptRoot,
  [string]$OutDir = $PSScriptRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ExpectedSha256 {
  param([string]$HashFile)
  $raw = (Get-Content -LiteralPath $HashFile -Raw).Trim()
  if ([string]::IsNullOrWhiteSpace($raw)) {
    throw "Hash file is empty: $HashFile"
  }
  return $raw.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)[0].ToLowerInvariant()
}

function Join-OneInstaller {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  $hashFile = Join-Path $PartsDir ($Name + '.sha256')
  if (-not (Test-Path -LiteralPath $hashFile)) {
    throw "Missing hash file for ${Name}: $hashFile"
  }

  $parts = @(
    Get-ChildItem -LiteralPath $PartsDir -File -Filter ($Name + '.part*') |
      Where-Object { $_.Name -match ('^{0}\.part\d{{2}}$' -f [regex]::Escape($Name)) } |
      Sort-Object Name
  )

  $outPath = Join-Path $OutDir $Name
  if ($parts.Count -eq 0) {
    $single = Join-Path $PartsDir $Name
    if (-not (Test-Path -LiteralPath $single)) {
      throw "No parts or complete installer found for $Name under $PartsDir"
    }
    if ((Resolve-Path -LiteralPath $single).Path -ne (Resolve-Path -LiteralPath $outPath -ErrorAction SilentlyContinue).Path) {
      Copy-Item -LiteralPath $single -Destination $outPath -Force
    }
  }
  else {
    Write-Host ("Joining {0} from {1} part(s)..." -f $Name, $parts.Count)
    $buffer = New-Object byte[] (1024 * 1024)
    $output = [System.IO.File]::Open($outPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
      foreach ($part in $parts) {
        Write-Host ("  + {0}" -f $part.Name)
        $inputStream = [System.IO.File]::OpenRead($part.FullName)
        try {
          while (($read = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $output.Write($buffer, 0, $read)
          }
        }
        finally {
          $inputStream.Dispose()
        }
      }
    }
    finally {
      $output.Dispose()
    }
  }

  $expected = Get-ExpectedSha256 -HashFile $hashFile
  $actual = (Get-FileHash -LiteralPath $outPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $expected) {
    throw ("SHA-256 mismatch for {0}`n  expected: {1}`n  actual:   {2}" -f $Name, $expected, $actual)
  }

  Write-Host ("OK: {0}" -f $outPath)
  Write-Host ("SHA-256: {0}" -f $actual)
  return $outPath
}

if ([string]::IsNullOrWhiteSpace($InstallerName)) {
  $targets = @(
    Get-ChildItem -LiteralPath $PartsDir -File |
      Where-Object { $_.Name -match '^GoldenEraModInstaller-.*\.exe\.part\d{2}$' } |
      ForEach-Object { ($_.Name -replace '\.part\d{2}$', '') } |
      Sort-Object -Unique
  )
  if ($targets.Count -eq 0) {
    $targets = @(
      Get-ChildItem -LiteralPath $PartsDir -File -Filter 'GoldenEraModInstaller-*.exe' |
        Where-Object { $_.Name -notmatch '\.part\d{2}$' } |
        ForEach-Object { $_.Name }
    )
  }
  if ($targets.Count -eq 0) {
    throw "No GoldenEraModInstaller-*.exe.partNN files found in $PartsDir"
  }
}
else {
  $targets = @($InstallerName)
}

foreach ($target in $targets) {
  Join-OneInstaller -Name $target | Out-Null
}

Write-Host ''
Write-Host 'Join complete. Run the reassembled .exe to install Golden Era.'
