@echo off
setlocal
cd /d "%~dp0\..\.."
C:\Python312\python.exe tools\homm3_mocap_cleanup\server.py --unit h3_amalek --port 8766
if errorlevel 1 (
  echo Failed to start the cleanup editor.
  pause
)
