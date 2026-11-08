@echo off
setlocal
cd /d "%~dp0.."
set SKIP_RIFE=1
set SKIP_STRIP_METAS=1
set SKIP_MIRROR=1
set "HOMM3_UNIT_LIST=%~dp0manifest_resume_from_orc.txt"
set "HOMM3_BUNDLE_UNIT_LIST=%~dp0manifest_minus_temple_griffon.txt"
call run_homm3_rife_production.cmd
