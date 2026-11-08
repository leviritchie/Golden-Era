@echo off
setlocal EnableDelayedExpansion
REM Builds placeholder Unity bundles for the shared HoMM3 import lane:
REM Tower ToA alternates plus Castle, Rampart, Inferno, Necropolis, Dungeon, Fortress, Conflux, and Cove.
REM This only touches lane-B source metadata, the selected Unity project, and tools/homm3_import/build_out.

set "SCRIPT_DIR=%~dp0"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set OUT=%SCRIPT_DIR%build_out
set MANIFEST=%SCRIPT_DIR%homm3_units_manifest.json
set UNIT_LIST=%SCRIPT_DIR%remaining_faction_unit_sids.txt
set "LOGS=%SCRIPT_DIR%remaining_faction_logs"
if defined HOMM3_UNIT_LIST set "UNIT_LIST=%HOMM3_UNIT_LIST%"

if not exist "%UNITY%" (
  echo Edit UNITY= in this script if your editor path differs.
  exit /b 1
)

set "PROJECT="
if defined OLDENERA_UNITY_PROJECT (
  if exist "%OLDENERA_UNITY_PROJECT%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%OLDENERA_UNITY_PROJECT%"
)
if not defined PROJECT if exist "%PROJECT_LOCAL%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%PROJECT_LOCAL%"
if not defined PROJECT (
  echo No Unity project found. Set OLDENERA_UNITY_PROJECT.
  exit /b 1
)
echo Using Unity project: %PROJECT%

if not exist "%LOGS%" mkdir "%LOGS%"

if "%SKIP_EXTRACT%"=="1" (
  py -3 "%SCRIPT_DIR%prepare_remaining_faction_bundles.py"
  if errorlevel 1 exit /b 1
) else (
  py -3 "%SCRIPT_DIR%prepare_remaining_faction_bundles.py" --unity-project "%PROJECT%" --extract-bootstrap
  if errorlevel 1 exit /b 1
)

if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
xcopy /Y /Q "%SCRIPT_DIR%unity_editor\*.cs" "%PROJECT%\Assets\Editor\" >nul
xcopy /Y /Q "%SCRIPT_DIR%..\custom_prefab_pipeline\unity_editor\BuildCustomUnitBundles.cs" "%PROJECT%\Assets\Editor\" >nul

echo Sound stage: stage_homm3_unit_audio.py for listed units
for /F "usebackq tokens=*" %%S in ("%UNIT_LIST%") do (
  set "H3SID=%%S"
  if not "!H3SID!"=="" if not "!H3SID:~0,1!"=="#" (
    py -3 "%SCRIPT_DIR%stage_homm3_unit_audio.py" --unity-project "%PROJECT%" --unit "!H3SID!"
    if errorlevel 1 exit /b 1
  )
)

echo Sound prefabs: Homm3BattleSoundPrefabsBuild.RebuildAllFromManifest
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.Homm3Import.Homm3BattleSoundPrefabsBuild.RebuildAllFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%UNIT_LIST%" ^
  -logFile "%LOGS%\unity_homm3_remaining_sound_prefab_build.log"
if errorlevel 1 (
  echo Sound prefab build failed - see %LOGS%\unity_homm3_remaining_sound_prefab_build.log
  exit /b 1
)

echo Animator rebuild: Homm3BillboardAnimatorBuild.RebuildAllFromManifest
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.Homm3Import.Homm3BillboardAnimatorBuild.RebuildAllFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%UNIT_LIST%" ^
  -logFile "%LOGS%\unity_homm3_remaining_anim_build.log"
if errorlevel 1 (
  echo Animator build failed - see %LOGS%\unity_homm3_remaining_anim_build.log
  exit /b 1
)

echo AssetBundles: BuildCustomUnitBundles
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%UNIT_LIST%" ^
  -outputPath "%OUT%" ^
  -logFile "%LOGS%\unity_homm3_remaining_bundle_build.log"
if errorlevel 1 (
  echo Bundle build failed - see %LOGS%\unity_homm3_remaining_bundle_build.log
  exit /b 1
)

echo OK - bundles under %OUT%
exit /b 0
