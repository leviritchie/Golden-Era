@echo off
setlocal
REM Full Unity-project export of HeroesOE_Data via AssetRipper (headless HTTP API).
REM 1) tools\AssetRipper\bootstrap.cmd
REM 2) Edit paths below if your install differs.
REM 3) Run this script. Go make coffee — load + export can take a long time.
REM Output: tools\reference\assetripper_olden_demo_unity\  (large; gitignore locally if needed)

set "AR_EXE=%~dp0dist\AssetRipper.GUI.Free.exe"
set "GAME_DATA=V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data"
set "EXPORT_OUT=%~dp0..\reference\assetripper_olden_demo_unity"

if not exist "%AR_EXE%" (
  echo Run bootstrap.cmd first.
  exit /b 1
)
if not exist "%GAME_DATA%" (
  echo Edit GAME_DATA= to your HeroesOE_Data folder.
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0export_heroesoe_unity_project.ps1" ^
  -ArExe "%AR_EXE%" ^
  -GameDataPath "%GAME_DATA%" ^
  -ExportPath "%EXPORT_OUT%"

if errorlevel 1 exit /b 1
echo.
echo Or run full headless pipeline: pipeline_esquire_reference_headless.cmd
exit /b 0
