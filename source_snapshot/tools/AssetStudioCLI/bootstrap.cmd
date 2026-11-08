@echo off
setlocal
REM Downloads Razviar AssetStudio (net8) and extracts to .\dist\ (requires curl, tar or PowerShell Expand-Archive).
set "ROOT=%~dp0"
set "ZIP=%ROOT%AssetStudio-net8.0-win.zip"
set "DIST=%ROOT%dist"
set "URL=https://github.com/Razviar/assetstudio/releases/download/v2.4.1/AssetStudio-net8.0-win.zip"

if exist "%DIST%\AssetStudio.CLI.exe" (
  echo AssetStudio.CLI already present: %DIST%\AssetStudio.CLI.exe
  exit /b 0
)

where curl >nul 2>&1
if errorlevel 1 (
  echo Install curl or download manually: %URL%
  exit /b 1
)

echo Downloading AssetStudio net8...
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

if not exist "%DIST%\AssetStudio.CLI.exe" (
  echo Extraction failed: AssetStudio.CLI.exe not found under %DIST%
  exit /b 1
)

echo OK: %DIST%\AssetStudio.CLI.exe
exit /b 0
