#!/usr/bin/env python3
"""Re-emit current port town catalogs with their extracted native camera contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAN_DIR = ROOT / "tools" / "homm3_town_scene_meshes"
sys.path.insert(0, str(PAN_DIR))
import conflux_town_camera_pan as PAN

EXPECTED_FACTIONS = {
    "homm3_bulwark", "homm3_castle", "homm3_conflux", "homm3_cove", "homm3_dungeon", "homm3_factory",
    "homm3_fortress", "homm3_inferno", "homm3_necropolis", "homm3_rampart", "homm3_stronghold", "homm3_tower",
}


def verified_city_camera(path: Path, game_data_root: Path, label: str) -> tuple[dict, dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "homm3.vanilla_city_camera_pan.v2":
        raise SystemExit(f"{label} camera JSON must use v2 exact consumed-file provenance")
    if Path(str(doc.get("gameDataRoot", ""))).resolve() != game_data_root.resolve():
        raise SystemExit(f"{label} camera JSON gameDataRoot does not match {game_data_root}")
    rows = [row for row in doc.get("cities", []) if row.get("scene") == "cityHuman2"]
    if len(rows) != 1 or len(doc.get("cities", [])) != 1:
        raise SystemExit(f"{label} camera JSON must contain only one cityHuman2 row")
    row = rows[0]
    level = row["level"]
    expected_files = {level, f"sharedassets{level.replace('level', '')}.assets",
                      "globalgamemanagers.assets", Path(row["settingsRef"]["file"]).name}
    files = doc.get("gameFiles", {})
    if set(files) != expected_files:
        raise SystemExit(f"{label} camera JSON consumed-file provenance must be exactly {sorted(expected_files)}")
    for name, digest in files.items():
        if (not isinstance(digest, str) or len(digest) != 64 or
                any(ch not in "0123456789abcdef" for ch in digest)):
            raise SystemExit(f"{label} camera JSON has invalid SHA256 for {name}")
        source = game_data_root / name
        if not source.is_file():
            raise SystemExit(f"{label} consumed source file is missing: {source}")
        hasher = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise SystemExit(f"{label} consumed source file differs from the camera JSON: {source}")
    return doc, row


def require_camera_compatible(port: dict, canonical: dict) -> None:
    differences = PAN.native_layout_differences(port, canonical)
    if differences:
        raise SystemExit(f"cityHuman2 port camera differs from current Golden extraction at {differences}; "
                         "catalog retarget refused pending a measured framing adjustment")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", type=Path, required=True,
                    help="current Golden scene3d directory; only catalogs are read")
    ap.add_argument("--camera-json", type=Path, required=True,
                    help="v2 camera extraction made from the target port's game-data root")
    ap.add_argument("--camera-game-data-root", type=Path, required=True,
                    help="read-only target port HeroesOldenEra_Data root used by --camera-json")
    ap.add_argument("--canonical-camera-json", type=Path, required=True,
                    help="fresh v2 cityHuman2 extraction made from the Golden Era install")
    ap.add_argument("--canonical-game-data-root", type=Path, required=True,
                    help="read-only Golden Era HeroesOldenEra_Data root used by --canonical-camera-json")
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="separate staging directory for re-emitted catalogs; never the install tree")
    args = ap.parse_args()
    source_dir = args.source_dir.resolve()
    out_dir = args.out_dir.resolve()
    camera_json = args.camera_json.resolve()
    canonical_json = args.canonical_camera_json.resolve()
    camera_data_root = args.camera_game_data_root.resolve()
    canonical_data_root = args.canonical_game_data_root.resolve()
    if (not source_dir.is_dir() or not camera_json.is_file() or not canonical_json.is_file() or
            not camera_data_root.is_dir() or not canonical_data_root.is_dir()):
        raise SystemExit("source catalogs, camera JSONs, and their game-data roots must exist")
    if source_dir == out_dir or source_dir in out_dir.parents or out_dir in source_dir.parents:
        raise SystemExit("source-dir and out-dir must be separate, non-overlapping directories")

    _, port = verified_city_camera(camera_json, camera_data_root, "port")
    _, canonical = verified_city_camera(canonical_json, canonical_data_root, "Golden")
    rest_pose = PAN.rest_pose_contract("cityHuman2", pan_json=camera_json)
    require_camera_compatible(port, canonical)
    field_of_view = port.get("camera", {}).get("fieldOfView")
    if not isinstance(field_of_view, (int, float)) or not math.isfinite(field_of_view):
        raise SystemExit("camera-json lacks the native MainCamera field of view")

    source_catalogs = sorted(source_dir.glob("*/catalog.json"))
    actual_factions = {p.parent.name for p in source_catalogs}
    if actual_factions != EXPECTED_FACTIONS:
        raise SystemExit(f"expected all 12 current town catalogs; missing={sorted(EXPECTED_FACTIONS - actual_factions)}, "
                         f"unexpected={sorted(actual_factions - EXPECTED_FACTIONS)}")

    generated = []
    for source_path in source_catalogs:
        catalog = json.loads(source_path.read_text(encoding="utf-8"))
        reference = catalog.get("referenceCamera") or {}
        if catalog.get("schema") != "homm3_town_scene3d_catalog.v2" or not catalog.get("fullScene3d"):
            raise SystemExit(f"{source_path}: expected a full-3D v2 town catalog")
        catalog_fov = reference.get("fov")
        if not isinstance(catalog_fov, (int, float)) or not math.isclose(
                float(catalog_fov), float(field_of_view), rel_tol=0.0, abs_tol=1e-5):
            raise SystemExit(f"{source_path}: Golden catalog FOV {catalog_fov!r} differs from port MainCamera "
                             f"FOV {field_of_view!r}; no layout adjustment was applied")
        reference["restPose"] = rest_pose
        output_path = out_dir / source_path.parent.name / "catalog.json"
        payload = json.dumps(catalog, indent=1, ensure_ascii=True) + "\n"
        if output_path.is_file() and output_path.read_text(encoding="utf-8") != payload:
            raise SystemExit(f"refusing to overwrite different staged catalog: {output_path}")
        generated.append((output_path, payload, source_path.parent.name))

    for output_path, payload, _ in generated:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not output_path.exists():
            output_path.write_text(payload, encoding="utf-8")
    print(f"retargeted {len(generated)} catalog(s); only referenceCamera.restPose was changed")
    print(f"native source level SHA256: {rest_pose['sourceLevelSha256']}")
    print(f"native camera FOV: {field_of_view}")
    print(f"output: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
