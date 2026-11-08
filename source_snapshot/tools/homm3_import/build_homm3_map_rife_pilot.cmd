@echo off
setlocal EnableDelayedExpansion
REM Map RIFE pilot: unit-list driven.
REM 10 native map keys -> 50 FPS dual-stream RIFE, Unity map Texture2DArray (mapTexture2DArray=1) + bundles.

set "SCRIPT_DIR=%~dp0"
set "OFFLINE=%SCRIPT_DIR%..\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set OUT=%SCRIPT_DIR%build_out
set MANIFEST=%SCRIPT_DIR%homm3_units_manifest.json
if not defined UNIT_LIST set "UNIT_LIST=%SCRIPT_DIR%map_rife_pilot_units.txt"
set LOGS=%SCRIPT_DIR%rife_production_logs
if not exist "%LOGS%" mkdir "%LOGS%"
if not defined HOMM3_MAP_TARGET_FPS set HOMM3_MAP_TARGET_FPS=50
if not defined HOMM3_MAP_SOURCE_FPS set HOMM3_MAP_SOURCE_FPS=10
if not defined HOMM3_RIFE_MODEL set HOMM3_RIFE_MODEL=rife-v4.6
if not defined GAME_ROOT set "GAME_ROOT=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
if not defined HOMM3_TMP_ROOT set HOMM3_TMP_ROOT=V:\homm3_tmp
if not exist "%HOMM3_TMP_ROOT%" mkdir "%HOMM3_TMP_ROOT%"
set "TMP=%HOMM3_TMP_ROOT%"
set "TEMP=%HOMM3_TMP_ROOT%"

set "PROJECT="
if defined OLDENERA_UNITY_PROJECT (
  if exist "%OLDENERA_UNITY_PROJECT%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%OLDENERA_UNITY_PROJECT%"
)
if not defined PROJECT if exist "%PROJECT_LOCAL%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%PROJECT_LOCAL%"
if not defined PROJECT (
  echo No Unity project. Set OLDENERA_UNITY_PROJECT.
  exit /b 1
)
echo Unity project: %PROJECT%

echo.
echo === Map RIFE @ %HOMM3_MAP_TARGET_FPS% FPS (from 10fps backup; no Unity pull) ===
set PYTHONUNBUFFERED=1
REM Do not sync FROM Unity first: a prior rebake may have left 150+ dense keys there and
REM double-RIFE makes 750-frame / 15s cycles. Always restore extracted_map_source_10fps/.
py -3 "%SCRIPT_DIR%interpolate_homm3_map_sequences.py" ^
  --lab-root "%OFFLINE%\homm3_lab" ^
  --unit-list "%UNIT_LIST%" ^
  --target-fps %HOMM3_MAP_TARGET_FPS% ^
  --source-fps %HOMM3_MAP_SOURCE_FPS% ^
  --rife-model %HOMM3_RIFE_MODEL% ^
  --reset-from-source-backup ^
  --reuse-cache
if errorlevel 1 exit /b 1

echo.
echo === Mirror map frames + authoring to Unity ===
py -3 "%SCRIPT_DIR%mirror_homm3_lab_battle_to_unity.py" ^
  --unity-project "%PROJECT%" ^
  --unit-list "%UNIT_LIST%" ^
  --map-only ^
  --workers 2
if errorlevel 1 exit /b 1

if not exist "%PROJECT%\Assets\Shaders" mkdir "%PROJECT%\Assets\Shaders"
copy /Y "%SCRIPT_DIR%unity_shaders\Homm3BillboardArray.shader" "%PROJECT%\Assets\Shaders\Homm3BillboardArray.shader" >nul
if not exist "%PROJECT%\Assets\CustomUnits\Homm3Import" mkdir "%PROJECT%\Assets\CustomUnits\Homm3Import"
xcopy /Y /Q "%SCRIPT_DIR%unity_runtime\*.cs" "%PROJECT%\Assets\CustomUnits\Homm3Import\" >nul
if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
xcopy /Y /Q "%SCRIPT_DIR%unity_editor\*.cs" "%PROJECT%\Assets\Editor\" >nul
xcopy /Y /Q "%SCRIPT_DIR%..\custom_prefab_pipeline\unity_editor\BuildCustomUnitBundles.cs" "%PROJECT%\Assets\Editor\" >nul

echo.
echo === Unity rebuild map billboards (pilot units) ===
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.Homm3Import.Homm3BillboardAnimatorBuild.RebuildAllFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%UNIT_LIST%" ^
  -logFile "%LOGS%\unity_map_rife_pilot_anim.log"
if errorlevel 1 exit /b 1

echo.
echo === AssetBundles: map RIFE pilot unit list ===
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%UNIT_LIST%" ^
  -outputPath "%OUT%" ^
  -logFile "%LOGS%\unity_map_rife_pilot_bundle.log"
if errorlevel 1 exit /b 1

echo.
echo === Deploy to Steam plugin ===
dotnet build "%OFFLINE%\OfflineUnlockMod.csproj" -c Release "-p:GameRoot=%GAME_ROOT%" -clp:ErrorsOnly
if errorlevel 1 exit /b 1

echo.
echo OK — map RIFE pilot deployed:
echo   Unit list: %UNIT_LIST%
echo   Bundles: %OUT%
echo   Plugin: %GAME_ROOT%\BepInEx\plugins\OfflineUnlockMod\homm3_bundles\
exit /b 0
