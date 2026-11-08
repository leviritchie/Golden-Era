<#
.SYNOPSIS
  Unattended, non-deploying OfflineUnlockMod build (compile + quick tier) from a clean git export.

.DESCRIPTION
  Exports -Ref with `git archive` (the plugin project and tools/), or uses -SourceDir if it is already a
  clean export. The export lives outside the repo, so the csproj's ..\..\tools validators come from the
  same commit and not from the shared worktree. The script then runs the quick tier:
    compile; ValidatePluginLiveInteropRefs; ValidateGameSymbolsHintContract (current build, with the
    literal-confinement and generated-scope freshness checks).
  It never deploys and never starts, attaches to or stops the game. The game interop under -GameRoot
  is only read.

  Each gating property is passed explicitly, because MSBuild also imports environment variables as
  properties. A stray SkipGameSymbolsHintContract / DeployPluginToGame / FullValidation in the agent's
  environment therefore cannot change what runs. Only one build runs at a time per -WorkDir (lock file).

  Untracked compile inputs: two git-ignored folders the plugin compiles against are not in an export,
  so they are copied read-only from -UntrackedInputsFrom (default: the repo checkout's plugin folder).
  This is the same pair rc_build.sh copied:
    publish_plugin\                     Unity/BepInEx reference assemblies (UnityInteropRootDir);
    tools\_dump_types\bin\              its Hex*.dll are SDK None items. MSBuild's CandidateAssemblyFiles
                                        search path picks them before the Hex HintPath (GameRoot interop),
                                        so shipping builds compile against them.
  The Hex.dll SHA-256 of each is recorded in the summary.

  -ReleaseCandidate compiles the shipping (ReleaseCandidateBuild=true) code set: the live-probe
  workbench, AI driver bridge and other maintainer-only sources are left out and RELEASE_CANDIDATE_BUILD
  is defined. In the csproj, ReleaseCandidateBuild=true also forces FullValidationNormalized=true. The
  nightly lane is approved to ship on the quick tier, so the build patches that one coupling in the
  throwaway export only, never in the repo. The patch must match exactly once or the build fails with
  exit 2. The repo csproj and every other gate are untouched. The built DLL is then checked to contain
  none of the maintainer-only markers.
  -InformationalVersion sets AssemblyInformationalVersion, for example nightly-20261006-abc1234.
  Plugin.PluginVersion, the BepInEx version, is a source constant and stays as committed.

  Exit codes: 0 = pass; 1 = build or gate failure (short summary printed); 2 = bad arguments or
  environment; 3 = timeout (only this script's own dotnet process tree is stopped).

.EXAMPLE
  pwsh -NoProfile -File tools/nightly/build_plugin.ps1 `
    -GameRoot 'V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era' `
    -OutDir 'V:\olden_port_work\nightly\out'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $GameRoot,
    [Parameter(Mandatory)] [string] $OutDir,
    [string] $Ref = 'HEAD',
    [string] $Repo,
    [string] $SourceDir,
    [string] $UntrackedInputsFrom,
    [string] $WorkDir,
    [int] $TimeoutMinutes = 30,
    [switch] $KeepExport,
    [switch] $ReleaseCandidate,
    [string] $InformationalVersion
)

$ErrorActionPreference = 'Stop'
$PluginRel = 'Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod'
$ExportPaths = @($PluginRel, 'tools')

function Fail([int] $code, [string] $message) {
    Write-Host "NIGHTLY BUILD: FAIL ($message)"
    exit $code
}

function Under([string] $child, [string] $parent) {
    $c = [IO.Path]::GetFullPath($child).TrimEnd('\') + '\'
    $p = [IO.Path]::GetFullPath($parent).TrimEnd('\') + '\'
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}

# ---- arguments and toolchain ------------------------------------------------------------------
foreach ($tool in 'dotnet', 'python', 'git') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Fail 2 "$tool not on PATH" }
}
$GameRoot = [IO.Path]::GetFullPath($GameRoot)
$interop = Join-Path $GameRoot 'BepInEx\interop'
if (-not (Test-Path -LiteralPath (Join-Path $interop 'Hex.dll'))) { Fail 2 "no BepInEx\interop\Hex.dll under GameRoot $GameRoot" }
$OutDir = [IO.Path]::GetFullPath($OutDir)
if (-not $WorkDir) { $WorkDir = Join-Path $OutDir '_work' }
$WorkDir = [IO.Path]::GetFullPath($WorkDir)
if (-not $SourceDir) {
    if (-not $Repo) { $Repo = (& git -C $PSScriptRoot rev-parse --show-toplevel 2>$null) }
    if (-not $Repo) { Fail 2 'no -Repo given and the script is not inside a git checkout (pass -Repo or -SourceDir)' }
    $Repo = [IO.Path]::GetFullPath($Repo)
    foreach ($d in $OutDir, $WorkDir) {
        if (Under $d $Repo) { Fail 2 "$d is inside the repo; use a scratch dir outside it so ..\..\tools resolves into the export" }
    }
}
if ((Under $OutDir $GameRoot) -or (Under $WorkDir $GameRoot)) { Fail 2 'OutDir/WorkDir must not be inside GameRoot (this script never deploys)' }

[void](New-Item -ItemType Directory -Force -Path $OutDir, $WorkDir)
$lockPath = Join-Path $WorkDir 'build.lock'
try { $lock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
catch { Fail 2 "another build holds $lockPath" }

$watch = [Diagnostics.Stopwatch]::StartNew()
$log = Join-Path $OutDir 'build.log'
$summaryPath = Join-Path $OutDir 'build_summary.json'
$binDir = Join-Path $OutDir 'bin'
$exitCode = 1
$commit = $null
$refHexSha = $null
$exported = $false
try {
    # ---- source: clean export of -Ref --------------------------------------------------------
    if ($SourceDir) {
        $src = [IO.Path]::GetFullPath($SourceDir)
        $commit = if (Test-Path -LiteralPath (Join-Path $src 'EXPORT_COMMIT')) { (Get-Content -LiteralPath (Join-Path $src 'EXPORT_COMMIT') -Raw).Trim() } else { 'unknown (-SourceDir)' }
    } else {
        $commit = (& git -C $Repo rev-parse --verify "$Ref^{commit}").Trim()
        if ($LASTEXITCODE -ne 0 -or -not $commit) { Fail 2 "cannot resolve ref $Ref" }
        $src = Join-Path $WorkDir 'src'
        $staleLink = Join-Path $src 'artifacts\port_current\p2\index_cache'
        if (Test-Path -LiteralPath $staleLink) { (Get-Item -LiteralPath $staleLink).Delete() }   # unlink only, never the shared cache
        if (Test-Path -LiteralPath $src) { Remove-Item -LiteralPath $src -Recurse -Force }
        [void](New-Item -ItemType Directory -Force -Path $src)
        $tarball = Join-Path $WorkDir 'export.tar'
        & git -C $Repo archive --format=tar -o $tarball $commit -- @ExportPaths
        if ($LASTEXITCODE -ne 0) { Fail 2 "git archive $commit failed" }
        # Windows bsdtar: a GNU tar from Git/MSYS on PATH would read 'V:\...' as a remote host.
        $winTar = Join-Path $env:SystemRoot 'System32\tar.exe'
        if (Test-Path -LiteralPath $winTar) { & $winTar -xf $tarball -C $src } else { & tar --force-local -xf $tarball -C $src }
        if ($LASTEXITCODE -ne 0) { Fail 2 'tar extract failed' }
        Remove-Item -LiteralPath $tarball -Force
        Set-Content -LiteralPath (Join-Path $src 'EXPORT_COMMIT') -Value $commit -NoNewline
        $exported = $true
    }
    $pluginSrc = Join-Path $src $PluginRel
    if (-not $UntrackedInputsFrom -and $Repo) { $UntrackedInputsFrom = Join-Path $Repo $PluginRel }
    $refHexSha = [ordered]@{}
    foreach ($rel in 'publish_plugin', 'tools\_dump_types\bin') {
        $dest = Join-Path $pluginSrc $rel
        if ($UntrackedInputsFrom) {
            $from = Join-Path ([IO.Path]::GetFullPath($UntrackedInputsFrom)) $rel
            if (-not (Test-Path -LiteralPath $from)) { Fail 2 "untracked compile input missing: $from" }
            if ([IO.Path]::GetFullPath($from).TrimEnd([char]92) -ne [IO.Path]::GetFullPath($dest).TrimEnd([char]92)) {
                if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
                [void](New-Item -ItemType Directory -Force -Path (Split-Path $dest))
                Copy-Item -LiteralPath $from -Destination $dest -Recurse
            }
        }
        $hex = @(Get-ChildItem -LiteralPath $dest -Recurse -Filter 'Hex.dll' -File -ErrorAction SilentlyContinue)
        if (-not $hex) { Fail 2 "no Hex.dll under $dest (pass -UntrackedInputsFrom)" }
        $refHexSha[$rel] = (Get-FileHash -LiteralPath $hex[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $csproj = Join-Path $src ($PluginRel + '/OfflineUnlockMod.csproj')
    if (-not (Test-Path -LiteralPath $csproj)) { Fail 2 "no OfflineUnlockMod.csproj in $src" }
    $rcQuickTierPatch = $null
    if ($ReleaseCandidate) {
        if (-not $exported) { Fail 2 '-ReleaseCandidate patches the export csproj, so it needs -Ref (not -SourceDir)' }
        # Export-only: drop "or ReleaseCandidateBuild == true" from the FullValidationNormalized condition.
        $needle = " or '`$(ReleaseCandidateBuild)' == 'true'`">true</FullValidationNormalized>"
        $projText = [IO.File]::ReadAllText($csproj)
        $hits = ([regex]::Matches($projText, [regex]::Escape($needle))).Count
        if ($hits -ne 1) { Fail 2 "RC quick-tier patch expected 1 FullValidationNormalized/ReleaseCandidateBuild coupling in the csproj, found $hits" }
        [IO.File]::WriteAllText($csproj, $projText.Replace($needle, '">true</FullValidationNormalized>'))
        $rcQuickTierPatch = 'export csproj: ReleaseCandidateBuild no longer implies FullValidationNormalized'
    }

    # The interop shape index is content-keyed (Hex.dll + every interop dll + indexer source), so a
    # cache shared across runs can never be stale. Keep it outside the throwaway export.
    $cache = Join-Path $WorkDir 'index_cache'
    [void](New-Item -ItemType Directory -Force -Path $cache)
    $cacheLink = Join-Path $src 'artifacts\port_current\p2\index_cache'
    if (-not (Test-Path -LiteralPath $cacheLink)) {
        [void](New-Item -ItemType Directory -Force -Path (Split-Path $cacheLink))
        [void](New-Item -ItemType Junction -Path $cacheLink -Target $cache)
    }

    # ---- quick-tier build, never deploying -----------------------------------------------------
    if (Test-Path -LiteralPath $binDir) { Remove-Item -LiteralPath $binDir -Recurse -Force }
    $gameRootArg = $GameRoot.TrimEnd('\') + '\'
    $buildArgs = @(
        'build', "`"$csproj`"", '-c', 'Release', '--nologo', '-m:1', '-nodeReuse:false',
        '-p:UseSharedCompilation=false',
        '-p:OfficialDeobfBuild=true',
        '-p:DeployPluginToGame=false',
        '-p:FullValidation=false',
        "-p:ReleaseCandidateBuild=$(if ($ReleaseCandidate) { 'true' } else { 'false' })",
        '-p:GameSymbolsHintContractBuild=current',
        '-p:SkipGameSymbolsHintContract=false',
        '-p:SkipPluginLiveInteropRefs=false',
        "`"-p:GameRoot=$gameRootArg\`"",
        "`"-p:OutDir=$binDir\\`""
    )
    if ($InformationalVersion) {
        if ($InformationalVersion -notmatch '^[A-Za-z0-9][A-Za-z0-9.+-]{0,63}$') { Fail 2 "bad -InformationalVersion '$InformationalVersion'" }
        $buildArgs += "-p:InformationalVersion=$InformationalVersion"
    }
    $stderr = Join-Path $OutDir 'build.stderr.log'
    $proc = Start-Process -FilePath (Get-Command dotnet).Source -ArgumentList $buildArgs -WorkingDirectory $src `
        -NoNewWindow -PassThru -RedirectStandardOutput $log -RedirectStandardError $stderr
    [void]$proc.Handle
    if (-not $proc.WaitForExit($TimeoutMinutes * 60 * 1000)) {
        # Stop only the process tree this script started.
        $all = @(Get-CimInstance Win32_Process)
        $owned = [Collections.Generic.HashSet[int]]::new(); [void]$owned.Add($proc.Id)
        do {
            $added = $false
            foreach ($p in $all) { if ($owned.Contains([int]$p.ParentProcessId) -and $owned.Add([int]$p.ProcessId)) { $added = $true } }
        } while ($added)
        foreach ($id in $owned) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
        $exitCode = 3
    } else {
        $proc.WaitForExit()
        $exitCode = if ($proc.ExitCode -eq 0) { 0 } else { 1 }
    }
} finally {
    $watch.Stop()
    $lock.Dispose()
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}

# ---- summary --------------------------------------------------------------------------------
$text = if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log } else { @() }
$problems = @($text | Where-Object {
        $_ -match ': error ' -or $_ -match '^\s+NEW ' -or $_ -match '^\s+STALE ' -or $_ -match '^\s*FAIL' -or $_ -match 'contract: FAIL'
    } | ForEach-Object { ($_ -replace '\s+\[[^\]]*\.csproj\]$', '').Trim() } | Select-Object -Unique)
$gateLine = @($text | Where-Object { $_ -match 'game symbols hint contract: ' } | Select-Object -Last 1)
$interopLine = @($text | Where-Object { $_ -match 'Live interop reference check:' } | Select-Object -Last 1)
$dll = Join-Path $binDir 'OfflineUnlockMod.dll'
$dllSha = if ($exitCode -eq 0 -and (Test-Path -LiteralPath $dll)) { (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
if ($exitCode -eq 0 -and -not $dllSha) { $exitCode = 1; $problems += 'build exited 0 but OfflineUnlockMod.dll is missing' }
if ($exitCode -eq 0 -and $ReleaseCandidate) {
    # The maintainer-only sources must be compiled out of a ReleaseCandidate DLL.
    $latin1 = [Text.Encoding]::GetEncoding('iso-8859-1').GetString([IO.File]::ReadAllBytes($dll))
    foreach ($marker in 'Homm3LiveProbeWorkbench', 'live_probe_bridge') {
        if ($latin1.Contains($marker)) { $exitCode = 1; $problems += "ReleaseCandidate DLL still contains $marker" }
    }
}
$status = switch ($exitCode) { 0 { 'pass' } 3 { 'timeout' } default { 'fail' } }
[ordered]@{
    schema = 'nightly_plugin_build.v1'
    status = $status
    exitCode = $exitCode
    commit = $commit
    gameRoot = $GameRoot
    untrackedInputsFrom = $UntrackedInputsFrom
    untrackedInputHexSha256 = $refHexSha
    releaseCandidate = [bool]$ReleaseCandidate
    rcQuickTierPatch = $rcQuickTierPatch
    informationalVersion = $(if ($InformationalVersion) { $InformationalVersion } else { $null })
    elapsedSeconds = [Math]::Round($watch.Elapsed.TotalSeconds, 1)
    dll = $(if ($dllSha) { $dll } else { $null })
    dllSha256 = $dllSha
    hintContract = $(if ($gateLine) { $gateLine[0].Trim() } else { $null })
    liveInterop = $(if ($interopLine) { $interopLine[0].Trim() } else { $null })
    problems = @($problems | Select-Object -First 40)
    log = $log
    deployed = $false
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding utf8

if ($exported -and -not $KeepExport -and $exitCode -eq 0) {
    if (Test-Path -LiteralPath $cacheLink) { (Get-Item -LiteralPath $cacheLink).Delete() }   # unlink first; keeps the shared cache
    Remove-Item -LiteralPath $src -Recurse -Force -ErrorAction SilentlyContinue
}

if ($exitCode -eq 0) {
    Write-Host "NIGHTLY BUILD: PASS commit=$commit elapsed=$([Math]::Round($watch.Elapsed.TotalSeconds))s dll=$dll sha256=$dllSha"
    exit 0
}
Write-Host "NIGHTLY BUILD: $($status.ToUpper()) commit=$commit exit=$exitCode elapsed=$([Math]::Round($watch.Elapsed.TotalSeconds))s"
$problems | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" }
Write-Host "  log: $log  summary: $summaryPath"
exit $exitCode
