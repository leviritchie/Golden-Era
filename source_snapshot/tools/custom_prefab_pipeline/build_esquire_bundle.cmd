@echo off
setlocal
REM Rebuild custom_units_esquire. Close the Unity Editor for the chosen project first.
REM
REM Unity project resolution (first match wins):
REM   1) OLDENERA_UNITY_PROJECT environment variable (full path to project root containing ProjectSettings)
REM   2) Repo-local:  ..\..\oldenera_factions  (i.e. Olden Era Playtest Tweak\oldenera_factions)
REM   3) Legacy:       C:\Users\<user>\oldenera_factions
REM Move or junction-link your Unity project into (2) once; then builds use the repo drive only.
REM This script xcopys tools\custom_prefab_pipeline\unity_editor\*.cs into the project's Assets\Editor before batch builds.
REM Output custom_units_esquire: build_out\ next to this script. Game: BepInEx\plugins\OfflineUnlockMod\
REM
set "SCRIPT_DIR=%~dp0"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set "PROJECT_LEGACY=C:\Users\<user>\oldenera_factions"

REM Unity Hub editor (must match ProjectSettings/ProjectVersion.txt in oldenera_factions — currently 6000.0.66f2):
REM   %ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
REM Git Bash equivalent: tools/custom_prefab_pipeline/build_esquire_bundle.sh (same steps).
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set MANIFEST=%~dp0custom_units_manifest.json
set OUT=%~dp0build_out
set LOG=%~dp0unity_esquire_bundle_build.log
set SOUNDLOG=%~dp0unity_esquire_sound_prefabs.log

if not exist "%UNITY%" (
  echo Edit UNITY= in this script if your 6000.0.66f2 editor lives elsewhere.
  exit /b 1
)

set "PROJECT="
if defined OLDENERA_UNITY_PROJECT (
  if exist "%OLDENERA_UNITY_PROJECT%\ProjectSettings\ProjectVersion.txt" (
    set "PROJECT=%OLDENERA_UNITY_PROJECT%"
  ) else (
    echo ERROR: OLDENERA_UNITY_PROJECT is set but ProjectSettings\ProjectVersion.txt was not found:
    echo   %OLDENERA_UNITY_PROJECT%
    exit /b 1
  )
)
if not defined PROJECT (
  if exist "%PROJECT_LOCAL%\ProjectSettings\ProjectVersion.txt" (
    set "PROJECT=%PROJECT_LOCAL%"
  )
)
if not defined PROJECT (
  if exist "%PROJECT_LEGACY%\ProjectSettings\ProjectVersion.txt" (
    set "PROJECT=%PROJECT_LEGACY%"
  )
)
if not defined PROJECT (
  echo ERROR: No Unity project found for Esquire bundle build.
  echo   Option A: Move or mklink /J your project to:
  echo     %PROJECT_LOCAL%
  echo   Option B: set OLDENERA_UNITY_PROJECT=^<path to Unity project root^>
  echo   Option C: Restore project at %PROJECT_LEGACY%
  exit /b 1
)
echo Using Unity project: %PROJECT%

set "STAGE_SND="
if defined HOMM3_SND set "STAGE_SND=%HOMM3_SND%"
if not defined STAGE_SND if exist "%SCRIPT_DIR%..\..\HoMM 3 Complete\Data\Heroes3.snd" (
  set "STAGE_SND=%SCRIPT_DIR%..\..\HoMM 3 Complete\Data\Heroes3.snd"
)
if defined STAGE_SND (
  echo Step 0/4: Stage Esquire battle WAVs from HoMM3 SND...
  py -3 "%~dp0stage_esquire_homm3_audio.py" --unity-project "%PROJECT%" --snd "%STAGE_SND%"
  if errorlevel 1 (
    echo HoMM3 audio staging failed — set HOMM3_SND to Heroes3.snd or install HoMM3 Complete next to the repo.
    exit /b 1
  )
) else (
  echo Step 0/4: Skip HoMM3 audio staging ^(no Heroes3.snd — optional HOMM3_SND^).
)

if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
xcopy /Y /Q "%~dp0unity_editor\*.cs" "%PROJECT%\Assets\Editor\" >nul

set ANIMLOG=%~dp0unity_esquire_anim_build.log

echo Step 1/4: Generate Esquire battle sound prefabs (one prefab per ESQUIRE_*.wav/.ogg)...
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.CustomUnitBuilder.EsquireBattleSoundPrefabsBuild.RebuildFromBatch ^
  -logFile "%SOUNDLOG%"
if errorlevel 1 (
  echo Sound prefab build failed — see %SOUNDLOG%
  exit /b 1
)

echo Step 2/4: Rebuild battle flip-book + map mesh billboard (battle.prefab + map.prefab^)...
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.CustomUnitBuilder.EsquireBillboardAnimatorBuild.RebuildFromBatch ^
  -logFile "%ANIMLOG%"
if errorlevel 1 (
  echo Animator build failed — see %ANIMLOG%
  exit /b 1
)

echo Step 3/4: Build AssetBundles...
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -outputPath "%OUT%" ^
  -logFile "%LOG%"
if errorlevel 1 (
  echo AssetBundle build failed — see %LOG%
  exit /b 1
)

echo Sound prefab log: %SOUNDLOG%
echo Animator log: %ANIMLOG%
echo Bundle log: %LOG%
echo Next: copy build_out\custom_units_esquire to BepInEx\plugins\OfflineUnlockMod\ or build OfflineUnlockMod ^(csproj copies on build^).
