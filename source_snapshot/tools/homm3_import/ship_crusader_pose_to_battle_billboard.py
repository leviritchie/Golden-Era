#!/usr/bin/env python3
"""Ship fitted crusader poses into the existing combat billboard path.

Renders transparent DEF-sized frames from fixed_length poseSnapshots, overwrites
``h3_crusader`` extracted_battle PNGs (same filenames / counts), then rebuilds the
``custom_units_castle_h3_crusader`` bundle with SKIP_EXTRACT=1 SKIP_RIFE=1.

This is an intentional transitional ship: 3D-fitted mesh art on the live
Texture2DArray billboard contract (not a skinned-mesh battle prefab yet).

  py -3 tools/homm3_import/ship_crusader_pose_to_battle_billboard.py --render-only
  py -3 tools/homm3_import/ship_crusader_pose_to_battle_billboard.py --apply --rebuild
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
IMPORT = ROOT / "tools/homm3_import"
ART = ROOT / "artifacts/crusader_pose_pipeline"
OUT_STAGE = ART / "def_billboard_ship"
BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
LAB = ROOT / "oldenera_factions/Assets/CustomUnits/homm3_lab/h3_crusader"
BATTLE_DIR = LAB / "extracted_battle/CCRUSD.dir"
BATTLE_JSON = LAB / "extracted_battle/CCRUSD.json"
CONTRACT = ROOT / "custom_factions/contracts/homm3_bundle_payload_contract.json"
BUNDLE_NAME = "custom_units_castle_h3_crusader"
BUILD_OUT = IMPORT / "build_out" / BUNDLE_NAME

# Combat-critical DEF groups → fit dir + optional pose slice + loopable.
# Idle (2) / attack-front (12) are sliced from the combined idle_attack_front fit
# (8 idle native + 7 attack native).
GROUP_PLAN = {
    0: {
        "fit": "g00_move_fixed_length",
        "loopable": True,
        "pose_start": 0,
        "pose_end": -1,
    },
    2: {
        "fit": "idle_attack_front_fixed_length",
        "loopable": True,
        "pose_start": 0,
        "pose_end": 8,
    },
    3: {
        "fit": "g03_hitted_fixed_length",
        "loopable": False,
        "pose_start": 0,
        "pose_end": -1,
    },
    5: {
        "fit": "g05_death_fixed_length",
        "loopable": False,
        "pose_start": 0,
        "pose_end": -1,
    },
    11: {
        "fit": "g11_attack_up_fixed_length",
        "loopable": False,
        "pose_start": 0,
        "pose_end": -1,
    },
    12: {
        "fit": "idle_attack_front_fixed_length",
        "loopable": False,
        "pose_start": 8,
        "pose_end": -1,
    },
    13: {
        "fit": "g13_attack_down_fixed_length",
        "loopable": False,
        "pose_start": 0,
        "pose_end": -1,
    },
    20: {
        "fit": "g20_move_start_fixed_length",
        "loopable": False,
        "pose_start": 0,
        "pose_end": -1,
    },
    21: {
        "fit": "g21_move_end_fixed_length",
        "loopable": False,
        "pose_start": 0,
        "pose_end": -1,
    },
}


def _py() -> list[str]:
    return [sys.executable]


def _load_sequences() -> dict[int, list[str]]:
    doc = json.loads(BATTLE_JSON.read_text(encoding="utf-8"))
    out: dict[int, list[str]] = {}
    for row in doc["sequences"]:
        gid = int(row["group"])
        frames = []
        for fr in row["frames"]:
            # paths like ccrusd.dir\00_0000.png
            name = Path(str(fr).replace("\\", "/")).name
            frames.append(name)
        out[gid] = frames
    return out


def _detect_pad_width(names: list[str]) -> int:
    # 00_0000.png → 4; 01_00.png → 2
    sample = names[0]
    stem = Path(sample).stem  # 00_0000
    idx = stem.split("_", 1)[1]
    return len(idx)


def _render_group(gid: int, frame_names: list[str]) -> Path:
    plan = GROUP_PLAN[gid]
    fit_dir = ART / "out_fit" / plan["fit"]
    report = fit_dir / "fit_report.json"
    if not report.is_file():
        raise FileNotFoundError(f"missing fit report for group {gid}: {report}")
    out_dir = OUT_STAGE / f"g{gid:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pad = _detect_pad_width(frame_names)
    prefix = f"{gid:02d}_"
    cmd = [
        str(BLENDER),
        "-b",
        "--python",
        str(TOOL / "render_fitted_def_billboard_frames.py"),
        "--",
        "--fit-dir",
        str(fit_dir),
        "--out-dir",
        str(out_dir),
        "--frame-count",
        str(len(frame_names)),
        "--width",
        "450",
        "--height",
        "400",
        "--pose-start",
        str(plan["pose_start"]),
        "--pose-end",
        str(plan["pose_end"]),
        "--name-prefix",
        prefix,
        "--name-width",
        str(pad),
    ]
    if plan["loopable"]:
        cmd.append("--loopable")
    else:
        cmd.append("--no-loopable")
    log = out_dir / "render.log"
    with log.open("w", encoding="utf-8") as fh:
        rc = subprocess.run(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT).returncode
    if rc != 0:
        raise RuntimeError(f"render group {gid} failed rc={rc}; see {log}")
    # Fail-closed: every expected filename must exist.
    missing = [n for n in frame_names if not (out_dir / n).is_file()]
    if missing:
        raise RuntimeError(f"group {gid}: missing rendered frames: {missing[:5]}")
    return out_dir


def _backup_battle_dir() -> Path:
    bak = LAB / "extracted_battle" / f"CCRUSD.dir.bak_before_pose_ship"
    if bak.exists():
        return bak
    shutil.copytree(BATTLE_DIR, bak)
    return bak


def _apply_frames(groups: dict[int, list[str]]) -> dict:
    bak = _backup_battle_dir()
    applied = []
    for gid, names in groups.items():
        if gid not in GROUP_PLAN:
            continue
        src_dir = OUT_STAGE / f"g{gid:02d}"
        for name in names:
            src = src_dir / name
            dst = BATTLE_DIR / name
            if not src.is_file():
                raise FileNotFoundError(src)
            shutil.copy2(src, dst)
            applied.append(str(dst).replace("\\", "/"))
    return {"backup": str(bak).replace("\\", "/"), "copied": len(applied)}


def _update_contract_sha() -> dict:
    data = BUILD_OUT.read_bytes()
    digest = hashlib.sha256(data).hexdigest().upper()
    length = len(data)
    doc = json.loads(CONTRACT.read_text(encoding="utf-8-sig"))
    row = doc.setdefault("bundles", {}).setdefault(BUNDLE_NAME, {})
    prev = {"length": row.get("length"), "sha256": row.get("sha256")}
    row["length"] = length
    row["sha256"] = digest
    CONTRACT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {"previous": prev, "length": length, "sha256": digest}


def _rebuild_bundle() -> None:
    cmd = ["cmd.exe", "/c", "build_homm3_units.cmd", "h3_crusader"]
    env = os.environ.copy()
    env["SKIP_EXTRACT"] = "1"
    env["SKIP_RIFE"] = "1"
    log = IMPORT / "unity_crusader_pose_ship_build.log"
    with log.open("w", encoding="utf-8") as fh:
        rc = subprocess.run(
            cmd,
            cwd=str(IMPORT),
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
        ).returncode
    if rc != 0:
        raise RuntimeError(f"Unity rebuild failed rc={rc}; see {log}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--groups",
        type=int,
        nargs="+",
        default=sorted(GROUP_PLAN.keys()),
        help="DEF groups to render/apply",
    )
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--apply", action="store_true", help="Overwrite lab extracted_battle PNGs")
    ap.add_argument("--rebuild", action="store_true", help="SKIP_EXTRACT+SKIP_RIFE Unity rebuild")
    ap.add_argument("--update-contract", action="store_true", help="Refresh payload SHA/length")
    args = ap.parse_args()

    seqs = _load_sequences()
    for gid in args.groups:
        if gid not in GROUP_PLAN:
            raise SystemExit(f"no ship plan for group {gid}")
        if gid not in seqs:
            raise SystemExit(f"CCRUSD.json missing group {gid}")

    results = {"rendered": {}, "apply": None, "rebuild": None, "contract": None}
    for gid in args.groups:
        print(f"[ship-crusader] render group {gid} ({len(seqs[gid])} frames) …", flush=True)
        out = _render_group(gid, seqs[gid])
        results["rendered"][str(gid)] = str(out).replace("\\", "/")

    if args.apply:
        print("[ship-crusader] apply frames into lab extracted_battle …", flush=True)
        results["apply"] = _apply_frames({g: seqs[g] for g in args.groups})

    if args.rebuild:
        if not args.apply and not args.render_only:
            # rebuild without apply is allowed if frames already applied earlier
            pass
        print("[ship-crusader] rebuild Unity bundle (SKIP_EXTRACT SKIP_RIFE) …", flush=True)
        _rebuild_bundle()
        results["rebuild"] = {"ok": True, "bundle": str(BUILD_OUT).replace("\\", "/")}

    if args.update_contract:
        if not BUILD_OUT.is_file():
            raise SystemExit(f"missing bundle for contract update: {BUILD_OUT}")
        results["contract"] = _update_contract_sha()

    summary_path = OUT_STAGE / "ship_summary.json"
    OUT_STAGE.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "summary": str(summary_path).replace("\\", "/")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
