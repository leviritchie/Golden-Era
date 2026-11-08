@echo off
setlocal
set "GAME_ROOT=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
set "PROJECT=%~dp0..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj"

dotnet build -c Release ^
  "-p:GameRoot=%GAME_ROOT%" ^
  "-p:DeployPluginToGame=false" ^
  "-p:OfficialDeobfBuild=true" ^
  "%PROJECT%" ^
  -clp:ErrorsOnly
exit /b %ERRORLEVEL%
