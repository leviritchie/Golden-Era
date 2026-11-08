@echo off
setlocal
REM Download AssetRipper (Windows x64) into .\dist\ — same pattern as AssetStudioCLI\bootstrap.cmd
set "ROOT=%~dp0"
set "ZIP=%ROOT%AssetRipper_win_x64.zip"
set "DIST=%ROOT%dist"
set "VER=1.3.14"
set "URL=https://github.com/AssetRipper/AssetRipper/releases/download/%VER%/AssetRipper_win_x64.zip"

if exist "%DIST%\AssetRipper.GUI.Free.exe" (
  echo AssetRipper already present: %DIST%\AssetRipper.GUI.Free.exe
  exit /b 0
)

where curl >nul 2>&1
if errorlevel 1 (
  echo Install curl or download manually: %URL%
  exit /b 1
)

echo Downloading AssetRipper %VER%...
curl -fsSL -o "%ZIP%" "%URL%"
if errorlevel 1 exit /b 1

if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%" 2>nul

echo Extracting...
tar -xf "%ZIP%" -C "%DIST%" 2>nul
if errorlevel 1 (
  powershell -NoProfile -Command "Expand-Archive -Path '%ZIP%' -DestinationPath '%DIST%' -Force"
  if errorlevel 1 exit /b 1
)

if not exist "%DIST%\AssetRipper.GUI.Free.exe" (
  echo Extraction failed: AssetRipper.GUI.Free.exe not found under %DIST%
  exit /b 1
)

del "%ZIP%" 2>nul
echo OK: %DIST%\AssetRipper.GUI.Free.exe
exit /b 0
