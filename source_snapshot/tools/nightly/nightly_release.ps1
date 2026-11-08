<#
.SYNOPSIS
  Nightly Golden Era release: full payload build, both installers and (with -Publish) the rolling
  `nightly` prerelease on the public repo. Non-interactive; meant to run every 6 hours.

.DESCRIPTION
  Steps (each is timed in the JSON summary):
    preflight     N: is mounted with label GENightly, toolchain present, gh authenticated, lock taken,
                  previous run's work removed, free space >= measured need.
    build         tools/nightly/build_plugin.ps1 on a clean git export of -Ref: ReleaseCandidate code
                  set, quick tier (compile + live-interop refs + game-symbols hint gate), never deploys.
    stage         tools/nightly/stage_release_payload.ps1: full payload from the Golden Era install
                  plus the -Ref plugin DLL, with the leftover filters, JSON sanitizer and leak gate.
    zip           payload zip (Fastest) written straight into the public clone's dist folder on N:,
                  sha256, structure check; the stage is deleted as soon as the zip checks out. The zip
                  is deterministic (ordinal path order, one fixed entry timestamp), so an unchanged
                  file gives the same bytes in every nightly.
    installers    both installers (upscaled / standard portraits) from the public clone's tools, tag
                  `nightly`, payload name golden_era_release_payload-<label>.zip.
    split         the zip is split IN PLACE (copy the tail to a part, truncate, repeat), so the peak is
                  zip + one part, never two copies. Parts are hashed as written. Nightly: parts are cut
                  at zip entry boundaries chosen from the entry names (-ChunkMinBytes, -ChunkModulo,
                  -ChunkSoftMaxBytes), the central directory is its own part, and each part is named
                  golden_era_payload.<sha256 prefix>.part, so a code-only change makes only a few new
                  parts; the installer footers are rewritten to list them. Versioned releases keep
                  uniform 1.9 GB <base>.partNN parts.
    plan          --print-plan of both EXEs: every download URL must be .../releases/download/nightly/<part>
                  for a part that exists in the asset folder; footers must agree with the parts.
    verify        offline installer check from the clean 25672315 mirror. A full --headless install
                  needs mirror + 2 x uncompressed payload of free space and a -Homm3Root; when that
                  does not fit, the installer's own --verify-payload runs instead (sha256 over the
                  parts, zip structure, overlay operation count). The choice and numbers are recorded.
    notes         generic release notes from filtered commit subjects (never bug-report text).
    publish       only with -Publish: create/update the `nightly` prerelease (never Latest), upload
                  with --clobber (a content-named part already on the release with the same size is
                  not uploaded again), delete stale nightly assets, set notes, move the nightly tag to the
                  public main. No other tag or release is touched; Latest is verified unchanged.
    cleanup       N: is emptied except logs (last 10 runs), state.json, builds.json and reports.
                  Without -Publish the asset folder is kept for inspection (the path is printed).

  Versioned release mode (-ReleaseTag vX.Y.Z [-Latest] -NotesFile <md> [-ReleaseTitle] [-ExpectPublicSha]):
  same build, gates and checks, but the label, asset names and installer tag are the release tag;
  Plugin.PluginVersion at -Ref must equal it; the tag must not exist yet; public main must have no
  workflow that fires on a push, tag or release; the notes come from -NotesFile (leak-scanned). Publish
  creates a draft at the public main the installers were built from, uploads, checks, then publishes it
  as a full release (Latest with -Latest). It refuses a payload whose sha equals the previous release's
  or the current Latest's .sha256 asset. After publishing it waits -SettleSeconds (180), re-lists the
  assets through the API and fails loudly if names, sizes, digests, asset ids, the advertised payload
  sha, the tag or Latest changed, or if any workflow run started since the publish. Nightly state
  (lastPublishedSha) is not touched.

  Exit codes: 0 pass; 10 preflight; 11 another run holds the lock; 20 plugin build; 21 build
  timeout; 30 payload staging/gates; 40 sanitizer/leak gate; 50 zip/split; 60 installers/plan;
  70 install verification; 80 publish; 90 unexpected.

.EXAMPLE
  pwsh -NoProfile -ExecutionPolicy Bypass -File tools/nightly/nightly_release.ps1            # dry run
  pwsh -NoProfile -ExecutionPolicy Bypass -File tools/nightly/nightly_release.ps1 -Publish   # publish
  pwsh -NoProfile -ExecutionPolicy Bypass -File tools/nightly/nightly_release.ps1 -Publish -ReleaseTag v0.1.320 -Latest -NotesFile notes.md
