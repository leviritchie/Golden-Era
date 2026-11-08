@echo off
setlocal
REM Rebake array timing + bundles for Griffin/Pikeman, deploy to Steam plugin, rebuild mod DLL.
set "SCRIPT_DIR=%~dp0"
set "OFFLINE=%SCRIPT_DIR%..\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod"
if not defined GAME_ROOT set "GAME_ROOT=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
if not defined BEPINEX_PLUGINS set "BEPINEX_PLUGINS=%GAME_ROOT%\BepInEx\plugins\OfflineUnlockMod"
set PLUGIN=%BEPINEX_PLUGINS%
set OUT=%SCRIPT_DIR%build_out

call "%SCRIPT_DIR%build_homm3_array_timing_test.cmd"
if errorlevel 1 exit /b 1

echo.
echo === dotnet build OfflineUnlockMod ===
dotnet build "%OFFLINE%\OfflineUnlockMod.csproj" -c Release "-p:GameRoot=%GAME_ROOT%" -clp:ErrorsOnly
if errorlevel 1 exit /b 1

if not exist "%PLUGIN%" (
  echo Missing plugin folder: %PLUGIN%
  exit /b 1
)

copy /Y "%OFFLINE%\bin\Release\netstandard2.1\OfflineUnlockMod.dll" "%PLUGIN%\OfflineUnlockMod.dll" >nul

for %%U in (h3_griffin h3_pikeman) do (
  echo Deploy homm3_lab\%%U
  if not exist "%PLUGIN%\homm3_lab\%%U" mkdir "%PLUGIN%\homm3_lab\%%U"
  if exist "%OFFLINE%\homm3_lab\%%U\authoring.json" copy /Y "%OFFLINE%\homm3_lab\%%U\authoring.json" "%PLUGIN%\homm3_lab\%%U\" >nul
  if exist "%OFFLINE%\homm3_lab\%%U\Generated" (
    xcopy /E /Y /I /Q "%OFFLINE%\homm3_lab\%%U\Generated" "%PLUGIN%\homm3_lab\%%U\Generated\" >nul
  )
)

for %%B in (custom_units_castle_h3_griffin custom_units_castle_h3_pikeman) do (
  if not exist "%OUT%\%%B" (
    echo Missing bundle: %OUT%\%%B
    exit /b 1
  )
  echo Deploy homm3_bundles\%%B
  if exist "%PLUGIN%\homm3_bundles\%%B\" rmdir /S /Q "%PLUGIN%\homm3_bundles\%%B"
  copy /Y "%OUT%\%%B" "%PLUGIN%\homm3_bundles\%%B" >nul
  if exist "%OUT%\%%B.manifest" copy /Y "%OUT%\%%B.manifest" "%PLUGIN%\homm3_bundles\%%B.manifest" >nul
)

echo.
echo Done. Restart the game and battle-test Castle Griffin + Pikeman.
exit /b 0
