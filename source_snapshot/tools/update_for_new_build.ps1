# update_for_new_build.ps1
# One-command workflow to update the mod for a new game build.
#
# Usage:
#   .\tools\update_for_new_build.ps1 -NewGamePath "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
#
# What it does:
#   1. Runs Il2CppDumper on the new game's GameAssembly.dll + metadata
#   2. Runs map_obfuscation.py to compare old vs new dump.cs
#   3. Runs apply_renames.py (--dry-run first) to preview changes
#   4. Optionally applies renames (--apply switch)
#   5. Reports what needs manual review
#
# Prerequisites:
#   - Il2CppDumper in tools/il2cpp_dumper/ (download from https://github.com/Perfare/Il2CppDumper/releases)
#   - Python 3 with no extra dependencies
#   - Previous dump.cs from old build (in tools/il2cpp_out_old/)

param(
    [Parameter(Mandatory=$true)]
    [string]$NewGamePath,

    [string]$OldDumpPath = "$PSScriptRoot\il2cpp_out_old",

    [string]$OutputDir = "$PSScriptRoot\il2cpp_out_new",

    [string]$RenameMapOutput = "$PSScriptRoot\rename_map_new.json",

    [string]$ModSourceDir = "$PSScriptRoot\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod",

    [switch]$Apply,

    [switch]$SkipDump,

    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

Write-Host "==============================" -ForegroundColor Cyan
Write-Host " Olden Era Mod — Build Updater" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""

# Resolve paths
$newGamePath = Resolve-Path $NewGamePath -ErrorAction Stop
$gameAssembly = Join-Path $newGamePath "GameAssembly.dll"
$metadata = Join-Path $newGamePath "HeroesOldenEra_Data\il2cpp_data\Metadata\global-metadata.dat"

if (-not (Test-Path $gameAssembly)) {
    Write-Error "GameAssembly.dll not found at: $gameAssembly"
    exit 1
}
if (-not (Test-Path $metadata)) {
    Write-Error "global-metadata.dat not found at: $metadata"
    exit 1
}

Write-Host "New game path: $newGamePath"
Write-Host "GameAssembly:  $gameAssembly"
Write-Host "Metadata:      $metadata"
Write-Host ""

# ─── Step 1: Run Il2CppDumper ───────────────────────────────────────────────

$dumperDir = Join-Path $scriptDir "il2cpp_dumper"
$dumperExe = Join-Path $dumperDir "Il2CppDumper.exe"

if (-not $SkipDump) {
    if (-not (Test-Path $dumperExe)) {
        Write-Warning "Il2CppDumper.exe not found at: $dumperExe"
        Write-Host ""
        Write-Host "Download Il2CppDumper from: https://github.com/Perfare/Il2CppDumper/releases"
        Write-Host "Extract to: $dumperDir"
        Write-Host ""
        Write-Host "Then re-run this script. Or use -SkipDump if you already have dump.cs."
        exit 1
    }

    Write-Host "[Step 1/4] Running Il2CppDumper..." -ForegroundColor Yellow
    
    # Create output directory
    if (Test-Path $OutputDir) {
        Write-Host "  Removing old output: $OutputDir"
        Remove-Item -Recurse -Force $OutputDir
    }
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

    # Check for headless config
    $configJson = Join-Path $dumperDir "config.json"
    if (Test-Path $configJson) {
        $config = Get-Content $configJson -Raw | ConvertFrom-Json
        if ($config.RequireAnyKey -eq $true) {
            Write-Host "  Setting RequireAnyKey=false for non-interactive run..."
            $config.RequireAnyKey = $false
            $config | ConvertTo-Json -Depth 5 | Set-Content $configJson
        }
    }

    Write-Host "  Running: Il2CppDumper.exe `"$gameAssembly`" `"$metadata`" `"$OutputDir`""
    $dumperArgs = @($gameAssembly, $metadata, $OutputDir)
    & $dumperExe $dumperArgs 2>&1 | ForEach-Object { Write-Host "    $_" }

    if ($LASTEXITCODE -ne 0) {
        Write-Error "Il2CppDumper failed with exit code $LASTEXITCODE"
        exit 1
    }

    Write-Host "  Dump complete: $OutputDir" -ForegroundColor Green
} else {
    Write-Host "[Step 1/4] Skipping Il2CppDumper (--SkipDump)" -ForegroundColor Yellow
}

$newDumpCs = Join-Path $OutputDir "dump.cs"
if (-not (Test-Path $newDumpCs)) {
    Write-Error "dump.cs not found at: $newDumpCs"
    Write-Host "Expected after running Il2CppDumper. Check that it ran successfully."
    exit 1
}

# ─── Step 2: Find old dump.cs ───────────────────────────────────────────────

$oldDumpCs = Join-Path $OldDumpPath "dump.cs"
if (-not (Test-Path $oldDumpCs)) {
    # Try alternate locations
    $altLocations = @(
        (Join-Path $scriptDir "il2cpp_out\dump.cs"),
        (Join-Path $repoRoot "tools\il2cpp_out\dump.cs")
    )
    foreach ($alt in $altLocations) {
        if (Test-Path $alt) {
            $oldDumpCs = $alt
            break
        }
    }
}

if (-not (Test-Path $oldDumpCs)) {
    Write-Warning "Old dump.cs not found. Tried:"
    Write-Warning "  $oldDumpCs"
    foreach ($alt in $altLocations) {
        Write-Warning "  $alt"
    }
    Write-Host ""
    Write-Host "You need the dump.cs from the previous game build."
    Write-Host "If you already ran Il2CppDumper on the old build, specify it with -OldDumpPath."
    Write-Host ""
    Write-Host "Continuing with manual review only (skip automatic renames)."
    Write-Host "This will still parse the new dump to show what types exist."
    $oldDumpCs = $null
}

# ─── Step 3: Generate rename map ─────────────────────────────────────────────

Write-Host "[Step 2/4] Generating rename map..." -ForegroundColor Yellow

$mapScript = Join-Path $scriptDir "map_obfuscation.py"
if (-not (Test-Path $mapScript)) {
    Write-Error "map_obfuscation.py not found at: $mapScript"
    exit 1
}

if ($oldDumpCs) {
    $mapArgs = @($mapScript, $oldDumpCs, $newDumpCs, "--output", $RenameMapOutput)
    if ($Verbose) { $mapArgs += "--verbose" }
    
    & python $mapArgs 2>&1 | ForEach-Object { Write-Host "  $_" }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "map_obfuscation.py failed"
        exit 1
    }
    
    Write-Host "  Rename map written to: $RenameMapOutput" -ForegroundColor Green
} else {
    Write-Host "  Skipping (no old dump.cs to compare)." -ForegroundColor Yellow
    Write-Host "  Creating a minimal rename map for manual filling..."
    
    # Create a template
    $template = @{
        type_renames = @{}
        method_renames = @{}
        field_renames = @{}
        manual_review = @()
        metadata = @{
            old_dump = "not_available"
            new_dump = (Resolve-Path $newDumpCs).Path
            note = "Fill in manually from new dump.cs"
        }
    }
    $template | ConvertTo-Json -Depth 5 | Set-Content $RenameMapOutput
    Write-Host "  Template written to: $RenameMapOutput"
}

