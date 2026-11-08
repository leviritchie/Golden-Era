@echo off
setlocal
REM Re-run Unity array rebuild only (textures already imported in oldenera_factions).
set SKIP_MIRROR=1
call "%~dp0build_homm3_array_prototype.cmd" %*
exit /b %ERRORLEVEL%
