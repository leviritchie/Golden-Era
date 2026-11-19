#Requires -Version 7
<#
.SYNOPSIS
  Copies a built codex site onto the public repo's gh-pages branch and, with -Push, pushes it.

.DESCRIPTION
  GitHub Pages serves gh-pages as "Deploy from a branch", so no workflow file is added to the public
  repo (the release pipeline refuses public commits whose workflows react to push/tag/release).
  The branch holds only the site. It is updated by a normal commit when the content changed and left
  alone when it did not, so unchanged images never grow the history.

  Uses a shallow single-branch clone in -WorkDir; the public main clone and its LFS content are
  never touched.

.EXAMPLE
  pwsh -NoProfile -File tools/unit_codex/publish_pages.ps1 -Site V:/olden_port_work/unit_codex/site -Label v0.1.329 -Push
#>
param(
    [Parameter(Mandatory)] [string] $Site,
    [string] $Label = 'dev',
    [string] $Repo = 'leviritchie/Golden-Era',
    [string] $Branch = 'gh-pages',
    [string] $WorkDir = (Join-Path ([IO.Path]::GetTempPath()) 'golden_era_codex_pages'),
    [switch] $Push
)
$ErrorActionPreference = 'Stop'

function Invoke-PagesGit { & git -C $WorkDir @args; if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') failed ($LASTEXITCODE)" } }

if (-not (Test-Path -LiteralPath (Join-Path $Site 'data/codex.json'))) { throw "not a built codex site (no data/codex.json): $Site" }
if (-not (Test-Path -LiteralPath (Join-Path $Site 'index.html'))) { throw "not a built codex site (no index.html): $Site" }

if (Test-Path -LiteralPath $WorkDir) { Remove-Item -LiteralPath $WorkDir -Recurse -Force }
$url = "https://github.com/$Repo.git"
& git ls-remote --exit-code --heads $url $Branch *> $null
$exists = $LASTEXITCODE -eq 0
if ($exists) {
    & git clone --quiet --depth 1 --single-branch --branch $Branch $url $WorkDir
    if ($LASTEXITCODE -ne 0) { throw "clone of $Repo $Branch failed" }
} else {
    [void](New-Item -ItemType Directory -Force -Path $WorkDir)
    Invoke-PagesGit init --quiet
    Invoke-PagesGit checkout --quiet --orphan $Branch
    Invoke-PagesGit remote add origin $url
}

# Mirror the site: drop everything tracked except .git, then copy the build in.
Get-ChildItem -LiteralPath $WorkDir -Force | Where-Object Name -ne '.git' | Remove-Item -Recurse -Force
Copy-Item -Path (Join-Path $Site '*') -Destination $WorkDir -Recurse -Force
Set-Content -LiteralPath (Join-Path $WorkDir '.nojekyll') -Value '' -NoNewline

Invoke-PagesGit add -A
& git -C $WorkDir diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "CODEX PAGES: unchanged ($Repo $Branch)"
    exit 0
}
$stat = (& git -C $WorkDir diff --cached --shortstat) -join ' '
Invoke-PagesGit commit --quiet -m "Codex: $Label"
if ($Push) {
    Invoke-PagesGit push --quiet origin "HEAD:$Branch"
    Write-Host "CODEX PAGES: pushed $Label to $Repo $Branch ($stat)"
} else {
    Write-Host "CODEX PAGES: committed locally in $WorkDir, not pushed ($stat)"
}