# ─── Step 4: Apply renames ──────────────────────────────────────────────────

Write-Host "[Step 3/4] Previewing changes..." -ForegroundColor Yellow

$applyScript = Join-Path $scriptDir "apply_renames.py"
if (-not (Test-Path $applyScript)) {
    Write-Error "apply_renames.py not found at: $applyScript"
    exit 1
}

if (-not (Test-Path $ModSourceDir)) {
    Write-Warning "Mod source directory not found: $ModSourceDir"
    Write-Host "Specify the correct path with -ModSourceDir"
    exit 1
}

# Always do dry-run first
$dryArgs = @($applyScript, $RenameMapOutput, $ModSourceDir, "--dry-run")
if ($Verbose) { $dryArgs += "--verbose" }

Write-Host ""
Write-Host "  Dry run: checking what would change..."
& python $dryArgs 2>&1 | ForEach-Object { Write-Host "  $_" }

if ($Apply) {
    Write-Host ""
    Write-Host "[Step 4/4] Applying renames..." -ForegroundColor Yellow
    
    # Create backup first
    $applyArgs = @($applyScript, $RenameMapOutput, $ModSourceDir, "--backup")
    if ($Verbose) { $applyArgs += "--verbose" }
    
    & python $applyArgs 2>&1 | ForEach-Object { Write-Host "  $_" }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "apply_renames.py failed"
        exit 1
    }
    
    Write-Host "  Renames applied!" -ForegroundColor Green
    Write-Host "  Backup saved to: $ModSourceDir\_rename_backup"
} else {
    Write-Host ""
    Write-Host "[Step 4/4] Skipped — re-run with -Apply to write changes." -ForegroundColor Yellow
}

# ─── Step 5: Report manual review items ─────────────────────────────────────

if (Test-Path $RenameMapOutput) {
    $map = Get-Content $RenameMapOutput -Raw | ConvertFrom-Json
    $manual = $map.manual_review
    
    if ($manual -and $manual.Count -gt 0) {
        Write-Host ""
        Write-Host "==============================" -ForegroundColor Magenta
        Write-Host " MANUAL REVIEW NEEDED" -ForegroundColor Magenta
        Write-Host "==============================" -ForegroundColor Magenta
        Write-Host ""
        Write-Host "The following items couldn't be automatically remapped."
        Write-Host "Search the new dump.cs for these and update manually:"
        Write-Host ""
        foreach ($item in $manual) {
            Write-Host "  - $item" -ForegroundColor Yellow
        }
        Write-Host ""
        Write-Host "Search tips (in $newDumpCs):"
        Write-Host "  - For class members: search for the parent class, then scan its methods/fields"
        Write-Host "  - For obfuscated names: look for similar patterns or line counts"
    }

    # Show type renames summary
    $typeRenames = $map.type_renames
    if ($typeRenames -and $typeRenames.PSObject.Properties.Count -gt 0) {
        Write-Host ""
        Write-Host "Type renames:" -ForegroundColor Cyan
        foreach ($prop in $typeRenames.PSObject.Properties) {
            Write-Host "  $($prop.Name) -> $($prop.Value)"
        }
    }
}

# ─── Done ────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "==============================" -ForegroundColor Green
Write-Host " Pipeline complete!" -ForegroundColor Green
Write-Host "==============================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
if (-not $Apply) {
    Write-Host "  1. Review the dry-run output above"
    Write-Host "  2. Run again with -Apply to apply changes"
}
Write-Host "  3. Build with: dotnet build -c Release"
Write-Host "  4. Fix any remaining compile errors manually"
Write-Host "  5. Test in-game"
Write-Host ""
Write-Host "To regenerate BepInEx interop DLLs (if needed):"
Write-Host "  Use Il2CppInterop generator on the new GameAssembly.dll"
Write-Host ""