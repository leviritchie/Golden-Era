@echo off
setlocal
REM One-shot headless path: bootstrap AssetRipper -> export HeroesOE_Data -> copy best esquire battle
REM AnimatorController (+ same-folder .anim) into oldenera_factions Reference.
REM
REM Optional environment:
REM   FORCE_EXPORT=1     Re-run AssetRipper export even if output folder exists.
REM   SKIP_EXPORT=1      Only copy from existing export (no rip).
REM   SKIP_BOOTSTRAP=1   Assume dist\AssetRipper.GUI.Free.exe already present.
REM   RUN_UNITY=1        After copy, run tools\custom_prefab_pipeline\build_esquire_bundle.cmd
REM
REM Edit UNITY_PROJECT= or GAME_DATA= below if your paths differ.

set "UNITY_PROJECT=C:\Users\<user>\oldenera_factions"
set "GAME_DATA=V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data"

set "PS_OPTS=-NoProfile -ExecutionPolicy Bypass"
set "SCRIPT=%~dp0pipeline_esquire_reference_headless.ps1"

set "EXTRA="
if defined FORCE_EXPORT set "EXTRA=%EXTRA% -ForceExport"
if defined SKIP_EXPORT set "EXTRA=%EXTRA% -SkipExport"
if defined SKIP_BOOTSTRAP set "EXTRA=%EXTRA% -SkipBootstrap"
if defined RUN_UNITY set "EXTRA=%EXTRA% -RunUnityRebuild"

powershell %PS_OPTS% -File "%SCRIPT%" -UnityProject "%UNITY_PROJECT%" -GameDataPath "%GAME_DATA%" %EXTRA%
exit /b %ERRORLEVEL%
