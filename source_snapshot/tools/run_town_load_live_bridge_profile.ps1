param(
    [ValidateSet("WatchOpen", "Snapshot", "Refresh", "All")]
    [string]$Mode = "WatchOpen",
    [string]$BridgeDir = "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\live_probe_bridge",
    [string]$OutputRoot = "V:\Games\Olden Era Playtest Tweak\artifacts\live_bridge_town_load_profiles",
    [int]$DurationSeconds = 30,
    [int]$IntervalMs = 500,
    [int]$RefreshIterations = 8,
    [int]$TimeoutMs = 5000,
    [switch]$WaitForClickPrompt
)

$ErrorActionPreference = "Stop"

function Save-JsonFile {
    param($Value, [string]$Path)
    $json = $Value | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($Path, $json + "`n", [System.Text.UTF8Encoding]::new($false))
}

function New-RunDirectory {
    param([string]$Root, [string]$ModeName)
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $dir = Join-Path $Root ("{0}_{1}" -f $stamp, $ModeName)
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    return $dir
}

function Get-BridgeToken {
    param([string]$Bridge)
    $tokenPath = Join-Path $Bridge "token.txt"
    if (-not (Test-Path -LiteralPath $tokenPath)) {
        throw "Bridge token not found: $tokenPath"
    }
    return (Get-Content -LiteralPath $tokenPath -Raw).Trim()
}

function Invoke-BridgeRequest {
    param(
        [string]$Bridge,
        [string]$Token,
        [hashtable]$Payload,
        [int]$TimeoutMilliseconds
    )

    $id = [guid]::NewGuid().ToString("N")
    $name = "request-$id"
    $commandName = $Payload["command"]
    $Payload["id"] = $id
    $Payload["token"] = $Token

    $requestPath = Join-Path (Join-Path $Bridge "inbox") ("$name.json")
    $responsePath = Join-Path (Join-Path $Bridge "outbox") ("$name.json")
    $json = $Payload | ConvertTo-Json -Compress -Depth 8
    $started = [System.Diagnostics.Stopwatch]::StartNew()
    [System.IO.File]::WriteAllText($requestPath, $json, [System.Text.UTF8Encoding]::new($false))

    while ($started.ElapsedMilliseconds -lt $TimeoutMilliseconds -and -not (Test-Path -LiteralPath $responsePath)) {
        Start-Sleep -Milliseconds 25
    }

    $elapsed = $started.ElapsedMilliseconds
    if (-not (Test-Path -LiteralPath $responsePath)) {
        Write-Host ("bridge timeout command={0} elapsedMs={1}" -f $commandName, $elapsed)
        return [ordered]@{
            ok = $false
            id = $id
            command = $commandName
            elapsedMs = $elapsed
            responsePath = $responsePath
            response = $null
            errorCode = "timeout"
            errorMessage = "No bridge response within $TimeoutMilliseconds ms"
        }
    }

    $raw = Get-Content -LiteralPath $responsePath -Raw
    try {
        $parsed = $raw | ConvertFrom-Json
    } catch {
        Write-Host ("bridge parse failed command={0} elapsedMs={1}" -f $commandName, $elapsed)
        return [ordered]@{
            ok = $false
            id = $id
            command = $commandName
            elapsedMs = $elapsed
            responsePath = $responsePath
            response = $null
            errorCode = "json_parse_failed"
            errorMessage = $_.Exception.Message
        }
    }

    $ok = [bool]$parsed.ok
    Write-Host ("bridge command={0} ok={1} elapsedMs={2}" -f $commandName, $ok, $elapsed)
    return [ordered]@{
        ok = $ok
        id = $id
        command = $commandName
        elapsedMs = $elapsed
        responsePath = $responsePath
        response = $parsed
        errorCode = if ($ok -or $null -eq $parsed.error) { "" } else { $parsed.error.code }
        errorMessage = if ($ok -or $null -eq $parsed.error) { "" } else { $parsed.error.message }
    }
}

function Select-TownSampleSummary {
    param($StatusResult, $TownResult, [int]$Index = -1)
    $status = $StatusResult.response.status
    $town = $TownResult.response.townUi
    $layers = $town.layers
    return [ordered]@{
        utc = (Get-Date).ToUniversalTime().ToString("o")
        index = $Index
        statusOk = [bool]$StatusResult.ok
        townOk = [bool]$TownResult.ok
        statusElapsedMs = $StatusResult.elapsedMs
        townElapsedMs = $TownResult.elapsedMs
        statusResponsePath = $StatusResult.responsePath
        townResponsePath = $TownResult.responsePath
        state = $status.state
        frame = $status.frame
        scene = $status.scene
        currentFraction = $town.currentFraction
        cachedFraction = $town.cachedFraction
        cityData = [bool]$town.currentCityDataNonNull
        cityConfig = [bool]$town.currentCityConfigNonNull
        cachedWrapper = [bool]$town.cachedWrapperPresent
        layerRoot = [bool]$layers.rootExists
        layerRootActive = [bool]$layers.rootActive
        layerRootPath = $layers.rootPath
        activeLayers = $layers.activeLayerCount
        rawImages = $layers.rawImageCount
        graphics = $layers.graphicCount
        statusError = $StatusResult.errorMessage
        townError = $TownResult.errorMessage
    }
}

