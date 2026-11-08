@echo off
setlocal EnableExtensions
REM Non-interactive chain: extract -> bootstrap esquire scaffold -> Unity animator -> AssetBundle -> verify.
REM Does NOT launch the game. Requires: HoMM3 LOD paths in units_inventory.json, Unity 6000.0.66f2, esquire assets in Unity project.

set "SCRIPT_DIR=%~dp0"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set "PROJECT_LEGACY=C:\Users\<user>\oldenera_factions"

if "%~1"=="" (
  echo Usage: run_e2e_until_game.cmd ^<homm3UnitSid^> [deployToModDir]
  echo   deployToModDir optional: BepInEx\plugins\OfflineUnlockMod folder to copy bundle + presets\^<sid^\^>\homm3_import.json
  exit /b 1
)
set "H3SID=%~1"

set "PROJECT="
if defined OLDENERA_UNITY_PROJECT (
  if exist "%OLDENERA_UNITY_PROJECT%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%OLDENERA_UNITY_PROJECT%"
)
if not defined PROJECT if exist "%PROJECT_LOCAL%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%PROJECT_LOCAL%"
if not defined PROJECT if exist "%PROJECT_LEGACY%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%PROJECT_LEGACY%"
if not defined PROJECT (
  echo run_e2e_until_game: No Unity project. Set OLDENERA_UNITY_PROJECT.
  exit /b 1
)
echo run_e2e_until_game: Unity project=%PROJECT%

echo [1/4] extract_creature.py --unit %H3SID%
py -3 "%SCRIPT_DIR%extract_creature.py" --unit "%H3SID%" --unity-project "%PROJECT%"
if errorlevel 1 exit /b 1

echo [2/4] bootstrap_homm3_lab.py --unit %H3SID%
py -3 "%SCRIPT_DIR%bootstrap_homm3_lab.py" --unity-project "%PROJECT%" --unit "%H3SID%"
if errorlevel 1 exit /b 1

echo [3/4] build_homm3_units.cmd %H3SID%  (HOM3_EXTRACT unset — already extracted^)
set "HOM3_EXTRACT="
call "%SCRIPT_DIR%build_homm3_units.cmd" "%H3SID%"
if errorlevel 1 exit /b 1

echo [4/4] verify_homm3_build.py
py -3 "%SCRIPT_DIR%verify_homm3_build.py" --unit "%H3SID%"
if errorlevel 1 exit /b 1

if not "%~2"=="" (
  if not exist "%~2\homm3_bundles" mkdir "%~2\homm3_bundles"
  for /f "usebackq delims=" %%P in (`py -3 "%SCRIPT_DIR%verify_homm3_build.py" --unit "%H3SID%" --emit-bundle-path`) do (
    copy /Y "%%P" "%~2\homm3_bundles\" >nul || exit /b 1
  )
  copy /Y "%SCRIPT_DIR%presets\%H3SID%\homm3_import.json" "%~2\homm3_import.json" >nul || exit /b 1
  echo run_e2e_until_game: deployed to %~2
)

echo run_e2e_until_game: ALL OK — ready to launch game with mod DLL + config flags.
exit /b 0
