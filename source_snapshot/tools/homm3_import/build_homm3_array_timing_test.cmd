@echo off
setlocal EnableDelayedExpansion
REM Fast path: rebake Texture2DArray (BC7) timing clips + bundles for Griffin/Pikeman only.
REM Skips RIFE, extract, sound, and full-manifest production. Typical: 2 Unity launches (~minutes).
REM
REM   set SKIP_MIRROR=0   if Unity lab PNGs are stale (re-import from OfflineUnlockMod\homm3_lab)
REM   set SKIP_BUNDLE=1   animator + manifest only (no homm3_bundles deploy until you bundle)
REM
REM Prereq: 60fps frames already in homm3_lab\...\extracted_battle (production RIFE or SKIP_RIFE=1).

set "SCRIPT_DIR=%~dp0"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set OUT=%SCRIPT_DIR%build_out
set MANIFEST=%SCRIPT_DIR%homm3_units_manifest.json
set "OFFLINE=%SCRIPT_DIR%..\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod"
set UNIT_LIST=%SCRIPT_DIR%rife_production_logs\manifest_array_timing_test.txt
set LOG=%SCRIPT_DIR%rife_production_logs\unity_array_timing_test.log
if not defined HOMM3_TARGET_FPS set HOMM3_TARGET_FPS=60
if not defined HOMM3_BATTLE_TEXTURE_ARRAY set HOMM3_BATTLE_TEXTURE_ARRAY=1
if not defined SKIP_MIRROR set SKIP_MIRROR=1
if not defined HOMM3_TMP_ROOT set HOMM3_TMP_ROOT=V:\homm3_tmp
if not exist "%HOMM3_TMP_ROOT%" mkdir "%HOMM3_TMP_ROOT%"
set "TMP=%HOMM3_TMP_ROOT%"
set "TEMP=%HOMM3_TMP_ROOT%"

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
  echo No Unity project found. Set OLDENERA_UNITY_PROJECT or create %PROJECT_LOCAL%
  exit /b 1
)
echo Using Unity project: %PROJECT%
echo Temp: %TEMP%

if /I "%HOMM3_CLEAN_LIBRARY%"=="1" (
  if exist "%PROJECT%\Library" (
    echo HOMM3_CLEAN_LIBRARY=1: removing %PROJECT%\Library ^(44GB+ ArtifactDB^)...
    rmdir /S /Q "%PROJECT%\Library"
    if exist "%PROJECT%\Library" (
      echo Failed to remove Library folder.
      exit /b 1
    )
    rem A Library wipe must create the marker (docs/unity_queue_runner.md, cold Library): the queue then demands a warm-up.
    type nul > "%PROJECT%\.library_wiped"
  )
)

if "%SKIP_MIRROR%"=="1" (
  if not exist "%PROJECT%\Assets\CustomUnits\homm3_lab\h3_pikeman\extracted_battle\CPKMAN.dir" (
    echo Unity lab missing battle frames; forcing SKIP_MIRROR=0.
    set SKIP_MIRROR=0
  )
)

for %%U in (h3_griffin h3_pikeman) do (
  echo Sync authoring preset for %%U
  if not exist "%OFFLINE%\homm3_lab\%%U" mkdir "%OFFLINE%\homm3_lab\%%U"
  copy /Y "%SCRIPT_DIR%presets\%%U\authoring.json" "%OFFLINE%\homm3_lab\%%U\authoring.json" >nul
  if errorlevel 1 exit /b 1
)

if /I "%SKIP_MIRROR%"=="1" (
  echo SKIP_MIRROR=1: keeping existing Unity lab battle PNGs.
) else (
  echo Mirror battle frames to Unity lab...
  py -3 "%SCRIPT_DIR%mirror_homm3_lab_battle_to_unity.py" --unity-project "%PROJECT%" --manifest "%MANIFEST%" --workers 4 --unit-list "%UNIT_LIST%"
  if errorlevel 1 exit /b 1
)

