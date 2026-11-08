@echo off
setlocal
REM Option D prototype: rebuild battle using Texture2DArray for h3_gnoll + h3_lizardman.
set "SCRIPT_DIR=%~dp0"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set OUT=%SCRIPT_DIR%build_out
set MANIFEST=%SCRIPT_DIR%homm3_units_manifest.json
set "OFFLINE=%SCRIPT_DIR%..\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod"
set LOG=%SCRIPT_DIR%unity_homm3_array_prototype.log

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
  echo No Unity project found.
  exit /b 1
)
echo Using Unity project: %PROJECT%

for %%U in (h3_gnoll h3_lizardman) do (
  echo Sync authoring preset for %%U
  if not exist "%OFFLINE%\homm3_lab\%%U" mkdir "%OFFLINE%\homm3_lab\%%U"
  copy /Y "%SCRIPT_DIR%presets\%%U\authoring.json" "%OFFLINE%\homm3_lab\%%U\authoring.json"
  if errorlevel 1 exit /b 1
)

if /I "%SKIP_MIRROR%"=="1" (
  echo SKIP_MIRROR=1: keeping existing Unity lab battle PNGs ^(no re-import^).
) else (
  echo Mirror battle frames to Unity lab...
  py -3 "%SCRIPT_DIR%mirror_homm3_lab_battle_to_unity.py" --unity-project "%PROJECT%" --manifest "%MANIFEST%" --workers 4 --unit-list "%SCRIPT_DIR%rife_production_logs\manifest_array_prototype.txt"
  if errorlevel 1 exit /b 1
)

if not exist "%PROJECT%\Assets\Shaders" mkdir "%PROJECT%\Assets\Shaders"
copy /Y "%SCRIPT_DIR%unity_shaders\Homm3BillboardArray.shader" "%PROJECT%\Assets\Shaders\Homm3BillboardArray.shader" >nul

if not exist "%PROJECT%\Assets\CustomUnits\Homm3Import" mkdir "%PROJECT%\Assets\CustomUnits\Homm3Import"
xcopy /Y /Q "%SCRIPT_DIR%unity_runtime\*.cs" "%PROJECT%\Assets\CustomUnits\Homm3Import\" >nul

if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
xcopy /Y /Q "%SCRIPT_DIR%unity_editor\*.cs" "%PROJECT%\Assets\Editor\" >nul
xcopy /Y /Q "%SCRIPT_DIR%..\custom_prefab_pipeline\unity_editor\BuildCustomUnitBundles.cs" "%PROJECT%\Assets\Editor\" >nul

for %%U in (h3_gnoll h3_lizardman) do (
  echo.
  echo === Texture2DArray battle rebuild: %%U ===
  "%UNITY%" -batchmode -quit -nographics ^
    -projectPath "%PROJECT%" ^
    -homm3UnitSid "%%U" ^
    -executeMethod OldenEra.Homm3Import.Homm3BillboardAnimatorBuild.RebuildFromBatch ^
    -logFile "%LOG%.%%U.log"
  if errorlevel 1 (
    echo Rebuild failed for %%U — see %LOG%.%%U.log
    exit /b 1
  )
)

echo.
echo === Build AssetBundles for prototype units ===
"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest ^
  -manifestPath "%MANIFEST%" ^
  -homm3UnitListPath "%SCRIPT_DIR%rife_production_logs\manifest_array_prototype.txt" ^
  -outputPath "%OUT%" ^
  -logFile "%SCRIPT_DIR%unity_homm3_array_prototype_bundle.log"
if errorlevel 1 exit /b 1

echo.
echo Option D prototype build complete. Deploy bundles from %OUT% and enable homm3_import for h3_gnoll / h3_lizardman in battle.
exit /b 0
