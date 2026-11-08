"""Unity-editor proof renders for owned-skinned unit facing (native vs delivered, same rig).

    python tools/homm3_import/owned_skinned_facing_proof.py --rules before --tag before
    python tools/homm3_import/owned_skinned_facing_proof.py --rules after --tag after
    python tools/homm3_import/owned_skinned_facing_proof.py --rules fleet --tag fleet

Extracts the native donor (default troglodyte_upg_alt: the map shell every def_retarget cove/conflux unit uses)
read-only from the installed game with tools/homm3_style_compare/extract_native.py, stages
tools/homm3_import/unity_editor/Homm3FacingProofRig.cs into the Unity project, renders every lane
(map, preview synthetic / vanilla donor, battle left / right) through unitylock (memgate first), and composes a
labelled sheet. `--rules` picks the plugin composition (before = pre-fix, after = the native scale_roll yaw rule, fleet = native
yaw minus the fleet bind facing -60 in every lane, battle unchanged);
the lab prefab on disk supplies its baked Orientation yaw, so "before" must run before the lab rebuild.
Proof tier: generated-artifact (editor rig render of the lane compositions); not an in-game capture.
"""
from __future__ import annotations

import argparse
import json
import math
import re
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

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "oldenera_factions"
UNITY = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")
SRC = ROOT / "tools/homm3_import/unity_editor/Homm3FacingProofRig.cs"
STAGED = PROJECT / "Assets/Editor/Homm3FacingProof/Homm3FacingProofRig.cs"
MARKER = "HOMM3_FACING_PROOF_GENERATED"
OUT = ROOT / "artifacts/homm3_owned_skinned_facing_proof"
LANES = ["map", "preview_synthetic", "preview_vanilla", "battleL", "battleR"]
DEFAULT_PREFABS = ["hota_cove_oceanid", "hota_cove_tidecaller", "h3_dwarf"]
LEFT = re.compile(r"(?i)^(hip|shoulder|thigh)_l$|^(mixamorig:)?left(upleg|arm)$")
RIGHT = re.compile(r"(?i)^(hip|shoulder|thigh)_r$|^(mixamorig:)?right(upleg|arm)$")


def extract(prefab: str) -> Path:
    name = prefab.removesuffix("@authored").rsplit("/", 1)[-1]
    d = OUT / "native" / name
    if not (d / "mesh.npz").is_file():
        subprocess.run([sys.executable, str(ROOT / "tools/homm3_style_compare/extract_native.py"), "--out", str(OUT / "native"), prefab],
                       check=True, timeout=900)
    return d


def native_mesh(d: Path) -> tuple[dict, dict]:
    m = np.load(d / "mesh.npz")
    bones = json.loads((d / "bones.json").read_text(encoding="utf-8"))["bones"]
    ls = [np.asarray(v)[:3, 3] for k, v in bones.items() if LEFT.search(k)]
    rs = [np.asarray(v)[:3, 3] for k, v in bones.items() if RIGHT.search(k)]
    if not ls or not rs:
        raise SystemExit(f"FAIL: {d.name} has no left/right limb bones for a forward")
    fwd = np.cross(np.mean(rs, 0) - np.mean(ls, 0), [0.0, 1.0, 0.0])
    fwd = fwd / np.linalg.norm(fwd)
    subs = []
    for i in sorted(set(int(x) for x in m["mat"])):
        subs.append({"texture": str(d / f"mat_{i}.png"), "tri": m["tri"][m["mat"] == i].reshape(-1).astype(int).tolist()})
    mesh = {"name": d.name, "pos": np.round(m["pos"].reshape(-1), 5).tolist(), "uv": np.round(m["uv"].reshape(-1), 5).tolist(),
            "forward": [round(float(x), 5) for x in fwd], "subs": subs}
    return mesh, bones


def prefab_yaws(prefab: str) -> tuple[float, str, float]:
    """(root local yaw, first child name, first child local yaw) of an installed unit prefab, read with UnityPy."""
    import UnityPy
    game = "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data/"
    env = UnityPy.load(game + "globalgamemanagers", game + "resources.assets")
    mgr = next(o.read() for o in env.objects if o.type.name == "ResourceManager")
    cont = {str(k).lower(): v for k, v in mgr.m_Container}
    go = cont["units/" + prefab.removesuffix("@authored").lower()].read()
    root = next(c.read() for c in (x.component if hasattr(x, "component") else x for x in go.m_Component)
                if c.read().object_reader.type.name == "Transform")
    first = root.m_Children[0].read()

    def yaw(q):
        x, y, z, w = q.x, q.y, q.z, q.w
        return math.degrees(math.atan2(2 * (x * z + y * w), 1 - 2 * (x * x + y * y)))
    return yaw(root.m_LocalRotation), first.m_GameObject.read().m_Name, yaw(first.m_LocalRotation)


