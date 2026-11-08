@echo off
setlocal EnableDelayedExpansion
REM ============================================================================
REM Headless attempts to export esquire-related AnimatorController (or Animator)
REM via AssetStudio.CLI — no GUI. See StockEsquireBattle_IMPORT.txt for Unity path.
REM
REM Prerequisites: bootstrap.cmd (CLI binary) and, for tries that use --map_op Load,
REM   ..\reference\assetstudio_maps\olden_demo_assets.xml from build_asset_map.cmd
REM
REM Usage:
REM   try_export_stock_esquire_animator_headless.cmd
REM       — fast pass: HeroesOE_Data\level1 only (same bundle family as esquire clips).
REM   try_export_stock_esquire_animator_headless.cmd --full
REM       — slow: entire HeroesOE_Data (many minutes). Optional after level1 is empty.
REM
REM Output: ..\reference\assetstudio_esquire_headless_export\<try_id>\
REM
REM Smoke test (2026-04-26, Olden Era Demo, AssetStudio CLI v2.4.1, level1):
REM   try_A/B/D/E: "Nothing exported", 0 files each.
REM   try_C (Animator, Raw, names esquire_|esuire_|Campaign_esquire): 0 files (no matching Animator names).
REM   Do not use Animator + Convert here: parallel FBX export can AccessViolation-crash.
REM   --full not run in smoke; expect same empty Convert for controllers.
REM   => StockEsquireBattle.controller: AssetRipper CLI or AssetStudio.GUI.
REM ============================================================================

set "CLI=%~dp0dist\AssetStudio.CLI.exe"
set "MAP=%~dp0..\reference\assetstudio_maps\olden_demo_assets"
set "LEVEL1=V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data\level1"
set "GAME_DATA=V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data"
set "OUT_BASE=%~dp0..\reference\assetstudio_esquire_headless_export"

if not exist "%CLI%" (
  echo Run bootstrap.cmd first: %CLI%
  exit /b 1
)

if /i "%~1"=="--full" (
  set "INPUT_PATH=%GAME_DATA%"
  set "RUN_LABEL=full_data"
) else (
  set "INPUT_PATH=%LEVEL1%"
  set "RUN_LABEL=level1"
)

if not exist "%INPUT_PATH%" (
  echo Edit LEVEL1= / GAME_DATA= to your HeroesOE_Data paths. Missing: %INPUT_PATH%
  exit /b 1
)

if "%RUN_LABEL%"=="level1" if not exist "%MAP%.xml" (
  echo Map missing for Load tries: %MAP%.xml
  echo Run build_asset_map.cmd first, or only no-map tries will run.
)

mkdir "%OUT_BASE%" 2>nul
mkdir "%OUT_BASE%\%RUN_LABEL%" 2>nul

echo.
echo === Headless animator export matrix (%RUN_LABEL%) ===
echo Input:
echo !INPUT_PATH!
echo Output base:
echo !OUT_BASE!
echo.

call :run_try try_A_animatorcontroller_mapload Load AnimatorController Convert
call :run_try try_B_animatorcontroller_nomap None AnimatorController Convert
REM Convert on Animator uses FBX export and can AV-crash on some assets; use Raw for a safe headless sample.
REM Optional name filter limits Raw dump size (same regex idea as export_esquire_clips.cmd).
call :run_try try_C_animator_mapload_raw Load Animator Raw "esquire_|esuire_|Campaign_esquire"
call :run_try try_D_runtimeanimatorcontroller_mapload Load RuntimeAnimatorController Convert
call :run_try try_E_runtimeanimatorcontroller_nomap None RuntimeAnimatorController Convert

echo.
echo Done. Inspect subfolders under:
echo   !OUT_BASE!
echo If all empty: see StockEsquireBattle_IMPORT.txt ^(AssetRipper / GUI^).
exit /b 0

:run_try
set "TRY_ID=%~1"
set "MAP_OP=%~2"
set "U_TYPE=%~3"
set "EX_TYPE=%~4"
if not defined EX_TYPE set "EX_TYPE=Convert"
set "NAME_FILTER=%~5"
set "TRY_DIR=%OUT_BASE%\%RUN_LABEL%\%TRY_ID%"
if exist "%TRY_DIR%" rmdir /s /q "%TRY_DIR%" 2>nul
mkdir "%TRY_DIR%" 2>nul

echo --- %TRY_ID% (%U_TYPE%, map_op=%MAP_OP%, export=%EX_TYPE%) ---

if /i "%MAP_OP%"=="Load" (
  if not exist "%MAP%.xml" (
    echo SKIP: no asset map at %MAP%.xml
    exit /b 0
  )
  if not "%NAME_FILTER%"=="" (
    "%CLI%" "%INPUT_PATH%" "%TRY_DIR%" --game Normal --map_op Load --map_name "%MAP%" --types "%U_TYPE%" --names "%NAME_FILTER%" --export_type %EX_TYPE% --silent
  ) else (
    "%CLI%" "%INPUT_PATH%" "%TRY_DIR%" --game Normal --map_op Load --map_name "%MAP%" --types "%U_TYPE%" --export_type %EX_TYPE% --silent
  )
) else (
  if not "%NAME_FILTER%"=="" (
    "%CLI%" "%INPUT_PATH%" "%TRY_DIR%" --game Normal --map_op None --types "%U_TYPE%" --names "%NAME_FILTER%" --export_type %EX_TYPE% --silent
  ) else (
    "%CLI%" "%INPUT_PATH%" "%TRY_DIR%" --game Normal --map_op None --types "%U_TYPE%" --export_type %EX_TYPE% --silent
  )
)

set FCOUNT=0
for /r "%TRY_DIR%" %%F in (*) do set /a FCOUNT+=1
echo    files in output: !FCOUNT!
exit /b 0
