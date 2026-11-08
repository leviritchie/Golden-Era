#!/usr/bin/env python3
"""Replace HoMM3 lab battle DEF frame sequences with RIFE v4.0 @ target FPS (production: 60) for Unity bundle builds.

Reads each unit's defextract JSON under extracted_battle/, runs rife-v4 with -n (10× frame count),
writes new PNGs into the same .dir folders, updates the manifest, and backs up the original tree once
to extracted_battle_source_12fps/.

Prereq: bash tools/homm3_import/setup_vfi_env.sh
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

from homm3_rife_core import (
    DEFAULT_RIFE_EXE,
    DEFAULT_WORK_ROOT,
    SOURCE_FPS,
    TARGET_FPS,
    configure_target_fps,
    interpolate_rgba_sequence,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAB_ROOT = (
    REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
)
DEFAULT_BUNDLE_MANIFEST = Path(__file__).resolve().parent / "homm3_units_manifest.json"
BACKUP_DIR_NAME = "extracted_battle_source_12fps"
DONE_META_NAME = ".rife120_done.json"

# DEF groups used by Homm3BillboardAnimatorBuild battle clips (plus projectile / teleport).
BATTLE_GROUP_IDS = frozenset({0, 1, 2, 3, 5, 11, 12, 13, 14, 15, 16, 20, 21})

TELEPORT_WALK_UNIT_SIDS = frozenset(
    {"hota_cove_nymph", "hota_cove_oceanid", "hota_cove_nereid"}
)

# Last native idle key prepended before attack keys before RIFE (group 12 only).
ATTACK_IDLE_TAIL_LEAD_UNIT_SIDS = frozenset({"h3_skeleton"})
GROUP_IDLE = 2
GROUP_ATTACK_FRONT = 12


def manifest_unit_sids(manifest_path: Path) -> list[str]:
    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    return sorted(
        {
            str(u.get("unitSid", "")).strip()
            for u in (data.get("units") or [])
            if str(u.get("unitSid", "")).strip()
        }
    )


def groups_with_frames(manifest: dict) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for seq in manifest.get("sequences") or []:
        group_id = int(seq.get("group", -1))
        rel = [str(f).strip() for f in (seq.get("frames") or []) if str(f or "").strip()]
        if rel:
            out[group_id] = rel
    return out


def effective_battle_groups(manifest: dict, unit_sid: str, *, skip_unused: bool) -> set[int]:
    """Groups needed for Unity clips + battle disk remap (optional skip of walk fallback group 1)."""
    by_group = groups_with_frames(manifest)
    needed: set[int] = set()
    for group_id in (2, 3, 5):
        if group_id in by_group:
            needed.add(group_id)
    for group_id in (0, 1, 2):
        if group_id in by_group:
            needed.add(group_id)
            break
    if unit_sid in TELEPORT_WALK_UNIT_SIDS or (20 in by_group and 21 in by_group):
        needed.update(g for g in (20, 21) if g in by_group)
    needed.update(g for g in (11, 12, 13, 14, 15, 16) if g in by_group)
    if skip_unused and 0 in needed and 1 in needed:
        needed.discard(1)
    return needed & BATTLE_GROUP_IDS

def find_battle_manifest(battle_dir: Path) -> Path | None:
    for path in sorted(battle_dir.glob("*.json")):
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


def iter_lab_units(lab_root: Path) -> list[str]:
    if not lab_root.is_dir():
        return []
    return sorted(
        p.name
        for p in lab_root.iterdir()
        if p.is_dir() and (p / "extracted_battle").is_dir()
    )


def load_done_meta(battle_dir: Path) -> dict:
    path = battle_dir / DONE_META_NAME
    if not path.is_file():
        return {"groups": {}, "targetFps": TARGET_FPS, "sourceFps": SOURCE_FPS}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_done_meta(battle_dir: Path, meta: dict) -> None:
    meta["targetFps"] = TARGET_FPS
    meta["sourceFps"] = SOURCE_FPS
    (battle_dir / DONE_META_NAME).write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )


def ensure_backup(battle_dir: Path) -> None:
    backup = battle_dir.parent / BACKUP_DIR_NAME
    if backup.is_dir():
        return
    ignore = shutil.ignore_patterns(BACKUP_DIR_NAME, DONE_META_NAME)
    shutil.copytree(battle_dir, backup, ignore=ignore)
    print(f"  backup -> {backup.name}/")


def restore_from_source_backup(unit_dir: Path) -> None:
    battle_dir = unit_dir / "extracted_battle"
    backup = unit_dir / BACKUP_DIR_NAME
    if not backup.is_dir():
        raise FileNotFoundError(
            f"Cannot reset {unit_dir.name}: missing {BACKUP_DIR_NAME}/"
        )
    if battle_dir.exists():
        shutil.rmtree(battle_dir)
    ignore = shutil.ignore_patterns(DONE_META_NAME)
    shutil.copytree(backup, battle_dir, ignore=ignore)


def assert_not_reinterpolating_dense_manifest(
    unit_sid: str,
    battle_dir: Path,
    manifest: dict,
    done_groups: dict[str, dict],
    *,
    allow_reinterpolate: bool,
) -> None:
    if allow_reinterpolate or not done_groups:
        return
    # When sparse native keys exist under extracted_battle_source_12fps, resume
    # and reinterpolate are safe (process_unit loads keys from that backup).
    backup = battle_dir.parent / BACKUP_DIR_NAME
    if backup.is_dir():
        return
    by_group = groups_with_frames(manifest)
    offenders: list[str] = []
    for key, prev in done_groups.items():
        if not prev.get("interpolated"):
            continue
        try:
            group_id = int(key)
        except ValueError:
            continue
        rel_paths = by_group.get(group_id) or []
        source_count = int(prev.get("sourceCount") or 0)
        output_count = int(prev.get("outputCount") or 0)
        if (
            source_count > 0
            and output_count > source_count
            and len(rel_paths) == output_count
            and rel_paths
            and (battle_dir / rel_paths[0].replace("\\", "/")).is_file()
        ):
            offenders.append(f"{group_id}:{source_count}->{output_count}")
    if offenders:
        raise RuntimeError(
            f"{unit_sid} appears to already contain RIFE-expanded frames "
            f"({', '.join(offenders[:5])}). Use --reset-from-source-backup to "
            "restore extracted_battle_source_12fps first, or pass "
            "--allow-reinterpolate-dense if double interpolation is intentional."
        )


def resolve_frame_path(battle_dir: Path, rel: str) -> Path:
    path = battle_dir / rel.replace("\\", "/")
    if path.is_file():
        return path
    parts = rel.replace("\\", "/").split("/")
    if len(parts) == 2:
        folder_name, file_name = parts
        folder = battle_dir / folder_name
        if not folder.is_dir():
            for candidate in battle_dir.iterdir():
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


def load_group_frames(battle_dir: Path, rel_paths: list[str]) -> list[Image.Image]:
    from homm3_vcmi_png_alpha import open_sprite_rgba

    frames: list[Image.Image] = []
    for rel in rel_paths:
        path = resolve_frame_path(battle_dir, rel)
        if not path.is_file():
            raise FileNotFoundError(path)
        # DEF extracts are already RGBA with special-slot alpha. HotA JSON+PNG
        # mode-P frames key transparency by palette index (often cyan @ 0) with
        # no tRNS — naive convert("RGBA") leaves an opaque cyan plate.
        frames.append(open_sprite_rgba(path))
    return frames


def load_native_group_sources(
    unit_dir: Path, group_id: int
) -> tuple[list[Image.Image], str] | None:
    """Sparse DEF keyframes from extracted_battle_source_12fps (never dense RIFE output)."""
    backup = unit_dir / BACKUP_DIR_NAME
    if not backup.is_dir():
        return None
    manifest_path = find_battle_manifest(backup)
    if not manifest_path:
        return None
    manifest = load_manifest(manifest_path)
    for seq in manifest.get("sequences") or []:
        if int(seq.get("group", -1)) != group_id:
            continue
        rel_paths = [str(f).strip() for f in (seq.get("frames") or []) if str(f or "").strip()]
        if not rel_paths:
            return None
        return load_group_frames(backup, rel_paths), dir_name_from_rel(rel_paths[0])
    return None


def attack_sources_with_idle_tail_lead(
    unit_sid: str, unit_dir: Path
) -> tuple[list[Image.Image], str] | None:
    if unit_sid not in ATTACK_IDLE_TAIL_LEAD_UNIT_SIDS:
        return None
    idle = load_native_group_sources(unit_dir, GROUP_IDLE)
    attack = load_native_group_sources(unit_dir, GROUP_ATTACK_FRONT)
    if not idle or not attack:
        return None
    idle_frames, _ = idle
    attack_frames, attack_dir = attack
    sources = [idle_frames[-1].copy(), *attack_frames]
    return sources, attack_dir


def dir_name_from_rel(rel: str) -> str:
    return rel.replace("\\", "/").split("/")[0]


def write_group_frames(
    battle_dir: Path, group_id: int, dir_name: str, frames: list[Image.Image]
) -> list[str]:
    out_dir = battle_dir / dir_name
    out_dir.mkdir(parents=True, exist_ok=True)
    rel_paths: list[str] = []
    for i, frame in enumerate(frames):
        name = f"{group_id:02d}_{i:04d}.png"
        rel = f"{dir_name}\\{name}"
        frame.save(out_dir / name)
        rel_paths.append(rel)
    return rel_paths


def remove_old_frame_files(battle_dir: Path, old_rel_paths: list[str]) -> None:
    for rel in old_rel_paths:
        path = battle_dir / rel.replace("\\", "/")
        if path.is_file():
            path.unlink()


def prune_stale_group_frames(
    battle_dir: Path, dir_name: str, group_id: int, keep_rel_paths: list[str]
) -> None:
    """Drop orphan PNGs for this DEF group (e.g. native 02_00.png after 02_0000.png)."""
    keep = {rel.replace("\\", "/") for rel in keep_rel_paths}
    prefix = f"{group_id:02d}_"
    group_dir = battle_dir / dir_name
    if not group_dir.is_dir():
        return
    for path in group_dir.glob(f"{prefix}*.png"):
        rel = f"{dir_name}\\{path.name}"
        if rel.replace("\\", "/") not in keep:
            path.unlink(missing_ok=True)


def update_authoring_fps(unit_dir: Path, *, apply: bool) -> bool:
    auth = unit_dir / "authoring.json"
    if not auth.is_file():
        return False
    data = json.loads(auth.read_text(encoding="utf-8-sig"))
    changed = False
    for key in ("flipBookFps", "deathClipFps"):
        if data.get(key) != float(TARGET_FPS):
            data[key] = float(TARGET_FPS)
            changed = True
    if changed and apply:
        auth.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changed


def mirror_to_unity_lab(unit_sid: str, lab_root: Path, unity_lab: Path) -> None:
    src = lab_root / unit_sid / "extracted_battle"
    dst = unity_lab / unit_sid / "extracted_battle"
    if not src.is_dir() or unity_lab == lab_root:
        return
    if dst.exists():
        shutil.rmtree(dst)
    ignore = shutil.ignore_patterns(BACKUP_DIR_NAME)
    shutil.copytree(src, dst, ignore=ignore)
    src_auth = lab_root / unit_sid / "authoring.json"
    dst_auth = unity_lab / unit_sid / "authoring.json"
    if src_auth.is_file() and dst_auth.parent.is_dir():
        shutil.copy2(src_auth, dst_auth)


def process_unit(
    unit_sid: str,
    lab_root: Path,
    *,
    rife_exe: Path,
    work_root: Path,
    force: bool,
    reuse_cache: bool,
    skip_backup: bool,
    groups_filter: set[int] | None,
    skip_unused_groups: bool,
    dry_run: bool,
    dual_stream_alpha: bool,
    rife_model: str,
    reset_from_source_backup: bool,
    allow_reinterpolate_dense: bool,
) -> tuple[int, int]:
    unit_dir = lab_root / unit_sid
    if reset_from_source_backup and not dry_run:
        restore_from_source_backup(unit_dir)
        unit_work_dir = work_root / unit_sid
        if unit_work_dir.exists():
            shutil.rmtree(unit_work_dir)
        print(f"  reset -> {BACKUP_DIR_NAME}/ (cleared RIFE cache for unit)")

    battle_dir = lab_root / unit_sid / "extracted_battle"
    manifest_path = find_battle_manifest(battle_dir)
    if not manifest_path:
        print(f"  skip: no defextract JSON in {battle_dir}")
        return 0, 0

    manifest = load_manifest(manifest_path)
    sequences = manifest.get("sequences") or []
    allowed_groups = effective_battle_groups(manifest, unit_sid, skip_unused=skip_unused_groups)
    done_meta = load_done_meta(battle_dir)
    done_groups: dict[str, dict] = done_meta.setdefault("groups", {})
    assert_not_reinterpolating_dense_manifest(
        unit_sid,
        battle_dir,
        manifest,
        done_groups,
        allow_reinterpolate=allow_reinterpolate_dense,
    )

    if not skip_backup and not dry_run:
        ensure_backup(battle_dir)

    # Always read sparse native keys from backup when present. HotA JSON+PNG
    # sequences (COLGOIX/CJUGGER/CSANDWX/…) reuse filenames across groups;
    # remove_old_frame_files after group N would break later groups if we still
    # loaded keys from the mutating battle_dir.
    backup_dir = unit_dir / BACKUP_DIR_NAME
    source_battle_dir = backup_dir if backup_dir.is_dir() else battle_dir

    alpha_mode = "dual_stream" if dual_stream_alpha else "key_alpha"
    ok = 0
    skipped = 0
    for seq in sequences:
        group_id = int(seq.get("group", -1))
        if group_id not in allowed_groups:
            continue
        if groups_filter and group_id not in groups_filter:
            continue
        rel_paths = [str(f).strip() for f in (seq.get("frames") or []) if str(f or "").strip()]
        if not rel_paths:
            continue

        cache_key = str(group_id)
        prev = done_groups.get(cache_key)
        idle_tail_lead = (
            unit_sid in ATTACK_IDLE_TAIL_LEAD_UNIT_SIDS and group_id == GROUP_ATTACK_FRONT
        )
        if (
            not force
            and prev
            and prev.get("interpolated")
            and prev.get("targetFps") == TARGET_FPS
            and prev.get("alphaMode", "key_alpha") == alpha_mode
            and prev.get("rifeModel", "rife-v4") == rife_model
            and prev.get("outputCount") == len(rel_paths)
            and bool(prev.get("idleTailLead")) == idle_tail_lead
            and (battle_dir / rel_paths[0].replace("\\", "/")).is_file()
        ):
            skipped += 1
            continue

        mode_label = f"{rife_model} dual-stream" if dual_stream_alpha else f"{rife_model}"
        print(f"  group {group_id}: {len(rel_paths)} source frames -> RIFE {mode_label}...")
        if dry_run:
            ok += 1
            continue

        dir_name = dir_name_from_rel(rel_paths[0])
        lead = (
            attack_sources_with_idle_tail_lead(unit_sid, unit_dir) if idle_tail_lead else None
        )
        if lead:
            sources, dir_name = lead
            print(
                f"    idle-tail-lead: 1 idle + {len(sources) - 1} attack native keys "
                f"({len(sources)} total)"
            )
        else:
            if idle_tail_lead:
                print(
                    "    WARN idle-tail-lead: missing backup native idle/attack; "
                    "using current manifest paths"
                )
            try:
                sources = load_group_frames(source_battle_dir, rel_paths)
            except FileNotFoundError as ex:
                print(f"    FAIL missing frame: {ex}")
                raise

        work_dir = work_root / unit_sid / f"g{group_id:02d}"
        if idle_tail_lead and force and work_dir.exists():
            shutil.rmtree(work_dir)
        try:
            dense = interpolate_rgba_sequence(
                sources,
                rife_exe=rife_exe,
                work_dir=work_dir,
                model_name=rife_model,
                reuse_cache=reuse_cache and not force,
                dual_stream_alpha=dual_stream_alpha,
            )
        except Exception as ex:
            print(f"    FAIL RIFE group {group_id}: {ex}")
            raise

        if not dense:
            print(f"    WARN group {group_id}: no output frames")
            continue

        # Remove native/previous paths before writing dense 4-digit frames. Doing this
        # after write deletes the new files when rel_paths already lists dense names.
        remove_old_frame_files(battle_dir, rel_paths)
        new_rel = write_group_frames(battle_dir, group_id, dir_name, dense)
        prune_stale_group_frames(battle_dir, dir_name, group_id, new_rel)
        seq["frames"] = new_rel
        done_groups[cache_key] = {
            "interpolated": True,
            "sourceCount": len(sources),
            "outputCount": len(dense),
            "targetFps": TARGET_FPS,
            "alphaMode": alpha_mode,
            "rifeModel": rife_model,
            "dir": dir_name,
            "idleTailLead": idle_tail_lead,
        }
        ok += 1
        print(f"    OK {len(sources)} keys -> {len(dense)} frames @ {TARGET_FPS} FPS")

    if not dry_run and ok:
        save_manifest(manifest_path, manifest)
        save_done_meta(battle_dir, done_meta)
        if update_authoring_fps(lab_root / unit_sid, apply=True):
            print(f"  authoring.json -> flipBookFps/deathClipFps={TARGET_FPS}")

    return ok, skipped


def load_unit_list(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=DEFAULT_LAB_ROOT)
    parser.add_argument(
        "--unity-project",
        type=Path,
        default=None,
        help="After each unit, mirror battle frames into Unity (slow for batch; prefer mirror_homm3_lab_battle_to_unity.py)",
    )
    parser.add_argument(
        "--bundle-manifest",
        type=Path,
        default=DEFAULT_BUNDLE_MANIFEST,
        help="Used with --manifest-only to limit units",
    )
    parser.add_argument("--manifest-only", action="store_true", help="Only units listed in bundle manifest")
    parser.add_argument("--unit-list", type=Path, help="Text file of unitSid rows (like remaining_faction_unit_sids.txt)")
    parser.add_argument("--units", nargs="*", help="Unit SIDs (default: all with extracted_battle)")
    parser.add_argument("--groups", nargs="*", type=int, help="Limit DEF group ids")
    parser.add_argument(
        "--all-battle-groups",
        action="store_true",
        help="Interpolate every battle DEF group in the manifest (default: clip + disk-remap subset only)",
    )
    parser.add_argument("--target-fps", type=int, default=TARGET_FPS)
    parser.add_argument(
        "--rife-model",
        default="rife-v4",
        help="rife-ncnn model folder name (default rife-v4; use rife-v4.6 with --dual-stream-alpha)",
    )
    parser.add_argument(
        "--dual-stream-alpha",
        action="store_true",
        help="Separate RIFE pass on alpha mask + gray-plate RGB (RIFE-with-Transparency style)",
    )
    parser.add_argument("--rife-exe", type=Path, default=DEFAULT_RIFE_EXE)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--force", action="store_true", help="Re-run even if .rife120_done.json matches")
    parser.add_argument("--reuse-cache", action="store_true", help="Reuse tools/.cache/vfi-work PNGs")
    parser.add_argument(
        "--reset-from-source-backup",
        action="store_true",
        help=f"Replace extracted_battle from {BACKUP_DIR_NAME}/ before interpolating and clear that unit's RIFE cache",
    )
    parser.add_argument(
        "--allow-reinterpolate-dense",
        action="store_true",
        help="Allow RIFE over a manifest already marked as interpolated (normally refused)",
    )
    parser.add_argument("--skip-backup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-file", type=Path, help="Append-friendly log path")
    args = parser.parse_args()

    # Keep this module's imported TARGET_FPS binding in sync with homm3_rife_core.
    # The long-running bulk scripts depend on --target-fps overriding the historic
    # 120 FPS default for metadata, authoring, skip checks, and logging.
    globals()["TARGET_FPS"], _ = configure_target_fps(args.target_fps)

    if not args.dry_run and not args.rife_exe.is_file():
        print("Run setup first: bash tools/homm3_import/setup_vfi_env.sh", file=sys.stderr)
        return 1

    lab_root = args.lab_root.resolve()
    lab_units = set(iter_lab_units(lab_root))
    if args.unit_list:
        units = [u for u in load_unit_list(args.unit_list.resolve()) if u in lab_units]
    elif args.units:
        units = [u for u in args.units if u in lab_units]
    elif args.manifest_only:
        manifest_sids = set(manifest_unit_sids(args.bundle_manifest.resolve()))
        units = sorted(manifest_sids & lab_units)
    else:
        units = sorted(lab_units)

    if not units:
        print(f"No units to process under {lab_root}", file=sys.stderr)
        return 1

    groups_filter = set(args.groups) if args.groups else None
    skip_unused = not args.all_battle_groups
    unity_lab = None
    if args.unity_project:
        unity_lab = (args.unity_project.resolve() / "Assets" / "CustomUnits" / "homm3_lab")

    log_fp = None
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        log_fp = args.log_file.open("a", encoding="utf-8")

    def log(msg: str) -> None:
        print(msg, flush=True)
        if log_fp:
            log_fp.write(msg + "\n")
            log_fp.flush()

    log(
        f"RIFE production ({args.rife_model}"
        f"{', dual-stream alpha' if args.dual_stream_alpha else ''}): "
        f"{len(units)} unit(s), target {TARGET_FPS} FPS, "
        f"manifest_only={args.manifest_only}, skip_unused_groups={skip_unused}"
    )

    total_ok = 0
    total_skipped = 0
    for idx, unit_sid in enumerate(units, start=1):
        log(f"[{idx}/{len(units)}] {unit_sid}")
        ok, skipped = process_unit(
            unit_sid,
            lab_root,
            rife_exe=args.rife_exe,
            work_root=args.work_root,
            force=args.force,
            reuse_cache=args.reuse_cache,
            skip_backup=args.skip_backup,
            groups_filter=groups_filter,
            skip_unused_groups=skip_unused,
            dry_run=args.dry_run,
            dual_stream_alpha=args.dual_stream_alpha,
            rife_model=args.rife_model,
            reset_from_source_backup=args.reset_from_source_backup,
            allow_reinterpolate_dense=args.allow_reinterpolate_dense,
        )
        total_ok += ok
        total_skipped += skipped
        if skipped:
            log(f"  ({skipped} group(s) already at {TARGET_FPS} FPS)")
        if unity_lab and ok and not args.dry_run:
            mirror_to_unity_lab(unit_sid, lab_root, unity_lab)
            log(f"  mirrored -> {unity_lab / unit_sid}")

    log(
        f"Done. Interpolated {total_ok} sequence(s), skipped {total_skipped} group(s), "
        f"across {len(units)} unit(s)."
    )
    if not args.dry_run:
        log(
            "Next: mirror_homm3_lab_battle_to_unity.py then run_homm3_rife_production.cmd "
            "with SKIP_RIFE=1 for Unity-only rebuild."
        )
    if log_fp:
        log_fp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
