#!/usr/bin/env python3
"""Replace HoMM3 lab adventure-map DEF cycles with RIFE dual-stream @ 50 FPS (10 native keys).

Reads each unit's defextract JSON under extracted_map/, interpolates the map walk/idle cycle
(group 2 idle preferred, else group 0 movement), updates the manifest, and backs up once to
extracted_map_source_10fps/.

Prereq: bash tools/homm3_import/setup_vfi_env.sh
Map extracts usually live under the Unity homm3_lab; use sync_homm3_lab_map_from_unity.py first.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

from homm3_rife_core import (
    DEFAULT_RIFE_EXE,
    DEFAULT_WORK_ROOT,
    configure_fps,
    interpolate_rgba_sequence_dual_stream,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAB_ROOT = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
)
BACKUP_DIR_NAME = "extracted_map_source_10fps"
DONE_META_NAME = ".rife_map_done.json"

MAP_SOURCE_FPS = 10
MAP_TARGET_FPS = 50
GROUP_IDLE = 2
GROUP_MOVEMENT = 0

RIFE_MODEL_DEFAULT = "rife-v4.6"
ALPHA_STABILIZE_ZERO_BELOW = 12
ALPHA_STABILIZE_OPAQUE_ABOVE = 248
ALPHA_STABILIZE_QUANT_STEP = 4


def find_map_manifest(map_dir: Path) -> Path | None:
    for path in sorted(map_dir.glob("*.json")):
        name = path.name.lower()
        if name == "manifest.json" or name == DONE_META_NAME.lower() or name.startswith("."):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue
        if isinstance(data.get("sequences"), list):
            return path
    return None


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=4) + "\n", encoding="utf-8")


def iter_lab_units_with_map(lab_root: Path) -> list[str]:
    if not lab_root.is_dir():
        return []
    out: list[str] = []
    for p in lab_root.iterdir():
        if not p.is_dir():
            continue
        map_dir = p / "extracted_map"
        if map_dir.is_dir() and find_map_manifest(map_dir):
            out.append(p.name)
    return sorted(out)


def pick_map_cycle(manifest: dict) -> tuple[dict, int] | None:
    by_group: dict[int, dict] = {}
    for seq in manifest.get("sequences") or []:
        group_id = int(seq.get("group", -1))
        frames = [str(f).strip() for f in (seq.get("frames") or []) if str(f or "").strip()]
        if frames:
            by_group[group_id] = seq
    for group_id in (GROUP_IDLE, GROUP_MOVEMENT):
        if group_id in by_group:
            return by_group[group_id], group_id
    return None


def load_done_meta(map_dir: Path, *, target_fps: int, source_fps: int) -> dict:
    path = map_dir / DONE_META_NAME
    if not path.is_file():
        return {"cycle": None, "targetFps": target_fps, "sourceFps": source_fps}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_done_meta(map_dir: Path, meta: dict, *, target_fps: int, source_fps: int) -> None:
    meta["targetFps"] = target_fps
    meta["sourceFps"] = source_fps
    (map_dir / DONE_META_NAME).write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )


def ensure_backup(map_dir: Path) -> None:
    backup = map_dir.parent / BACKUP_DIR_NAME
    if backup.is_dir():
        return
    ignore = shutil.ignore_patterns(BACKUP_DIR_NAME, DONE_META_NAME)
    shutil.copytree(map_dir, backup, ignore=ignore)
    print(f"  backup -> {backup.name}/")


def restore_from_source_backup(unit_dir: Path) -> None:
    map_dir = unit_dir / "extracted_map"
    backup = unit_dir / BACKUP_DIR_NAME
    if not backup.is_dir():
        raise FileNotFoundError(
            f"Cannot reset {unit_dir.name}: missing {BACKUP_DIR_NAME}/"
        )
    if map_dir.exists():
        shutil.rmtree(map_dir)
    ignore = shutil.ignore_patterns(DONE_META_NAME)
    shutil.copytree(backup, map_dir, ignore=ignore)


def resolve_frame_path(map_dir: Path, rel: str) -> Path:
    path = map_dir / rel.replace("\\", "/")
    if path.is_file():
        return path
    parts = rel.replace("\\", "/").split("/")
    if len(parts) == 2:
        folder_name, file_name = parts
        folder = map_dir / folder_name
        if not folder.is_dir():
            for candidate in map_dir.iterdir():
                if candidate.is_dir() and candidate.name.lower() == folder_name.lower():
                    folder = candidate
                    break
        candidate = folder / file_name
        if candidate.is_file():
            return candidate
        if folder.is_dir():
            for file_candidate in folder.iterdir():
                if file_candidate.is_file() and file_candidate.name.lower() == file_name.lower():
                    return file_candidate
    return path


def load_group_frames(map_dir: Path, rel_paths: list[str]):
    from PIL import Image

    frames = []
    for rel in rel_paths:
        path = resolve_frame_path(map_dir, rel)
        if not path.is_file():
            raise FileNotFoundError(path)
        frames.append(Image.open(path).convert("RGBA"))
    return frames


def dir_name_from_rel(rel: str) -> str:
    return rel.replace("\\", "/").split("/")[0]


def write_group_frames(
    map_dir: Path, group_id: int, dir_name: str, frames
) -> list[str]:
    out_dir = map_dir / dir_name
    out_dir.mkdir(parents=True, exist_ok=True)
    rel_paths: list[str] = []
    for i, frame in enumerate(frames):
        name = f"{group_id:02d}_{i:04d}.png"
        rel = f"{dir_name}\\{name}"
        frame.save(out_dir / name)
        rel_paths.append(rel)
    return rel_paths


def stabilize_alpha_edges(frames):
    from PIL import Image

    stabilized = []
    for frame in frames:
        rgba = np.asarray(frame.convert("RGBA"), dtype=np.uint8).copy()
        alpha = rgba[:, :, 3].astype(np.uint16)
        alpha[alpha <= ALPHA_STABILIZE_ZERO_BELOW] = 0
        alpha[alpha >= ALPHA_STABILIZE_OPAQUE_ABOVE] = 255
        soft = (alpha > 0) & (alpha < 255)
        if ALPHA_STABILIZE_QUANT_STEP > 1:
            step = ALPHA_STABILIZE_QUANT_STEP
            alpha[soft] = ((alpha[soft] + (step // 2)) // step) * step
            alpha[alpha > 255] = 255
            alpha[alpha <= ALPHA_STABILIZE_ZERO_BELOW] = 0
        rgba[:, :, 3] = alpha.astype(np.uint8)
        stabilized.append(Image.fromarray(rgba, mode="RGBA"))
    return stabilized


def remove_old_frame_files(map_dir: Path, old_rel_paths: list[str]) -> None:
    for rel in old_rel_paths:
        path = map_dir / rel.replace("\\", "/")
        if path.is_file():
            path.unlink()


def prune_stale_group_frames(
    map_dir: Path, dir_name: str, group_id: int, keep_rel_paths: list[str]
) -> None:
    keep = {rel.replace("\\", "/") for rel in keep_rel_paths}
    prefix = f"{group_id:02d}_"
    group_dir = map_dir / dir_name
    if not group_dir.is_dir():
        return
    for path in group_dir.glob(f"{prefix}*.png"):
        rel = f"{dir_name}\\{path.name}"
        if rel.replace("\\", "/") not in keep:
            path.unlink(missing_ok=True)


def update_map_authoring_fps(unit_dir: Path, *, target_fps: float, apply: bool) -> bool:
    auth = unit_dir / "authoring.json"
    if not auth.is_file():
        return False
    data = json.loads(auth.read_text(encoding="utf-8-sig"))
    if data.get("mapFlipBookFps") == float(target_fps):
        return False
    data["mapFlipBookFps"] = float(target_fps)
    if apply:
        auth.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def cycle_already_done(
    done_meta: dict,
    *,
    target_fps: int,
    group_id: int,
    rel_paths: list[str],
    map_dir: Path,
    force: bool,
) -> bool:
    if force:
        return False
    cycle = done_meta.get("cycle") or {}
    if not cycle.get("interpolated"):
        return False
    if int(cycle.get("targetFps") or 0) != target_fps:
        return False
    if int(cycle.get("group") or -1) != group_id:
        return False
    output_count = int(cycle.get("outputCount") or 0)
    if output_count <= 0 or len(rel_paths) != output_count:
        return False
    return (map_dir / rel_paths[0].replace("\\", "/")).is_file()


def assert_not_reinterpolating_dense(
    unit_sid: str,
    map_dir: Path,
    rel_paths: list[str],
    done_meta: dict,
    *,
    allow_reinterpolate: bool,
) -> None:
    if allow_reinterpolate:
        return
    cycle = done_meta.get("cycle") or {}
    if not cycle.get("interpolated"):
        return
    source_count = int(cycle.get("sourceCount") or 0)
    output_count = int(cycle.get("outputCount") or 0)
    if (
        source_count > 0
        and output_count > source_count
        and len(rel_paths) == output_count
        and rel_paths
        and (map_dir / rel_paths[0].replace("\\", "/")).is_file()
    ):
        raise RuntimeError(
            f"{unit_sid} map cycle already RIFE-expanded ({source_count}->{output_count}). "
            f"Use --reset-from-source-backup or --allow-reinterpolate-dense."
        )
    if source_count > 0 and len(rel_paths) >= source_count and len(rel_paths) > source_count:
        raise RuntimeError(
            f"{unit_sid} map manifest already dense ({len(rel_paths)} frames; "
            f"last sourceCount={source_count}). Use --reset-from-source-backup before RIFE."
        )


def process_unit(
    unit_sid: str,
    lab_root: Path,
    *,
    rife_exe: Path,
    work_root: Path,
    target_fps: int,
    source_fps: int,
    rife_model: str,
    force: bool,
    reuse_cache: bool,
    skip_backup: bool,
    stabilize_alpha: bool,
    dry_run: bool,
    reset_from_source_backup: bool,
    allow_reinterpolate_dense: bool,
) -> tuple[int, int]:
    unit_dir = lab_root / unit_sid
    map_dir = unit_dir / "extracted_map"
    manifest_path = find_map_manifest(map_dir)
    if not manifest_path:
        print(f"  skip: no map manifest under {map_dir}")
        return 0, 0

    if reset_from_source_backup:
        backup = unit_dir / BACKUP_DIR_NAME
        if not backup.is_dir() and not skip_backup:
            ensure_backup(map_dir)
        restore_from_source_backup(unit_dir)
        done_path = map_dir / DONE_META_NAME
        if done_path.is_file():
            done_path.unlink()

    manifest = load_manifest(manifest_path)
    picked = pick_map_cycle(manifest)
    if not picked:
        print("  skip: no map idle/movement cycle in manifest")
        return 0, 0

    seq, group_id = picked
    rel_paths = [str(f).strip() for f in (seq.get("frames") or []) if str(f or "").strip()]
    if len(rel_paths) < 2:
        print(f"  skip: group {group_id} has < 2 frames")
        return 0, 0

    done_meta = load_done_meta(map_dir, target_fps=target_fps, source_fps=source_fps)
    if cycle_already_done(
        done_meta,
        target_fps=target_fps,
        group_id=group_id,
        rel_paths=rel_paths,
        map_dir=map_dir,
        force=force,
    ):
        print(f"  skip: map cycle group {group_id} already @ {target_fps} FPS")
        return 0, 1

    assert_not_reinterpolating_dense(
        unit_sid,
        map_dir,
        rel_paths,
        done_meta,
        allow_reinterpolate=allow_reinterpolate_dense,
    )

    if dry_run:
        print(
            f"  dry-run: would RIFE group {group_id} "
            f"({len(rel_paths)} keys -> ~{target_fps} FPS)"
        )
        return 1, 0

    if not skip_backup:
        ensure_backup(map_dir)

    sources = load_group_frames(map_dir, rel_paths)
    dir_name = dir_name_from_rel(rel_paths[0])
    work_dir = work_root / unit_sid / f"map_g{group_id:02d}"
    if force and work_dir.exists():
        shutil.rmtree(work_dir)

    print(f"  RIFE map group {group_id}: {len(sources)} native keys -> {target_fps} FPS")
    dense = interpolate_rgba_sequence_dual_stream(
        sources,
        rife_exe=rife_exe,
        work_dir=work_dir,
        model_name=rife_model,
        reuse_cache=reuse_cache and not force,
    )
    if not dense:
        print("  FAIL: RIFE produced no frames")
        return 0, 0
    if stabilize_alpha:
        dense = stabilize_alpha_edges(dense)
        print(
            "  alpha stabilized "
            f"(zero<={ALPHA_STABILIZE_ZERO_BELOW}, "
            f"opaque>={ALPHA_STABILIZE_OPAQUE_ABOVE}, "
            f"quant={ALPHA_STABILIZE_QUANT_STEP})"
        )

    remove_old_frame_files(map_dir, rel_paths)
    new_rel = write_group_frames(map_dir, group_id, dir_name, dense)
    prune_stale_group_frames(map_dir, dir_name, group_id, new_rel)
    seq["frames"] = new_rel
    save_manifest(manifest_path, manifest)
    done_meta["cycle"] = {
        "interpolated": True,
        "group": group_id,
        "sourceCount": len(sources),
        "outputCount": len(dense),
        "targetFps": target_fps,
        "rifeModel": rife_model,
        "dir": dir_name,
        "alphaStabilized": bool(stabilize_alpha),
    }
    save_done_meta(map_dir, done_meta, target_fps=target_fps, source_fps=source_fps)
    if update_map_authoring_fps(unit_dir, target_fps=float(target_fps), apply=True):
        print(f"  authoring.json -> mapFlipBookFps={target_fps}")
    print(f"  OK {len(sources)} keys -> {len(dense)} frames")
    return 1, 0


def load_unit_list(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=DEFAULT_LAB_ROOT)
    parser.add_argument("--units", nargs="*", help="Lab unit SIDs")
    parser.add_argument("--unit-list", type=Path)
    parser.add_argument("--target-fps", type=int, default=MAP_TARGET_FPS)
    parser.add_argument("--source-fps", type=int, default=MAP_SOURCE_FPS)
    parser.add_argument("--rife-model", default=RIFE_MODEL_DEFAULT)
    parser.add_argument("--rife-exe", type=Path, default=DEFAULT_RIFE_EXE)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT / "map50")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--reuse-cache", action="store_true")
    parser.add_argument("--skip-backup", action="store_true")
    parser.add_argument(
        "--no-alpha-stabilize",
        action="store_true",
        help="Disable conservative post-RIFE alpha edge cleanup.",
    )
    parser.add_argument("--reset-from-source-backup", action="store_true")
    parser.add_argument("--allow-reinterpolate-dense", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_fps, target_fps, _ = configure_fps(args.source_fps, args.target_fps)

    if not args.dry_run and not args.rife_exe.is_file():
        print("Run setup first: bash tools/homm3_import/setup_vfi_env.sh", file=sys.stderr)
        return 1

    lab_root = args.lab_root.resolve()
    lab_units = set(iter_lab_units_with_map(lab_root))
    if args.unit_list:
        units = [u for u in load_unit_list(args.unit_list.resolve()) if u in lab_units]
        missing = [
            u
            for u in load_unit_list(args.unit_list.resolve())
            if u not in lab_units
        ]
        for u in missing:
            print(f"WARN: {u} has no extracted_map under {lab_root}", file=sys.stderr)
    elif args.units:
        units = [u for u in args.units if u in lab_units]
    else:
        units = sorted(lab_units)

    if not units:
        print(f"No map units to process under {lab_root}", file=sys.stderr)
        return 1

    print(
        f"Map RIFE ({args.rife_model}, dual-stream): {len(units)} unit(s), "
        f"{source_fps} -> {target_fps} FPS"
    )
    total_ok = 0
    total_skipped = 0
    for idx, unit_sid in enumerate(units, start=1):
        print(f"[{idx}/{len(units)}] {unit_sid}")
        ok, skipped = process_unit(
            unit_sid,
            lab_root,
            rife_exe=args.rife_exe,
            work_root=args.work_root,
            target_fps=target_fps,
            source_fps=source_fps,
            rife_model=args.rife_model,
            force=args.force,
            reuse_cache=args.reuse_cache,
            skip_backup=args.skip_backup,
            stabilize_alpha=not args.no_alpha_stabilize,
            dry_run=args.dry_run,
            reset_from_source_backup=args.reset_from_source_backup,
            allow_reinterpolate_dense=args.allow_reinterpolate_dense,
        )
        total_ok += ok
        total_skipped += skipped

    print(
        f"Done. Interpolated {total_ok} unit(s), skipped {total_skipped}, "
        f"from {len(units)} listed."
    )
    if not args.dry_run and total_ok:
        print(
            "Next: mirror_homm3_lab_battle_to_unity.py --include-map, then Unity "
            "RebuildAllFromManifest + bundles for these units."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
