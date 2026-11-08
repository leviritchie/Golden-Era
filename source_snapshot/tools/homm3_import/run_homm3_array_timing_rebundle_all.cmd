@echo off
setlocal EnableDelayedExpansion
REM Rebake all manifest HoMM3 array timing clips + bundles at 60fps (same fix as Griffin/Pikeman).
REM Requires 60fps frames already in OfflineUnlockMod\homm3_lab\...\extracted_battle (.rife120_done.json).
REM
REM Skips: RIFE, 12fps source restore. Runs: mirror -> Unity animator -> bundles -> dotnet deploy to GAME_ROOT.
REM
REM Optional env:
REM   SKIP_MIRROR=1        skip mirror (only if Unity lab already has all battle PNGs)
REM   SKIP_STRIP_METAS=1     keep TextureImporter .meta (much faster Unity import; default 1)
REM   SKIP_BUNDLE=1          animator + manifest sync only
REM   HOMM3_UNIT_LIST=path   subset list (one sid per line)
REM   GAME_ROOT=...          Steam install (default Golden Era)

set SKIP_RIFE=1
set HOMM3_RESET_FROM_SOURCE=0
if not defined SKIP_MIRROR set SKIP_MIRROR=0
if not defined SKIP_STRIP_METAS set SKIP_STRIP_METAS=1
if not defined HOMM3_DUAL_STREAM_ALPHA set HOMM3_DUAL_STREAM_ALPHA=1
if not defined HOMM3_BATTLE_TEXTURE_ARRAY set HOMM3_BATTLE_TEXTURE_ARRAY=1
if not defined HOMM3_TARGET_FPS set HOMM3_TARGET_FPS=60
if not defined HOMM3_BUNDLE_BATCHES set HOMM3_BUNDLE_BATCHES=3

echo === HoMM3 array timing rebake (all eligible units) ===
echo   SKIP_RIFE=1  HOMM3_RESET_FROM_SOURCE=0  SKIP_MIRROR=%SKIP_MIRROR%  SKIP_STRIP_METAS=%SKIP_STRIP_METAS%  HOMM3_BUNDLE_BATCHES=%HOMM3_BUNDLE_BATCHES%
call "%~dp0run_homm3_rife_production.cmd"
exit /b %ERRORLEVEL%
