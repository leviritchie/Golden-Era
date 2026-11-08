<#
.SYNOPSIS
  Best-effort: put the plugin from a nightly commit into the local Golden Era copy. Never a blocker.

.DESCRIPTION
  Builds -Ref with build_plugin.ps1 in its maintainer code set (no -ReleaseCandidate). The local copy runs
  maintainer builds, so the live-probe tooling other agents use stays. It then swaps only
  BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll. The nightly payload's content is staged from this
  same copy, so the DLL is the only thing the nightly changes, plus its OfflineUnlockMod.payload_abi.json
  sidecar: after the swap the sidecar is regenerated with tools/plugin_payload_abi/payload_abi.py emit, run from
  a git export of -Ref (so its surface versions are that commit's PluginPayloadAbi.cs consts), and verified with
  check-installed --require-source. A stale sidecar makes ship_def_retarget_slice.py deploy refuse.

  It skips, with exit 0 and a reason, instead of failing when:
    - the game (HeroesOldenEra) is running. The process is only looked up, never touched;
    - the cross-agent board has a task in 'doing' scoped to resource golden-era-deploy (read-only SQLite query);
    - the installed DLL was written after -Ref was committed (someone deployed something newer);
    - the installed DLL is already this build (same SHA-256) and its sidecar checks out. A stale sidecar next
      to an already-current DLL is regenerated instead ("DEPLOYED sidecar-only ...");
    - the DLL is locked when it comes to copying it.
  The previous DLL and its sidecar are backed up under -WorkDir\backup (newest 5 kept), and the copy is read
  back by SHA-256. On a readback mismatch, a failed sidecar emit or a failed check-installed, both are restored
  (a sidecar that did not exist before is removed) and the result is FAIL, never DEPLOYED.

  Last line: "LOCAL DEPLOY: DEPLOYED ...", "LOCAL DEPLOY: SKIPPED <reason>" or "LOCAL DEPLOY: FAIL <reason>".
  Exit codes: 0 = deployed or skipped; 1 = build, copy or sidecar failure (the local copy is left as it was).
  A summary goes to -WorkDir\deploy_summary.json.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Ref,
    [Parameter(Mandatory)] [string] $Repo,
    [string] $GameRoot = 'V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era',
    [string] $WorkDir = 'N:\nightly\local_deploy',
    [string] $UntrackedInputsFrom,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginRel = 'Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod'
$target = Join-Path $GameRoot 'BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll'
$pluginDir = Split-Path -Parent $target
$sidecar = Join-Path $pluginDir 'OfflineUnlockMod.payload_abi.json'
[void](New-Item -ItemType Directory -Force -Path $WorkDir)
$summary = [ordered]@{ ref = $Ref; target = $target; started = (Get-Date).ToString('o') }

function Finish([string] $status, [string] $reason, [int] $code) {
    $summary.status = $status; $summary.reason = $reason; $summary.finished = (Get-Date).ToString('o')
    $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $WorkDir 'deploy_summary.json') -Encoding utf8
    Write-Host "LOCAL DEPLOY: $status $reason"
    exit $code
}

function Test-GameRunning {
    [bool](Get-Process -Name 'HeroesOldenEra' -ErrorAction SilentlyContinue)
}

# payload_abi.py from the -Ref export (see "payload ABI tool at -Ref" below): exit code and output.
function Invoke-Abi([string[]] $abiArgs) {
    $ErrorActionPreference = 'Continue'
    $o = & python $abiPy @abiArgs 2>&1
    @{ code = $LASTEXITCODE; out = (($o | ForEach-Object { "$_" }) -join ' | ') }
}

# Regenerates the installed sidecar for the installed DLL and verifies it. Returns $null or the failure.
function Update-Sidecar {
    $emit = Invoke-Abi @('emit', '--dll', $target)
    $summary.abiEmit = $emit.out
    if ($emit.code -ne 0) { return "payload_abi emit failed: $($emit.out)" }
    $check = Invoke-Abi @('check-installed', '--plugin-dir', $pluginDir, '--require-source')
    $summary.abiCheck = $check.out
    if ($check.code -ne 0) { return "payload_abi check-installed failed: $($check.out)" }
    return $null
}

