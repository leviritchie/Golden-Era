#!/usr/bin/env python3
"""Build homm3_map_billboards AssetBundle via Unity batchmode.

Sources the main billboard frames only (OfflineUnlockMod/homm3_runtime_assets/map_object_refs/
**/00_00.png); flipbook frames 00_01+ are intentionally excluded.

Bundle sprites are named map_billboard_<relative key>, where the relative key is deterministic
from the map_object_refs relative directory: strip a trailing .dir from the leaf component,
join components with "__", lowercase, and replace non [a-z0-9_] characters with "_"
(e.g. homm3_castle_city/capitol.dir/00_00.png -> map_billboard_homm3_castle_city__capitol).

An asset manifest JSON listing every bundled sprite name is produced next to the bundle and
staged beside it as manifest.json so runtime code and validators can check membership without
a LoadAllAssets decode.
"""

from __future__ import annotations

import json
import os
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

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
UNITY = Path(os.environ.get(
    "UNITY_EDITOR",
    r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe",
))
PROJECT = Path(os.environ.get("OLDENERA_UNITY_PROJECT", REPO_ROOT / "oldenera_factions"))
OUT = SCRIPT_DIR / "build_out"
LOG = SCRIPT_DIR / "unity_homm3_map_billboard_bundle.log"
EDITOR_SRC = SCRIPT_DIR / "unity_editor" / "Homm3MapBillboardBundleBuild.cs"

OFFLINE_UNLOCK_MOD = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
)
MAP_OBJECT_REFS = OFFLINE_UNLOCK_MOD / "homm3_runtime_assets" / "map_object_refs"
PLUGIN_STAGE = OFFLINE_UNLOCK_MOD / "homm3_map_billboards"

BUNDLE_NAME = "homm3_map_billboards"
ASSET_PREFIX = "map_billboard_"
KEY_SANITIZE_RE = re.compile(r"[^a-z0-9_]")


def derive_billboard_key(refs_root: Path, png_path: Path) -> str:
    relative = png_path.parent.relative_to(refs_root)
    parts = list(relative.parts)
    last = parts[-1]
    if last.lower().endswith(".dir"):
        last = last[: -len(".dir")]
        parts[-1] = last
    for part in parts:
        if not part or part == ".":
            raise SystemExit(
                f"Billboard frame is not under a named map_object_refs subdirectory: {png_path}"
            )
    joined = "__".join(parts).lower()
    return KEY_SANITIZE_RE.sub("_", joined)


def collect_expected_asset_names(refs_root: Path) -> set[str]:
    names: set[str] = set()
    source_by_name: dict[str, Path] = {}
    for png in sorted(refs_root.rglob("00_00.png")):
        name = ASSET_PREFIX + derive_billboard_key(refs_root, png)
        if name in source_by_name:
            raise SystemExit(
                f"Asset name collision for {name}: {source_by_name[name]} vs {png}"
            )
        source_by_name[name] = png
        names.add(name)
    return names


def main() -> int:
    if not UNITY.is_file():
        print(f"Unity editor missing: {UNITY}", file=sys.stderr)
        return 1
    if not (PROJECT / "ProjectSettings" / "ProjectVersion.txt").is_file():
        print(f"Unity project missing: {PROJECT}", file=sys.stderr)
        return 1
    if not MAP_OBJECT_REFS.is_dir():
        print(f"Map object refs dir missing: {MAP_OBJECT_REFS}", file=sys.stderr)
        return 1

    expected = collect_expected_asset_names(MAP_OBJECT_REFS)
    if not expected:
        print(f"No **/00_00.png billboard frames found under {MAP_OBJECT_REFS}", file=sys.stderr)
        return 1
    print(f"Expected asset count: {len(expected)}")

    editor_dst = PROJECT / "Assets" / "Editor"
    editor_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EDITOR_SRC, editor_dst / EDITOR_SRC.name)

    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(UNITY),
        "-batchmode",
        "-quit",
        "-nographics",
        "-projectPath",
        str(PROJECT),
        "-buildTarget",
        "StandaloneWindows64",
        "-executeMethod",
        "OldenEra.Homm3Import.Homm3MapBillboardBundleBuild.BuildFromBatch",
        "-mapObjectRefsDir",
        str(MAP_OBJECT_REFS),
        "-outputPath",
        str(OUT),
        "-logFile",
        str(LOG),
    ]
    print("Using Unity project:", PROJECT)
    print("Map object refs source:", MAP_OBJECT_REFS)
    print("Running:", " ".join(cmd))
    proc = UQ.run_cmd(cmd, kind="map_billboard_bundle", direct=UNITY_DIRECT)
    if proc.returncode != 0:
        print(f"Map billboard bundle build failed; see {LOG}", file=sys.stderr)
        return proc.returncode

    bundle = OUT / BUNDLE_NAME
    if not bundle.is_file():
        print(f"Expected bundle missing: {bundle}", file=sys.stderr)
        return 1

    manifest_path = OUT / f"{BUNDLE_NAME}.asset_manifest.json"
    if not manifest_path.is_file():
        print(f"Expected asset manifest missing: {manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_assets = set(manifest.get("assets", []))
    if manifest.get("bundle") != BUNDLE_NAME:
        print(f"Asset manifest bundle mismatch: {manifest.get('bundle')}", file=sys.stderr)
        return 1
    if manifest_assets != expected:
        missing = sorted(expected - manifest_assets)
        extra = sorted(manifest_assets - expected)
        print(
            f"Asset manifest membership mismatch: missing={missing[:5]} extra={extra[:5]} "
            f"(missing_count={len(missing)} extra_count={len(extra)})",
            file=sys.stderr,
        )
        return 1
    print(f"Asset manifest lists {len(manifest_assets)} sprite(s); membership matches source scan.")

    PLUGIN_STAGE.mkdir(parents=True, exist_ok=True)
    staged = PLUGIN_STAGE / BUNDLE_NAME
    shutil.copy2(bundle, staged)
    staged_manifest = PLUGIN_STAGE / "manifest.json"
    shutil.copy2(manifest_path, staged_manifest)
    print(f"Built and staged {staged} ({staged.stat().st_size} bytes)")
    print(f"Staged asset manifest {staged_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
