#!/usr/bin/env python3
"""Build homm3_artifact_map_billboards AssetBundle via Unity batchmode.

Sources cropped AVA map frames:
  OfflineUnlockMod/homm3_runtime_assets/artifacts/map/homm3_artifact_*/00_00.png

Bundle sprites are named artifact_map_billboard_<sid> (sid lowercased; non [a-z0-9_] -> _).

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
UNITY = Path(
    os.environ.get(
        "UNITY_EDITOR",
        r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe",
    )
)
PROJECT = Path(os.environ.get("OLDENERA_UNITY_PROJECT", REPO_ROOT / "oldenera_factions"))
OUT = SCRIPT_DIR / "build_out"
LOG = SCRIPT_DIR / "unity_homm3_artifact_map_billboard_bundle.log"
EDITOR_SRC = SCRIPT_DIR / "unity_editor" / "Homm3ArtifactMapBillboardBundleBuild.cs"

OFFLINE_UNLOCK_MOD = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
)
ARTIFACT_MAP = OFFLINE_UNLOCK_MOD / "homm3_runtime_assets" / "artifacts" / "map"
PLUGIN_STAGE = OFFLINE_UNLOCK_MOD / "homm3_artifact_map_billboards"

BUNDLE_NAME = "homm3_artifact_map_billboards"
ASSET_PREFIX = "artifact_map_billboard_"
SID_SANITIZE_RE = re.compile(r"[^a-z0-9_]")


def asset_name_for_sid(sid: str) -> str:
    sanitized = SID_SANITIZE_RE.sub("_", sid.strip().lower())
    if not sanitized:
        raise SystemExit(f"Artifact map SID sanitized empty: {sid!r}")
    return ASSET_PREFIX + sanitized


def collect_expected_asset_names(map_root: Path) -> set[str]:
    names: set[str] = set()
    source_by_name: dict[str, Path] = {}
    for sid_dir in sorted(map_root.glob("homm3_artifact_*")):
        if not sid_dir.is_dir():
            continue
        png = sid_dir / "00_00.png"
        if not png.is_file():
            continue
        name = asset_name_for_sid(sid_dir.name)
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
    if not ARTIFACT_MAP.is_dir():
        print(f"Artifact map dir missing: {ARTIFACT_MAP}", file=sys.stderr)
        return 1

    expected = collect_expected_asset_names(ARTIFACT_MAP)
    if not expected:
        print(f"No homm3_artifact_*/00_00.png frames found under {ARTIFACT_MAP}", file=sys.stderr)
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
        "OldenEra.Homm3Import.Homm3ArtifactMapBillboardBundleBuild.BuildFromBatch",
        "-artifactMapDir",
        str(ARTIFACT_MAP),
        "-outputPath",
        str(OUT),
        "-logFile",
        str(LOG),
    ]
    print("Using Unity project:", PROJECT)
    print("Artifact map source:", ARTIFACT_MAP)
    print("Running:", " ".join(cmd))
    proc = UQ.run_cmd(cmd, kind="artifact_map_billboard_bundle", direct=UNITY_DIRECT)
    if proc.returncode != 0:
        print(f"Artifact map billboard bundle build failed; see {LOG}", file=sys.stderr)
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