# Puts the backed-up DLL and sidecar back (removes a sidecar that did not exist before the swap).
function Restore-Backup {
    $done = @()
    try { Copy-Item -LiteralPath $backup -Destination $target -Force; $done += 'dll' }
    catch { $done += "dll NOT restored ($($_.Exception.Message))" }
    try {
        if ($sidecarBackup) { Copy-Item -LiteralPath $sidecarBackup -Destination $sidecar -Force }
        elseif (Test-Path -LiteralPath $sidecar) { Remove-Item -LiteralPath $sidecar -Force }
        $done += 'sidecar'
    } catch { $done += "sidecar NOT restored ($($_.Exception.Message))" }
    $summary.restored = $done -join ', '
    return $summary.restored
}

$Repo = [IO.Path]::GetFullPath($Repo)
$sha = (& git -C $Repo rev-parse --verify "$Ref^{commit}" 2>$null)
if (-not $sha) { Finish 'FAIL' "cannot resolve $Ref" 1 }
$sha = $sha.Trim(); $summary.sha = $sha
$commonDir = (& git -C $Repo rev-parse --path-format=absolute --git-common-dir).Trim()
$mainCheckout = [IO.Path]::GetFullPath((Split-Path -Parent $commonDir))
if (-not $UntrackedInputsFrom) {
    $UntrackedInputsFrom = Join-Path $Repo $pluginRel
    if (-not (Test-Path -LiteralPath (Join-Path $UntrackedInputsFrom 'publish_plugin\Hex.dll'))) { $UntrackedInputsFrom = Join-Path $mainCheckout $pluginRel }
}
if (-not (Test-Path -LiteralPath $target)) { Finish 'SKIPPED' "no installed plugin at $target" 0 }

# ---- cheap skip checks before building --------------------------------------------------------------
if (Test-GameRunning) { Finish 'SKIPPED' 'game is running' 0 }

$store = Join-Path $mainCheckout '.cross-agent\state.sqlite3'
if (Test-Path -LiteralPath $store) {
    $claimPy = @'
import sqlite3, sys
uri = "file:" + sys.argv[1].replace("\\", "/") + "?mode=ro"
c = sqlite3.connect(uri, uri=True)
rows = c.execute("select t.id, a.name from tasks t join task_scopes s on s.task_id = t.id left join agents a on a.id = t.owner_agent_id "
                 "where t.status = 'doing' and s.kind = 'resource' and s.value = 'golden-era-deploy'").fetchall()
print(";".join(f"{r[0]}:{r[1]}" for r in rows))
'@
    $claims = ($claimPy | python - $store 2>$null)
    if ($LASTEXITCODE -ne 0) { Finish 'SKIPPED' 'could not read the cross-agent board' 0 }
    if ($claims) { $summary.claims = $claims; Finish 'SKIPPED' "golden-era-deploy is claimed ($claims)" 0 }
}

$commitTime = [DateTimeOffset]::FromUnixTimeSeconds([long](& git -C $Repo show -s --format=%ct $sha)).UtcDateTime
$installedTime = (Get-Item -LiteralPath $target).LastWriteTimeUtc
$summary.commitUtc = $commitTime.ToString('o'); $summary.installedUtc = $installedTime.ToString('o')
if (-not $Force -and $installedTime -gt $commitTime) { Finish 'SKIPPED' 'installed DLL is newer than this commit (a later local deploy)' 0 }

