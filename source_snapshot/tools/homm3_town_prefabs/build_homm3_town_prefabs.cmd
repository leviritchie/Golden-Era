@echo off
setlocal
REM Builds HoMM3 town-screen layer prefabs into one AssetBundle consumed by OfflineUnlockMod.
REM Optional: pass a single faction sid, e.g. build_homm3_town_prefabs.cmd homm3_cove

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%..\.."
set "PROJECT_LOCAL=%REPO_ROOT%\oldenera_factions"
set "PROJECT_LEGACY=C:\Users\<user>\oldenera_factions"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set "OUT=%SCRIPT_DIR%build_out"
set "LOG=%SCRIPT_DIR%unity_homm3_town_prefab_build.log"
set "SOURCE=%REPO_ROOT%\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\homm3_runtime_assets\town_scene_refs"

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

if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
xcopy /Y /Q "%SCRIPT_DIR%unity_editor\*.cs" "%PROJECT%\Assets\Editor\" >nul

set "FRACTION_ARG="
if not "%~1"=="" set "FRACTION_ARG=-fraction %~1"

"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -executeMethod OldenEra.Homm3TownPrefabs.BuildHomm3TownPrefabs.BuildFromRuntimeAssets ^
  -sourceRoot "%SOURCE%" ^
  -outputPath "%OUT%" ^
  %FRACTION_ARG% ^
  -logFile "%LOG%"
if errorlevel 1 (
  echo Town prefab build failed - see %LOG%
  exit /b 1
)

echo OK - output under %OUT%
echo Deploy with dotnet build or copy %OUT%\homm3_town_prefabs to BepInEx\plugins\OfflineUnlockMod\homm3_town_prefabs\
exit /b 0
