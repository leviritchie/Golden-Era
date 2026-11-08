#!/usr/bin/env python3
"""Copy generated HoMM3 battle Texture2DArray manifests from Unity authoring."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNITY_PROJECT = REPO_ROOT / "oldenera_factions"
DEFAULT_SOURCE_LAB = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
)


def read_target_fps(lab_unit_root: Path) -> float | None:
    rife = lab_unit_root / "extracted_battle" / ".rife120_done.json"
    if rife.is_file():
        try:
            data = json.loads(rife.read_text(encoding="utf-8"))
            top = data.get("targetFps")
            if isinstance(top, (int, float)) and float(top) > 0:
                return float(top)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
    authoring = lab_unit_root / "authoring.json"
    if authoring.is_file():
        try:
            data = json.loads(authoring.read_text(encoding="utf-8"))
            fps = data.get("flipBookFps")
            if isinstance(fps, (int, float)) and float(fps) > 0:
                return float(fps)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
    return None


def normalize_manifest_fps(manifest_path: Path, target_fps: float | None) -> None:
    if target_fps is None or target_fps <= 0:
        return
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    clips = data.get("clips")
    if not isinstance(clips, list):
        return
    changed = False
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        if clip.get("fps") != target_fps:
            clip["fps"] = target_fps
            changed = True
    if changed:
        manifest_path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")


def copy_manifests(unity_lab: Path, target_lab: Path) -> int:
    count = 0
    for manifest in unity_lab.glob("*/Generated/BillboardAnim/array_battle_manifest.json"):
        rel = manifest.relative_to(unity_lab)
        dst = target_lab / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest, dst)
        unit_sid = manifest.parent.parent.parent.name
        target_fps = read_target_fps(target_lab / unit_sid)
        if target_fps is None:
            target_fps = read_target_fps(unity_lab / unit_sid)
        normalize_manifest_fps(dst, target_fps)
        count += 1
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--unity-project", type=Path, default=DEFAULT_UNITY_PROJECT)
    ap.add_argument("--target-lab", type=Path, default=DEFAULT_SOURCE_LAB)
    args = ap.parse_args()

    unity_lab = args.unity_project / "Assets/CustomUnits/homm3_lab"
    if not unity_lab.is_dir():
        raise SystemExit(f"Unity HoMM3 lab not found: {unity_lab}")
    copied = copy_manifests(unity_lab, args.target_lab)
    print(f"Copied {copied} array battle manifest(s) -> {args.target_lab}")
    return 0 if copied else 1


if __name__ == "__main__":
    raise SystemExit(main())
