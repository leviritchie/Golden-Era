#!/usr/bin/env python3
"""Build homm3_ui_portraits AssetBundle via Unity batchmode.

Sources unit portraits (OfflineUnlockMod/homm3_portraits/h3_*.png) and upscaled hero
portraits (OfflineUnlockMod/homm3_hero_portraits_upscaled/homm3_*_hero_*.png). Hero masters
are 1254x1254; the Unity importer caps them at maxTextureSize 512 so the bundle carries the
runtime-size (<=512) textures rather than master-resolution payloads.

Bundle sprites are named ui_portrait_<sid>. An asset manifest JSON listing every bundled
sprite name is produced next to the bundle and staged beside it as manifest.json so runtime
code and validators can check membership without a LoadAllAssets decode.
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
LOG = SCRIPT_DIR / "unity_homm3_ui_portrait_bundle.log"
EDITOR_SRC = SCRIPT_DIR / "unity_editor" / "Homm3UiPortraitBundleBuild.cs"

OFFLINE_UNLOCK_MOD = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
)
UNIT_PORTRAITS = OFFLINE_UNLOCK_MOD / "homm3_portraits"
HERO_PORTRAITS_UPSCALED = OFFLINE_UNLOCK_MOD / "homm3_hero_portraits_upscaled"
PLUGIN_STAGE = OFFLINE_UNLOCK_MOD / "homm3_ui_portraits"

BUNDLE_NAME = "homm3_ui_portraits"
ASSET_PREFIX = "ui_portrait_"
UNIT_FILE_RE = re.compile(r"^h3_[a-z0-9_]+\.png$", re.IGNORECASE)
HERO_FILE_RE = re.compile(r"^homm3_.+_hero_\d+\.png$", re.IGNORECASE)


def collect_expected_asset_names(source_dir: Path, pattern: re.Pattern[str], label: str) -> set[str]:
    names: set[str] = set()
    for png in sorted(source_dir.glob("*.png")):
        if not pattern.fullmatch(png.name):
            raise SystemExit(
                f"Unexpected PNG file name under {source_dir}: {png.name} "
                f"(expected {label} pattern {pattern.pattern}). Refusing to bundle unscoped art."
            )
        names.add(ASSET_PREFIX + png.stem.lower())
    return names


def main() -> int:
    if not UNITY.is_file():
        print(f"Unity editor missing: {UNITY}", file=sys.stderr)
        return 1
    if not (PROJECT / "ProjectSettings" / "ProjectVersion.txt").is_file():
        print(f"Unity project missing: {PROJECT}", file=sys.stderr)
        return 1
    if not UNIT_PORTRAITS.is_dir():
        print(f"Unit portrait dir missing: {UNIT_PORTRAITS}", file=sys.stderr)
        return 1
    if not HERO_PORTRAITS_UPSCALED.is_dir():
        print(f"Hero portrait dir missing: {HERO_PORTRAITS_UPSCALED}", file=sys.stderr)
        return 1

    expected = collect_expected_asset_names(UNIT_PORTRAITS, UNIT_FILE_RE, "unit")
    expected |= collect_expected_asset_names(HERO_PORTRAITS_UPSCALED, HERO_FILE_RE, "hero")
    if not expected:
        print("No portrait PNGs found under the configured source dirs", file=sys.stderr)
        return 1
    print(f"Expected asset count: {len(expected)} "
          f"(unit={sum(1 for n in expected if n.startswith(ASSET_PREFIX + 'h3_'))}, "
          f"hero={sum(1 for n in expected if '_homm3_' in n)})")

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
        "OldenEra.Homm3Import.Homm3UiPortraitBundleBuild.BuildFromBatch",
        "-unitPortraitDir",
        str(UNIT_PORTRAITS),
        "-heroPortraitDir",
        str(HERO_PORTRAITS_UPSCALED),
        "-outputPath",
        str(OUT),
        "-logFile",
        str(LOG),
    ]
    print("Using Unity project:", PROJECT)
    print("Unit portrait source:", UNIT_PORTRAITS)
    print("Hero portrait source:", HERO_PORTRAITS_UPSCALED)
    print("Running:", " ".join(cmd))
    proc = UQ.run_cmd(cmd, kind="ui_portrait_bundle", direct=UNITY_DIRECT)
    if proc.returncode != 0:
        print(f"UI portrait bundle build failed; see {LOG}", file=sys.stderr)
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
