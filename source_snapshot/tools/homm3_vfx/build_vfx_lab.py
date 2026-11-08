"""Build the HoMM3 VFX lab assets in the Unity project (editor-only, one batch Unity process).

Copies a def_retarget GLB (copy, never the build output in place), the flipbook textures from
titan_vfx_textures.py, and Homm3VfxLabBuild.cs into oldenera_factions, then runs Unity batch to
make the preview prefab, extracted clips and flipbook ParticleSystem prefabs under
Assets/Homm3VfxLab/<unit>/. Fails closed if memgate is not OK or Unity.exe is already running.

Usage: python tools/homm3_vfx/build_vfx_lab.py [--payload DIR] [--timeout 900]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Unity jobs go through the Unity queue (docs/unity_queue_runner.md): agents submit, not launch. --unity-direct is the
# explicit, loudly logged opt-out.
import importlib.util as _uq_ilu  # noqa: E402
_uq_spec = _uq_ilu.spec_from_file_location("unity_queue", Path(__file__).resolve().parents[1] / "unity_queue" / "unity_queue.py")
UQ = _uq_ilu.module_from_spec(_uq_spec)
_uq_spec.loader.exec_module(UQ)
UNITY_DIRECT = UQ.take_direct_flag()

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "oldenera_factions"
UNITY = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")
EDITOR_SRC = Path(__file__).parent / "unity" / "Homm3VfxLabBuild.cs"
RUNTIME_SRC = Path(__file__).parent / "unity" / "Homm3VfxLabSkinRefresh.cs"
MARKER = "HOMM3_VFX_LAB_GENERATED"
CLIPS = ["Unit_AttackFront", "Unit_ShootFront", "Unit_Idle"]


def unity_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Unity.exe"], capture_output=True, text=True).stdout
    return "Unity.exe" in out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", default=str(ROOT / "artifacts/homm3_vfx_experiments/titan/work/unity_payload"))
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    payload = Path(a.payload)
    lab = json.loads((payload / "vfx_lab_spec.json").read_text())
    unit = lab["unitSid"]
    asset_root = f"Assets/Homm3VfxLab/{unit}"
    dest = PROJECT / asset_root
    dest.mkdir(parents=True, exist_ok=True)

    glb_dest = dest / f"{unit}_vfxlab.glb"
    src_glb = ROOT / lab["glb"]
    if not glb_dest.exists() or glb_dest.stat().st_size != src_glb.stat().st_size:
        shutil.copy2(src_glb, glb_dest)
    for s in lab["systems"]:
        shutil.copy2(payload / s["texture"], dest / s["texture"])

    editor_dir = PROJECT / "Assets/Editor/Homm3VfxLab"
    editor_dir.mkdir(parents=True, exist_ok=True)
    target = editor_dir / EDITOR_SRC.name
    if target.exists() and MARKER not in target.read_text(encoding="utf-8"):
        raise FileExistsError(f"refusing to overwrite unmanaged {target}")
    shutil.copy2(EDITOR_SRC, target)
    runtime_dir = PROJECT / "Assets/Homm3VfxLab/Scripts"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    helper = runtime_dir / RUNTIME_SRC.name
    if helper.exists() and MARKER not in helper.read_text(encoding="utf-8"):
        raise FileExistsError(f"refusing to overwrite unmanaged {helper}")
    shutil.copy2(RUNTIME_SRC, helper)

    unity_spec = {
        "schema": lab["schema"], "unitSid": unit, "assetRoot": asset_root,
        "glbAssetPath": f"{asset_root}/{glb_dest.name}", "clips": CLIPS,
        "prefabList": [{"name": k, "systems": v} for k, v in lab["prefabs"].items()],
        "systems": lab["systems"],
    }
    work = payload.parent / "unity_build"
    work.mkdir(exist_ok=True)
    spec_path = work / "unity_lab_spec.json"
    spec_path.write_text(json.dumps(unity_spec, indent=1))

    gate = subprocess.run([sys.executable, str(ROOT / "tools/homm3_def_retarget/memgate.py")], capture_output=True, text=True)
    print(gate.stdout.strip())
    if gate.returncode != 0:
        raise SystemExit("memgate not OK; not starting Unity")
    log = work / "unity_build.log"
    cmd = [str(UNITY), "-batchmode", "-quit", "-projectPath", str(PROJECT), "-homm3VfxLabSpec", str(spec_path),
           "-executeMethod", "OldenEra.Homm3Vfx.Homm3VfxLabBuild.BuildFromCommandLine", "-logFile", str(log)]
    done = UQ.run_cmd(cmd, kind="vfx_lab_build", timeout_s=a.timeout, direct=UNITY_DIRECT)
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    ok = done.returncode == 0 and "HOMM3_VFX_LAB_BUILD_OK" in text
    for line in text.splitlines():
        if "HOMM3_VFX_LAB" in line or "error CS" in line or "Exception" in line:
            print(line)
    print("exit", done.returncode, "OK" if ok else "FAILED", log)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
