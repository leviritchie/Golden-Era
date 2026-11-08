@echo off

call "%~dp0deploy_official_deobf_port_smoke.sh"

exit /b %ERRORLEVEL%

