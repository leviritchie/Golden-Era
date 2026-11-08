@echo off
setlocal
REM Dual-stream RIFE (v4.6) lab frames + Texture2DArray bundles -> Steam OfflineUnlockMod.
set "SCRIPT_DIR=%~dp0"
set "OFFLINE=%SCRIPT_DIR%..\..\Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod"
if not defined GAME_ROOT set "GAME_ROOT=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
if not defined BEPINEX_PLUGINS set "BEPINEX_PLUGINS=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod"
set "PLUGIN=%BEPINEX_PLUGINS%"
set LOG=%SCRIPT_DIR%rife_production_logs\dual_stream_gnoll_lizardman.log

echo === RIFE dual-stream alpha @ 120 FPS (h3_gnoll, h3_lizardman) ===
py -3 "%SCRIPT_DIR%interpolate_homm3_battle_sequences.py" ^
  --lab-root "%OFFLINE%\homm3_lab" ^
  --units h3_gnoll h3_lizardman ^
  --force ^
  --reset-from-source-backup ^
  --dual-stream-alpha ^
  --rife-model rife-v4.6 ^
  --log-file "%LOG%"
if errorlevel 1 exit /b 1

echo.
echo === Unity Texture2DArray rebuild ===
call "%SCRIPT_DIR%build_homm3_array_prototype.cmd"
if errorlevel 1 exit /b 1

echo.
echo === Build and deploy OfflineUnlockMod.dll ===
dotnet build "%OFFLINE%\OfflineUnlockMod.csproj" -c Release "-p:GameRoot=%GAME_ROOT%" -clp:ErrorsOnly
if errorlevel 1 exit /b 1

echo.
echo === Deploy to Steam plugin ===
if not exist "%PLUGIN%" (
  echo Missing plugin folder: %PLUGIN%
  exit /b 1
)

for %%U in (h3_gnoll h3_lizardman) do (
  echo Deploy lab\%%U
  if not exist "%PLUGIN%\homm3_lab\%%U" mkdir "%PLUGIN%\homm3_lab\%%U"
  xcopy /E /Y /I /Q "%OFFLINE%\homm3_lab\%%U\extracted_battle" "%PLUGIN%\homm3_lab\%%U\extracted_battle\" >nul
  if exist "%OFFLINE%\homm3_lab\%%U\Generated" (
    xcopy /E /Y /I /Q "%OFFLINE%\homm3_lab\%%U\Generated" "%PLUGIN%\homm3_lab\%%U\Generated\" >nul
  )
  if exist "%OFFLINE%\homm3_lab\%%U\authoring.json" (
    copy /Y "%OFFLINE%\homm3_lab\%%U\authoring.json" "%PLUGIN%\homm3_lab\%%U\authoring.json" >nul
  )
)

set OUT=%SCRIPT_DIR%build_out
for %%B in (custom_units_fortress_h3_gnoll custom_units_fortress_h3_lizardman) do (
  if not exist "%OUT%\%%B" (
    echo Missing bundle folder: %OUT%\%%B
    exit /b 1
  )
  echo Deploy homm3_bundles\%%B
  if not exist "%PLUGIN%\homm3_bundles\%%B" mkdir "%PLUGIN%\homm3_bundles\%%B"
  xcopy /E /Y /I /Q "%OUT%\%%B" "%PLUGIN%\homm3_bundles\%%B\" >nul
)

echo.
echo Done. Battle-test h3_gnoll / h3_lizardman with homm3ImportEnabled.
echo Log: %LOG%
exit /b 0
