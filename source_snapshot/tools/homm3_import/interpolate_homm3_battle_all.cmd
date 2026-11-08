@echo off
setlocal
REM Batch RIFE v4 at the configured target FPS (production default 60).
REM Prereq: bash tools/homm3_import/setup_vfi_env.sh
REM Resume: re-run skips groups recorded in extracted_battle/.rife120_done.json
REM Force rebuild: add --force to the python line below.

set "SCRIPT_DIR=%~dp0"
set "OFFLINE_LAB=%SCRIPT_DIR%..\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\homm3_lab"

if "%~1"=="--dry-run" (
  py -3 "%SCRIPT_DIR%interpolate_homm3_battle_sequences.py" --lab-root "%OFFLINE_LAB%" --dry-run
  exit /b %ERRORLEVEL%
)

py -3 "%SCRIPT_DIR%interpolate_homm3_battle_sequences.py" --lab-root "%OFFLINE_LAB%" %*
exit /b %ERRORLEVEL%
