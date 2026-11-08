@echo off
setlocal
REM Export vanilla esquire-related AnimationClips from one level file using a pre-built asset map.
set "CLI=%~dp0dist\AssetStudio.CLI.exe"
set "MAP=%~dp0..\reference\assetstudio_maps\olden_demo_assets"
set "LEVEL=V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data\level1"
set "OUT=%~dp0..\reference\assetstudio_esquire_export_raw"

if not exist "%CLI%" (
  echo Run bootstrap.cmd first.
  exit /b 1
)
if not exist "%MAP%.xml" (
  echo Build the map first: build_asset_map.cmd
  exit /b 1
)

mkdir "%OUT%" 2>nul
"%CLI%" "%LEVEL%" "%OUT%" --game Normal --map_op Load --map_name "%MAP%" --types AnimationClip --names "esquire_|esuire_|Campaign_esquire" --export_type Raw --silent
echo Output under: %OUT%
exit /b 0
