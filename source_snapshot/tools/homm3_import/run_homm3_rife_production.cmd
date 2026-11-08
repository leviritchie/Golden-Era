@echo off
setlocal EnableDelayedExpansion
REM Full HoMM3 RIFE @ 60 FPS dual-stream pipeline:
REM   Phase 1 - RIFE all manifest units (GPU, resumable; no per-unit Unity)
REM   Phase 2 - bulk mirror extracted_battle -> Unity Assets/homm3_lab
REM   Phase 3 - ONE Unity batch: Homm3BillboardAnimatorBuild.RebuildAllFromManifest
REM   Phase 4 - ONE Unity batch: BuildCustomUnitBundles.BuildFromManifest (all bundles)
REM
REM Env:
REM   SKIP_RIFE=1       skip phase 1 (frames already baked)
REM   SKIP_UNITY=1      RIFE + mirror only
REM   SKIP_STRIP_METAS=1  do not delete battle .meta (avoids ~130k texture reimport)
REM   SKIP_MIRROR=1     skip phase 2 mirror (resume after partial animator rebuild)
REM   SKIP_ANIM=1       skip phase 3 animator rebuild (bundle batches only)
REM   OLDENERA_UNITY_PROJECT  Unity project root
REM   HOMM3_UNIT_LIST   optional subset (passed to mirror/Unity)
REM   HOMM3_TARGET_FPS  battle RIFE FPS (default 60)
REM   HOMM3_RIFE_MODEL  rife-ncnn model (default rife-v4.6)
REM   HOMM3_RESET_FROM_SOURCE=1 restore extracted_battle_source_12fps before RIFE
REM   HOMM3_DUAL_STREAM_ALPHA=1 use separate alpha-mask RIFE pass
REM   HOMM3_BATTLE_TEXTURE_ARRAY=1 force Texture2DArray battle build
REM   GAME_ROOT         Steam game root for final OfflineUnlockMod deploy

set "SCRIPT_DIR=%~dp0"
set "OFFLINE_LAB=%SCRIPT_DIR%..\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\homm3_lab"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set "PROJECT_LEGACY=C:\Users\<user>\oldenera_factions"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set OUT=%SCRIPT_DIR%build_out
set MANIFEST=%SCRIPT_DIR%homm3_units_manifest.json
set "LOGS=%SCRIPT_DIR%rife_production_logs"
set "HOMM3_TEMP_ROOT=%~d0\homm3_tmp"
if not exist "%HOMM3_TEMP_ROOT%" mkdir "%HOMM3_TEMP_ROOT%"
set "TEMP=%HOMM3_TEMP_ROOT%"
set "TMP=%HOMM3_TEMP_ROOT%"
set "LOCALAPPDATA=%~d0\homm3_tmp\localappdata"
if not exist "%LOCALAPPDATA%" mkdir "%LOCALAPPDATA%"
if not defined GAME_ROOT set "GAME_ROOT=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
if not defined HOMM3_TARGET_FPS set HOMM3_TARGET_FPS=60
if not defined HOMM3_RIFE_MODEL set HOMM3_RIFE_MODEL=rife-v4.6
if not defined HOMM3_DUAL_STREAM_ALPHA set HOMM3_DUAL_STREAM_ALPHA=1
if not defined HOMM3_RESET_FROM_SOURCE set HOMM3_RESET_FROM_SOURCE=1
if not defined HOMM3_BATTLE_TEXTURE_ARRAY set HOMM3_BATTLE_TEXTURE_ARRAY=1
set UNIT_LIST_ARG=
set BUNDLE_LIST_ARG=
set "HOMM3_UNIT_LIST_UNITY=%TEMP%\homm3_rife_unit_list.txt"
set "HOMM3_BUNDLE_LIST_UNITY=%TEMP%\homm3_rife_bundle_list.txt"

if not exist "%LOGS%" mkdir "%LOGS%"

set "PROJECT="
if defined OLDENERA_UNITY_PROJECT (
  if exist "%OLDENERA_UNITY_PROJECT%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%OLDENERA_UNITY_PROJECT%"
)
if not defined PROJECT if exist "%PROJECT_LOCAL%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%PROJECT_LOCAL%"
if not defined PROJECT if exist "%PROJECT_LEGACY%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%PROJECT_LEGACY%"

