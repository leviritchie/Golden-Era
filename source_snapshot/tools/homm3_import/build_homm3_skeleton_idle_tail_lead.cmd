@echo off
setlocal EnableDelayedExpansion
REM Re-bake h3_skeleton attack (group 12) with idle-tail-lead + production dual-stream RIFE,
REM then Unity animator + single bundle. Does not rebuild other units.
REM
REM Prereq: extracted_battle_source_12fps/ backup exists for h3_skeleton.

set "SCRIPT_DIR=%~dp0"
set "OFFLINE=%SCRIPT_DIR%..\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set OUT=%SCRIPT_DIR%build_out
set MANIFEST=%SCRIPT_DIR%homm3_units_manifest.json
set UNIT_LIST=%SCRIPT_DIR%rife_production_logs\manifest_h3_skeleton_only.txt
set LOGS=%SCRIPT_DIR%rife_production_logs
if not defined HOMM3_TARGET_FPS set HOMM3_TARGET_FPS=60
if not defined HOMM3_RIFE_MODEL set HOMM3_RIFE_MODEL=rife-v4.6
if not defined HOMM3_DUAL_STREAM_ALPHA set HOMM3_DUAL_STREAM_ALPHA=1
if not defined HOMM3_BATTLE_TEXTURE_ARRAY set HOMM3_BATTLE_TEXTURE_ARRAY=1
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
  echo No Unity project. Set OLDENERA_UNITY_PROJECT or create %PROJECT_LOCAL%
  exit /b 1
)
echo Unity project: %PROJECT%

echo.
echo === RIFE: h3_skeleton group 12 attack (idle-tail-lead) ===
set PYTHONUNBUFFERED=1
py -3 "%SCRIPT_DIR%interpolate_homm3_battle_sequences.py" ^
  --lab-root "%OFFLINE%\homm3_lab" ^
  --units h3_skeleton ^
  --groups 12 ^
  --target-fps %HOMM3_TARGET_FPS% ^
  --rife-model %HOMM3_RIFE_MODEL% ^
  --dual-stream-alpha ^
  --force ^
  --allow-reinterpolate-dense
if errorlevel 1 exit /b 1

echo.
echo === Mirror h3_skeleton battle frames to Unity ===
py -3 "%SCRIPT_DIR%mirror_homm3_lab_battle_to_unity.py" --unity-project "%PROJECT%" --manifest "%MANIFEST%" --workers 4 --unit-list "%UNIT_LIST%"
if errorlevel 1 exit /b 1

if not exist "%PROJECT%\Assets\Shaders" mkdir "%PROJECT%\Assets\Shaders"
copy /Y "%SCRIPT_DIR%unity_shaders\Homm3BillboardArray.shader" "%PROJECT%\Assets\Shaders\Homm3BillboardArray.shader" >nul
if not exist "%PROJECT%\Assets\CustomUnits\Homm3Import" mkdir "%PROJECT%\Assets\CustomUnits\Homm3Import"
xcopy /Y /Q "%SCRIPT_DIR%unity_runtime\*.cs" "%PROJECT%\Assets\CustomUnits\Homm3Import\" >nul
if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
xcopy /Y /Q "%SCRIPT_DIR%unity_editor\*.cs" "%PROJECT%\Assets\Editor\" >nul
xcopy /Y /Q "%SCRIPT_DIR%..\custom_prefab_pipeline\unity_editor\BuildCustomUnitBundles.cs" "%PROJECT%\Assets\Editor\" >nul

echo.
echo === Unity animator rebuild: h3_skeleton only ===
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.Homm3Import.Homm3BillboardAnimatorBuild.RebuildAllFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%UNIT_LIST%" ^
  -homm3BattleTexture2DArray "%HOMM3_BATTLE_TEXTURE_ARRAY%" ^
  -logFile "%LOGS%\unity_skeleton_idle_tail_lead_anim.log"
if errorlevel 1 exit /b 1

py -3 "%SCRIPT_DIR%sync_homm3_array_manifests_from_unity.py" --unity-project "%PROJECT%" --target-lab "%OFFLINE%\homm3_lab"
if errorlevel 1 exit /b 1

echo.
echo === AssetBundle: custom_units_necropolis_h3_skeleton only ===
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%UNIT_LIST%" ^
  -outputPath "%OUT%" ^
  -logFile "%LOGS%\unity_skeleton_idle_tail_lead_bundle.log"
if errorlevel 1 exit /b 1

echo.
echo === Deploy OfflineUnlockMod (copies build_out bundle via csproj) ===
dotnet build "%OFFLINE%\OfflineUnlockMod.csproj" -c Release "-p:GameRoot=%GAME_ROOT%" -clp:ErrorsOnly
if errorlevel 1 exit /b 1

echo.
echo OK — h3_skeleton idle-tail-lead attack deployed:
echo   Lab: "%OFFLINE%\homm3_lab\h3_skeleton\extracted_battle"
echo   Bundle: %OUT%\custom_units_necropolis_h3_skeleton
echo   Plugin: %GAME_ROOT%\BepInEx\plugins\OfflineUnlockMod\homm3_bundles\custom_units_necropolis_h3_skeleton
exit /b 0
