@echo off
setlocal
REM Pull Castle Pikeman battle sprite (cpkman.def in H3sprite.lod — not PIKEMAN.DEF) from local HoMM3 / VCMI, defextract, rename to avwpike.* for Unity.

set "ROOT=%~dp0.."
set "H3LOD=%ROOT%\HoMM 3 Complete\Data\H3sprite.lod"
if not exist "%H3LOD%" set "H3LOD=%ROOT%\vcmi\Data\H3sprite.lod"
if not exist "%H3LOD%" (
  echo No H3sprite.lod under "HoMM 3 Complete\Data" or "vcmi\Data". Edit this script if your copy lives elsewhere.
  exit /b 1
)

set "TMP=%ROOT%\tools\build_temp_pikeman"
set "LODOUT=%TMP%\cpkman.def"
if exist "%TMP%" rmdir /s /q "%TMP%"
mkdir "%TMP%"

echo Using LOD: %H3LOD%
python "%~dp0lod_extract_entry_py3.py" "%H3LOD%" "cpkman.def" "%LODOUT%"
if errorlevel 1 exit /b 1

python "%~dp0defextract_py3.py" "%LODOUT%" "%TMP%"
if errorlevel 1 exit /b 1

set "UNITY_ESQUIRE=C:\Users\<user>\oldenera_factions\Assets\CustomUnits\esquire\extracted_avwpike"
if not exist "%UNITY_ESQUIRE%" (
  echo Unity esquire folder missing: %UNITY_ESQUIRE%
  echo Edit UNITY_ESQUIRE in this script or create the folder.
  exit /b 1
)

REM Builder expects avwpike.dir + avwpike.json; defextract emitted cpkman.dir + cpkman.json
if exist "%UNITY_ESQUIRE%\avwpike.dir" rmdir /s /q "%UNITY_ESQUIRE%\avwpike.dir"
if exist "%UNITY_ESQUIRE%\avwpike.json" del /q "%UNITY_ESQUIRE%\avwpike.json"

mkdir "%UNITY_ESQUIRE%\avwpike.dir"
xcopy /e /q "%TMP%\cpkman.dir\*" "%UNITY_ESQUIRE%\avwpike.dir\"
if errorlevel 1 exit /b 1
copy /y "%TMP%\cpkman.json" "%TMP%\__avwpike__.json"
if errorlevel 1 exit /b 1
python "%~dp0fix_avwpike_json_paths.py" "%TMP%\__avwpike__.json"
if errorlevel 1 exit /b 1
move /y "%TMP%\__avwpike__.json" "%UNITY_ESQUIRE%\avwpike.json"
if errorlevel 1 exit /b 1

echo OK: %UNITY_ESQUIRE%\avwpike.dir and avwpike.json
echo Next: in Unity run Olden Era -^> Rebuild Esquire Battle Billboard Animator, or build_esquire_bundle.cmd
exit /b 0