if not "%SKIP_UNITY%"=="1" (
  if not defined PROJECT (
    echo No Unity project found. Set OLDENERA_UNITY_PROJECT or create oldenera_factions.
    exit /b 1
  )
  echo Using Unity project: %PROJECT%
)

REM Unity on Windows breaks \"%path with spaces\" into multiple argv tokens; pass %%TEMP%% path only.
if not defined HOMM3_UNIT_LIST (
  if exist "%LOGS%\manifest_eligible_no_temple_fangarm.txt" (
    set "HOMM3_UNIT_LIST=%LOGS%\manifest_eligible_no_temple_fangarm.txt"
  ) else if exist "%LOGS%\manifest_minus_temple_griffon.txt" (
    set "HOMM3_UNIT_LIST=%LOGS%\manifest_minus_temple_griffon.txt"
  )
)
if defined HOMM3_UNIT_LIST (
  py -3 -c "import shutil,sys; shutil.copy2(sys.argv[1], sys.argv[2])" "%HOMM3_UNIT_LIST%" "%HOMM3_UNIT_LIST_UNITY%"
  if errorlevel 1 (
    echo Failed to copy unit list to %HOMM3_UNIT_LIST_UNITY%
    exit /b 1
  )
  set "UNIT_LIST_ARG=-homm3UnitListPath %HOMM3_UNIT_LIST_UNITY%"
)

if defined HOMM3_BUNDLE_UNIT_LIST (
  py -3 -c "import shutil,sys; shutil.copy2(sys.argv[1], sys.argv[2])" "%HOMM3_BUNDLE_UNIT_LIST%" "%HOMM3_BUNDLE_LIST_UNITY%"
  if errorlevel 1 (
    echo Failed to copy bundle unit list to %HOMM3_BUNDLE_LIST_UNITY%
    exit /b 1
  )
  set "BUNDLE_LIST_ARG=-homm3UnitListPath %HOMM3_BUNDLE_LIST_UNITY%"
) else if defined HOMM3_UNIT_LIST (
  set "BUNDLE_LIST_ARG=%UNIT_LIST_ARG%"
)

if not "%SKIP_RIFE%"=="1" (
  echo === Phase 1: RIFE %HOMM3_RIFE_MODEL% @ %HOMM3_TARGET_FPS% FPS ^(manifest units, reset/resumable^) ===
  set PYTHONUNBUFFERED=1
  set RIFE_ARGS=--target-fps %HOMM3_TARGET_FPS% --rife-model %HOMM3_RIFE_MODEL%
  if "%HOMM3_DUAL_STREAM_ALPHA%"=="1" set RIFE_ARGS=!RIFE_ARGS! --dual-stream-alpha
  if "%HOMM3_RESET_FROM_SOURCE%"=="1" set RIFE_ARGS=!RIFE_ARGS! --force --reset-from-source-backup
  if defined HOMM3_UNIT_LIST (
    py -3 "%SCRIPT_DIR%interpolate_homm3_battle_sequences.py" ^
      --lab-root "%OFFLINE_LAB%" ^
      --unit-list "%HOMM3_UNIT_LIST%" ^
      !RIFE_ARGS! ^
      --log-file "%LOGS%\rife_interpolate.log"
  ) else (
    py -3 "%SCRIPT_DIR%interpolate_homm3_battle_sequences.py" ^
      --lab-root "%OFFLINE_LAB%" ^
      --manifest-only ^
      !RIFE_ARGS! ^
      --log-file "%LOGS%\rife_interpolate.log"
  )
  if errorlevel 1 (
    echo RIFE phase failed - see %LOGS%\rife_interpolate.log
    exit /b 1
  )
) else (
  echo === Phase 1: SKIP_RIFE=1 ===
)

if "%SKIP_UNITY%"=="1" (
  echo === Phases 2-4 skipped ^(SKIP_UNITY=1^) ===
  exit /b 0
)

echo === Phase 2: bulk mirror battle frames to Unity lab ===
if not "%SKIP_STRIP_METAS%"=="1" (
  py -3 "%SCRIPT_DIR%strip_unity_battle_metas.py" --unity-project "%PROJECT%"
) else (
  echo === Phase 2a: SKIP_STRIP_METAS=1 ^(keeping existing TextureImporter .meta^) ===
)
if not "%SKIP_MIRROR%"=="1" (
  if defined HOMM3_UNIT_LIST (
    py -3 "%SCRIPT_DIR%mirror_homm3_lab_battle_to_unity.py" --unity-project "%PROJECT%" --manifest "%MANIFEST%" --workers 8 --unit-list "%HOMM3_UNIT_LIST%"
  ) else (
    py -3 "%SCRIPT_DIR%mirror_homm3_lab_battle_to_unity.py" --unity-project "%PROJECT%" --manifest "%MANIFEST%" --workers 8
  )
  if errorlevel 1 exit /b 1
) else (
  echo === Phase 2b: SKIP_MIRROR=1 ===
)

