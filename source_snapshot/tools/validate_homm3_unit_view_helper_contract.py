"""Contract validator for Homm3UnitViewHelperRuntime bone resolution across active delivered GLBs.

    python tools/validate_homm3_unit_view_helper_contract.py [--repo-root R] [--require-artifacts]

Always (source/static):
  - parses SpawnBoneNames, HeadSpawnBoneNames, HeadSpawnUnitHints, and ChestBoneNames directly from
    Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3UnitViewHelperRuntime.cs;
  - verifies legacy Mixamo priority (RightHand/LeftHand and Spine2/Spine1/Spine stay first);
  - verifies TryEnsure routes spawn bone selection through SelectSpawnBoneNames and hooks still attach the helper;
  - runs fast synthetic Mixamo, Rigify, and eye-beam resolution checks.

When selection artifact folders exist (or --require-artifacts is passed):
  - reads ONLY the GLB 12-byte header + JSON chunk (<1s across all active delivered units);
  - verifies every active (non-superseded) delivered unit resolves both a spawn bone and a chest bone
    using the exact C# FindBone / SelectSpawnBoneNames logic;
  - asserts rebuilt ranged units (Lizardmen, Medusas, Beholders) bind to their expected spawn/chest bones.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import time
from pathlib import Path

VIEW_HELPER_REL = Path("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3UnitViewHelperRuntime.cs")
BATTLE_HOOK_REL = Path("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportReleaseBattleVisualHook.cs")
SELECTIONS_DIR_REL = Path("tools/homm3_def_retarget_delivery")
GLB_MAGIC = 0x46546C67
GLB_JSON_CHUNK = 0x4E4F534A

EXPECTED_RANGED_BINDINGS = {
    "h3_lizardman": ("DEF-hand.R", "DEF-chest"),
    "h3_lizard_warrior": ("DEF-hand.R", "DEF-chest"),
    "h3_lizard_assassin": ("DEF-hand.R", "DEF-chest"),
    "h3_medusa": ("DEF-hand.R", "DEF-chest"),
    "h3_medusa_queen": ("DEF-hand.R", "DEF-chest"),
    "h3_medusa_warrior": ("DEF-hand.R", "DEF-chest"),
    "h3_beholder": ("Head", "DEF-chest"),
    "h3_evil_eye": ("Head", "DEF-chest"),
    "h3_fargazer": ("Head", "DEF-chest"),
}


def parse_csharp_string_array(source: str, field_name: str) -> list[str]:
    pattern = re.compile(
        rf"private\s+static\s+readonly\s+string\[\]\s+{re.escape(field_name)}\s*=\s*\{{(.*?)\}};",
        re.DOTALL,
    )
    match = pattern.search(source)
    if not match:
        raise ValueError(f"missing string[] field '{field_name}' in {VIEW_HELPER_REL}")
    values = re.findall(r'"([^"]+)"', match.group(1))
    if not values:
        raise ValueError(f"empty string[] field '{field_name}' in {VIEW_HELPER_REL}")
    return values


def read_glb_node_names(glb_path: Path) -> list[str]:
    with open(glb_path, "rb") as handle:
        header = handle.read(12)
        if len(header) < 12:
            raise ValueError(f"{glb_path}: truncated GLB header")
        magic, _version, _length = struct.unpack("<III", header)
        if magic != GLB_MAGIC:
            raise ValueError(f"{glb_path}: bad GLB magic 0x{magic:08x}")
        chunk_header = handle.read(8)
        if len(chunk_header) < 8:
            raise ValueError(f"{glb_path}: truncated GLB JSON chunk header")
        chunk_len, chunk_type = struct.unpack("<II", chunk_header)
        if chunk_type != GLB_JSON_CHUNK:
            raise ValueError(f"{glb_path}: first chunk is not JSON (0x{chunk_type:08x})")
        gltf = json.loads(handle.read(chunk_len).decode("utf-8"))
    return [str(node.get("name", "")) for node in gltf.get("nodes", []) if isinstance(node, dict)]


def select_spawn_bone_names(
    unit_key: str,
    spawn_bones: list[str],
    head_spawn_bones: list[str],
    head_hints: list[str],
) -> list[str]:
    lowered = (unit_key or "").lower()
    if any(hint.lower() in lowered for hint in head_hints):
        return head_spawn_bones
    return spawn_bones


def find_bone(node_names: list[str], wanted_names: list[str]) -> str | None:
    for wanted in wanted_names:
        suffix = ":" + wanted
        for name in node_names:
            if name == wanted or name.endswith(suffix):
                return name
    return None


def validate_contract(repo_root: Path, require_artifacts: bool = False) -> tuple[int, list[str]]:
    errors: list[str] = []
    view_helper_path = repo_root / VIEW_HELPER_REL
    if not view_helper_path.is_file():
        return 0, [f"missing C# source: {VIEW_HELPER_REL}"]
    source = view_helper_path.read_text(encoding="utf-8-sig")

    try:
        spawn_bones = parse_csharp_string_array(source, "SpawnBoneNames")
        head_spawn_bones = parse_csharp_string_array(source, "HeadSpawnBoneNames")
        head_hints = parse_csharp_string_array(source, "HeadSpawnUnitHints")
        chest_bones = parse_csharp_string_array(source, "ChestBoneNames")
    except ValueError as exc:
        return 0, [str(exc)]

    if spawn_bones[:2] != ["RightHand", "LeftHand"]:
        errors.append(f"SpawnBoneNames must keep legacy Mixamo hands first, got {spawn_bones[:2]!r}")
    if chest_bones[:3] != ["Spine2", "Spine1", "Spine"]:
        errors.append(f"ChestBoneNames must keep legacy Mixamo spines first, got {chest_bones[:3]!r}")
    for anchor in ("SelectSpawnBoneNames(key)", "FindBone(instance.transform, spawnNames)", "FindBone(instance.transform, ChestBoneNames)"):
        if anchor not in source:
            errors.append(f"{VIEW_HELPER_REL}: missing runtime anchor {anchor!r}")

    hook_path = repo_root / BATTLE_HOOK_REL
    if not hook_path.is_file():
        errors.append(f"missing C# source: {BATTLE_HOOK_REL}")
    else:
        hook_src = hook_path.read_text(encoding="utf-8-sig")
        for anchor in ("Homm3UnitViewHelperRuntime.TryEnsure(", "Homm3UnitViewHelperRuntime.TryBindDrawer("):
            if anchor not in hook_src:
                errors.append(f"{BATTLE_HOOK_REL}: missing attach/bind anchor {anchor!r}")

    # Synthetic Mixamo, Rigify, and eye-beam checks always run regardless of gitignored artifacts.
    if find_bone(["Hips", "Spine2", "mixamorig:RightHand"], select_spawn_bone_names("h3_archer", spawn_bones, head_spawn_bones, head_hints)) != "mixamorig:RightHand":
        errors.append("synthetic Mixamo archer failed spawn bone lookup")
    if find_bone(["Head", "DEF-hand.R", "DEF-chest"], select_spawn_bone_names("custom_units_dungeon_h3_beholder", spawn_bones, head_spawn_bones, head_hints)) != "Head":
        errors.append("synthetic Beholder failed Head preference")
    if find_bone(["Head", "DEF-hand.R", "DEF-chest"], select_spawn_bone_names("h3_medusa", spawn_bones, head_spawn_bones, head_hints)) != "DEF-hand.R":
        errors.append("synthetic Medusa failed DEF-hand.R preference")

    sel_dir = repo_root / SELECTIONS_DIR_REL
    selection_paths = sorted(sel_dir.glob("*.json")) if sel_dir.is_dir() else []
    if not selection_paths:
        errors.append(f"no delivery selection JSONs found under {SELECTIONS_DIR_REL}")
        return 0, errors

    glbs_checked = 0
    observed_ranged: dict[str, tuple[str, str]] = {}

    for sel_path in selection_paths:
        try:
            sel = json.loads(sel_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sel_path.name}: unreadable JSON ({exc})")
            continue
        if not isinstance(sel, dict) or sel.get("supersededBy"):
            continue
        out_rel = sel.get("out", "")
        out_dir = repo_root / out_rel if out_rel else Path()
        if not out_rel or not out_dir.is_dir():
            if require_artifacts:
                errors.append(f"{sel_path.name}: output directory missing ({out_rel!r})")
            continue

        for row in sel.get("units", []):
            lab_sid = str(row.get("labSid", ""))
            bundle_name = str(row.get("bundleName", ""))
            if not lab_sid:
                errors.append(f"{sel_path.name}: unit row missing labSid")
                continue
            glb_path = out_dir / lab_sid / "delivered_idle_retimed.glb"
            if not glb_path.is_file():
                errors.append(f"{sel_path.name}: {lab_sid}: missing {glb_path.relative_to(repo_root)}")
                continue
            try:
                nodes = read_glb_node_names(glb_path)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{sel_path.name}: {lab_sid}: failed reading GLB nodes ({exc})")
                continue

            glbs_checked += 1
            spawn_order_sid = select_spawn_bone_names(lab_sid, spawn_bones, head_spawn_bones, head_hints)
            spawn_order_bundle = select_spawn_bone_names(bundle_name or lab_sid, spawn_bones, head_spawn_bones, head_hints)
            spawn_bone = find_bone(nodes, spawn_order_sid)
            spawn_bone_bundle = find_bone(nodes, spawn_order_bundle)
            chest_bone = find_bone(nodes, chest_bones)

            if spawn_bone is None:
                errors.append(f"{sel_path.name}: {lab_sid}: no spawn bone matched in {glb_path.name}")
            if spawn_bone != spawn_bone_bundle:
                errors.append(f"{sel_path.name}: {lab_sid}: spawn mismatch labSid={spawn_bone!r} vs bundleName={spawn_bone_bundle!r}")
            if chest_bone is None:
                errors.append(f"{sel_path.name}: {lab_sid}: no chest bone matched in {glb_path.name}")

            if lab_sid in EXPECTED_RANGED_BINDINGS and spawn_bone and chest_bone:
                observed_ranged[lab_sid] = (spawn_bone, chest_bone)
                expected = EXPECTED_RANGED_BINDINGS[lab_sid]
                if (spawn_bone, chest_bone) != expected:
                    errors.append(
                        f"{sel_path.name}: {lab_sid}: expected (spawn, chest)={expected!r}, got {(spawn_bone, chest_bone)!r}"
                    )

    if require_artifacts:
        if glbs_checked == 0:
            errors.append("--require-artifacts set but 0 GLBs were checked")
        missing_ranged = sorted(set(EXPECTED_RANGED_BINDINGS) - set(observed_ranged))
        if missing_ranged:
            errors.append(f"missing expected rebuilt ranged GLBs: {missing_ranged}")

    return glbs_checked, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--require-artifacts", action="store_true")
    args = parser.parse_args()

    t0 = time.monotonic()
    glbs_checked, errors = validate_contract(args.repo_root.resolve(), require_artifacts=args.require_artifacts)
    elapsed = time.monotonic() - t0
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(
            f"validate_homm3_unit_view_helper_contract: FAILED ({len(errors)} error(s), glbs={glbs_checked}, {elapsed:.3f}s)",
            file=sys.stderr,
        )
        return 1
    print(f"validate_homm3_unit_view_helper_contract: OK (glbs={glbs_checked}, {elapsed:.3f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
