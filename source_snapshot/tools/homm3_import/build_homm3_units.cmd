@echo off
setlocal EnableDelayedExpansion
REM Lane B: HoMM3 lab bundles only. Does NOT run esquire sound step or edit custom_units_manifest.json.
REM Prereq: Unity 6000.0.66f2, oldenera_factions project, authoring.json + prefabs/materials/Reference under homm3_lab/<unit>.
REM By default this extracts DEF frames before rebuilding. Set SKIP_EXTRACT=1 to use cached extracted_battle frames.
REM Battle clips use RIFE @ HOMM3_TARGET_FPS (default 60) unless SKIP_RIFE=1 (requires setup_vfi_env.sh).

set "SCRIPT_DIR=%~dp0"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set "PROJECT_LEGACY=C:\Users\<user>\oldenera_factions"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set OUT=%~dp0build_out
set LOGB=%~dp0unity_homm3_bundle_build.log
set LOGA=%~dp0unity_homm3_anim_build.log
set MANIFEST=%~dp0homm3_units_manifest.json
if not defined HOMM3_TARGET_FPS set HOMM3_TARGET_FPS=60
if not defined HOMM3_RIFE_MODEL set HOMM3_RIFE_MODEL=rife-v4.6
if not defined HOMM3_DUAL_STREAM_ALPHA set HOMM3_DUAL_STREAM_ALPHA=1
if not defined HOMM3_BATTLE_TEXTURE_ARRAY set HOMM3_BATTLE_TEXTURE_ARRAY=1

if "%~1"=="" (
  echo Usage: build_homm3_units.cmd ^<homm3UnitSid^>
  echo   Extraction runs by default. Set SKIP_EXTRACT=1 to reuse cached extracted_battle frames.
  exit /b 1
)
set "H3SID=%~1"
if not exist "%OUT%" mkdir "%OUT%"
set "HOMM3_SINGLE_UNIT_LIST=%OUT%\homm3_bundle_unit_%H3SID%.txt"
> "%HOMM3_SINGLE_UNIT_LIST%" echo %H3SID%

if not exist "%UNITY%" (
  echo Edit UNITY= in this script if your editor path differs.
  exit /b 1
)

set "PROJECT="
if defined OLDENERA_UNITY_PROJECT (
  if exist "%OLDENERA_UNITY_PROJECT%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%OLDENERA_UNITY_PROJECT%"
)
if not defined PROJECT if exist "%PROJECT_LOCAL%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%PROJECT_LOCAL%"
if not defined PROJECT if exist "%PROJECT_LEGACY%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%PROJECT_LEGACY%"
if not defined PROJECT (
  echo No Unity project found. Set OLDENERA_UNITY_PROJECT or create %PROJECT_LOCAL%
  exit /b 1
)
echo Using Unity project: %PROJECT%

if "%SKIP_EXTRACT%"=="1" (
  set HOM3_EXTRACT=0
) else if not "%HOM3_EXTRACT%"=="0" (
  set HOM3_EXTRACT=1
)

if "%HOM3_EXTRACT%"=="1" (
  echo Extract step: py -3 "%SCRIPT_DIR%extract_creature.py" --unit "%H3SID%" --unity-project "%PROJECT%"
  py -3 "%SCRIPT_DIR%extract_creature.py" --unit "%H3SID%" --unity-project "%PROJECT%"
  if errorlevel 1 exit /b 1
)

set "UNITY_LAB=%PROJECT%\Assets\CustomUnits\homm3_lab"
if not "%SKIP_RIFE%"=="1" (
  echo RIFE %HOMM3_RIFE_MODEL% battle interpolation @ %HOMM3_TARGET_FPS% FPS: interpolate_homm3_battle_sequences.py
  set RIFE_ARGS=--target-fps %HOMM3_TARGET_FPS% --rife-model %HOMM3_RIFE_MODEL%
  if "%HOMM3_DUAL_STREAM_ALPHA%"=="1" set RIFE_ARGS=!RIFE_ARGS! --dual-stream-alpha
  py -3 "%SCRIPT_DIR%interpolate_homm3_battle_sequences.py" --lab-root "%UNITY_LAB%" --unity-project "%PROJECT%" --units "%H3SID%" !RIFE_ARGS!
  if errorlevel 1 exit /b 1
)

if not exist "%PROJECT%\Assets\CustomUnits\Homm3Import" mkdir "%PROJECT%\Assets\CustomUnits\Homm3Import"
xcopy /Y /Q "%SCRIPT_DIR%unity_runtime\*.cs" "%PROJECT%\Assets\CustomUnits\Homm3Import\" >nul
if not exist "%PROJECT%\Assets\Shaders" mkdir "%PROJECT%\Assets\Shaders"
xcopy /Y /Q "%SCRIPT_DIR%unity_shaders\Homm3BillboardArray.shader" "%PROJECT%\Assets\Shaders\" >nul
if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
xcopy /Y /Q "%SCRIPT_DIR%unity_editor\*.cs" "%PROJECT%\Assets\Editor\" >nul
xcopy /Y /Q "%SCRIPT_DIR%..\custom_prefab_pipeline\unity_editor\BuildCustomUnitBundles.cs" "%PROJECT%\Assets\Editor\" >nul

echo HoMM3 SND staging (optional; needs Heroes3.snd + sndBattlePrefix in units_inventory.json)
py -3 "%SCRIPT_DIR%stage_homm3_unit_audio.py" --unity-project "%PROJECT%" --unit "%H3SID%"
if errorlevel 1 exit /b 1

echo Sound prefabs: Homm3BattleSoundPrefabsBuild -homm3UnitSid %H3SID%
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -homm3UnitSid "%H3SID%" ^
  -executeMethod OldenEra.Homm3Import.Homm3BattleSoundPrefabsBuild.RebuildFromBatch ^
  -logFile "%~dp0unity_homm3_sound_prefab_build.log"
if errorlevel 1 (
  echo Homm3BattleSoundPrefabsBuild failed — see %~dp0unity_homm3_sound_prefab_build.log
  exit /b 1
)

echo Animator rebuild: Homm3BillboardAnimatorBuild -homm3UnitSid %H3SID%
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -homm3UnitSid "%H3SID%" ^
  -homm3BattleTexture2DArray "%HOMM3_BATTLE_TEXTURE_ARRAY%" ^
  -executeMethod OldenEra.Homm3Import.Homm3BillboardAnimatorBuild.RebuildFromBatch ^
  -logFile "%LOGA%"
if errorlevel 1 (
  echo Animator failed — see %LOGA%
  exit /b 1
)

echo AssetBundles: BuildCustomUnitBundles
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%HOMM3_SINGLE_UNIT_LIST%" ^
  -outputPath "%OUT%" ^
  -logFile "%LOGB%"
if errorlevel 1 (
  echo Bundle build failed — see %LOGB%
  exit /b 1
)

echo OK — output under %OUT%
echo Copy bundles to BepInEx\plugins\OfflineUnlockMod\homm3_bundles\ (see README).
exit /b 0
