@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "GAME_ROOT=%CD%"
set "GA=%GAME_ROOT%\GameAssembly.dll"
set "META=%GAME_ROOT%\HeroesOE_Data\il2cpp_data\Metadata\global-metadata.dat"
set "OUT=%GAME_ROOT%\tools\il2cpp_out"
set "DUMPER=%GAME_ROOT%\tools\il2cpp_dumper\Il2CppDumper.exe"

if not exist "%GA%" (
  echo ERROR: GameAssembly.dll not found:
  echo   %GA%
  echo Run this from the repo; game install must include the playtest root DLL.
  exit /b 1
)
if not exist "%META%" (
  echo ERROR: global-metadata.dat not found:
  echo   %META%
  exit /b 1
)
if not exist "%DUMPER%" (
  echo ERROR: Il2CppDumper.exe not found:
  echo   %DUMPER%
  echo.
  echo Download a release from: https://github.com/Perfare/Il2CppDumper/releases
  echo Extract Il2CppDumper.exe into: tools\il2cpp_dumper\
  echo This repo ignores that folder; it is local-only.
  exit /b 1
)

where python >nul 2>nul && python "%~dp0il2cpp_dumper_headless_config.py" "%GAME_ROOT%"

if not exist "%OUT%" mkdir "%OUT%"
echo Running Il2CppDumper...
echo   binary:  %GA%
echo   meta:    %META%
echo   output:  %OUT%
echo.
"%DUMPER%" "%GA%" "%META%" "%OUT%"
set "EC=%ERRORLEVEL%"
echo.
if "%EC%"=="0" (
  echo OK. Browse %OUT%\dump.cs and stringliteral.json. See docs\il2cpp-map-generate-trace.md ^(LocKit / Loc search^).
) else (
  echo Il2CppDumper exited with code %EC%.
)
exit /b %EC%