function Invoke-StatePair {
    param([string]$Bridge, [string]$Token, [int]$Index = -1)
    $status = Invoke-BridgeRequest -Bridge $Bridge -Token $Token -TimeoutMilliseconds $TimeoutMs -Payload @{ command = "status" }
    $town = Invoke-BridgeRequest -Bridge $Bridge -Token $Token -TimeoutMilliseconds $TimeoutMs -Payload @{ command = "town_ui_state" }
    return Select-TownSampleSummary -StatusResult $status -TownResult $town -Index $Index
}

function Invoke-WatchOpen {
    param([string]$Bridge, [string]$Token, [string]$RunDir)
    if ($WaitForClickPrompt) {
        Write-Host "Start this watcher while still outside the town. Press Enter, then click/open the town immediately."
        [void][Console]::ReadLine()
    }

    $samples = New-Object System.Collections.Generic.List[object]
    $deadline = (Get-Date).AddSeconds($DurationSeconds)
    $index = 0
    while ((Get-Date) -lt $deadline) {
        $summary = Invoke-StatePair -Bridge $Bridge -Token $Token -Index $index
        $samples.Add($summary)
        Write-Host ("[{0}] scene={1} frame={2} fraction={3} cityData={4} layers={5}/{6} rootActive={7} statusMs={8} townMs={9}" -f `
            $index, $summary.scene, $summary.frame, $summary.currentFraction, $summary.cityData, $summary.activeLayers, $summary.rawImages, $summary.layerRootActive, $summary.statusElapsedMs, $summary.townElapsedMs)
        $index++
        Start-Sleep -Milliseconds $IntervalMs
    }

    Save-JsonFile $samples (Join-Path $RunDir "watch_samples.json")
}

function Invoke-Snapshot {
    param([string]$Bridge, [string]$Token, [string]$RunDir)
    $summary = Invoke-StatePair -Bridge $Bridge -Token $Token -Index 0
    Save-JsonFile $summary (Join-Path $RunDir "snapshot_summary.json")
    Write-Host ("Snapshot scene={0} frame={1} fraction={2} cityData={3} layers={4}/{5} rootActive={6} statusMs={7} townMs={8}" -f `
        $summary.scene, $summary.frame, $summary.currentFraction, $summary.cityData, $summary.activeLayers, $summary.rawImages, $summary.layerRootActive, $summary.statusElapsedMs, $summary.townElapsedMs)
}

function Invoke-RefreshProfile {
    param([string]$Bridge, [string]$Token, [string]$RunDir)
    $results = New-Object System.Collections.Generic.List[object]
    for ($i = 0; $i -lt $RefreshIterations; $i++) {
        $before = Invoke-StatePair -Bridge $Bridge -Token $Token -Index $i
        $refresh = Invoke-BridgeRequest -Bridge $Bridge -Token $Token -TimeoutMilliseconds $TimeoutMs -Payload @{ command = "volatile_refresh_town_layers_from_cached_wrapper"; reason = "town-load-profile-$i" }
        $after = Invoke-StatePair -Bridge $Bridge -Token $Token -Index $i
        $entry = [ordered]@{
            index = $i
            utc = (Get-Date).ToUniversalTime().ToString("o")
            refreshOk = [bool]$refresh.ok
            refreshElapsedMs = $refresh.elapsedMs
            refreshResponsePath = $refresh.responsePath
            refreshError = $refresh.errorMessage
            before = $before
            after = $after
        }
        $results.Add($entry)
        Write-Host ("refresh[{0}] ok={1} elapsedMs={2} error='{3}'" -f $i, $entry.refreshOk, $entry.refreshElapsedMs, $entry.refreshError)
        Start-Sleep -Milliseconds 100
    }
    Save-JsonFile $results (Join-Path $RunDir "refresh_summary.json")
}

if (-not (Test-Path -LiteralPath $BridgeDir)) {
    throw "Bridge directory not found: $BridgeDir"
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$runDir = New-RunDirectory -Root $OutputRoot -ModeName $Mode
$token = Get-BridgeToken -Bridge $BridgeDir

$metadata = [ordered]@{
    utc = (Get-Date).ToUniversalTime().ToString("o")
    mode = $Mode
    bridgeDir = $BridgeDir
    outputDir = $runDir
    durationSeconds = $DurationSeconds
    intervalMs = $IntervalMs
    refreshIterations = $RefreshIterations
    note = "Read-only except Mode Refresh/All, which invokes volatile_refresh_town_layers_from_cached_wrapper. Raw bridge responses are referenced by path in summaries."
}
Save-JsonFile $metadata (Join-Path $runDir "metadata.json")

switch ($Mode) {
    "WatchOpen" { Invoke-WatchOpen -Bridge $BridgeDir -Token $token -RunDir $runDir }
    "Snapshot" { Invoke-Snapshot -Bridge $BridgeDir -Token $token -RunDir $runDir }
    "Refresh" { Invoke-RefreshProfile -Bridge $BridgeDir -Token $token -RunDir $runDir }
    "All" {
        Invoke-WatchOpen -Bridge $BridgeDir -Token $token -RunDir $runDir
        Invoke-Snapshot -Bridge $BridgeDir -Token $token -RunDir $runDir
        Invoke-RefreshProfile -Bridge $BridgeDir -Token $token -RunDir $runDir
    }
}

Write-Host "Output: $runDir"