def run_unity(spec_path: Path, log: Path) -> None:
    subprocess.run([sys.executable, str(ROOT / "tools/homm3_def_retarget/memgate.py")], check=True, timeout=300)
    cmd = [str(UNITY), "-batchmode", "-quit", "-projectPath", str(PROJECT), "-homm3FacingProofSpec", str(spec_path),
           "-executeMethod", "OldenEra.Homm3FacingProof.Homm3FacingProofRig.RunFromCommandLine", "-logFile", str(log)]
    rc = UQ.run_cmd(cmd, kind="owned_skinned_facing_proof", timeout_s=3600, direct=UNITY_DIRECT).returncode
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    if rc != 0 or "HOMM3_FACING_PROOF_OK" not in text:
        raise SystemExit(f"FAIL: Unity rc={rc}; see {log}")


def compose(out: Path, prefabs: list[str], native: str, rules: str) -> Path:
    from PIL import Image, ImageDraw
    report = json.loads((out / "facing_report.json").read_text(encoding="utf-8"))
    tiles = {(t["lane"], t["unit"]): t for t in report["tiles"]}
    cols = ["native_" + native] + prefabs
    size, head, lab = 320, 36, 58
    sheet = Image.new("RGB", (len(cols) * size, head + len(LANES) * (size + lab)), (24, 24, 28))
    dr = ImageDraw.Draw(sheet)
    dr.text((8, 10), f"owned-skinned facing proof, rules={rules} (camera at -Z; green = faces camera)", fill=(235, 235, 235))
    for r, lane in enumerate(LANES):
        y = head + r * (size + lab)
        for c, unit in enumerate(cols):
            t = tiles.get((lane, unit))
            if not t:
                continue
            im = Image.open(out / t["png"]).convert("RGB").resize((size, size))
            sheet.paste(im, (c * size, y))
            ok = t["facesCamera"]
            colour = (90, 220, 110) if ok else (235, 80, 70) if ok is False else (200, 200, 200)
            dr.rectangle([c * size, y, c * size + size - 1, y + size - 1], outline=colour, width=3)
            baked = t.get("prefabBakedOrientationYaw")
            dr.text((c * size + 6, y + size + 4), f"{lane} | {unit}", fill=(235, 235, 235))
            dr.text((c * size + 6, y + size + 20), f"world fwd yaw {t['worldForwardYaw']}  vs camera {t['angleFromCameraDir']} deg", fill=colour)
            if baked is not None:
                dr.text((c * size + 6, y + size + 36), f"prefab baked Orientation yaw {baked}", fill=(190, 190, 190))
    path = out / f"facing_sheet_{rules}.png"
    sheet.save(path)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules", choices=("before", "after", "fleet"), required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--native", default="dungeon/1prefabs/troglodyte_upg_alt")
    ap.add_argument("--prefab", action="append", default=[])
    args = ap.parse_args()
    prefabs = args.prefab or DEFAULT_PREFABS
    battle_dir = extract(args.native)
    map_dir = extract(args.native + "_map@authored")
    battle, _ = native_mesh(battle_dir)
    mapm, _ = native_mesh(map_dir)
    battle_name = battle_dir.name
    map_root_yaw, map_first, map_first_yaw = prefab_yaws(args.native + "_map")
    battle_root_yaw, battle_first, battle_first_yaw = prefab_yaws(args.native)
    if not map_first.strip().lower().startswith("scale_roll") or not battle_first.strip().lower().startswith("scale_roll"):
        raise SystemExit(f"FAIL: first children are {map_first!r} / {battle_first!r}, not scale_roll")
    if abs(battle_root_yaw) > 1e-3:
        raise SystemExit(f"FAIL: battle prefab root yaw {battle_root_yaw}; the preview rig assumes an unrotated root")
    spec = {"schema": "homm3_owned_skinned_facing_proof.v1", "rules": args.rules,
            "outDir": str((OUT / args.tag).resolve()), "nativeName": battle_name,
            "nativeBattle": battle, "nativeMap": mapm,
            "mapShellRootYaw": round(map_root_yaw, 3),
            "mapScaleRollYaw": round(map_first_yaw, 3),
            "battleScaleRollYaw": round(battle_first_yaw, 3),
            "previewRootYaw": 22.0, "battleSideYawLeft": 150.0, "battleSideYawRight": -30.0,
            "bindFacingYaw": -60.0,
            "prefabs": [f"Assets/CustomUnits/homm3_lab/{p}/OwnedSkinned/owned_skinned.prefab" for p in prefabs], "tile": 384}
    out = OUT / args.tag
    out.mkdir(parents=True, exist_ok=True)
    spec_path = out / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    STAGED.parent.mkdir(parents=True, exist_ok=True)
    if STAGED.exists() and MARKER not in STAGED.read_text(encoding="utf-8", errors="replace"):
        raise SystemExit(f"FAIL: refusing to overwrite unmanaged {STAGED}")
    shutil.copy2(SRC, STAGED)
    run_unity(spec_path, out / "unity.log")
    sheet = compose(out, prefabs, battle_name, args.rules)
    print(json.dumps({"sheet": str(sheet), "mapShellRootYaw": spec["mapShellRootYaw"], "mapScaleRollYaw": spec["mapScaleRollYaw"],
                      "battleScaleRollYaw": spec["battleScaleRollYaw"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