if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
if not exist "%PROJECT%\Assets\CustomUnits\Homm3Import" mkdir "%PROJECT%\Assets\CustomUnits\Homm3Import"
xcopy /Y /Q "%SCRIPT_DIR%unity_runtime\*.cs" "%PROJECT%\Assets\CustomUnits\Homm3Import\" >nul
if not exist "%PROJECT%\Assets\Shaders" mkdir "%PROJECT%\Assets\Shaders"
xcopy /Y /Q "%SCRIPT_DIR%unity_shaders\Homm3BillboardArray.shader" "%PROJECT%\Assets\Shaders\" >nul
xcopy /Y /Q "%SCRIPT_DIR%unity_editor\*.cs" "%PROJECT%\Assets\Editor\" >nul
xcopy /Y /Q "%SCRIPT_DIR%..\custom_prefab_pipeline\unity_editor\BuildCustomUnitBundles.cs" "%PROJECT%\Assets\Editor\" >nul

if "%SKIP_ANIM%"=="1" (
  echo === Phase 3 skipped ^(SKIP_ANIM=1^) ===
) else (
  echo === Phase 3: Unity animator rebuild ^(all units, one editor launch^) ===
  "%UNITY%" -batchmode -quit -nographics ^
    -projectPath "%PROJECT%" ^
    -executeMethod OldenEra.Homm3Import.Homm3BillboardAnimatorBuild.RebuildAllFromManifest ^
    -manifestPath "%MANIFEST%" ^
    -homm3BattleTexture2DArray "%HOMM3_BATTLE_TEXTURE_ARRAY%" ^
    %UNIT_LIST_ARG% ^
    -logFile "%LOGS%\unity_anim_rebuild_all.log"
  if errorlevel 1 (
    echo Animator rebuild failed - see %LOGS%\unity_anim_rebuild_all.log
    exit /b 1
  )
  py -3 "%SCRIPT_DIR%sync_homm3_array_manifests_from_unity.py" --unity-project "%PROJECT%" --target-lab "%OFFLINE_LAB%"
  if errorlevel 1 (
    echo Failed to sync HoMM3 array manifests from Unity project
    exit /b 1
  )
)

:phase4
if "%SKIP_BUNDLE%"=="1" (
  echo === Phase 4 skipped ^(SKIP_BUNDLE=1^) ===
  if "%SKIP_DOTNET%"=="1" (
    echo === Phase 5 skipped ^(SKIP_DOTNET=1^) ===
    exit /b 0
  )
  goto phase5
)

if defined HOMM3_BUNDLE_BATCHES (
  if not "%HOMM3_BUNDLE_BATCHES%"=="1" (
    echo === Phase 4: batched bundles via run_homm3_array_timing_bundle_batches.cmd ^(%HOMM3_BUNDLE_BATCHES% batches^) ===
    call "%SCRIPT_DIR%run_homm3_array_timing_bundle_batches.cmd"
    if errorlevel 1 exit /b 1
    if "%SKIP_DOTNET%"=="1" exit /b 0
    goto phase5
  )
)

echo === Phase 4: Unity AssetBundles ^(all manifest bundles, one launch^) ===
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest ^
  -manifestPath "%MANIFEST%" ^
  %BUNDLE_LIST_ARG% ^
  -outputPath "%OUT%" ^
  -logFile "%LOGS%\unity_bundle_build_all.log"
if errorlevel 1 (
  echo Bundle build failed - see %LOGS%\unity_bundle_build_all.log
  exit /b 1
)

:phase5
echo === Phase 5: Build/deploy OfflineUnlockMod ===
dotnet build "%SCRIPT_DIR%..\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release "-p:GameRoot=%GAME_ROOT%" -clp:ErrorsOnly
if errorlevel 1 (
  echo OfflineUnlockMod build/deploy failed
  exit /b 1
)

echo OK - RIFE production complete and deployed via OfflineUnlockMod.csproj.
exit /b 0
