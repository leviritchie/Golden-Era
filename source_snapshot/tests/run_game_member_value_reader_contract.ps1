$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$reader = Join-Path $repoRoot 'Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\GameMemberValueReader.cs'
$fixture = Join-Path $PSScriptRoot 'GameMemberValueReaderContract.cs'

Add-Type -Path @($reader, $fixture)
[GameMemberValueReaderContract]::Run()
Write-Output 'GameMemberValueReader synthetic contract: OK'
