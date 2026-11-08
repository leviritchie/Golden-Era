@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PROJECT_LOCAL=%SCRIPT_DIR%..\..\oldenera_factions"
set UNITY=%ProgramFiles%\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe
set OUT=%SCRIPT_DIR%build_out
set LOG=%SCRIPT_DIR%unity_homm3_array_upscale_shader_bundle.log

if not exist "%UNITY%" (
  echo Edit UNITY= in this script if your editor path differs.
  exit /b 1
)

set "PROJECT="
if defined OLDENERA_UNITY_PROJECT (
  if exist "%OLDENERA_UNITY_PROJECT%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%OLDENERA_UNITY_PROJECT%"
)
if not defined PROJECT if exist "%PROJECT_LOCAL%\ProjectSettings\ProjectVersion.txt" set "PROJECT=%PROJECT_LOCAL%"
if not defined PROJECT (
  echo No Unity project found.
  exit /b 1
)
echo Using Unity project: %PROJECT%

if not exist "%PROJECT%\Assets\Shaders" mkdir "%PROJECT%\Assets\Shaders"
copy /Y "%SCRIPT_DIR%unity_shaders\Homm3BillboardArrayUpscale.shader" "%PROJECT%\Assets\Shaders\Homm3BillboardArrayUpscale.shader" >nul

if not exist "%PROJECT%\Assets\Editor" mkdir "%PROJECT%\Assets\Editor"
xcopy /Y /Q "%SCRIPT_DIR%unity_editor\Homm3ArrayUpscaleShaderBundleBuild.cs" "%PROJECT%\Assets\Editor\" >nul

"%UNITY%" -batchmode -quit -nographics ^
  -projectPath "%PROJECT%" ^
  -buildTarget StandaloneWindows64 ^
  -executeMethod OldenEra.Homm3Import.Homm3ArrayUpscaleShaderBundleBuild.BuildFromBatch ^
  -outputPath "%OUT%" ^
  -logFile "%LOG%"
if errorlevel 1 (
  echo Shader bundle build failed; see %LOG%
  exit /b 1
)

echo Built %OUT%\homm3_array_upscale_shader
exit /b 0
