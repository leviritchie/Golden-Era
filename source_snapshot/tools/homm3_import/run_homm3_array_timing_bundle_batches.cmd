@echo off
setlocal EnableDelayedExpansion
REM Phase 4 only: build AssetBundles in 3 batches (~70 units each) for ~32GB RAM.
REM Run after run_homm3_array_timing_rebundle_all.cmd finishes Phase 3 + manifest sync.
REM
REM   set HOMM3_BUNDLE_BATCHES=3   (default 3)
REM   set SKIP_DOTNET=1            bundle build only, no Steam deploy
REM   GAME_ROOT                    Steam root for final dotnet deploy (once, after all batches)

set "SCRIPT_DIR=%~dp0"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set OUT=%SCRIPT_DIR%build_out
set MANIFEST=%SCRIPT_DIR%homm3_units_manifest.json
set "LOGS=%SCRIPT_DIR%rife_production_logs"
if not defined HOMM3_BUNDLE_BATCHES set HOMM3_BUNDLE_BATCHES=3
if not defined GAME_ROOT set "GAME_ROOT=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"

set "PROJECT="
if defined OLDENERA_UNITY_PROJECT (
  if exist "%OLDENERA_UNITY_PROJECT%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%OLDENERA_UNITY_PROJECT%"
)
if not defined PROJECT if exist "%PROJECT_LOCAL%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%PROJECT_LOCAL%"
if not defined PROJECT (
  echo No Unity project found.
  exit /b 1
)
echo Using Unity project: %PROJECT%

echo Regenerating %HOMM3_BUNDLE_BATCHES% batch unit lists...
py -3 "%SCRIPT_DIR%split_homm3_unit_list_batches.py" --batches %HOMM3_BUNDLE_BATCHES%
if errorlevel 1 exit /b 1

if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
xcopy /Y /Q "%SCRIPT_DIR%..\custom_prefab_pipeline\unity_editor\BuildCustomUnitBundles.cs" "%PROJECT%\Assets\Editor\" >nul

for /L %%I in (1,1,%HOMM3_BUNDLE_BATCHES%) do (
  set "BATCH_LIST=%LOGS%\manifest_bundle_batch%%I.txt"
  if not exist "!BATCH_LIST!" (
    echo Missing !BATCH_LIST!
    exit /b 1
  )
  echo.
  echo === AssetBundles batch %%I / %HOMM3_BUNDLE_BATCHES% ===
  set "HOMM3_BUNDLE_LIST_UNITY=%TEMP%\homm3_bundle_batch%%I.txt"
  copy /Y "!BATCH_LIST!" "!HOMM3_BUNDLE_LIST_UNITY!" >nul
  "%UNITY%" -batchmode -quit -nographics ^
    -projectPath "%PROJECT%" ^
    -executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest ^
    -manifestPath "%MANIFEST%" ^
    -homm3UnitListPath "!HOMM3_BUNDLE_LIST_UNITY!" ^
    -outputPath "%OUT%" ^
    -logFile "%LOGS%\unity_bundle_build_batch%%I.log"
  if errorlevel 1 (
    echo Batch %%I failed — see %LOGS%\unity_bundle_build_batch%%I.log
    exit /b 1
  )
)

if "%SKIP_DOTNET%"=="1" (
  echo Bundle batches OK. Generated bundles remain in build_out until an explicit validated DeployHomm3Bundles=true build.
  exit /b 0
)

echo.
echo === dotnet build / deploy plugin assets (generated bundles remain opt-in) ===
dotnet build "%SCRIPT_DIR%..\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release "-p:GameRoot=%GAME_ROOT%" -clp:ErrorsOnly
if errorlevel 1 exit /b 1
echo OK - %HOMM3_BUNDLE_BATCHES% bundle batches built; ordinary deploy completed without build_out bundle copying.
exit /b 0
