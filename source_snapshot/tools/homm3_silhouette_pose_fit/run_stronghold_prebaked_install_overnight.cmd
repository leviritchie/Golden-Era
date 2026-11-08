@echo off
REM Overnight Stronghold job, launched by Windows Task Scheduler (task
REM "Homm3StrongholdPrebakedInstall"): continuous-track every Stronghold unit's DEF
REM sequences in priority order, solve + pre-bake per-unit lighting, export skinned
REM clips, build the Unity lab + bundles, and deploy each validated bundle into the
REM Golden Era install.
REM
REM --track-deadline 06:30 stops STARTING new tracker runs at 06:30 so the light
REM solve / bake / Unity / deploy tail has the morning window. Sequences not reached
REM ship from the unit's existing fused-push result and are labelled as such in the
REM summary (artifacts\prebaked_continuous_stronghold_rollout\overnight_summary.json).

setlocal
set REPO=V:\Games\Olden Era Playtest Tweak
set OUT=%REPO%\artifacts\prebaked_continuous_stronghold_rollout

cd /d "%REPO%" || exit /b 1
if not exist "%OUT%" mkdir "%OUT%"

py -3 "%REPO%\tools\homm3_silhouette_pose_fit\run_stronghold_prebaked_install_overnight.py" ^
  --track-deadline 06:30 ^
  --out "%OUT%" ^
  > "%OUT%\batch_console.log" 2>&1

echo exit_code=%ERRORLEVEL% >> "%OUT%\batch_console.log"
endlocal
