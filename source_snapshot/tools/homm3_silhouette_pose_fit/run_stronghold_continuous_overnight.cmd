@echo off
REM Overnight Stronghold continuous-tracking batch, launched by Windows Task Scheduler.
REM
REM Wrapper exists because schtasks wants a single executable plus arguments, and this
REM keeps the working directory, log location, and deadline in one reviewable place
REM instead of buried in a task definition.
REM
REM --deadline 08:00 stops STARTING new units after 08:00; a unit already running is
REM allowed to finish. Units not started are recorded as skipped with that reason.

setlocal
set REPO=V:\Games\Olden Era Playtest Tweak
set LOGDIR=%REPO%\artifacts\pose_picker_runs\_batches\stronghold_def_continuous_stronghold
set STAMP=%DATE:/=-%_%TIME::=-%
set STAMP=%STAMP: =_%

cd /d "%REPO%" || exit /b 1
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

py -3 "%REPO%\tools\homm3_silhouette_pose_fit\run_stronghold_continuous_overnight.py" ^
  --clip idle_start_move_end ^
  --lane def_continuous_stronghold ^
  --deadline 08:00 ^
  > "%LOGDIR%\batch_console.log" 2>&1

echo exit_code=%ERRORLEVEL% >> "%LOGDIR%\batch_console.log"
endlocal