if not exist "%PROJECT%\Assets\Shaders" mkdir "%PROJECT%\Assets\Shaders"
copy /Y "%SCRIPT_DIR%unity_shaders\Homm3BillboardArray.shader" "%PROJECT%\Assets\Shaders\Homm3BillboardArray.shader" >nul
if not exist "%PROJECT%\Assets\CustomUnits\Homm3Import" mkdir "%PROJECT%\Assets\CustomUnits\Homm3Import"
xcopy /Y /Q "%SCRIPT_DIR%unity_runtime\*.cs" "%PROJECT%\Assets\CustomUnits\Homm3Import\" >nul
if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
xcopy /Y /Q "%SCRIPT_DIR%unity_editor\*.cs" "%PROJECT%\Assets\Editor\" >nul
xcopy /Y /Q "%SCRIPT_DIR%..\custom_prefab_pipeline\unity_editor\BuildCustomUnitBundles.cs" "%PROJECT%\Assets\Editor\" >nul

echo.
echo === Unity array rebuild: h3_griffin + h3_pikeman ^(BC7 arrays, one editor session^) ===
set "PHASE3_START=%TIME%"
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.Homm3Import.Homm3BillboardAnimatorBuild.RebuildAllFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%UNIT_LIST%" ^
  -homm3BattleTexture2DArray "%HOMM3_BATTLE_TEXTURE_ARRAY%" ^
  -logFile "%LOG%"
if errorlevel 1 (
  echo Animator rebuild failed — see %LOG%
  exit /b 1
)
findstr /C:"HOMM3_ARRAY_BUILD_PROFILE" "%LOG%" >nul 2>&1
if errorlevel 1 (
  echo Phase 3 did not emit HOMM3_ARRAY_BUILD_PROFILE ^(Unity likely crashed at startup — check disk space / Library^).
  findstr /I /C:"not enough space" /C:"Resizing lmdb" /C:"Crash" "%LOG%" 2>nul
  exit /b 1
)
set "PHASE3_END=%TIME%"
echo Phase 3 wall clock: %PHASE3_START% -^> %PHASE3_END%
findstr /C:"RebuildAllFromManifest" /C:"HOMM3_ARRAY_BUILD_PROFILE" "%LOG%" 2>nul

py -3 "%SCRIPT_DIR%sync_homm3_array_manifests_from_unity.py" --unity-project "%PROJECT%" --target-lab "%OFFLINE%\homm3_lab"
if errorlevel 1 exit /b 1

if /I "%SKIP_BUNDLE%"=="1" (
  echo SKIP_BUNDLE=1: done. Deploy lab\Generated + array_battle_manifest.json for a runtime-only test, or rerun without SKIP_BUNDLE.
  exit /b 0
)

echo.
echo === AssetBundles: griffin + pikeman only ===
set "PHASE4_START=%TIME%"
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%UNIT_LIST%" ^
  -outputPath "%OUT%" ^
  -logFile "%SCRIPT_DIR%rife_production_logs\unity_array_timing_test_bundle.log"
if errorlevel 1 exit /b 1
findstr /C:"HOMM3_BUNDLE_BUILD_PROFILE" "%SCRIPT_DIR%rife_production_logs\unity_array_timing_test_bundle.log" >nul 2>&1
if errorlevel 1 (
  echo Phase 4 did not emit HOMM3_BUNDLE_BUILD_PROFILE — see unity_array_timing_test_bundle.log
  exit /b 1
)
set "PHASE4_END=%TIME%"
echo Phase 4 wall clock: %PHASE4_START% -^> %PHASE4_END%
findstr /C:"HOMM3_BUNDLE_BUILD_PROFILE" "%SCRIPT_DIR%rife_production_logs\unity_array_timing_test_bundle.log" 2>nul
for %%B in (custom_units_castle_h3_griffin custom_units_castle_h3_pikeman) do (
  if exist "%OUT%\%%B" (
    for %%F in ("%OUT%\%%B") do echo Bundle file %%B: %%~zF bytes
  )
)

echo.
echo OK — copy from %OUT%:
echo   custom_units_castle_h3_griffin
echo   custom_units_castle_h3_pikeman
echo Or run: build_and_deploy_homm3_griffin_pikeman_timing.cmd
exit /b 0
