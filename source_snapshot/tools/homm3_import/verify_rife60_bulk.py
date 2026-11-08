#!/usr/bin/env python3
"""Verify the HoMM3 60 FPS dual-stream bulk RIFE/Texture2DArray deployment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LAB_ROOT = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
)
DEFAULT_MANIFEST = SCRIPT_DIR / "homm3_units_manifest.json"
DEFAULT_UNIT_LIST = SCRIPT_DIR / "rife_production_logs/manifest_eligible_no_temple_fangarm.txt"
DEFAULT_BUILD_OUT = SCRIPT_DIR / "build_out"
DEFAULT_GAME_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
)
DONE_META_NAME = ".rife120_done.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_units(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def manifest_bundles(path: Path) -> dict[str, str]:
    data = load_json(path)
    return {
        str(row.get("unitSid", "")).strip(): str(row.get("bundleName", "")).strip()
        for row in data.get("units", [])
        if str(row.get("unitSid", "")).strip()
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--unit-list", type=Path, default=DEFAULT_UNIT_LIST)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--lab-root", type=Path, default=DEFAULT_LAB_ROOT)
    ap.add_argument("--build-out", type=Path, default=DEFAULT_BUILD_OUT)
    ap.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    ap.add_argument("--target-fps", type=int, default=60)
    ap.add_argument("--rife-model", default="rife-v4.6")
    ap.add_argument("--alpha-mode", default="dual_stream")
    ap.add_argument("--require-unity", action="store_true")
    ap.add_argument("--require-deploy", action="store_true")
    args = ap.parse_args()

    units = read_units(args.unit_list.resolve())
    bundles = manifest_bundles(args.manifest.resolve())
    lab_root = args.lab_root.resolve()
    build_out = args.build_out.resolve()
    plugin_root = args.game_root.resolve() / "BepInEx/plugins/OfflineUnlockMod"

    failures: list[str] = []
    checked_meta = 0
    checked_arrays = 0
    checked_bundles = 0
    checked_deploy = 0

    for sid in units:
        unit_root = lab_root / sid
        meta_path = unit_root / "extracted_battle" / DONE_META_NAME
        if not meta_path.is_file():
            failures.append(f"{sid}: missing {DONE_META_NAME}")
        else:
            checked_meta += 1
            meta = load_json(meta_path)
            groups = meta.get("groups") or {}
            if not groups:
                failures.append(f"{sid}: no metadata groups")
            for group, row in groups.items():
                if not isinstance(row, dict) or not row.get("interpolated"):
                    continue
                if int(row.get("targetFps") or 0) != args.target_fps:
                    failures.append(f"{sid}: group {group} targetFps={row.get('targetFps')}")
                if str(row.get("rifeModel") or "") != args.rife_model:
                    failures.append(f"{sid}: group {group} rifeModel={row.get('rifeModel')}")
                if str(row.get("alphaMode") or "") != args.alpha_mode:
                    failures.append(f"{sid}: group {group} alphaMode={row.get('alphaMode')}")

        authoring_path = unit_root / "authoring.json"
        if authoring_path.is_file():
            authoring = load_json(authoring_path)
            for key in ("flipBookFps", "deathClipFps"):
                value = authoring.get(key)
                if float(value or 0) != float(args.target_fps):
                    failures.append(f"{sid}: authoring {key}={value}")

        array_manifest = unit_root / "Generated/BillboardAnim/array_battle_manifest.json"
        if array_manifest.is_file():
            checked_arrays += 1
            data = load_json(array_manifest)
            frame_count = int(data.get("frameCount") or 0)
            array_count = int(data.get("arrayCount") or 0)
            if frame_count <= 0:
                failures.append(f"{sid}: array manifest frameCount={frame_count}")
            if array_count <= 0:
                failures.append(f"{sid}: array manifest arrayCount={array_count}")
        elif args.require_unity:
            failures.append(f"{sid}: missing array_battle_manifest.json")

        bundle = bundles.get(sid)
        if not bundle:
            failures.append(f"{sid}: missing bundleName in manifest")
            continue
        if (build_out / bundle).is_file():
            checked_bundles += 1
        elif args.require_unity:
            failures.append(f"{sid}: missing build_out bundle {bundle}")

        if (plugin_root / "homm3_bundles" / bundle).is_file():
            checked_deploy += 1
        elif args.require_deploy:
            failures.append(f"{sid}: missing deployed bundle {bundle}")

        deployed_array = plugin_root / "homm3_lab" / sid / "Generated/BillboardAnim/array_battle_manifest.json"
        if args.require_deploy and not deployed_array.is_file():
            failures.append(f"{sid}: missing deployed array manifest")

    print(f"units: {len(units)}")
    print(f"metadata ok: {checked_meta}")
    print(f"array manifests: {checked_arrays}")
    print(f"build bundles: {checked_bundles}")
    print(f"deployed bundles: {checked_deploy}")
    if failures:
        print(f"failures: {len(failures)}")
        print("  " + "\n  ".join(failures[:80]))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
