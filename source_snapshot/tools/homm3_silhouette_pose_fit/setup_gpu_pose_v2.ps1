[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\.." )).Path
$Venv = Join-Path $Root ".venv_gpu_pose_v2"
$Requirements = Join-Path $PSScriptRoot "requirements_gpu_pose_v2.txt"

$PyvenvCfg = Join-Path $Venv "pyvenv.cfg"
$NeedsRecreate = $Recreate -or (
    (Test-Path -LiteralPath $PyvenvCfg) -and
    ((Get-Content -LiteralPath $PyvenvCfg -Raw) -match "include-system-site-packages\s*=\s*false")
)
if ($NeedsRecreate -and (Test-Path -LiteralPath $Venv)) {
    Remove-Item -LiteralPath $Venv -Recurse -Force
}
if (-not (Test-Path -LiteralPath (Join-Path $Venv "Scripts\python.exe"))) {
    & $Python -m venv --system-site-packages $Venv
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install -r $Requirements
& $VenvPython -m ipykernel install --user --name "homm3-gpu-pose-v2" --display-name "Python 3 (HoMM3 GPU Pose V2)"
Write-Output (ConvertTo-Json -Depth 4 ([ordered]@{
    ok = $true
    environment = $Venv
    python = $VenvPython
    requirements = $Requirements
    note = "PyTorch is intentionally inherited from the existing CUDA installation; nvdiffrast is commit-pinned in the requirements file."
}))