#>
[CmdletBinding()]
param(
    [string] $Ref = 'HEAD',
    [switch] $Publish,
    [string] $WorkRoot = 'N:\nightly',
    [string] $GameRoot = 'V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era',
    [string] $CleanMirror = 'V:\olden_mirrors\Heroes of Might and Magic Olden Era - Current Era 25672315',
    [string] $Repo,
    [string] $Homm3Root,
    # Plugin folder holding the git-ignored compile inputs, forwarded to build_plugin.ps1. Default: -Repo's
    # plugin folder, or the main checkout's when -Repo is a linked worktree without them. Read only.
    [string] $UntrackedInputsFrom,
    [int] $BuildTimeoutMinutes = 40,
    [long] $MaxPartBytes = 1900000000,
    # Nightly part cuts (see split): a part ends at the first zip entry at or past -ChunkMinBytes whose
    # name hashes to 0 mod -ChunkModulo, or at the first entry at or past -ChunkSoftMaxBytes.
    [long] $ChunkMinBytes = 128MB,
    [long] $ChunkSoftMaxBytes = 512MB,
    [int] $ChunkModulo = 8,
    [switch] $KeepAssets,
    [switch] $KeepWork,
    # Versioned release mode (README: "Versioned release"). -ReleaseTag switches the run from the
    # rolling nightly to a new, never-used stable tag such as v0.1.320.
    [string] $ReleaseTag,
    [switch] $Latest,
    [string] $NotesFile,
    [string] $ReleaseTitle,
    [string] $ExpectPublicSha,
    [int] $SettleSeconds = 180
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Off

$Tag = 'nightly'
$ReleaseMode = [bool]$ReleaseTag
if ($ReleaseMode) {
    if ($ReleaseTag -notmatch '^v\d+\.\d+\.\d+$') { Write-Host 'RELEASE: FAIL exit=10 -ReleaseTag must look like v0.1.320'; exit 10 }
    if (-not $NotesFile -or -not (Test-Path -LiteralPath $NotesFile)) { Write-Host 'RELEASE: FAIL exit=10 -NotesFile is required in release mode and must exist'; exit 10 }
    $NotesFile = (Resolve-Path -LiteralPath $NotesFile).Path
    $Tag = $ReleaseTag
    if (-not $ReleaseTitle) { $ReleaseTitle = "Golden Era $ReleaseTag" }
} elseif ($Latest -or $NotesFile -or $ReleaseTitle -or $ExpectPublicSha) {
    Write-Host 'NIGHTLY: FAIL exit=10 -Latest, -NotesFile, -ReleaseTitle and -ExpectPublicSha need -ReleaseTag'; exit 10
}
$RunKind = if ($ReleaseMode) { 'RELEASE' } else { 'NIGHTLY' }
$PublicRepo = 'leviritchie/Golden-Era'
$PublicCloneUrl = 'https://github.com/leviritchie/Golden-Era.git'
$DriveLabel = 'GENightly'
$KeepLogRuns = 10
$here = $PSScriptRoot
$GhExe = (Get-Command gh.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source

class NightlyFailure : System.Exception {
    [int] $Code
    NightlyFailure([int] $code, [string] $message) : base($message) { $this.Code = $code }
}
function Fail([int] $code, [string] $message) { throw [NightlyFailure]::new($code, $message) }

$runStart = [DateTime]::UtcNow
$summary = [ordered]@{
    schema = 'nightly_release_summary.v1'
    status = 'fail'
    exitCode = 90
    failureClass = $null
    failures = @()
    mode = $(if ($ReleaseMode) { 'release' } else { 'nightly' })
    releaseTag = $Tag
    publishRequested = [bool]$Publish
    published = $false
    ref = $Ref
    sha = $null
    label = $null
    startedUtc = $runStart.ToString('o')
    steps = [ordered]@{}
    disk = [ordered]@{}
    sizes = [ordered]@{}
    assets = @()
}
$FailureClass = @{ 10 = 'preflight'; 11 = 'locked'; 20 = 'build'; 21 = 'build-timeout'; 30 = 'stage'; 40 = 'sanitizer';
    50 = 'zip-split'; 60 = 'installers'; 70 = 'install-verify'; 80 = 'publish'; 90 = 'unexpected' }

# ---- helpers ------------------------------------------------------------------------------------
function Log([string] $msg) { Write-Host ("[{0:HH:mm:ss}] {1}" -f [DateTime]::Now, $msg) }

function Free([string] $root) { [IO.DriveInfo]::new([IO.Path]::GetPathRoot($root)).AvailableFreeSpace }

$minFree = [hashtable]::Synchronized(@{ value = [long]::MaxValue; stop = $false })
function Sample-Free { $f = Free $WorkRoot; if ($f -lt $minFree.value) { $minFree.value = $f } }

function Step([string] $name, [int] $code, [scriptblock] $body) {
    Log "== $name"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $entry = [ordered]@{ status = 'running'; seconds = $null }
    $summary.steps[$name] = $entry
    try {
        $result = & $body
        $entry.status = 'pass'
        return $result
    } catch [NightlyFailure] {
        $entry.status = 'fail'; throw
    } catch {
        $entry.status = 'fail'
        Fail $code "${name}: $($_.Exception.Message)"
    } finally {
        $sw.Stop()
        $entry.seconds = [Math]::Round($sw.Elapsed.TotalSeconds, 1)
        Sample-Free
        $entry.freeAfterBytes = Free $WorkRoot
        Log ("   {0} {1} in {2:N1}s, N: free {3:N1} GB" -f $name, $entry.status, $sw.Elapsed.TotalSeconds, ($entry.freeAfterBytes / 1GB))
    }
}

# Runs a child process with proper argument quoting, streams stdout/stderr to files, enforces a
# timeout, and on timeout stops only that child's own process tree.
function Invoke-Child {
    param([string] $File, [string[]] $Arguments, [string] $LogBase, [int] $TimeoutMinutes = 60,
        [string] $WorkingDirectory, [hashtable] $Environment)
    $psi = [Diagnostics.ProcessStartInfo]::new($File)
    foreach ($a in $Arguments) { $psi.ArgumentList.Add($a) }
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
    # Windows PowerShell 5.1 inherits pwsh 7's PSModulePath and then cannot load its own core
    # modules (Get-FileHash is missing). Drop it so 5.1 rebuilds its default module path.
    if ([IO.Path]::GetFileName($File) -ieq 'powershell.exe') { [void]$psi.Environment.Remove('PSModulePath') }
    if ($Environment) { foreach ($k in $Environment.Keys) { $psi.Environment[$k] = [string]$Environment[$k] } }
    $out = [IO.File]::Create("$LogBase.out.log")
    $err = [IO.File]::Create("$LogBase.err.log")
    $p = [Diagnostics.Process]::Start($psi)
    try {
        $t1 = $p.StandardOutput.BaseStream.CopyToAsync($out)
        $t2 = $p.StandardError.BaseStream.CopyToAsync($err)
        $timedOut = -not $p.WaitForExit([int][Math]::Min([int]::MaxValue, $TimeoutMinutes * 60000))
        if ($timedOut) { try { $p.Kill($true) } catch { } ; [void]$p.WaitForExit(30000) }
        else { $p.WaitForExit() }
        [void][Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($t1, $t2), 60000)
        return [pscustomobject]@{ ExitCode = $(if ($timedOut) { -1 } else { $p.ExitCode }); TimedOut = $timedOut;
            Out = "$LogBase.out.log"; Err = "$LogBase.err.log" }
    } finally { $out.Dispose(); $err.Dispose(); $p.Dispose() }
}

function Tail([string] $path, [int] $n = 8) {
    if (Test-Path -LiteralPath $path) { ((Get-Content -LiteralPath $path -Tail $n) -join ' | ') } else { '' }
}

function Dir-Bytes([string] $path) {
    if (-not (Test-Path -LiteralPath $path)) { return [int64]0 }
    [int64]((Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum)
}

function Remove-Tree([string] $path) {
    if (Test-Path -LiteralPath $path) {
        # Junctions are unlinked, never followed.
        Get-ChildItem -LiteralPath $path -Recurse -Force -Attributes ReparsePoint -ErrorAction SilentlyContinue |
            ForEach-Object { try { $_.Delete() } catch { } }
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

function Invoke-Gh([string[]] $ghArgs, [switch] $AllowFail) {
    $o = & $script:GhExe @ghArgs 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $AllowFail) { throw "gh $($ghArgs[0..1] -join ' ') failed ($code): $(($o | Select-Object -Last 3) -join ' ')" }
    return [pscustomobject]@{ Code = $code; Text = ($o | ForEach-Object { "$_" }) -join "`n" }
}

function Read-JsonFile([string] $path) { Get-Content -LiteralPath $path -Raw | ConvertFrom-Json -DateKind String }

# ---- versioned release (-ReleaseTag) --------------------------------------------------------------
function Get-GhJson([string[]] $ghArgs) { (Invoke-Gh $ghArgs).Text | ConvertFrom-Json -DateKind String }

# The payload sha a published release advertises in its golden_era_release_payload*.zip.sha256 asset,
# or $null when it has none (releases older than the Release-asset payload).
function Get-ReleasePayloadSha([string] $tag) {
    $rel = Get-GhJson @('api', "repos/$PublicRepo/releases/tags/$tag")
    $a = @($rel.assets | Where-Object { $_.name -match '^golden_era_release_payload.*\.zip\.sha256$' })
    if ($a.Count -eq 0) { return $null }
    if ($a.Count -gt 1) { throw "release $tag has $($a.Count) payload .sha256 assets" }
    $tmp = Join-Path $WorkDir "sha-$tag"
    Remove-Tree $tmp; [void](New-Item -ItemType Directory -Force -Path $tmp)
    [void](Invoke-Gh @('release', 'download', $tag, '-R', $PublicRepo, '-p', $a[0].name, '-D', $tmp))
    $h = (((Get-Content -LiteralPath (Join-Path $tmp $a[0].name) -Raw).Trim()) -split '\s+')[0].ToLowerInvariant()
    Remove-Tree $tmp
    if ($h -notmatch '^[0-9a-f]{64}$') { throw "release $tag payload .sha256 asset is unreadable" }
    return $h
}

# Compares a release's asset list (REST shape) with what this run built. Returns a list of problems.
function Compare-ReleaseAssets($rel, [hashtable] $uploadedIds) {
    $bad = @()
    $byName = @{}; foreach ($x in @($rel.assets)) { $byName[$x.name] = $x }
    foreach ($a in $summary.assets) {
        $x = $byName[$a.name]
        if (-not $x) { $bad += "missing $($a.name)"; continue }
        if ([int64]$x.size -ne [int64]$a.bytes) { $bad += "$($a.name) is $($x.size) bytes, built $($a.bytes)" }
        if ($x.state -and $x.state -ne 'uploaded') { $bad += "$($a.name) state is $($x.state)" }
        if ($x.digest -and $x.digest -ne "sha256:$($a.sha256)") { $bad += "$($a.name) digest $($x.digest) != built sha256:$($a.sha256)" }
        if ($uploadedIds -and $uploadedIds.ContainsKey($a.name) -and [int64]$uploadedIds[$a.name] -ne [int64]$x.id) { $bad += "$($a.name) was replaced (asset id $($uploadedIds[$a.name]) -> $($x.id))" }
    }
    $expected = @($summary.assets | ForEach-Object { $_.name })
    foreach ($x in @($rel.assets)) { if ($expected -notcontains $x.name) { $bad += "unexpected asset $($x.name)" } }
    return , $bad
}

function Publish-VersionedRelease {
    $script:relId = $null
    $script:publishStartUtc = [DateTime]::UtcNow
    Step 'publish' 80 {
        # The tag goes on exactly the public commit the installers were built from.
        $mainSha = (Invoke-Gh @('api', "repos/$PublicRepo/commits/main", '--jq', '.sha')).Text.Trim()
        if ($mainSha -ne $summary.publicMainSha) { throw "public main moved from $($summary.publicMainSha) (installers built from it) to $mainSha; refusing to tag" }
        if ((Invoke-Gh @('api', "repos/$PublicRepo/git/ref/tags/$Tag") -AllowFail).Code -eq 0) { throw "tag $Tag already exists; existing tags are never moved" }

        # Stale-payload guard: the payload must differ from the previous release's and from Latest's.
        $list = @(Get-GhJson @('api', "repos/$PublicRepo/releases?per_page=50"))
        $stable = @($list | Where-Object { -not $_.draft -and $_.tag_name -ne 'nightly' -and $_.tag_name -ne $Tag } | Sort-Object { [string]$_.published_at } -Descending)
        $previous = if ($stable.Count) { $stable[0].tag_name } else { $null }
        $lr = Invoke-Gh @('api', "repos/$PublicRepo/releases/latest") -AllowFail
        $latestBefore = if ($lr.Code -eq 0) { ($lr.Text | ConvertFrom-Json -DateKind String).tag_name } else { $null }
        $guard = [ordered]@{ built = $summary.payloadSha256; previous = $previous; previousSha256 = $null; latest = $latestBefore; latestSha256 = $null }
        if ($previous) { $guard.previousSha256 = Get-ReleasePayloadSha $previous }
        if ($latestBefore) { $guard.latestSha256 = if ($latestBefore -eq $previous) { $guard.previousSha256 } else { Get-ReleasePayloadSha $latestBefore } }
        $summary.stalePayloadGuard = $guard
        foreach ($k in 'previous', 'latest') {
            if ($guard["${k}Sha256"] -and $guard["${k}Sha256"] -eq $summary.payloadSha256) { throw "payload sha256 $($summary.payloadSha256) equals the payload of $k release $($guard[$k]); refusing to publish a stale payload" }
        }
        Log "   stale-payload guard: built $($summary.payloadSha256); $previous=$($guard.previousSha256); Latest $latestBefore=$($guard.latestSha256)"

        # Draft first: the tag is only created when the draft is published, after every asset is up.
        Log "   creating draft $Tag at public main $mainSha"
        [void](Invoke-Gh @('release', 'create', $Tag, '-R', $PublicRepo, '--draft', '--target', $mainSha, '--title', $ReleaseTitle, '--notes-file', $notesPath))
        $script:relId = (Get-GhJson @('release', 'view', $Tag, '-R', $PublicRepo, '--json', 'databaseId,isDraft')).databaseId
        if (-not $script:relId) { throw "cannot read the id of draft $Tag" }
        $order = @($summary.assets | Where-Object { $_.name -like "$PayloadBase*" }) + @($summary.assets | Where-Object { $_.name -notlike "$PayloadBase*" })
        foreach ($a in $order) {
            $ok = $false
            for ($try = 1; $try -le 3 -and -not $ok; $try++) {
                $r = Invoke-Child -File $GhExe -LogBase (Join-Path $logDir "upload-$($a.name)") -TimeoutMinutes 120 -Arguments @(
                    'release', 'upload', $Tag, (Join-Path $assets $a.name), '-R', $PublicRepo, '--clobber')
                $ok = $r.ExitCode -eq 0
                if (-not $ok) { Log "   upload $($a.name) attempt $try failed: $(Tail $r.Err 2)" }
            }
            if (-not $ok) { throw "upload of $($a.name) failed 3 times; draft $Tag left unpublished" }
        }
        $draft = Get-GhJson @('api', "repos/$PublicRepo/releases/$($script:relId)")
        $bad = Compare-ReleaseAssets $draft $null
        if ($bad.Count) { throw "draft $Tag assets do not match the build (left unpublished): $($bad -join '; ')" }
        $script:uploadedIds = @{}; foreach ($x in @($draft.assets)) { $script:uploadedIds[$x.name] = [int64]$x.id }

        $latestFlag = if ($Latest) { '--latest' } else { '--latest=false' }
        [void](Invoke-Gh @('release', 'edit', $Tag, '-R', $PublicRepo, '--draft=false', '--prerelease=false', $latestFlag))
        $rel = Get-GhJson @('api', "repos/$PublicRepo/releases/$($script:relId)")
        if ($rel.draft -or $rel.prerelease) { throw "$Tag is still draft=$($rel.draft) prerelease=$($rel.prerelease) after publishing" }
        $ref = Get-GhJson @('api', "repos/$PublicRepo/git/ref/tags/$Tag")
        if ($ref.object.sha -ne $mainSha) { throw "tag $Tag points at $($ref.object.sha), expected $mainSha" }
        $latestAfter = (Get-GhJson @('api', "repos/$PublicRepo/releases/latest")).tag_name
        if ($Latest -and $latestAfter -ne $Tag) { throw "Latest is $latestAfter, expected $Tag" }
        if (-not $Latest -and $latestAfter -ne $latestBefore) { throw "Latest changed from $latestBefore to $latestAfter" }
        $summary.published = $true
        $summary.publish = [ordered]@{ tag = $Tag; target = $mainSha; latest = $latestAfter; releaseId = $script:relId; url = $rel.html_url
            publishedUtc = $rel.published_at; uploaded = $order.Count }
        'ok'
    } | Out-Null

    # Post-publish verification: something may still rewrite the assets after publishing (v0.1.319
    # was overwritten 9 minutes later by a tag-triggered workflow). Wait, re-list, compare, fail loudly.
    Step 'postPublishVerify' 80 {
        Log "   waiting $SettleSeconds s before re-listing $Tag"
        Start-Sleep -Seconds $SettleSeconds
        $rel = Get-GhJson @('api', "repos/$PublicRepo/releases/$($script:relId)")
        # The function returns its list as one object; unroll it so an empty list stays empty.
        $bad = @(Compare-ReleaseAssets $rel $script:uploadedIds | ForEach-Object { $_ })
        if ($rel.draft -or $rel.prerelease) { $bad += "release is draft=$($rel.draft) prerelease=$($rel.prerelease)" }
        # The advertised payload sha (.sha256 and download manifest) must be what was built.
        $tmp = Join-Path $WorkDir 'postverify'; Remove-Tree $tmp; [void](New-Item -ItemType Directory -Force -Path $tmp)
        [void](Invoke-Gh @('release', 'download', $Tag, '-R', $PublicRepo, '-p', "$PayloadBase.sha256", '-p', "$PayloadBase.download-manifest.json", '-D', $tmp))
        $shaLine = ((Get-Content -LiteralPath (Join-Path $tmp "$PayloadBase.sha256") -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
        if ($shaLine -ne $summary.payloadSha256) { $bad += "published .sha256 says $shaLine, built $($summary.payloadSha256)" }
        $man = Read-JsonFile (Join-Path $tmp "$PayloadBase.download-manifest.json")
        if ($man.expected_sha256 -ne $summary.payloadSha256) { $bad += "published manifest sha $($man.expected_sha256) != built $($summary.payloadSha256)" }
        if ([int64]$man.expected_bytes -ne [int64]$summary.sizes.zipBytes) { $bad += "published manifest bytes $($man.expected_bytes) != built $($summary.sizes.zipBytes)" }
        if ((@($man.parts) -join ',') -ne (@($split | ForEach-Object { $_.name }) -join ',')) { $bad += 'published manifest part list differs from the build' }
        Remove-Tree $tmp
        $ref = Get-GhJson @('api', "repos/$PublicRepo/git/ref/tags/$Tag")
        if ($ref.object.sha -ne $summary.publicMainSha) { $bad += "tag $Tag now points at $($ref.object.sha)" }
        $latestNow = (Get-GhJson @('api', "repos/$PublicRepo/releases/latest")).tag_name
        if ($Latest -and $latestNow -ne $Tag) { $bad += "Latest is now $latestNow" }
        # No workflow run may have been triggered by the new tag or release.
        $since = $script:publishStartUtc.AddMinutes(-1).ToString('yyyy-MM-ddTHH:mm:ssZ')
        $runs = @(Get-GhJson @('run', 'list', '-R', $PublicRepo, '--limit', '50', '--json', 'databaseId,event,headBranch,headSha,createdAt,workflowName,status'))
        $triggered = @($runs | Where-Object { $_.headBranch -eq $Tag -or [string]$_.createdAt -ge $since })
        foreach ($t in $triggered) { $bad += "workflow run $($t.databaseId) '$($t.workflowName)' event=$($t.event) branch=$($t.headBranch) created $($t.createdAt)" }
        $summary.postPublish = [ordered]@{
            settledSeconds = $SettleSeconds; checkedUtc = [DateTime]::UtcNow.ToString('o'); problems = $bad
            workflowRunsSincePublish = $triggered.Count; latest = $latestNow; tagSha = $ref.object.sha
            assets = @($rel.assets | Sort-Object name | ForEach-Object { [ordered]@{ name = $_.name; bytes = [int64]$_.size; digest = $_.digest; id = $_.id; updatedUtc = $_.updated_at } })
        }
        if ($bad.Count) { throw "POST-PUBLISH VERIFICATION FAILED for ${Tag}: $($bad -join '; ')" }
        "assets, sizes, digests and payload sha unchanged after $SettleSeconds s; no workflow runs"
    } | Out-Null
}

# ---- layout -------------------------------------------------------------------------------------
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
$LogsRoot = Join-Path $WorkRoot 'logs'
$WorkDir = Join-Path $WorkRoot 'work'
$StatePath = Join-Path $WorkRoot 'state.json'
$BuildsPath = Join-Path $WorkRoot 'builds.json'
$LockPath = Join-Path $WorkRoot 'nightly.lock'
$KeepNames = @('logs', 'reports', 'state.json', 'builds.json', 'nightly.lock')

$exitCode = 90
$lock = $null
$logDir = $null
$transcript = $false
try {
    # ---- preflight (before the lock: only read-only checks) -------------------------------------
    $driveRoot = [IO.Path]::GetPathRoot($WorkRoot)
    if (-not (Test-Path -LiteralPath $driveRoot)) { Fail 10 "drive $driveRoot is not mounted" }
    $drive = [IO.DriveInfo]::new($driveRoot)
    if (-not $drive.IsReady) { Fail 10 "drive $driveRoot is not ready" }
    if ($drive.VolumeLabel -ne $DriveLabel) { Fail 10 "drive $driveRoot has label '$($drive.VolumeLabel)', expected '$DriveLabel'" }
    [void](New-Item -ItemType Directory -Force -Path $WorkRoot, $LogsRoot)
    try { $lock = [IO.File]::Open($LockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { $exitCode = 11; throw [NightlyFailure]::new(11, "another nightly run holds $LockPath") }

    if (-not $Repo) { $Repo = (& git -C $here rev-parse --show-toplevel 2>$null) }
    if (-not $Repo) { Fail 10 'cannot locate the private repo (pass -Repo)' }
    $Repo = [IO.Path]::GetFullPath($Repo)
    # Git-ignored inputs (the plugin's publish_plugin\ and tools\_dump_types\bin\, the stager's dialog portrait
    # inventory) are not in a linked worktree. Read them from -Repo when present, else from the main checkout
    # that owns -Repo's git dir. Read only.
    $mainCheckout = $null
    $commonDir = (& git -C $Repo rev-parse --path-format=absolute --git-common-dir 2>$null)
    if ($commonDir) { $mainCheckout = [IO.Path]::GetFullPath((Split-Path -Parent $commonDir.Trim())) }
    function Resolve-UntrackedInput([string] $rel) {
        foreach ($root in @($Repo, $mainCheckout) | Where-Object { $_ }) {
            $candidate = Join-Path $root $rel
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
        return (Join-Path $Repo $rel)
    }
    if (-not $UntrackedInputsFrom) {
        $pluginRel = 'Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod'
        $UntrackedInputsFrom = Split-Path -Parent (Split-Path -Parent (Resolve-UntrackedInput (Join-Path $pluginRel 'publish_plugin\Hex.dll')))
    }
    $UntrackedInputsFrom = [IO.Path]::GetFullPath($UntrackedInputsFrom)
    $sha = (& git -C $Repo rev-parse --verify "$Ref^{commit}" 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $sha) { Fail 10 "cannot resolve ref $Ref" }
    $sha = $sha.Trim()
    $short = (& git -C $Repo rev-parse --short=8 $sha).Trim()
    $label = if ($ReleaseMode) { $ReleaseTag } else { 'nightly-{0:yyyyMMdd}-{1}' -f $runStart, $short }
    $infoVersion = if ($ReleaseMode) { '{0}+{1}' -f $ReleaseTag.Substring(1), $short } else { $label }
    $runId = '{0:yyyyMMdd-HHmmss}-{1}' -f $runStart, $short
    $summary.sha = $sha; $summary.label = $label; $summary.runId = $runId
    $logDir = Join-Path $LogsRoot $runId
    [void](New-Item -ItemType Directory -Force -Path $logDir)
    Start-Transcript -LiteralPath (Join-Path $logDir 'nightly.log') | Out-Null
    $transcript = $true
    Log "$($RunKind.ToLowerInvariant()) $label (publish=$([bool]$Publish)) sha=$sha"

    $PayloadBase = "golden_era_release_payload-$label.zip"
    $state = if (Test-Path -LiteralPath $StatePath) { Read-JsonFile $StatePath } else { [pscustomobject]@{} }

    Step 'preflight' 10 {
        foreach ($tool in 'git', 'gh', 'dotnet', 'python', 'pwsh', 'powershell') {
            if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not on PATH" }
        }
        $winTar = Join-Path $env:SystemRoot 'System32\tar.exe'
        if (-not (Test-Path -LiteralPath $winTar)) { throw "Windows tar not found at $winTar" }
        if (-not $GhExe) { throw 'gh.exe is not on PATH' }
        if ($ReleaseMode) {
            # The plugin's own version constant (what bug reports carry) must name this release.
            $pluginCs = (& git -C $Repo show "${sha}:Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Plugin.cs") -join "`n"
            $m = [regex]::Match($pluginCs, 'PluginVersion = "([^"]+)"')
            if (-not $m.Success -or $m.Groups[1].Value -ne $ReleaseTag.Substring(1)) { throw "Plugin.PluginVersion at $short is '$($m.Groups[1].Value)', expected '$($ReleaseTag.Substring(1))'" }
            # A versioned release tag is created once and never moved.
            $existing = Invoke-Gh @('api', "repos/$PublicRepo/git/ref/tags/$ReleaseTag") -AllowFail
            if ($existing.Code -eq 0) { throw "tag $ReleaseTag already exists on $PublicRepo; pick a new version" }
            $existingRel = Invoke-Gh @('release', 'view', $ReleaseTag, '-R', $PublicRepo, '--json', 'tagName') -AllowFail
            if ($existingRel.Code -eq 0) { throw "a release (or draft) named $ReleaseTag already exists on $PublicRepo" }
        }
        $auth = Invoke-Gh @('auth', 'status', '--hostname', 'github.com') -AllowFail
        if ($auth.Code -ne 0) { throw 'gh is not authenticated for github.com' }
        foreach ($p in (Join-Path $GameRoot 'HeroesOldenEra.exe'), (Join-Path $GameRoot 'BepInEx\plugins\OfflineUnlockMod'),
            (Join-Path $CleanMirror 'HeroesOldenEra_Data\StreamingAssets\Core.zip'), (Join-Path $CleanMirror 'GameAssembly.dll')) {
            if (-not (Test-Path -LiteralPath $p)) { throw "missing $p" }
        }
        foreach ($p in $GameRoot, $CleanMirror, $Repo) {
            if ($WorkRoot.StartsWith($p.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "WorkRoot must not be inside $p" }
        }
        # Remove the previous run's work (everything on WorkRoot except logs/state/reports).
        foreach ($item in Get-ChildItem -LiteralPath $WorkRoot -Force) {
            if ($KeepNames -notcontains $item.Name) { Remove-Tree $item.FullName }
        }
        $summary.disk.volumeBytes = $drive.TotalSize
        $free = Free $WorkRoot
        $summary.disk.freeAtStartBytes = $free
        $minFree.value = $free
        # Measured need: staged sources (upper bound of the stage) twice (stage + zip) plus 2 GB.
        $src = (Dir-Bytes (Join-Path $GameRoot 'BepInEx\plugins\OfflineUnlockMod')) +
            (Dir-Bytes (Join-Path $GameRoot 'HeroesOldenEra_Data\StreamingAssets\maps')) +
            (Dir-Bytes (Join-Path $GameRoot 'HeroesOldenEra_Data\StreamingAssets\video')) +
            (Dir-Bytes (Join-Path $GameRoot 'BepInEx\core')) + (Dir-Bytes (Join-Path $GameRoot 'dotnet'))
        $need = 2 * $src + 2GB
        if ($state.lastRunPeakDeltaBytes) { $need = [Math]::Max($need, [int64]([double]$state.lastRunPeakDeltaBytes * 1.05)) }
        $summary.disk.sourceBytesMeasured = $src
        $summary.disk.neededBytes = $need
        if ($free -lt $need) { throw ("N: has {0:N1} GB free; this run needs about {1:N1} GB" -f ($free / 1GB), ($need / 1GB)) }
        [void](New-Item -ItemType Directory -Force -Path $WorkDir)
        'ok'
    } | Out-Null

    # Background sampler for peak disk use (falls back to per-step samples).
    $sampler = $null
    try {
        $sampler = Start-ThreadJob -ArgumentList $minFree, $driveRoot -ScriptBlock {
            param($h, $root)
            while (-not $h.stop) {
                $f = [IO.DriveInfo]::new($root).AvailableFreeSpace
                if ($f -lt $h.value) { $h.value = $f }
                Start-Sleep -Milliseconds 1500
            }
        }
    } catch { Log "peak sampler unavailable: $($_.Exception.Message)" }

    # ---- build --------------------------------------------------------------------------------------
    $buildOut = Join-Path $WorkDir 'build'
    $build = Step 'build' 20 {
        $r = Invoke-Child -File (Get-Command pwsh).Source -LogBase (Join-Path $logDir 'build') -TimeoutMinutes ($BuildTimeoutMinutes + 5) -Arguments @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $here 'build_plugin.ps1'),
            '-GameRoot', $GameRoot, '-OutDir', $buildOut, '-Ref', $sha, '-Repo', $Repo,
            '-UntrackedInputsFrom', $UntrackedInputsFrom,
            '-ReleaseCandidate', '-InformationalVersion', $infoVersion, '-TimeoutMinutes', "$BuildTimeoutMinutes")
        $bs = Join-Path $buildOut 'build_summary.json'
        if (Test-Path -LiteralPath $bs) { Copy-Item -LiteralPath $bs -Destination (Join-Path $logDir 'build_summary.json'); Copy-Item -LiteralPath (Join-Path $buildOut 'build.log') -Destination (Join-Path $logDir 'build.msbuild.log') -ErrorAction SilentlyContinue }
        if ($r.TimedOut -or $r.ExitCode -eq 3) { Fail 21 "plugin build timed out: $(Tail $r.Out 4)" }
        if ($r.ExitCode -ne 0) { Fail 20 "plugin build failed (exit $($r.ExitCode)): $(Tail $r.Out 12)" }
        $j = Read-JsonFile $bs
        [ordered]@{ dllSha256 = $j.dllSha256; hintContract = $j.hintContract; liveInterop = $j.liveInterop; rcQuickTierPatch = $j.rcQuickTierPatch; seconds = $j.elapsedSeconds }
    }
    $summary.build = $build
    $dll = Join-Path $buildOut 'bin\OfflineUnlockMod.dll'

    # ---- stage --------------------------------------------------------------------------------------
    $toolsSrc = Join-Path $WorkDir 'src_tools'
    $stageRoot = Join-Path $WorkDir 'stage'
    $stage = Step 'stage' 30 {
        # The release_installer tools and the stager's repo inputs come from the same commit.
        [void](New-Item -ItemType Directory -Force -Path $toolsSrc)
        $tarball = Join-Path $WorkDir 'tools.tar'
        & git -C $Repo archive --format=tar -o $tarball $sha -- tools/release_installer scenarios/roe_castle_campaign/batch_manifest.json tools/install_roe_castle_continuity_weave.py
        if ($LASTEXITCODE -ne 0) { throw 'git archive of the release tools failed' }
        & (Join-Path $env:SystemRoot 'System32\tar.exe') -xf $tarball -C $toolsSrc
        if ($LASTEXITCODE -ne 0) { throw 'tar extract of the release tools failed' }
        Remove-Item -LiteralPath $tarball -Force
        # Git-ignored stager input (dialog portrait inventory), copied read-only from the checkout.
        $inv = 'artifacts\dialog_portrait_inventory\required_homm3_hero_icons.json'
        [void](New-Item -ItemType Directory -Force -Path (Split-Path (Join-Path $toolsSrc $inv)))
        Copy-Item -LiteralPath (Resolve-UntrackedInput $inv) -Destination (Join-Path $toolsSrc $inv)

        $terms = @($env:USERNAME, $env:COMPUTERNAME, (& git -C $Repo config user.email)) | Where-Object { $_ }
        $stageArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $here 'stage_release_payload.ps1'),
            '-GameRoot', $GameRoot, '-CleanReleaseCore', (Join-Path $CleanMirror 'HeroesOldenEra_Data\StreamingAssets\Core.zip'),
            '-StageRoot', $stageRoot, '-ToolsDir', (Join-Path $toolsSrc 'tools\release_installer'),
            '-PluginDllOverride', $dll, '-ReportPath', (Join-Path $logDir 'stage_report.json'), '-LeakTerm') + @($terms -join ',')
        # -File cannot pass an array, so -LeakTerm travels as one comma list and the stager splits it.
        $r = Invoke-Child -File (Get-Command pwsh).Source -LogBase (Join-Path $logDir 'stage') -TimeoutMinutes 90 -Arguments $stageArgs
        $rep = if (Test-Path -LiteralPath (Join-Path $logDir 'stage_report.json')) { Read-JsonFile (Join-Path $logDir 'stage_report.json') } else { $null }
        if ($r.ExitCode -eq 40) { Fail 40 "sanitizer/leak gate: $(if ($rep) { $rep.error } else { Tail $r.Out 6 })" }
        if ($r.ExitCode -ne 0) { Fail 30 "payload stage failed (exit $($r.ExitCode)): $(if ($rep -and $rep.error) { $rep.error } else { Tail $r.Out 8 })" }
        $stagedDll = Join-Path $stageRoot 'payload\BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll'
        [ordered]@{
            stageBytes = $rep.stageBytes; stageFiles = $rep.stageFiles
            stagedDllSha256 = (Get-FileHash -LiteralPath $stagedDll -Algorithm SHA256).Hash.ToLowerInvariant()
            pluginCopy = $rep.steps.plugin.result; homm3LabJson = $rep.steps.homm3Lab.result
            leftoversPruned = $rep.steps.leftoverPrune.result.count
            sanitized = $rep.steps.sanitizeJson.result | Select-Object filesChanged, stringsReplacedWhole, pathsReplacedEmbedded
            sanitizedFiles = @($rep.steps.sanitizeJson.result.files | ForEach-Object { $_.file })
            leakScan = $rep.steps.leakScan.result
            overlayOperations = $rep.steps.coreOverlay.result.operations
            importCoverage = $rep.steps.releaseInputClean.result
        }
    }
    $summary.stage = $stage
    $summary.sizes.stageBytes = $stage.stageBytes
    $summary.sizes.stageFiles = $stage.stageFiles
    Remove-Tree $toolsSrc
    if (-not $KeepWork) { Remove-Tree $buildOut }

    # Rewrites an installer's download footer (JSON, int64 length, 'GERADL01') to list the given parts,
    # then its .sha256 and .download-manifest.json. Only the parts and partBytes change.
    function Set-DownloadFooterParts([string] $Exe, [string[]] $Names, [long[]] $Sizes) {
        $xfs = [IO.File]::Open($Exe, 'Open', 'ReadWrite', 'None')
        try {
            $tail = New-Object byte[] 16
            [void]$xfs.Seek(-16, 'End'); if ($xfs.Read($tail, 0, 16) -ne 16) { throw "$Exe is too short" }
            if ([Text.Encoding]::ASCII.GetString($tail, 8, 8) -ne 'GERADL01') { throw "$Exe has no download footer" }
            $jlen = [BitConverter]::ToInt64($tail, 0)
            if ($jlen -le 0 -or $jlen -gt 1MB) { throw "$Exe footer length $jlen is invalid" }
            $jstart = $xfs.Length - 16 - $jlen
            $jb = New-Object byte[] $jlen
            [void]$xfs.Seek($jstart, 'Begin'); if ($xfs.Read($jb, 0, $jlen) -ne $jlen) { throw "$Exe footer is truncated" }
            $m = [Text.Encoding]::UTF8.GetString($jb) | ConvertFrom-Json -DateKind String
            if ($m.schema -ne 'golden_era_payload_download/v1') { throw "$Exe footer schema is $($m.schema)" }
            if ((($Sizes | Measure-Object -Sum).Sum) -ne [int64]$m.expectedBytes) { throw "$Exe parts do not add up to the footer's expectedBytes" }
            $m.parts = $Names; $m.partBytes = $Sizes
            $nb = [Text.Encoding]::UTF8.GetBytes(($m | ConvertTo-Json -Depth 8 -Compress))
            $xfs.SetLength($jstart); [void]$xfs.Seek(0, 'End')
            $xfs.Write($nb, 0, $nb.Length)
            $xfs.Write([BitConverter]::GetBytes([int64]$nb.Length), 0, 8)
            $xfs.Write([Text.Encoding]::ASCII.GetBytes('GERADL01'), 0, 8)
            $xfs.Flush($true)
        } finally { $xfs.Dispose() }
        $h = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash.ToLowerInvariant()
        Set-Content -LiteralPath "$Exe.sha256" -Value "$h  $(Split-Path -Leaf $Exe)" -Encoding ascii
        ($m | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath "$Exe.download-manifest.json" -Encoding utf8
    }

    # ---- public clone + zip -------------------------------------------------------------------------
    $public = Join-Path $WorkDir 'public'
    $publicMain = Step 'publicClone' 60 {
        # The public repo keeps old payload parts in Git LFS (release_inputs/, about 3.7 GB); only the
        # tools are needed, so LFS files stay as pointers.
        $env:GIT_LFS_SKIP_SMUDGE = '1'
        try { $o = & git -c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false clone --quiet --depth 1 --branch main $PublicCloneUrl $public 2>&1 }
        finally { Remove-Item Env:GIT_LFS_SKIP_SMUDGE -ErrorAction SilentlyContinue }
        if ($LASTEXITCODE -ne 0) { throw "git clone of the public repo failed: $(($o | Select-Object -Last 2) -join ' ')" }
        $cloneBytes = Dir-Bytes $public
        if ($cloneBytes -gt 500MB) { throw ("public clone is {0:N1} GB; LFS content must not be fetched" -f ($cloneBytes / 1GB)) }
        $head = (& git -C $public rev-parse HEAD).Trim()
        if ($ReleaseMode) {
            if ($ExpectPublicSha -and -not $head.StartsWith($ExpectPublicSha.ToLowerInvariant())) { throw "public main is $head, expected $ExpectPublicSha" }
            # The tag will point at this commit. GitHub runs tag- and release-triggered workflows from
            # the tagged commit's own workflow files, so none of them may react to a push, a tag or a
            # release (that is how v0.1.319's assets were overwritten by a stale rebuild).
            $wfDir = Join-Path $public '.github\workflows'
            $triggers = @()
            if (Test-Path -LiteralPath $wfDir) {
                foreach ($wf in Get-ChildItem -LiteralPath $wfDir -File -Recurse | Where-Object { $_.Extension -in '.yml', '.yaml' }) {
                    $t = Get-Content -LiteralPath $wf.FullName -Raw
                    if ($t -match '(?m)^\s*-?\s*(push|release|create|pull_request_target|workflow_run|schedule)\s*:' -or
                        $t -match '(?m)^\s*"?on"?\s*:\s*\[?[^\n#]*\b(push|release|create|workflow_run|schedule)\b') { $triggers += $wf.Name }
                }
            }
            if ($triggers.Count -gt 0) { throw "public main $head has workflows that can fire on a tag or release: $($triggers -join ', ')" }
            $summary.workflowTriggerCheck = "no push/tag/release triggers in .github/workflows at $head"
        }
        $head
    }
    $summary.publicMainSha = $publicMain
    $inputsDir = Join-Path $public 'dist\golden_era_release_inputs'
    $zipPath = Join-Path $inputsDir 'golden_era_release_payload.zip'
    $zipInfo = Step 'zip' 50 {
        [void](New-Item -ItemType Directory -Force -Path $inputsDir)
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        # Same entries as ZipFile.CreateFromDirectory (files plus empty folders), but deterministic:
        # ordinal path order and one fixed timestamp, so an unchanged file gives the same entry bytes in
        # every nightly. Each entry's local header offset is recorded for the split step's cuts.
        # Live-parity payloads are mostly already-compressed Unity/video data; Fastest matches the release.
        $stageFull = [IO.Path]::GetFullPath($stageRoot).TrimEnd('\') + '\'
        $rels = [Collections.Generic.List[string]]::new(); $paths = [Collections.Generic.List[string]]::new()
        foreach ($f in [IO.Directory]::EnumerateFiles($stageFull, '*', [IO.SearchOption]::AllDirectories)) { $rels.Add($f.Substring($stageFull.Length).Replace('\', '/')); $paths.Add($f) }
        foreach ($d in [IO.Directory]::EnumerateDirectories($stageFull, '*', [IO.SearchOption]::AllDirectories)) {
            if (-not [IO.Directory]::EnumerateFileSystemEntries($d).GetEnumerator().MoveNext()) { $rels.Add($d.Substring($stageFull.Length).Replace('\', '/') + '/'); $paths.Add('') }
        }
        $relArr = $rels.ToArray(); $pathArr = $paths.ToArray()
        [Array]::Sort($relArr, $pathArr, [StringComparer]::Ordinal)
        $fixedTime = [DateTimeOffset]::new(2026, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
        $layout = [Collections.Generic.List[object]]::new($relArr.Length)
        $zfs = [IO.File]::Open($zipPath, 'CreateNew', 'ReadWrite', 'None')
        try {
            $za = [IO.Compression.ZipArchive]::new($zfs, [IO.Compression.ZipArchiveMode]::Create, $true)
            try {
                for ($k = 0; $k -lt $relArr.Length; $k++) {
                    $layout.Add([pscustomobject]@{ name = $relArr[$k]; offset = $zfs.Position })
                    $e = $za.CreateEntry($relArr[$k], [IO.Compression.CompressionLevel]::Fastest)
                    $e.LastWriteTime = $fixedTime
                    # Open even a folder entry now, so its header is written here and not at Dispose.
                    $dst = $e.Open()
                    try {
                        if ($pathArr[$k]) { $src = [IO.File]::OpenRead($pathArr[$k]); try { $src.CopyTo($dst, 1MB) } finally { $src.Dispose() } }
                    } finally { $dst.Dispose() }
                }
                $script:zipCentralDirOffset = $zfs.Position
            } finally { $za.Dispose() }
        } finally { $zfs.Dispose() }
        $script:zipLayout = $layout
        Sample-Free
        $zsha = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Set-Content -LiteralPath "$zipPath.sha256" -Value "$zsha  golden_era_release_payload.zip" -Encoding ascii
        # Structure check: required entries and the overlay operation count.
        $z = [IO.Compression.ZipFile]::OpenRead($zipPath)
        try {
            $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
            $unc = [int64]0; $overlay = 0; $payloadN = 0
            foreach ($e in $z.Entries) {
                $n = $e.FullName.Replace('\', '/'); [void]$names.Add($n); $unc += $e.Length
                if ($n.StartsWith('core_overlay/')) { $overlay++ } elseif ($n.StartsWith('payload/')) { $payloadN++ }
            }
            foreach ($req in 'core_overlay/manifest.json', 'payload/BepInEx/plugins/OfflineUnlockMod/OfflineUnlockMod.dll',
                'payload/BepInEx/plugins/OfflineUnlockMod/config.json', 'payload/BepInEx/core/BepInEx.Unity.IL2CPP.dll',
                'payload/game_root/winhttp.dll', 'payload/game_root/dotnet/coreclr.dll', 'payload/unity_data/resources.assets',
                'payload/il2cpp_metadata/global-metadata.dat') {
                if (-not $names.Contains($req)) { throw "zip is missing $req" }
            }
            $mtext = [IO.StreamReader]::new($z.GetEntry('core_overlay/manifest.json').Open()).ReadToEnd()
            $m = $mtext | ConvertFrom-Json -DateKind String
            if ($m.PSObject.Properties.Name -contains 'operationCount' -and [int]$m.operationCount -ne @($m.operations).Count) {
                throw "overlay manifest operationCount $($m.operationCount) != $(@($m.operations).Count) operations"
            }
            [ordered]@{ zipBytes = (Get-Item -LiteralPath $zipPath).Length; sha256 = $zsha; entries = $z.Entries.Count;
                coreOverlayEntries = $overlay; payloadEntries = $payloadN; uncompressedBytes = $unc; overlayOperations = @($m.operations).Count }
        } finally { $z.Dispose() }
    }
    $summary.sizes.zipBytes = $zipInfo.zipBytes
    $summary.sizes.zipEntries = $zipInfo.entries
    $summary.sizes.uncompressedBytes = $zipInfo.uncompressedBytes
    $summary.payloadSha256 = $zipInfo.sha256
    $summary.zip = $zipInfo
    $stagedDllSha = $stage.stagedDllSha256
    if (-not $KeepWork) { Remove-Tree $stageRoot }

    # ---- installers ---------------------------------------------------------------------------------
    $variants = @(
        [ordered]@{ suffix = '-upscaled-portraits'; upscaled = 'true'; out = 'dist\installer-upscaled' },
        [ordered]@{ suffix = '-standard-portraits'; upscaled = 'false'; out = 'dist\installer-standard' })
    $installers = @(Step 'installers' 60 {
        $res = @()
        foreach ($v in $variants) {
            $r = Invoke-Child -File (Get-Command powershell).Source -WorkingDirectory $public -TimeoutMinutes 45 `
                -LogBase (Join-Path $logDir "package$($v.suffix)") -Arguments @(
                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $public 'tools\release_installer\package_from_release_inputs.ps1'),
                '-ReleaseInputZip', 'dist\golden_era_release_inputs\golden_era_release_payload.zip',
                '-OutputRoot', $v.out, '-PackageVersion', $Tag, '-InstallerNameSuffix', $v.suffix,
                '-Homm3UseUpscaledHeroPortraits', $v.upscaled, '-PayloadMode', 'Download',
                '-PayloadBaseName', $PayloadBase, '-MaxPartBytes', "$MaxPartBytes")
            if ($r.ExitCode -ne 0) { throw "package$($v.suffix) failed (exit $($r.ExitCode)): $(Tail $r.Out 6) $(Tail $r.Err 4)" }
            $exeName = "GoldenEraModInstaller-$Tag$($v.suffix).exe"
            $exe = Join-Path $public (Join-Path $v.out $exeName)
            if (-not (Test-Path -LiteralPath $exe)) { throw "package$($v.suffix) produced no $exeName" }
            $footer = Read-JsonFile "$exe.download-manifest.json"
            $res += [ordered]@{ name = $exeName; path = $exe; footer = $footer }
        }
        $res
    })

    # ---- split in place -----------------------------------------------------------------------------
    $assets = Join-Path $WorkDir 'assets'
    $split = @(Step 'split' 50 {
        [void](New-Item -ItemType Directory -Force -Path $assets)
        $total = (Get-Item -LiteralPath $zipPath).Length
        # Part boundaries as start offsets.
        $starts = [Collections.Generic.List[long]]::new(); $starts.Add(0)
        if ($ReleaseMode) {
            # Versioned releases: uniform parts, named <base>.partNN as before.
            for ($o = [int64]$MaxPartBytes; $o -lt $total; $o += $MaxPartBytes) { $starts.Add($o) }
        } else {
            # Nightly: cut only at entry boundaries, chosen from the entry names, so a changed file moves
            # no cut outside its own part and every other part keeps its bytes (and so its name). Local
            # entry records hold no offsets; only the central directory does, so it is a part of its own.
            if (-not $script:zipLayout -or $script:zipCentralDirOffset -le 0 -or $script:zipCentralDirOffset -ge $total) { throw 'zip layout is missing' }
            $md5 = [Security.Cryptography.MD5]::Create()
            $cuts = [Collections.Generic.List[long]]::new(); $cuts.Add(0); $from = [int64]0
            foreach ($en in $script:zipLayout) {
                $size = $en.offset - $from
                if ($size -lt $ChunkMinBytes) { continue }
                if ($size -ge $ChunkSoftMaxBytes -or ($md5.ComputeHash([Text.Encoding]::UTF8.GetBytes($en.name))[0] % $ChunkModulo) -eq 0) { $cuts.Add($en.offset); $from = $en.offset }
            }
            $md5.Dispose()
            if ($script:zipCentralDirOffset -gt $from) { $cuts.Add($script:zipCentralDirOffset) }
            $starts.Clear()
            for ($c = 0; $c -lt $cuts.Count; $c++) {
                $end = if ($c + 1 -lt $cuts.Count) { $cuts[$c + 1] } else { $total }
                # A single entry larger than a GitHub asset is sliced at -MaxPartBytes from its part start.
                for ($o = $cuts[$c]; $o -lt $end; $o += $MaxPartBytes) { $starts.Add($o) }
            }
        }
        $count = $starts.Count
        $parts = New-Object 'object[]' $count
        $buffer = New-Object byte[] (8MB)
        $partName = {
            param([int] $index, [string] $sha)
            if ($ReleaseMode) { if ($count -eq 1) { $PayloadBase } else { '{0}.part{1:D2}' -f $PayloadBase, ($index + 1) } }
            else { 'golden_era_payload.{0}.part' -f $sha.Substring(0, 20) }
        }
        $fs = [IO.File]::Open($zipPath, 'Open', 'ReadWrite', 'None')
        try {
            # Copy each tail part out and truncate, last part first, so the peak is the zip plus one part.
            for ($i = $count - 1; $i -ge 1; $i--) {
                $offset = $starts[$i]
                $len = [int64]$fs.Length - $offset
                $hash = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
                $tmp = Join-Path $assets 'part.tmp'
                $outFs = [IO.File]::Open($tmp, 'CreateNew', 'Write', 'None')
                try {
                    [void]$fs.Seek($offset, 'Begin')
                    $left = $len
                    while ($left -gt 0) {
                        $read = $fs.Read($buffer, 0, [int][Math]::Min($buffer.Length, $left))
                        if ($read -le 0) { throw "unexpected end of zip at part $($i + 1)" }
                        $outFs.Write($buffer, 0, $read); $hash.AppendData($buffer, 0, $read); $left -= $read
                    }
                    $outFs.Flush($true)
                } finally { $outFs.Dispose() }
                if ((Get-Item -LiteralPath $tmp).Length -ne $len) { throw "part $($i + 1) has the wrong length" }
                $psha = [Convert]::ToHexString($hash.GetHashAndReset()).ToLowerInvariant()
                $name = & $partName $i $psha
                if (Test-Path -LiteralPath (Join-Path $assets $name)) { throw "two parts are both named $name" }
                Move-Item -LiteralPath $tmp -Destination (Join-Path $assets $name)
                $fs.SetLength($offset)
                $parts[$i] = [ordered]@{ name = $name; bytes = $len; sha256 = $psha }
                Sample-Free
            }
            # What is left of the zip is the first part: hash it before the rename.
            $hash = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
            [void]$fs.Seek(0, 'Begin')
            while (($read = $fs.Read($buffer, 0, $buffer.Length)) -gt 0) { $hash.AppendData($buffer, 0, $read) }
            $p1sha = [Convert]::ToHexString($hash.GetHashAndReset()).ToLowerInvariant()
            $p1len = [int64]$fs.Length
        } finally { $fs.Dispose() }
        $name = & $partName 0 $p1sha
        if (Test-Path -LiteralPath (Join-Path $assets $name)) { throw "two parts are both named $name" }
        Move-Item -LiteralPath $zipPath -Destination (Join-Path $assets $name)
        $parts[0] = [ordered]@{ name = $name; bytes = $p1len; sha256 = $p1sha }
        if ((Get-Item -LiteralPath (Join-Path $assets $name)).Length -ne $parts[0].bytes) { throw 'part 1 has the wrong length' }
        if ((($parts | ForEach-Object { [int64]$_.bytes }) | Measure-Object -Sum).Sum -ne $total) { throw 'the parts do not add up to the zip' }
        if (-not $ReleaseMode) {
            # The packaging script names uniform .partNN files; point both footers at these parts instead.
            # The footer is plain JSON + int64 length + 'GERADL01' at the end of the EXE, and the wizard
            # takes any plain file names with partBytes that add up to expectedBytes.
            foreach ($ins in $installers) {
                Set-DownloadFooterParts -Exe $ins.path -Names @($parts | ForEach-Object { $_.name }) -Sizes @($parts | ForEach-Object { [int64]$_.bytes })
                $ins.footer = Read-JsonFile "$($ins.path).download-manifest.json"
            }
        }
        Set-Content -LiteralPath (Join-Path $assets "$PayloadBase.sha256") -Value "$($zipInfo.sha256)  $PayloadBase" -Encoding ascii
        $dm = [ordered]@{ schema = 'golden_era_payload_download/v1'; payload_base_name = $PayloadBase; expected_sha256 = $zipInfo.sha256;
            expected_bytes = $total; max_part_bytes = $MaxPartBytes; parts = @($parts | ForEach-Object { $_.name }); part_bytes = @($parts | ForEach-Object { $_.bytes }) }
        ($dm | ConvertTo-Json -Depth 4) | Set-Content -LiteralPath (Join-Path $assets "$PayloadBase.download-manifest.json") -Encoding utf8
        Remove-Item -LiteralPath "$zipPath.sha256" -Force -ErrorAction SilentlyContinue
        # Every installer footer must name exactly these parts, sizes and the payload hash.
        foreach ($ins in $installers) {
            $f = $ins.footer
            if ($f.releaseTag -ne $Tag -or $f.githubOwner -ne 'leviritchie' -or $f.githubRepo -ne 'Golden-Era') { throw "$($ins.name) footer targets $($f.githubOwner)/$($f.githubRepo)@$($f.releaseTag)" }
            if ($f.payloadBaseName -ne $PayloadBase -or $f.expectedSha256 -ne $zipInfo.sha256 -or [int64]$f.expectedBytes -ne $total) { throw "$($ins.name) footer payload does not match the zip" }
            if (@($f.parts).Count -ne $count -or @($f.partBytes).Count -ne $count) { throw "$($ins.name) footer has $(@($f.parts).Count) parts, split made $count" }
            for ($k = 0; $k -lt $count; $k++) {
                if ($f.parts[$k] -ne $parts[$k].name -or [int64]$f.partBytes[$k] -ne [int64]$parts[$k].bytes) { throw "$($ins.name) footer part $($k + 1) does not match $($parts[$k].name)" }
            }
            Copy-Item -LiteralPath $ins.path -Destination (Join-Path $assets $ins.name)
            Copy-Item -LiteralPath "$($ins.path).sha256" -Destination (Join-Path $assets "$($ins.name).sha256")
        }
        $parts
    })
    if (-not $KeepWork) { Remove-Tree $public }

    # ---- print-plan URL check -----------------------------------------------------------------------
    $scratch = Join-Path $WorkDir 'scratch'
    [void](New-Item -ItemType Directory -Force -Path $scratch)
    # The wizard manifest asks for requireAdministrator (needed for real installs into Program Files).
    # Every mode used here only reads the assets and writes under N:, and the code has no admin check,
    # so the child runs unelevated as the invoking user: RunAsInvoker lowers the request, never raises it.
    $exeEnv = @{ GOLDEN_ERA_INSTALLER_CACHE_ROOT = (Join-Path $scratch 'installer_cache'); DOTNET_BUNDLE_EXTRACT_BASE_DIR = (Join-Path $scratch 'dotnet_bundle'); __COMPAT_LAYER = 'RunAsInvoker' }
    $assetNames = @(Get-ChildItem -LiteralPath $assets -File | ForEach-Object Name)
    Step 'plan' 60 {
        $prefix = "https://github.com/$PublicRepo/releases/download/$Tag/"
        foreach ($ins in $installers) {
            $r = Invoke-Child -File (Join-Path $assets $ins.name) -Arguments @('--print-plan') -LogBase (Join-Path $logDir "plan-$($ins.name)") -TimeoutMinutes 5 -Environment $exeEnv -WorkingDirectory $assets
            if ($r.ExitCode -ne 0) { throw "$($ins.name) --print-plan exited $($r.ExitCode)" }
            $urls = @(Get-Content -LiteralPath $r.Err | Where-Object { $_ -match '^https?://' })
            if ($urls.Count -ne $split.Count) { throw "$($ins.name) printed $($urls.Count) URLs for $($split.Count) parts" }
            for ($k = 0; $k -lt $urls.Count; $k++) {
                $expected = $prefix + [Uri]::EscapeDataString($split[$k].name)
                if ($urls[$k].Trim() -ne $expected) { throw "$($ins.name) URL $($k + 1) is $($urls[$k]) (expected $expected)" }
                if ($assetNames -notcontains $split[$k].name) { throw "URL target $($split[$k].name) is not an asset" }
            }
        }
        "$($split.Count) URLs x $($installers.Count) installers match the assets"
    } | Out-Null

    # ---- install verification ---------------------------------------------------------------------------
    $verify = Step 'verify' 70 {
        $mirrorBytes = Dir-Bytes $CleanMirror
        $free = Free $WorkRoot
        $needHeadless = $mirrorBytes + 2 * [int64]$zipInfo.uncompressedBytes + 1GB
        $homm3Ok = $Homm3Root -and (Test-Path -LiteralPath $Homm3Root)
        $mode = if ($homm3Ok -and $free -ge $needHeadless) { 'headless-install' } else { 'verify-payload' }
        $reason = if ($mode -eq 'headless-install') { 'space and a HoMM3 folder are available' }
            elseif (-not $homm3Ok) { ("no -Homm3Root given; a headless install would also need {0:N1} GB free (have {1:N1} GB)" -f ($needHeadless / 1GB), ($free / 1GB)) }
            else { ("a headless install needs {0:N1} GB free (clean copy {1:N1} GB + extracted payload and installed copy 2 x {2:N1} GB + 1 GB); N: has {3:N1} GB" -f ($needHeadless / 1GB), ($mirrorBytes / 1GB), ($zipInfo.uncompressedBytes / 1GB), ($free / 1GB)) }
        Log "   install check: $mode ($reason)"
        $exe = Join-Path $assets $installers[0].name
        # No network: an unreachable base URL makes any attempted download fail instead of fetching.
        $envV = $exeEnv.Clone(); $envV.GOLDEN_ERA_INSTALLER_RELEASE_BASE_URL = 'http://127.0.0.1:9/nightly-offline'
        if ($mode -eq 'headless-install') {
            $target = Join-Path $scratch 'install'
            $hlog = Join-Path $logDir 'headless.log'
            $r = Invoke-Child -File $exe -LogBase (Join-Path $logDir 'headless') -TimeoutMinutes 90 -Environment $envV -WorkingDirectory $assets -Arguments @(
                '--headless', '--operation', 'install', '--source', $CleanMirror, '--target', $target, '--homm3', $Homm3Root, '--log', $hlog)
            $ok = (Test-Path -LiteralPath $hlog) -and (Select-String -LiteralPath $hlog -SimpleMatch 'HEADLESS_OK' -Quiet)
            Remove-Tree $target
            if ($r.ExitCode -ne 0 -or -not $ok) { throw "headless install failed (exit $($r.ExitCode)): $(Tail $hlog 6)" }
            $result = 'HEADLESS_OK'
        } else {
            $r = Invoke-Child -File $exe -Arguments @('--verify-payload') -LogBase (Join-Path $logDir 'verify-payload') -TimeoutMinutes 45 -Environment $envV -WorkingDirectory $assets
            $vlog = Join-Path $exeEnv.GOLDEN_ERA_INSTALLER_CACHE_ROOT 'Logs\verify-payload.log'
            if (Test-Path -LiteralPath $vlog) { Copy-Item -LiteralPath $vlog -Destination (Join-Path $logDir 'verify-payload.installer.log') }
            $ok = (Test-Path -LiteralPath $vlog) -and (Select-String -LiteralPath $vlog -SimpleMatch 'VERIFY_OK' -Quiet)
            if ($r.ExitCode -ne 0 -or -not $ok) { throw "--verify-payload failed (exit $($r.ExitCode)): $(Tail $vlog 6)" }
            $result = 'VERIFY_OK: ' + ((Get-Content -LiteralPath $vlog | Where-Object { $_ -match '^(Zip entries|Overlay operations)' }) -join '; ')
        }
        [ordered]@{ mode = $mode; reason = $reason; result = $result; installer = $installers[0].name
            mirrorBytes = $mirrorBytes; freeBytes = $free; headlessNeedBytes = $needHeadless }
    }
    $summary.installCheck = $verify
    Remove-Tree $scratch

    # ---- assets list ----------------------------------------------------------------------------------
    $partSha = @{}; foreach ($p in $split) { $partSha[$p.name] = $p.sha256 }
    $summary.assets = @(Get-ChildItem -LiteralPath $assets -File | Sort-Object Name | ForEach-Object {
            $h = if ($partSha.ContainsKey($_.Name)) { $partSha[$_.Name] } else { (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
            [ordered]@{ name = $_.Name; bytes = $_.Length; sha256 = $h }
        })

    # ---- notes ----------------------------------------------------------------------------------------
    $notesPath = Join-Path $logDir 'release_notes.md'
    if ($ReleaseMode) {
        Step 'notes' 40 {
            # Release notes are written by hand and passed in; they still go through the leak gate.
            Copy-Item -LiteralPath $NotesFile -Destination $notesPath -Force
            $nt = Get-Content -LiteralPath $notesPath -Raw
            if (-not $nt.Contains($ReleaseTag.Substring(1))) { throw "the notes file does not mention $ReleaseTag" }
            $nd = Join-Path $WorkDir 'notes_scan'; [void](New-Item -ItemType Directory -Force -Path $nd)
            Copy-Item -LiteralPath $notesPath -Destination (Join-Path $nd 'release_notes.md')
            $termArgs = @(); foreach ($t in @($env:USERNAME, $env:COMPUTERNAME, (& git -C $Repo config user.email))) { if ($t) { $termArgs += @('--term', $t) } }
            & python (Join-Path $here 'payload_leaks.py') scan --root $nd --report (Join-Path $logDir 'notes.leaks.json') @termArgs | Out-Null
            $code = $LASTEXITCODE
            Remove-Tree $nd
            if ($code -ne 0) { throw 'release notes failed the leak scan' }
            $summary.notes = [ordered]@{ path = $notesPath; source = 'file' }
            'ok'
        } | Out-Null
    } else {
    Step 'notes' 40 {
        $base = [string]$state.lastPublishedSha
        $range = $null
        if ($base) { & git -C $Repo merge-base --is-ancestor $base $sha 2>$null; if ($LASTEXITCODE -eq 0) { $range = "$base..$sha" } }
        $subjects = if ($range) { & git -C $Repo log --no-merges --format=%s $range } else { & git -C $Repo log --no-merges --format=%s --since='3 days ago' -n 200 $sha }
        $include = '(?i)\b(fix(es|ed)?|crash(es)?|restore[sd]?|correct(s|ed)?|repair(s|ed)?|prevent(s|ed)?|missing|wrong|broken|improve[sd]?|balance|town|battle|adventure map|unit|hero|spell|campaign|portrait|animation|installer|sound|audio|ui)\b'
        $exclude = '(?i)(^\s*(tools?|nightly|ci|tests?|docs?|symbols|validators?|gates?|contracts?|port|artifacts|cleanup|chore|refactor|wip|merge|revert|bump|agents?)\b)|\b(validator|contract|gate|tests?|probe|diag(nostic)?s?|bisect|census|agent|codex|claude|pipeline|nightly|baseline|hint|interop|workbench|scratch|meshy|credits?|bug[- ]?reports?|reports?|player|log(s)?|bench|queue|cache|guid|glb|reimports?|document(s|ed)?|record(s|ed)?|provenance|audit|fleet|slice|re-?pin(s|ned)?|extraction|catalogs?|wrappers?|routing|symbols?|current[- ]port|ssr|regrid|keyrotations|prefab|bundles?|frozen)\b|\w_\w|/|[A-Za-z]:[\\/]|@|https?:|["`]|[0-9a-f]{8}-[0-9a-f]{4}-|tools/|docs/|\.md\b|\.py\b|\.ps1\b'
        $picked = @($subjects | Where-Object { $_ -match $include -and $_ -notmatch $exclude } | ForEach-Object {
                $s = ($_ -replace '\s+', ' ').Trim(); if ($s.Length -gt 110) { $s = $s.Substring(0, 107) + '...' }; $s } | Select-Object -Unique)
        $shown = @($picked | Select-Object -First 25)
        $latest = Invoke-Gh @('release', 'view', '-R', $PublicRepo, '--json', 'tagName', '--jq', '.tagName') -AllowFail
        $stable = if ($latest.Code -eq 0 -and $latest.Text) { $latest.Text.Trim() } else { 'the latest release' }
        $exeUp = ($installers | Where-Object { $_.name -like '*upscaled*' }).name
        $exeStd = ($installers | Where-Object { $_.name -like '*standard*' }).name
        $lines = @(
            "Rolling nightly build **$label**, built $('{0:yyyy-MM-dd HH:mm}' -f $runStart) UTC.",
            '',
            "This prerelease is built automatically and only lightly tested. Each new nightly replaces it. For the stable version, use $stable.",
            '',
            '### Install',
            'Download one installer and run it:',
            "- ``$exeUp``: HoMM3 hero portraits upscaled",
            "- ``$exeStd``: original HoMM3 hero portraits",
            ('The installer downloads the payload ({0:N1} GB in {1} parts) from this release. To install offline, put every `.part` file from this release next to the installer.' -f ($zipInfo.zipBytes / 1e9), $split.Count),
            'An installer from an older nightly stops working once a newer nightly replaces this release. If that happens, download the current installer.',
            '',
            '### Changes'
        )
        if ($shown.Count -gt 0) { $lines += @($shown | ForEach-Object { "- $_" }) } else { $lines += '- Maintenance and internal changes.' }
        if ($picked.Count -gt $shown.Count) { $lines += "- ...and $($picked.Count - $shown.Count) more." }
        $lines += @('', '### Checksums', "Payload ``$PayloadBase``: sha256 ``$($zipInfo.sha256)``")
        foreach ($ins in $installers) { $lines += "``$($ins.name)``: sha256 ``$(((Get-Content -LiteralPath (Join-Path $assets "$($ins.name).sha256") -Raw).Trim() -split '\s+')[0])``" }
        Set-Content -LiteralPath $notesPath -Value ($lines -join "`n") -Encoding utf8
        # The notes go through the same leak gate as the payload.
        $nd = Join-Path $WorkDir 'notes_scan'; [void](New-Item -ItemType Directory -Force -Path $nd)
        Copy-Item -LiteralPath $notesPath -Destination (Join-Path $nd 'release_notes.md')
        $termArgs = @(); foreach ($t in @($env:USERNAME, $env:COMPUTERNAME, (& git -C $Repo config user.email))) { if ($t) { $termArgs += @('--term', $t) } }
        & python (Join-Path $here 'payload_leaks.py') scan --root $nd --report (Join-Path $logDir 'notes.leaks.json') @termArgs | Out-Null
        $code = $LASTEXITCODE
        Remove-Tree $nd
        if ($code -ne 0) { throw 'release notes failed the leak scan' }
        $summary.notes = [ordered]@{ path = $notesPath; range = $(if ($range) { $range } else { 'last 3 days' }); commits = @($subjects).Count; listed = $shown.Count; filteredOut = @($subjects).Count - $picked.Count }
        'ok'
    } | Out-Null
    }

    # Record the staged (scrubbed) DLL hash: bug reports carry it in payload_manifest.json.
    $builds = if (Test-Path -LiteralPath $BuildsPath) { @(Read-JsonFile $BuildsPath) } else { @() }
    $builds = @($builds | Where-Object { $_.label -ne $label }) + @([pscustomobject]@{ label = $label; sha = $sha; dllSha256 = $stagedDllSha;
            payloadSha256 = $zipInfo.sha256; builtUtc = $runStart.ToString('o'); published = $false })
    ConvertTo-Json -Depth 3 -InputObject @($builds | Select-Object -Last 200) | Set-Content -LiteralPath $BuildsPath -Encoding utf8

    # ---- publish ----------------------------------------------------------------------------------------
    if ($Publish -and $ReleaseMode) {
        Publish-VersionedRelease
    } elseif ($Publish) {
        Step 'publish' 80 {
            $latestBefore = (Invoke-Gh @('release', 'view', '-R', $PublicRepo, '--json', 'tagName', '--jq', '.tagName')).Text.Trim()
            if ($latestBefore -eq $Tag) { throw "the Latest release is '$Tag'; refusing to continue" }
            $mainSha = (Invoke-Gh @('api', "repos/$PublicRepo/commits/main", '--jq', '.sha')).Text.Trim()
            if ($mainSha -notmatch '^[0-9a-f]{40}$') { throw "bad public main sha '$mainSha'" }
            $view = Invoke-Gh @('release', 'view', $Tag, '-R', $PublicRepo, '--json', 'tagName,isPrerelease,isDraft,assets') -AllowFail
            $title = "Golden Era nightly ($label)"
            if ($view.Code -ne 0) {
                Log "   creating the $Tag prerelease at public main $mainSha"
                [void](Invoke-Gh @('release', 'create', $Tag, '-R', $PublicRepo, '--prerelease', '--latest=false', '--target', $mainSha, '--title', $title, '--notes-file', $notesPath))
                $existing = @()
            } else {
                $rel = $view.Text | ConvertFrom-Json
                if ($rel.tagName -ne $Tag -or -not $rel.isPrerelease) { throw "release '$($rel.tagName)' is not a prerelease; refusing to modify it" }
                $existing = @($rel.assets)
            }
            $have = @{}; foreach ($x in $existing) { $have[[string]$x.name] = [int64]$x.size }
            # Upload: payload parts and their manifests first, installers last, so an installer never
            # names parts that are not there yet. Old parts stay valid for old installers until the
            # stale-asset sweep. A nightly part is named by its content, so one already on the release
            # with the same size is kept, not uploaded again.
            $partNames = @($split | ForEach-Object { $_.name })
            $order = @($summary.assets | Where-Object { $partNames -contains $_.name -or $_.name -like "$PayloadBase*" }) + @($summary.assets | Where-Object { $partNames -notcontains $_.name -and $_.name -notlike "$PayloadBase*" })
            $reused = @()
            foreach ($a in $order) {
                if (-not $ReleaseMode -and $a.name -like 'golden_era_payload.*.part' -and $have.ContainsKey($a.name) -and $have[$a.name] -eq [int64]$a.bytes) { $reused += $a.name; continue }
                $ok = $false
                for ($try = 1; $try -le 3 -and -not $ok; $try++) {
                    $r = Invoke-Child -File $GhExe -LogBase (Join-Path $logDir "upload-$($a.name)") -TimeoutMinutes 120 -Arguments @(
                        'release', 'upload', $Tag, (Join-Path $assets $a.name), '-R', $PublicRepo, '--clobber')
                    $ok = $r.ExitCode -eq 0
                    if (-not $ok) { Log "   upload $($a.name) attempt $try failed: $(Tail $r.Err 2)" }
                }
                if (-not $ok) { throw "upload of $($a.name) failed 3 times" }
            }
            $keep = @($summary.assets | ForEach-Object { $_.name })
            $now = ((Invoke-Gh @('release', 'view', $Tag, '-R', $PublicRepo, '--json', 'assets')).Text | ConvertFrom-Json).assets
            $stale = @($now | Where-Object { $keep -notcontains $_.name } | ForEach-Object { $_.name })
            foreach ($n in $stale) { [void](Invoke-Gh @('release', 'delete-asset', $Tag, $n, '-R', $PublicRepo, '--yes')) }
            # Move the nightly tag (only this tag) to the public main.
            $ref = (Invoke-Gh @('api', "repos/$PublicRepo/git/ref/tags/$Tag")).Text | ConvertFrom-Json
            if ($ref.object.type -ne 'commit') { throw "tag $Tag is a $($ref.object.type), not a lightweight tag" }
            if ($ref.object.sha -ne $mainSha) { [void](Invoke-Gh @('api', '-X', 'PATCH', "repos/$PublicRepo/git/refs/tags/$Tag", '-f', "sha=$mainSha", '-F', 'force=true')) }
            [void](Invoke-Gh @('release', 'edit', $Tag, '-R', $PublicRepo, '--prerelease', '--latest=false', '--title', $title, '--notes-file', $notesPath))
            # Verify: exactly our assets with our sizes, still a prerelease, Latest unchanged.
            $after = (Invoke-Gh @('release', 'view', $Tag, '-R', $PublicRepo, '--json', 'isPrerelease,assets')).Text | ConvertFrom-Json
            if (-not $after.isPrerelease) { throw "$Tag is no longer a prerelease" }
            foreach ($a in $summary.assets) {
                $m = @($after.assets | Where-Object { $_.name -eq $a.name })
                if ($m.Count -ne 1 -or [int64]$m[0].size -ne [int64]$a.bytes) { throw "uploaded asset $($a.name) is missing or the wrong size" }
            }
            if (@($after.assets).Count -ne $summary.assets.Count) { throw "release has $(@($after.assets).Count) assets, expected $($summary.assets.Count)" }
            $latestAfter = (Invoke-Gh @('release', 'view', '-R', $PublicRepo, '--json', 'tagName', '--jq', '.tagName')).Text.Trim()
            if ($latestAfter -ne $latestBefore) { throw "Latest changed from $latestBefore to $latestAfter" }
            $summary.published = $true
            $summary.publish = [ordered]@{ tag = $Tag; target = $mainSha; latest = $latestAfter; uploaded = $order.Count - $reused.Count; reusedParts = $reused.Count;
                uploadedBytes = (@($order | Where-Object { $reused -notcontains $_.name } | ForEach-Object { [int64]$_.bytes }) | Measure-Object -Sum).Sum; staleDeleted = $stale; url = "https://github.com/$PublicRepo/releases/tag/$Tag" }
            'ok'
        } | Out-Null
        $state | Add-Member -Force -NotePropertyName lastPublishedSha -NotePropertyValue $sha
        $state | Add-Member -Force -NotePropertyName lastPublishedLabel -NotePropertyValue $label
        $state | Add-Member -Force -NotePropertyName lastPublishedUtc -NotePropertyValue ([DateTime]::UtcNow.ToString('o'))
        $builds = @(@(Read-JsonFile $BuildsPath) | ForEach-Object { if ($_.label -eq $label) { $_.published = $true }; $_ })
        ConvertTo-Json -Depth 3 -InputObject $builds | Set-Content -LiteralPath $BuildsPath -Encoding utf8
    }

    $summary.status = 'pass'
    $exitCode = 0
} catch [NightlyFailure] {
    $exitCode = $_.Exception.Code
    $summary.failures += $_.Exception.Message
} catch {
    $exitCode = 90
    $summary.failures += "unexpected: $($_.Exception.Message) at $($_.InvocationInfo.PositionMessage)"
} finally {
    $minFree.stop = $true
    if ($sampler) { try { Wait-Job $sampler -Timeout 5 | Out-Null; Remove-Job $sampler -Force } catch { } }
    if ($exitCode -ne 11 -and (Test-Path -LiteralPath $WorkRoot)) {
        Sample-Free
        $summary.exitCode = $exitCode
        $summary.failureClass = if ($exitCode -ne 0) { $FailureClass[$exitCode] } else { $null }
        if ($summary.disk.freeAtStartBytes) {
            $summary.disk.minFreeBytes = $minFree.value
            $summary.disk.peakUsedBytes = $summary.disk.volumeBytes - $minFree.value
            $summary.disk.peakRunDeltaBytes = $summary.disk.freeAtStartBytes - $minFree.value
        }
        # ---- cleanup: N: keeps logs, state, builds, reports (and the dry-run assets) -------------------
        $keepAssets = (-not $Publish -or $KeepAssets) -and $exitCode -eq 0
        try {
            if (Test-Path -LiteralPath $WorkDir) {
                if ($KeepWork) { }
                elseif ($keepAssets) {
                    foreach ($item in Get-ChildItem -LiteralPath $WorkDir -Force) { if ($item.Name -ne 'assets') { Remove-Tree $item.FullName } }
                    $summary.assetsDir = Join-Path $WorkDir 'assets'
                } else { Remove-Tree $WorkDir }
            }
        } catch { $summary.failures += "cleanup: $($_.Exception.Message)" }
        $summary.finishedUtc = [DateTime]::UtcNow.ToString('o')
        $summary.totalSeconds = [Math]::Round(([DateTime]::UtcNow - $runStart).TotalSeconds, 1)
        if ($exitCode -eq 0) {
            if (-not $state) { $state = [pscustomobject]@{} }
            if ($summary.disk.peakRunDeltaBytes) { $state | Add-Member -Force -NotePropertyName lastRunPeakDeltaBytes -NotePropertyValue $summary.disk.peakRunDeltaBytes }
            $state | Add-Member -Force -NotePropertyName lastRunLabel -NotePropertyValue $summary.label
            $state | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $StatePath -Encoding utf8
        }
        $summaryPath = if ($logDir) { Join-Path $logDir 'summary.json' } else { Join-Path $LogsRoot ('failed-{0:yyyyMMdd-HHmmss}.summary.json' -f $runStart) }
        try { [void](New-Item -ItemType Directory -Force -Path (Split-Path $summaryPath)) } catch { }
        $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding utf8
        Copy-Item -LiteralPath $summaryPath -Destination (Join-Path $LogsRoot 'latest_summary.json') -Force -ErrorAction SilentlyContinue
        # Keep the last $KeepLogRuns run folders.
        try {
            Get-ChildItem -LiteralPath $LogsRoot -Directory | Sort-Object Name -Descending | Select-Object -Skip $KeepLogRuns | ForEach-Object { Remove-Tree $_.FullName }
        } catch { }
        $state = $null
    }
    if ($transcript) { try { Stop-Transcript | Out-Null } catch { } }
    if ($lock) { $lock.Dispose(); Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue }
}

if ($exitCode -eq 0) {
    Write-Host "${RunKind}: PASS $($summary.label) published=$($summary.published) summary=$summaryPath$(if ($summary.assetsDir) { " assets=$($summary.assetsDir)" })"
} else {
    Write-Host "${RunKind}: FAIL exit=$exitCode class=$($FailureClass[$exitCode]) $($summary.failures -join ' | ')"
    if ($summaryPath) { Write-Host "  summary: $summaryPath" }
}
exit $exitCode
