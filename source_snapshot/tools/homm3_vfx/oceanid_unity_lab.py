"""Render the oceanid flowing-water candidates in the Unity editor (one gated batch process).

Stages COPIES of the waterlab outputs (oceanid_water_lab.py) plus the lab shader and
Homm3OceanidWaterLab.cs into oldenera_factions (Assets/Homm3VfxLab/hota_cove_oceanid_water/ and
Assets/Editor/Homm3VfxLab/), then runs Unity batch. The editor script renders every variant through
the calibrated SpriteCam at DEF frame times into artifacts/homm3_vfx_experiments/oceanid/renders/.
Proof tier of the output: Unity-editor-rendered (lab replica shader, not the in-game Hex/Lit).

Fails closed if unitylock/memgate refuse, or a staged file would overwrite an unmanaged asset.

Usage: python tools/homm3_vfx/oceanid_unity_lab.py [--timeout 1500] [--v2]

--v2 renders the look lab (Homm3OceanidLookLab.cs) from oceanid_look_lab.py's outputs into renders_v2/.
Both modes launch Unity only through tools/homm3_vfx/unitylock.py (exclusive lock + memgate).
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
WORK = ROOT / "artifacts/homm3_vfx_experiments/oceanid/work"
OUT = ROOT / "artifacts/homm3_vfx_experiments/oceanid/renders"
ASSET_ROOT = "Assets/Homm3VfxLab/hota_cove_oceanid_water"
MARKER = "HOMM3_VFX_LAB_GENERATED"
SRC = Path(__file__).parent / "unity"

# SpriteCam calibrated for the oceanid DEF (Blender coords), shared with oceanid_water_lab.py
CAM = {"camRight": [0.9065, -0.4223, 0.0], "camUp": [0.0734, 0.1577, 0.9848],
       "camForward": [0.4158, 0.8927, -0.1739], "pxPerUnit": 39.672, "offset": [193.79, 266.47],
       "size": [450, 400]}
VARIANTS = ["current", "A_uvscroll", "B_flipbook", "B2_defpalette", "C_shell", "D_flag"]


def stage(src: Path, dst: Path, managed_text: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if managed_text and dst.exists() and MARKER not in dst.read_text(encoding="utf-8", errors="replace"):
        raise FileExistsError(f"refusing to overwrite unmanaged {dst}")
    if not dst.exists() or dst.stat().st_size != src.stat().st_size or managed_text:
        shutil.copy2(src, dst)


LOOK = ROOT / "artifacts/homm3_vfx_experiments/oceanid/look"
OUT2 = ROOT / "artifacts/homm3_vfx_experiments/oceanid/renders_v2"
VARIANTS_V2 = ["current", "L", "B2L", "F", "F2", "A2", "A", "FX", "accents_only", "mask"]


def run_unity(spec_path: Path, method: str, spec_flag: str, log: Path, ok_token: str, timeout: int) -> int:
    cmd = [str(UNITY), "-batchmode", "-quit", "-projectPath", str(PROJECT), spec_flag, str(spec_path),
           "-executeMethod", method, "-logFile", str(log)]
    done = UQ.run_cmd(cmd, kind="vfx_oceanid_lab", timeout_s=timeout, direct=UNITY_DIRECT)
    print(done.stdout[-2000:], done.stderr[-2000:])
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    ok = done.returncode == 0 and ok_token in text
    for line in text.splitlines():
        if ("HOMM3_OCEANID" in line and "animatorMaterialST" not in line and "animatorST" not in line) or "error CS" in line or "Exception" in line:
            print(line[:400])
    print("exit", done.returncode, "OK" if ok else "FAILED", log)
    return 0 if ok else 1


def sun_travel_unity(cond: str = "sand") -> list:
    """The prebake's camera-relative arena sun (views_meta sunFrom, Blender coords) as a Unity travel direction.
    v1's lab shader default (0.624,-0.4035,0.6692) was a fixed world direction that lit the SpriteCam view
    from behind; the prebake applies the arena MainLight relative to the battle camera."""
    vm = json.loads((ROOT / "artifacts/homm3_vfx_experiments/oceanid/prebake/views/views_meta.json").read_text())
    f = vm["views"]["sprite_f001"]["sunFrom"][cond]
    return [f[0], -f[2], f[1]]  # travel = -from; Blender (x,y,z) -> Unity (-x,z,-y)


def main_v2(a) -> int:
    meta = json.loads((LOOK / "look_meta.json").read_text())
    dest = PROJECT / ASSET_ROOT
    marker = dest / "HOMM3_VFX_LAB_GENERATED.txt"
    if dest.exists() and not marker.exists() and any(dest.iterdir()):
        raise FileExistsError(f"refusing to write into unmanaged {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    marker.write_text("managed by tools/homm3_vfx/oceanid_unity_lab.py\n")
    stage(WORK / "hota_cove_oceanid_waterlab.glb", dest / "hota_cove_oceanid_waterlab.glb", False)
    for n in ["look_static.png", "look_boil_atlas.png", "look_flow_atlas.png", "look_flow2_atlas.png", "look_tile_atlas.png", "look_tile0.png"]:
        stage(LOOK / n, dest / n, False)
    accents = []
    for aid, m in meta["accents"].items():
        stage(LOOK / m["sheet"], dest / m["sheet"], False)
        accents.append({"id": aid, "clip": m["clip"], "sheet": m["sheet"], "frameCount": m["frameCount"],
                        "cellPx": m["cellPx"], "centreOffsetPx": m["centreOffsetPx"]})
    stage(SRC / "Homm3OceanidHexLitLab.shader", dest / "Homm3OceanidHexLitLab.shader", True)
    stage(SRC / "Homm3OceanidLookLab.cs", PROJECT / "Assets/Editor/Homm3VfxLab/Homm3OceanidLookLab.cs", True)
    stage(SRC / "Homm3OceanidWaterLab.cs", PROJECT / "Assets/Editor/Homm3VfxLab/Homm3OceanidWaterLab.cs", True)
    OUT2.mkdir(parents=True, exist_ok=True)
    c, t = meta["cells"], meta["tile"]
    spec = {
        "schema": "homm3_oceanid_look_lab.v2", "assetRoot": ASSET_ROOT,
        "glbAssetPath": f"{ASSET_ROOT}/hota_cove_oceanid_waterlab.glb",
        "staticTex": "look_static.png", "boilAtlas": "look_boil_atlas.png", "flowAtlas": "look_flow_atlas.png", "flow2Atlas": "look_flow2_atlas.png",
        "tileAtlas": "look_tile_atlas.png", "tile0": "look_tile0.png",
        "cellST": [x for st in c["cellST"] for x in st],
        "clips": [{"name": k, "cells": v["cells"], "flow": [i % c["loop"] for i in range(len(v["cells"]))]}
                  for k, v in c["clips"].items()],
        "tileCellScaleX": t["cellScaleX"], "tileCellOffsetX": t["cellOffsetX"], "tileWorldHeight": t["tileWorldHeight"],
        "tileScrollPerSecond": t["scrollTilesPerSecond"], "accents": accents, "accentTowardCamera": 0.4,
        "outDir": str(OUT2), "scale": a.scale, **CAM, "variants": VARIANTS_V2,
        "sunTravelUnity": sun_travel_unity(),
        "subsampleVariants": ["B2L", "F", "F2", "A2", "A"], "subsampleClip": "Unit_Idle", "subsamplePerFrame": 4,
    }
    spec_path = OUT2 / "unity_lab_spec.json"
    spec_path.write_text(json.dumps(spec, indent=1))
    return run_unity(spec_path, "OldenEra.Homm3Vfx.Homm3OceanidLookLab.RunFromCommandLine", "-homm3OceanidLookSpec",
                     OUT2 / "unity_lab.log", "HOMM3_OCEANID_LOOK_OK", a.timeout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--v2", action="store_true")
    a = ap.parse_args()
    if a.v2:
        return main_v2(a)
    cells = json.loads((WORK / "cells.json").read_text())
    dest = PROJECT / ASSET_ROOT
    marker = dest / "HOMM3_VFX_LAB_GENERATED.txt"
    if dest.exists() and not marker.exists() and any(dest.iterdir()):
        raise FileExistsError(f"refusing to write into unmanaged {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    marker.write_text("managed by tools/homm3_vfx/oceanid_unity_lab.py\n")
    for n in ["hota_cove_oceanid_waterlab.glb", "boil_atlas.png", "boil_atlas_defpal.png", "sparkle_atlas.png", "scroll_tile.png"]:
        stage(WORK / n, dest / n, False)
    stage(SRC / "Homm3OceanidHexLitLab.shader", dest / "Homm3OceanidHexLitLab.shader", True)
    stage(SRC / "Homm3OceanidWaterLab.cs", PROJECT / "Assets/Editor/Homm3VfxLab/Homm3OceanidWaterLab.cs", True)

    OUT.mkdir(parents=True, exist_ok=True)
    spec = {
        "schema": "homm3_oceanid_unity_lab.v1", "assetRoot": ASSET_ROOT,
        "glbAssetPath": f"{ASSET_ROOT}/hota_cove_oceanid_waterlab.glb",
        "boilAtlas": "boil_atlas.png", "boilAtlasDefPalette": "boil_atlas_defpal.png", "sparkleAtlas": "sparkle_atlas.png", "scrollTile": "scroll_tile.png",
        "cellST": [x for st in cells["cellST"] for x in st],
        "clips": [{"name": k, "cells": v["cells"]} for k, v in cells["clips"].items()],
        "outDir": str(OUT), "scale": a.scale, **CAM,
        # A: tile scrolls down the column (v) at ~3 DEF px/frame; a travelling control the DEF does not draw
        "uvScroll": [0.0, 0.6],
        # D: Hex/Lit flag formula; k ~ 2pi / 5 DEF px band period, ~1 DEF px amplitude, 12 rad/s
        "flagDirection": [0.0, 50.0, 0.0], "flagPower": [0.025, 0.0, 0.025], "flagSpeed": 12.0,
        "shellOffset": 0.012,
        "variants": VARIANTS,
    }
    spec_path = OUT / "unity_lab_spec.json"
    spec_path.write_text(json.dumps(spec, indent=1))

    return run_unity(spec_path, "OldenEra.Homm3Vfx.Homm3OceanidWaterLab.RunFromCommandLine", "-homm3OceanidLabSpec",
                     OUT / "unity_lab.log", "HOMM3_OCEANID_LAB_OK", a.timeout)

if __name__ == "__main__":
    raise SystemExit(main())
