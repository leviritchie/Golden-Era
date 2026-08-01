param(
    [string]$ReleaseInputsDir = "release_inputs",
    [string]$OutputZipName = "golden_era_release_payload.zip"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$InputsDir = if ([System.IO.Path]::IsPathRooted($ReleaseInputsDir)) {
    [System.IO.Path]::GetFullPath($ReleaseInputsDir)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $ReleaseInputsDir))
}
$OutputZip = Join-Path $InputsDir $OutputZipName
$ShaPath = "$OutputZip.sha256"

function Require-Path($Path, $Message) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw $Message
    }
}

Require-Path $InputsDir "Release inputs directory was not found: $InputsDir"
Require-Path $ShaPath "Release input checksum was not found: $ShaPath"

$parts = @(Get-ChildItem -LiteralPath $InputsDir -File -Filter "$OutputZipName.part*" |
    Sort-Object { [int]([regex]::Match($_.Name, '\.part(\d+)$').Groups[1].Value) })
if ($parts.Count -le 0) {
    Require-Path $OutputZip "Release input zip/parts were not found under: $InputsDir"
} else {
    Write-Host "Assembling $($parts.Count) release-input part(s) into $OutputZip"
    if (Test-Path -LiteralPath $OutputZip) {
        Remove-Item -LiteralPath $OutputZip -Force
    }
    $outStream = [System.IO.File]::Open($OutputZip, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $buffer = New-Object byte[] (1024 * 1024)
        foreach ($part in $parts) {
            Write-Host "  + $($part.Name) ($([Math]::Round($part.Length / 1MB, 1)) MB)"
            $inStream = [System.IO.File]::OpenRead($part.FullName)
            try {
                while (($read = $inStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $outStream.Write($buffer, 0, $read)
                }
            }
            finally {
                $inStream.Dispose()
            }
        }
    }
    finally {
        $outStream.Dispose()
    }
}

$expected = (Get-Content -LiteralPath $ShaPath).Split(" ")[0].Trim().ToLowerInvariant()
$actual = (Get-FileHash -LiteralPath $OutputZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    throw "Assembled release input checksum mismatch: expected $expected actual $actual"
}

Write-Host "Release input ready: $OutputZip"
Write-Host "Release input SHA-256: $actual"
