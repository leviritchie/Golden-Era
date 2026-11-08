@echo off
setlocal enabledelayedexpansion

REM Build all HoMM3 Stronghold visual bundles: bootstrap + extract + audio + Unity builds + bundle copy.
REM Prereq: Unity 6000.0.66f2, oldenera_factions project, HoMM 3 Complete/Data/H3sprite.lod + Heroes3.snd.
REM
REM Usage:
REM   build_homm3_stronghold.cmd              -- build all Stronghold units, including ToA alternate visuals
REM   build_homm3_stronghold.cmd h3_goblin    -- build single unit (still runs bootstrap)
REM   set SKIP_BOOTSTRAP=1  to skip bootstrap if lab folders already exist
REM   set SKIP_EXTRACT=1    to skip DEF extraction (use cached extracted_battle frames)
REM   set SKIP_COPY=1       to skip final bundle copy to BepInEx plugins folder

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%..\..\"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set "BUNDLES_OUT=%SCRIPT_DIR%build_out"
if not defined BEPINEX_TARGET set "BEPINEX_TARGET=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\homm3_bundles"

set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set "PROJECT_LEGACY=C:\Users\<user>\oldenera_factions"

set STRONGHOLD_UNITS=h3_goblin h3_hobgoblin h3_wolf_rider h3_wolf_raider h3_orc h3_orc_chieftain h3_ogre h3_ogre_mage h3_roc h3_thunderbird h3_cyclops h3_cyclops_king h3_behemoth h3_ancient_behemoth toa_goblin_trapper toa_boar_rider toa_orc_berserker toa_ogre_brute toa_shahrokh toa_blood_eyed_cyclops toa_ghost_behemoth

REM --- resolve Unity project ---
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

if not exist "%UNITY%" (
  echo Unity not found at: %UNITY%
  echo Edit UNITY= in this script if your editor path differs.
  exit /b 1
)

REM --- determine unit list ---
if not "%~1"=="" (
  set STRONGHOLD_UNITS=%~1
)

REM --- bootstrap step: scaffold homm3_lab/<unit> from esquire template ---
if not "%SKIP_BOOTSTRAP%"=="1" (
  echo.
  echo === Bootstrap lab folders ===
  for %%U in (%STRONGHOLD_UNITS%) do (
    echo Bootstrap: %%U
    py -3 "%SCRIPT_DIR%bootstrap_homm3_lab.py" --unity-project "%PROJECT%" --unit "%%U"
    if errorlevel 1 (
      echo bootstrap_homm3_lab failed for %%U
      exit /b 1
    )
  )
)

REM --- resolve HOM3_EXTRACT for per-unit builds ---
if "%SKIP_EXTRACT%"=="1" (
  set HOM3_EXTRACT=0
) else (
  set HOM3_EXTRACT=1
)

REM --- per-unit build loop ---
echo.
echo === Per-unit build: extract + audio + animator + bundles ===
for %%U in (%STRONGHOLD_UNITS%) do (
  echo.
  echo --- Unit: %%U ---
  call "%SCRIPT_DIR%build_homm3_units.cmd" "%%U"
  if errorlevel 1 (
    echo build_homm3_units failed for %%U
    exit /b 1
  )
)

REM --- copy bundles to BepInEx ---
if not "%SKIP_COPY%"=="1" (
  echo.
  echo === Copy bundles to BepInEx ===
  if not exist "%BEPINEX_TARGET%" mkdir "%BEPINEX_TARGET%"
  xcopy /Y /Q "%BUNDLES_OUT%\*" "%BEPINEX_TARGET%\" >nul
  if errorlevel 1 (
    echo Bundle copy failed. Source: %BUNDLES_OUT%
    exit /b 1
  )
  echo Copied bundles to "%BEPINEX_TARGET%"
)

echo.
echo === Done: all Stronghold units built ===
exit /b 0
