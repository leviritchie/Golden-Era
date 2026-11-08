#!/usr/bin/env python3
"""Metal-shine Unity jobs through the shared Unity queue (docs/homm3_metal_shine.md, docs/unity_queue_runner.md).

  python tools/homm3_metal_shine/unity_jobs.py run [--no-bundle] [--no-lab] [--units ...]
  python tools/homm3_metal_shine/unity_jobs.py board          # compose the boards from the last lab output

One queue job (one editor launch) in the unit project V:/homm3_unity_work, the project, Unity version and build call
the battle BillboardArray shader ships from:
  * bundle: OldenEra/Homm3/MetalShine -> homm3_metal_shine_shader (StandaloneWindows64, ChunkBasedCompression), a
    load-back probe (shader_probe.json), then the bundle is copied into OfflineUnlockMod/homm3_mesh_fx/metal_shine/;
  * lab: offline orthographic renders at a battle-like camera (pitch 40 deg, sand arena sun), Hex/Lit replica body
    with and without the appended shine pass: a 12-step unit turn plus idle and attack samples.

Staged into the project: Assets/Editor/Homm3MetalShine/Homm3MetalShineBuild.cs, Assets/Homm3MetalShine/** (shaders
and lab textures). `unstage` removes them again. Scratch: V:/olden_port_work/metal_shine/.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("unity_queue", ROOT / "tools" / "unity_queue" / "unity_queue.py")
UQ = importlib.util.module_from_spec(_spec)
sys.modules["unity_queue"] = UQ
_spec.loader.exec_module(UQ)
UNITY_DIRECT = UQ.take_direct_flag()

PROJECT = Path("V:/homm3_unity_work")
SCRATCH = Path("V:/olden_port_work/metal_shine")
PLUGIN_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_mesh_fx" / "metal_shine"
SHADER_SRC = ROOT / "tools" / "homm3_import" / "unity_shaders" / "Homm3MetalShine.shader"
REPLICA_SRC = ROOT / "tools" / "homm3_prebake" / "unity" / "Homm3PrebakeHexLitReplica.shader"
EDITOR_SRC = HERE / "unity" / "Homm3MetalShineBuild.cs"
BUNDLE = "homm3_metal_shine_shader"
METHOD = "OldenEra.Homm3MetalShine.Homm3MetalShineBuild.RunAll"

STAGE_EDITOR = PROJECT / "Assets" / "Editor" / "Homm3MetalShine"
STAGE_ASSETS = PROJECT / "Assets" / "Homm3MetalShine"

# Battle-like lab view (Unity world, the game's sand arena light: docs/homm3_prebaked_lighting.md).
LAB = {"sunDir": [0.624, -0.4035, 0.6692], "sunColor": [1.0, 0.905, 0.672], "ambient": [0.347, 0.418, 0.591],
       "camPitch": 40.0, "camYaw": 0.0, "fill": 0.82, "tile": 256, "idleFrames": 8, "attackFrames": 8,
       "yaws": [float(y) for y in range(0, 360, 30)], "unitYaw": 90.0}


def stage(units: dict) -> dict:
    STAGE_EDITOR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EDITOR_SRC, STAGE_EDITOR / EDITOR_SRC.name)
    sh = STAGE_ASSETS / "Shaders"
    sh.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SHADER_SRC, sh / "Homm3MetalShine.shader")
    shutil.copy2(REPLICA_SRC, sh / "Homm3PrebakeHexLitReplica.shader")
    catalog = json.loads((PLUGIN_DIR / "catalog.json").read_text(encoding="utf-8"))
    by_sid = {e["match"]["unitSids"][0]: e for e in catalog["entries"]}
    lab_units = []
    for sid, spec in units.items():
        e = by_sid[sid]
        sel = json.loads((ROOT / "tools" / "homm3_def_retarget_delivery" / f"{spec['slice']}.json").read_text(encoding="utf-8"))
        inputs = ROOT / sel["out"] / sid / "inputs"
        d = STAGE_ASSETS / "Lab" / sid
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inputs / "basecolor.png", d / "basecolor.png")
        shutil.copy2(PLUGIN_DIR / e["mask"]["file"], d / "mask.png")
        own = f"Assets/CustomUnits/homm3_lab/{sid}/OwnedSkinned"
        lab_units.append({"sid": sid, "prefab": f"{own}/owned_skinned.prefab",
                          "basecolor": f"Assets/Homm3MetalShine/Lab/{sid}/basecolor.png",
                          "mask": f"Assets/Homm3MetalShine/Lab/{sid}/mask.png",
                          "idleClip": f"{own}/Animations/Unit_Idle.anim",
                          "attackClip": f"{own}/Animations/Unit_AttackFront.anim",
                          "shine": e["shine"]})
    return {**LAB, "outDir": str(SCRATCH / "lab"), "units": lab_units}


def unstage() -> None:
    for p in (STAGE_EDITOR, STAGE_ASSETS):
        if p.exists():
            shutil.rmtree(p)
        meta = p.with_name(p.name + ".meta")
        if meta.exists():
            meta.unlink()
    print("unstaged metal-shine files from", PROJECT)


def run(a) -> int:
    cfg = json.loads((HERE / "units.json").read_text(encoding="utf-8"))["units"]
    units = {k: v for k, v in cfg.items() if not a.units or k in a.units}
    SCRATCH.mkdir(parents=True, exist_ok=True)
    lab = stage(units)
    spec_path = SCRATCH / "lab_spec.json"
    spec_path.write_text(json.dumps(lab, indent=1), encoding="utf-8")
    bundle_out = SCRATCH / "bundle"
    if (SCRATCH / "lab").exists():
        shutil.rmtree(SCRATCH / "lab")
    args = []
    if not a.no_bundle:
        args += ["-metalShineOut", str(bundle_out)]
    if not a.no_lab:
        args += ["-metalShineLabSpec", str(spec_path)]
    res = UQ.launch(kind="metal_shine", method=METHOD, args=args, project=PROJECT, log=SCRATCH / "unity.log",
                    inputs=[spec_path, SHADER_SRC, EDITOR_SRC], output_dir=SCRATCH, graphics=True,
                    build_target="StandaloneWindows64", requester="metal_shine unity_jobs", direct=UNITY_DIRECT,
                    timeout_s=1800)
    print(json.dumps({k: res.get(k) for k in ("status", "exitCode", "error", "id") if k in res}))
    if res.get("status") != "ok":
        print("Unity job failed; see", SCRATCH / "unity.log", file=sys.stderr)
        return 1
    if not a.no_bundle:
        probe = json.loads((bundle_out / "shader_probe.json").read_text(encoding="utf-8"))
        print("probe:", probe)
        shutil.copy2(bundle_out / BUNDLE, PLUGIN_DIR / BUNDLE)
        shutil.copy2(bundle_out / "shader_probe.json", PLUGIN_DIR / "shader_probe.json")
        print("bundle ->", PLUGIN_DIR / BUNDLE)
    if not a.no_lab:
        board()
    return 0


def _label(img: Image.Image, text: str) -> Image.Image:
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 8 + 7 * len(text), 14], fill=(0, 0, 0))
    d.text((3, 1), text, fill=(255, 255, 255))
    return img


def board() -> int:
    lab = SCRATCH / "lab"
    out = SCRATCH / "boards"
    out.mkdir(parents=True, exist_ok=True)
    for ud in sorted(p for p in lab.iterdir() if p.is_dir()):
        sid = ud.name
        for seq, n in (("turn", len(LAB["yaws"])), ("idle", LAB["idleFrames"]), ("attack", LAB["attackFrames"])):
            rows = []
            for kind, title in (("base", "Hex/Lit replica (today)"), ("shine", "+ metal shine"), ("only", "shine pass only x2")):
                tiles = []
                for i in range(n):
                    im = Image.open(ud / f"{seq}_{i:02d}_{kind}.png").convert("RGB")
                    if kind == "only":   # shown x2 (on black) so the subtle default is readable
                        im = Image.fromarray(np.clip(np.asarray(im, np.float32) * 2, 0, 255).astype(np.uint8))
                    tag = f"yaw {int(LAB['yaws'][i])}" if seq == "turn" else f"{seq} {i}/{n}"
                    tiles.append(_label(im, tag if i else f"{title} | {tag}"))
                rows.append(np.concatenate([np.asarray(t) for t in tiles], 1))
            Image.fromarray(np.concatenate(rows, 0)).save(out / f"{sid}_{seq}_board.png")
        # close look: 4 yaws, base over shine, cropped to the unit and doubled (nearest)
        pick = [0, 3, 6, 9]
        cols = []
        for i in pick:
            a = np.asarray(Image.open(ud / f"turn_{i:02d}_base.png").convert("RGB"))
            b = np.asarray(Image.open(ud / f"turn_{i:02d}_shine.png").convert("RGB"))
            cols.append(np.concatenate([a, b], 0))
        z = np.concatenate(cols, 1)
        t = LAB["tile"]
        z = z[:, :]
        im = Image.fromarray(z).resize((z.shape[1] * 2, z.shape[0] * 2), Image.NEAREST)
        _label(im, f"{sid}: top = Hex/Lit replica today, bottom = + metal shine; yaws " + ", ".join(str(int(LAB['yaws'][i])) for i in pick))
        im.save(out / f"{sid}_zoom_board.png")
        print("boards ->", out)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--no-bundle", action="store_true")
    r.add_argument("--no-lab", action="store_true")
    r.add_argument("--units", nargs="*")
    sub.add_parser("board")
    sub.add_parser("unstage")
    a = ap.parse_args()
    if a.cmd == "run":
        return run(a)
    if a.cmd == "board":
        return board()
    unstage()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
