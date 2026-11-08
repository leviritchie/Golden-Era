@echo off
setlocal
python "%~dp0build_homm3_billboard_bundle.py"
exit /b %ERRORLEVEL%