# ---- build (maintainer code set, quick tier) ------------------------------------------------------
$buildOut = Join-Path $WorkDir 'build'
$out = & pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'build_plugin.ps1') -GameRoot $GameRoot -OutDir $buildOut `
    -Ref $sha -Repo $Repo -UntrackedInputsFrom $UntrackedInputsFrom -InformationalVersion ("nightly-local-{0}" -f $sha.Substring(0, 8)) 2>&1
$summary.build = ($out | Select-Object -Last 1) -as [string]
if ($LASTEXITCODE -ne 0) { Finish 'FAIL' "plugin build failed: $($summary.build)" 1 }
$built = Join-Path $buildOut 'bin\OfflineUnlockMod.dll'

# ---- payload ABI tool at -Ref ----------------------------------------------------------------------
# payload_abi.py reads PluginPayloadAbi.cs relative to its own location, so it runs from an export of exactly
# this commit, not from -Repo's working tree (which may sit at another commit or hold uncommitted edits).
$abiSrc = Join-Path $WorkDir 'abi_src'
if (Test-Path -LiteralPath $abiSrc) { Remove-Item -LiteralPath $abiSrc -Recurse -Force }
[void](New-Item -ItemType Directory -Force -Path $abiSrc)
$abiRel = 'tools/plugin_payload_abi'
try { $abiSource = ((& git -C $Repo show "${sha}:$abiRel/surfaces.json") -join "`n" | ConvertFrom-Json).source }
catch { $abiSource = $null }
if (-not $abiSource) { Finish 'FAIL' "no readable $abiRel/surfaces.json at $sha" 1 }
$abiTar = Join-Path $WorkDir 'abi_src.tar'
& git -C $Repo archive --format=tar -o $abiTar $sha -- $abiRel $abiSource
if ($LASTEXITCODE -ne 0) { Finish 'FAIL' "git archive of the payload ABI tool at $sha failed" 1 }
# Windows bsdtar: a GNU tar from Git/MSYS on PATH would read 'N:\...' as a remote host.
$winTar = Join-Path $env:SystemRoot 'System32\tar.exe'
if (Test-Path -LiteralPath $winTar) { & $winTar -xf $abiTar -C $abiSrc } else { & tar --force-local -xf $abiTar -C $abiSrc }
if ($LASTEXITCODE -ne 0) { Finish 'FAIL' 'payload ABI tool extract failed' 1 }
Remove-Item -LiteralPath $abiTar -Force
$abiPy = Join-Path $abiSrc 'tools\plugin_payload_abi\payload_abi.py'

$newHash = (Get-FileHash -LiteralPath $built -Algorithm SHA256).Hash
$oldHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
$summary.newSha256 = $newHash; $summary.oldSha256 = $oldHash
if ($newHash -eq $oldHash) {
    $check = Invoke-Abi @('check-installed', '--plugin-dir', $pluginDir, '--require-source')
    $summary.abiCheck = $check.out
    if ($check.code -eq 0) { Finish 'SKIPPED' 'installed DLL is already this build' 0 }
    # Same DLL, stale or missing sidecar (a DLL copied by hand, or an older deploy_local): regenerate the sidecar only.
    if (Test-GameRunning) { Finish 'SKIPPED' 'installed DLL is already this build; game is running, sidecar left stale' 0 }
    $err = Update-Sidecar
    if ($err) { Finish 'FAIL' "installed DLL is already this build; $err" 1 }
    Finish 'DEPLOYED' ("sidecar-only sha={0} dll={1} (DLL unchanged, payload_abi sidecar regenerated)" -f $sha.Substring(0, 10), $newHash.Substring(0, 12)) 0
}

# The build takes a minute; the game may have started meanwhile.
if (Test-GameRunning) { Finish 'SKIPPED' 'game started during the build' 0 }

# ---- swap ------------------------------------------------------------------------------------------
$backupDir = Join-Path $WorkDir 'backup'
[void](New-Item -ItemType Directory -Force -Path $backupDir)
$backup = Join-Path $backupDir ("OfflineUnlockMod.{0:yyyyMMdd-HHmmss}.{1}.dll" -f (Get-Date), $oldHash.Substring(0, 8))
Copy-Item -LiteralPath $target -Destination $backup
$summary.backup = $backup
$sidecarBackup = $null
if (Test-Path -LiteralPath $sidecar) {
    $sidecarBackup = [IO.Path]::ChangeExtension($backup, '.payload_abi.json')
    Copy-Item -LiteralPath $sidecar -Destination $sidecarBackup
    $summary.sidecarBackup = $sidecarBackup
}
Get-ChildItem -LiteralPath $backupDir -Filter 'OfflineUnlockMod.*.dll' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 5 | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Force
    Remove-Item -LiteralPath ([IO.Path]::ChangeExtension($_.FullName, '.payload_abi.json')) -Force -ErrorAction SilentlyContinue
}

try { Copy-Item -LiteralPath $built -Destination $target -Force }
catch { Finish 'SKIPPED' "installed DLL is locked: $($_.Exception.Message)" 0 }

$readback = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
if ($readback -ne $newHash) {
    $restored = Restore-Backup
    Finish 'FAIL' "readback mismatch ($readback); restored: $restored" 1
}

# ---- sidecar: regenerate for the installed DLL, then verify ----------------------------------------
$err = Update-Sidecar
if ($err) {
    $restored = Restore-Backup
    Finish 'FAIL' "$err; restored: $restored" 1
}
Finish 'DEPLOYED' ("sha={0} dll={1} backup={2}" -f $sha.Substring(0, 10), $newHash.Substring(0, 12), $backup) 0
