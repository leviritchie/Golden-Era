@echo off
setlocal
REM Build XML asset map for a Unity game's HeroesOE_Data (slow: many minutes, large XML).
REM After this, use export_esquire_clips.cmd or AssetStudio.GUI + Asset Browser.
set "CLI=%~dp0dist\AssetStudio.CLI.exe"
set "GAME_DATA=V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data"
set "OUT=%~dp0..\reference\assetstudio_maps"

if not exist "%CLI%" (
  echo Run bootstrap.cmd first.
  exit /b 1
)

if not exist "%GAME_DATA%" (
  echo Edit GAME_DATA= to your install's HeroesOE_Data folder.
  exit /b 1
)

mkdir "%OUT%" 2>nul
"%CLI%" "%GAME_DATA%" "%OUT%" --game Normal --map_op AssetMap --map_type XML --map_name olden_demo_assets
echo Map: %OUT%\olden_demo_assets.xml
exit /b 0
