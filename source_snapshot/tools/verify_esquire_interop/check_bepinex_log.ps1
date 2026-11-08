# Read BepInEx/LogOutput.log for EsquirePikeman success/failure markers.
# Requires Windows PowerShell 5.1+ or PowerShell 7+ (Join-Path below is PS5-compatible).
#
# Usage (from cmd or PowerShell; use full path if "powershell" is not on PATH):
#   powershell.exe -NoProfile -File check_bepinex_log.ps1 -PlaytestRoot "V:\path\to\Heroes of Might & Magic Olden Era Playtest"
# PowerShell 7, if installed:
#   pwsh -File check_bepinex_log.ps1 -PlaytestRoot "V:\path\..."
# Git Bash often has Windows PowerShell but not pwsh on PATH — use:
#   "/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe" -NoProfile -File tools/verify_esquire_interop/check_bepinex_log.ps1 -PlaytestRoot "…"
#
# Exit 1 if a known EsquirePikeman failure line is present, or if the Harmony postfix success line is absent.
# Also flags repeating Il2CppInterop NREs on Hex.InitScene.BhAppStartScript::Update (see BepInEx/LogOutput.log
# for [Error  :Il2CppInterop] ... DMD<Hex.InitScene.BhAppStartScript::Update> ... bxg.pbo), unless
# -AllowBhAppStartIl2CppNre is passed.
# Optional: EsquirePikeman: loaded bundle from (info) is not required for exit 0.

param(
    [string] $PlaytestRoot = $env:HEROES_OE_PLAYTEST,
    [switch] $AllowBhAppStartIl2CppNre
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($PlaytestRoot)) {
    Write-Error "Pass -PlaytestRoot or set HEROES_OE_PLAYTEST"
    exit 1
}

if (-not (Test-Path -LiteralPath $PlaytestRoot)) {
    Write-Error "Path not found: $PlaytestRoot"
    exit 1
}

$logPath = Join-Path (Join-Path $PlaytestRoot "BepInEx") "LogOutput.log"
if (-not (Test-Path -LiteralPath $logPath)) {
    Write-Error "Log not found: $logPath"
    exit 1
}

$log = Get-Content -LiteralPath $logPath -Raw

# Only the latest BepInEx "Chainloader" session; avoids stale failure lines from prior launches.
$needle = "Chainloader initialized"
$pos = $log.LastIndexOf($needle)
$scan = if ($pos -ge 0) { $log.Substring($pos) } else { $log }

# When esquirePikemanVisuals is false, the mod skips ResManager patching (pre-Esquire behavior).
if ($scan.Contains("EsquirePikeman: disabled")) {
    Write-Host "Log check OK (EsquirePikeman intentionally off; set esquirePikemanVisuals=true in mod config to test the hook)."
    exit 0
}

$failures = @(
    "EsquirePikeman: Hex.ResManager assembly not found; pikeman swap disabled.",
    "EsquirePikeman: type ResManager not found; pikeman swap disabled.",
    "EsquirePikeman: ResManager.Get<...>(string) not found; pikeman swap disabled."
)
foreach ($line in $failures) {
    if ($scan.Contains($line)) {
        Write-Error "Found failure line in the latest log session: $line"
        exit 1
    }
}

# v0.1.19+ ResManager Prefix+skip; v0.1.23+ scene defer = Harmony postfix on LoadScene/LoadSceneAsync (Il2cpp sceneLoaded is not C#-subscribable).
$hookOk = ($scan -match "EsquirePikeman: Harmony (postfix|prefix) on") `
    -or ($scan -match "EsquirePikeman: narrow Harmony postfix on") `
    -or ($scan -match "EsquirePikeman: scheduled ResManager Harmony prefix") `
    -or ($scan -match "EsquirePikeman: will apply ResManager prefix after") `
    -or ($scan -match "EsquirePikeman: will apply ResManager prefix at end of frame") `
    -or ($scan -match "EsquirePikeman: Harmony NOT applied \(esquirePikemanApplyHarmony=false\)")
if (-not $hookOk) {
    Write-Error "Expected an EsquirePikeman hook/skip line (ResManager prefix/postfix, narrow postfix, scheduled deferred patch, or applyHarmony=false note) in the latest log session."
    exit 1
}

# Il2CppInterop logs each trampoline failure; same session may contain many identical blocks.
$dmd = "DMD<Hex.InitScene.BhAppStartScript::Update>"
$dmdCount = ([regex]::Matches($scan, [regex]::Escape($dmd))).Count
# Fallback if the DMD string changes but the pbo init frame remains:
$pboCount = 0
if ($dmdCount -eq 0) {
    $pboCount = ([regex]::Matches($scan, "at bxg\.pbo \(UnityEngine\.TextAsset")).Count
}

if ($dmdCount -gt 0 -or $pboCount -gt 0) {
    if ($dmdCount -gt 0) {
        Write-Host "BepInEx (latest session): Il2CppInterop reports $dmdCount occurrence(s) of '$dmd' (native->managed trampoline NRE, often bxg.pbo / bxt.Init under BhAppStartScript::Update). Full stacks: BepInEx\LogOutput.log"
    } else {
        Write-Host "BepInEx (latest session): $pboCount frame(s) matching 'at bxg.pbo (UnityEngine.TextAsset' (BhAppStart / init). Full stacks: BepInEx\LogOutput.log"
    }
    if (-not $AllowBhAppStartIl2CppNre) {
        $anchor = if ($dmdCount -gt 0) { $dmd } else { "at bxg.pbo (UnityEngine.TextAsset" }
        $hit = $scan.IndexOf($anchor)
        $sampleStart = -1
        if ($hit -ge 0) {
            $before = $scan.Substring(0, $hit)
            $sampleStart = $before.LastIndexOf("[Error  :Il2CppInterop]")
        }
        if ($sampleStart -lt 0) { $sampleStart = $scan.IndexOf("[Error  :Il2CppInterop]") }
        if ($sampleStart -ge 0) {
            $len = [Math]::Min(1800, $scan.Length - $sampleStart)
            if ($len -gt 0) {
                $snippet = $scan.Substring($sampleStart, $len) -replace "`r`n", "`n"
                Write-Host "Sample (log region around first $anchor, truncated; earlier lines may be other Il2CppInterop types e.g. BhFont):`n$snippet`n" -ForegroundColor DarkYellow
            }
        }
        Write-Error "Failing: Il2CppInterop reported $dmdCount hit(s) of $dmd in the latest BepInEx log session (repeating NRE in BhAppStartScript::Update; see BepInEx/LogOutput.log). Re-run with -AllowBhAppStartIl2CppNre to ignore for Esquire-only checks."
        exit 1
    }
    Write-Host "Allowing Il2CppInterop BhAppStart noise (-AllowBhAppStartIl2CppNre set)." -ForegroundColor Yellow
}

Write-Host "Log check OK (EsquirePikeman ResManager / narrow / deferred / or applyHarmony=false A/B line found)."
if ($dmdCount -eq 0 -and $pboCount -eq 0) {
    Write-Host "No DMD $dmd blocks in the latest log session (Il2CppInterop BhAppStart trampoline spam absent)."
}
exit 0
