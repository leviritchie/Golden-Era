#!/usr/bin/env python3
"""Inventory Meshy SmartRig GLBs, upgrade-family placeholders, and chosen clips.

This is the fail-closed planner for the physics-dampened skinned-mesh rollout.
It does not invent a smaller clip subset: chosen DEF groups are the OE skinned
contract in gpu_cascade_delivery (idle/move/mouseover/hitted/defence/death/
attack_front/move_start/move_end plus shoot when the DEF has those groups).
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
MESHY = ROOT / "artifacts/meshy_downloads"
OUT_DIR = ROOT / "artifacts/homm3_smartrig_skinned_rollout"
STATUS_PATH = OUT_DIR / "status.json"
MESH_NOTE_SUFFIX = "_MESH_NOTE.json"
MANIFEST_PATH = ROOT / "tools/homm3_import/homm3_units_manifest.json"
IMPORT_TABLE = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_import.json"
)
FACTION_DIR = ROOT / "custom_factions"
NEUTRAL_CONCEPT = ROOT / "tools/homm3_import/faction_concepts/homm3_neutral.json"
GOLDEN_ERA_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)

if str(TOOL) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(TOOL))

from gpu_cascade_delivery import (  # noqa: E402
    CHOSEN_DEF_GROUPS,
    CONTRACT_SUFFIX_BY_GROUP,
    CURRENT_CASCADE_KEEP,
    SKIPPED_DEF_GROUPS,
    clip_result_matches_current_keep,
    contract_name_for_group,
)
from materialize_rife_source_frames import (  # noqa: E402
    IDLE_GROUP,
    UNSHIPPED_DEF_GROUPS,
    inventory_authentic_def_groups,
)
from roc_semantic_hybrid_widgets import homm3_lab_root  # noqa: E402

VARIANT_SUFFIXES = ("", "_upg", "_upg_alt")
LAB_SID_RE = re.compile(r"homm3_lab/([^/]+)/")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def catalog_lab_sids() -> list[str]:
    payload = _load_json(MANIFEST_PATH)
    units = payload.get("units")
    if not isinstance(units, list) or not units:
        raise RuntimeError(f"{MANIFEST_PATH} has no units")
    sids: list[str] = []
    for row in units:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("unitSid") or "").strip()
        if sid and sid != "sample_creature":
            sids.append(sid)
    if not sids:
        raise RuntimeError(f"{MANIFEST_PATH} produced no catalog SIDs")
    return sids


def mesh_catalog_note(lab_sid: str) -> dict[str, Any] | None:
    path = MESHY / f"{lab_sid}_smartrigged{MESH_NOTE_SUFFIX}"
    if not path.is_file():
        return None
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else None


def smartrig_glbs() -> dict[str, Path]:
    """Map lab SID → authoritative Meshy SmartRig GLB.

    Prefer the rigidized derivative when it exists. Ignore quarantined
    ``_WRONG`` files and leading-underscore leftovers.
    """
    by_sid: dict[str, Path] = {}
    if not MESHY.is_dir():
        raise FileNotFoundError(MESHY)
    for path in sorted(MESHY.glob("*_smartrigged.glb")):
        name = path.name
        if name.startswith("_") or "WRONG" in name.upper():
            continue
        sid = name[: -len("_smartrigged.glb")]
        by_sid[sid] = path
    for path in sorted(MESHY.glob("*_smartrigged_rigidized.glb")):
        name = path.name
        if name.startswith("_") or "WRONG" in name.upper():
            continue
        sid = name[: -len("_smartrigged_rigidized.glb")]
        by_sid[sid] = path
    return by_sid


def alias_glbs_onto_catalog(glbs: dict[str, Path], catalog: list[str]) -> dict[str, Path]:
    """Attach leftover GLB filenames onto catalog SIDs with known prefix/suffix drift."""
    catalog_set = set(catalog)
    out = dict(glbs)
    for sid, path in glbs.items():
        if sid in catalog_set:
            continue
        rest = sid[3:] if sid.startswith("h3_") else sid
        candidates = [
            f"hota_cove_{rest}",
            f"hota_factory_{rest}",
            f"hota_bulwark_{rest}",
            f"hota_{rest}",
            f"{sid}_upg_alt",
            f"{sid}_upg",
        ]
        if sid.endswith("_upg_alt"):
            candidates.append(sid[: -len("_upg_alt")])
        for candidate in candidates:
            if candidate in catalog_set and candidate not in out:
                out[candidate] = path
    return out


def import_entries() -> list[dict[str, Any]]:
    table = _load_json(IMPORT_TABLE)
    entries = table.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError(f"{IMPORT_TABLE} has no entries")
    return [row for row in entries if isinstance(row, dict)]


def lab_sid_from_prefab(path: str) -> str | None:
    match = LAB_SID_RE.search(str(path).replace("\\", "/"))
    return match.group(1) if match else None


def game_sid_to_lab() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in import_entries():
        lab = lab_sid_from_prefab(str(entry.get("battlePrefabAssetPath") or ""))
        if not lab:
            continue
        for sid in entry.get("gameUnitSids") or []:
            if isinstance(sid, str) and sid:
                mapping[sid] = lab
    return mapping


def lab_to_import() -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for entry in import_entries():
        lab = lab_sid_from_prefab(str(entry.get("battlePrefabAssetPath") or ""))
        if not lab:
            continue
        mapping.setdefault(lab, entry)
    return mapping


def upgrade_families() -> dict[str, list[str]]:
    """Core-SID families: base + _upg + _upg_alt when those variants exist."""
    families: dict[str, list[str]] = {}
    for path in sorted(FACTION_DIR.glob("homm3_*.json")):
        if path.parent.name != "custom_factions":
            continue
        payload = _load_json(path)
        lines = payload.get("unitLines")
        if not isinstance(lines, list):
            continue
        variants = payload.get("unitVariants") or list(VARIANT_SUFFIXES)
        if not isinstance(variants, list) or not variants:
            variants = list(VARIANT_SUFFIXES)
        for line in lines:
            if not isinstance(line, dict):
                continue
            base = str(line.get("baseSid") or "").strip()
            if not base:
                continue
            variant_sids = line.get("variantSids")
            members: list[str] = []
            if isinstance(variant_sids, dict) and variant_sids:
                for suffix in variants:
                    if not isinstance(suffix, str):
                        continue
                    named = variant_sids.get(suffix)
                    if isinstance(named, str) and named.strip():
                        members.append(named.strip())
                    elif suffix == "":
                        members.append(base)
                    else:
                        members.append(f"{base}{suffix}")
            else:
                members = [f"{base}{suffix}" for suffix in variants if isinstance(suffix, str)]
            families[base] = list(dict.fromkeys(members))
    if NEUTRAL_CONCEPT.is_file():
        payload = _load_json(NEUTRAL_CONCEPT)
        for unit in payload.get("units") or []:
            if not isinstance(unit, dict):
                continue
            sid = str(unit.get("sid") or "").strip()
            if sid:
                families.setdefault(sid, [sid])
    return families


def family_for_game_sid(game_sid: str, families: dict[str, list[str]]) -> tuple[str, list[str]]:
    aliases = [game_sid]
    for prefix in ("hota_cove_", "hota_factory_", "hota_bulwark_", "hota_"):
        if game_sid.startswith(prefix):
            aliases.append("h3_" + game_sid[len(prefix) :])
    for alias in aliases:
        for base, members in families.items():
            if alias == base or alias in members:
                return base, list(members)
    if game_sid.endswith("_upg_alt"):
        base = game_sid[: -len("_upg_alt")]
        return base, [base, f"{base}_upg", game_sid]
    if game_sid.endswith("_upg"):
        base = game_sid[: -len("_upg")]
        return base, [base, game_sid, f"{game_sid}_upg_alt"]
    return game_sid, [game_sid, f"{game_sid}_upg", f"{game_sid}_upg_alt"]


def donor_scale_from_core(game_sid: str, overlay_item: Mapping | None) -> dict[str, Any]:
    if not isinstance(overlay_item, dict):
        return {
            "scale": None,
            "modelHeight": None,
            "defaultHeight": None,
            "source": "missing",
        }
    return {
        "scale": overlay_item.get("scale"),
        "modelHeight": overlay_item.get("modelHeight"),
        "defaultHeight": overlay_item.get("defaultHeight"),
        "mesh": overlay_item.get("mesh"),
        "mapMesh": overlay_item.get("mapMesh"),
        "source": "installed_core_overlay",
    }


def read_core_views() -> dict[str, dict[str, Any]]:
    views: dict[str, dict[str, Any]] = {}
    if not GOLDEN_ERA_CORE.is_file():
        return views
    with zipfile.ZipFile(GOLDEN_ERA_CORE) as zf:
        for name in zf.namelist():
            if not name.startswith("DB/units/units_views/") or not name.endswith("_v.json"):
                continue
            sid = Path(name).stem
            if sid.endswith("_v"):
                sid = sid[:-2]
            try:
                doc = json.loads(zf.read(name).decode("utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError):
                continue
            array = doc.get("array") if isinstance(doc, dict) else None
            if isinstance(array, list) and array and isinstance(array[0], dict):
                views[sid] = array[0]
    return views


def lab_def_groups(lab_root: Path, lab_sid: str) -> dict[int, int]:
    unit_dir = lab_root / lab_sid
    source_root = unit_dir / "extracted_battle_source_12fps"
    if not source_root.is_dir():
        return {}
    from roc_semantic_hybrid_widgets import _select_lab_def_directory

    def_dir = _select_lab_def_directory(unit_dir)
    if def_dir is None:
        return {}
    try:
        inventory = inventory_authentic_def_groups(def_dir)
    except (OSError, RuntimeError, ValueError):
        return {}
    return {int(group): len(frames) for group, frames in inventory.items()}


def clip_result_status(lab_sid: str, animation: str) -> dict[str, Any]:
    path = (
        ROOT
        / "artifacts"
        / "pose_picker_runs"
        / lab_sid
        / animation
        / "gpu_cascade_delivery"
        / "gpu_clip_result.json"
    )
    if not path.is_file():
        return {"path": str(path), "exists": False, "matchesKeep": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"path": str(path), "exists": True, "matchesKeep": False, "error": "unreadable"}
    return {
        "path": str(path),
        "exists": True,
        "matchesKeep": bool(clip_result_matches_current_keep(payload)),
        "score": payload.get("score"),
        "physicsSmoothEnabled": bool((payload.get("config") or {}).get("physics_smooth_enabled")),
    }


def chosen_sequences(group_counts: dict[int, int]) -> list[dict[str, Any]]:
    from materialize_rife_source_frames import idle_leading_def_sequences

    sequences = []
    for groups in idle_leading_def_sequences(group_counts):
        ship = [int(group) for group in groups if int(group) in CHOSEN_DEF_GROUPS]
        if not ship:
            continue
        if ship[0] != IDLE_GROUP and IDLE_GROUP in groups:
            continue
        sequences.append(
            {
                "groups": list(groups),
                "chosenGroups": ship,
                "contracts": [
                    contract_name_for_group(group, "Unit")
                    for group in ship
                    if not (group == IDLE_GROUP and len(groups) > 1)
                ],
                "frameCount": sum(int(group_counts[group]) for group in groups),
            }
        )
    return sequences


def build_status() -> dict[str, Any]:
    catalog = catalog_lab_sids()
    glbs = alias_glbs_onto_catalog(smartrig_glbs(), catalog)
    families = upgrade_families()
    game_to_lab = game_sid_to_lab()
    lab_to_game: dict[str, list[str]] = {}
    for game_sid, lab_sid in game_to_lab.items():
        lab_to_game.setdefault(lab_sid, []).append(game_sid)
    import_by_lab = lab_to_import()
    lab_root = homm3_lab_root(ROOT)
    core_views = read_core_views()

    extra_glbs = sorted(sid for sid in glbs if sid not in catalog)
    units: list[dict[str, Any]] = []
    missing_family_mesh: list[str] = []

    for lab_sid in catalog:
        glb = glbs.get(lab_sid)
        game_sids = lab_to_game.get(lab_sid) or [lab_sid]
        primary_game = game_sids[0]
        family_base, family_game_sids = family_for_game_sid(primary_game, families)
        family_lab_sids: list[str] = []
        catalog_set = set(catalog)
        for game_sid in family_game_sids:
            mapped = game_to_lab.get(game_sid)
            if mapped:
                family_lab_sids.append(mapped)
            if game_sid in catalog_set:
                family_lab_sids.append(game_sid)
            if game_sid.startswith("h3_"):
                rest = game_sid[3:]
                for prefix in ("hota_cove_", "hota_factory_", "hota_bulwark_", "hota_"):
                    alt = prefix + rest
                    if alt in catalog_set:
                        family_lab_sids.append(alt)
        family_lab_sids = list(dict.fromkeys(family_lab_sids))
        placeholder_from = None
        mesh_role = "own_glb"
        if glb is None:
            for peer in family_lab_sids:
                if peer != lab_sid and peer in glbs:
                    placeholder_from = peer
                    glb = glbs[peer]
                    mesh_role = "family_placeholder"
                    break
            if placeholder_from is None:
                mesh_role = "unfilled"
                if not any(peer in glbs for peer in family_lab_sids):
                    missing_family_mesh.append(family_base)

        import_row = import_by_lab.get(lab_sid) or {}
        mesh_note = mesh_catalog_note(lab_sid)
        view = None
        for game_sid in game_sids:
            if game_sid in core_views:
                view = core_views[game_sid]
                break
        scale = donor_scale_from_core(primary_game, view)
        groups = lab_def_groups(lab_root, lab_sid)
        sequences = chosen_sequences(groups) if groups else []
        present_chosen = sorted(group for group in groups if group in CHOSEN_DEF_GROUPS)
        skipped_present = sorted(group for group in groups if group in SKIPPED_DEF_GROUPS)
        clip_status = []
        from materialize_rife_source_frames import def_sequence_animation_name

        for seq in sequences:
            animation = def_sequence_animation_name(seq["groups"])
            clip_status.append(
                {
                    "animation": animation,
                    "groups": seq["groups"],
                    "contracts": seq["contracts"],
                    "gpu": clip_result_status(lab_sid, animation),
                }
            )

        units.append(
            {
                "labSid": lab_sid,
                "gameUnitSids": game_sids,
                "familyBase": family_base,
                "familyLabSids": family_lab_sids,
                "meshRole": mesh_role,
                "glb": None if glb is None else str(glb),
                "placeholderFrom": placeholder_from,
                "scale": scale,
                "previewPath": str(import_row.get("battleResPath") or ""),
                "adventureMapPath": str(import_row.get("mapResPath") or ""),
                "bundleName": str(import_row.get("bundleName") or ""),
                "battlePrefabAssetPath": str(import_row.get("battlePrefabAssetPath") or ""),
                "mapPrefabAssetPath": str(import_row.get("mapPrefabAssetPath") or ""),
                "labDefGroups": {str(k): v for k, v in sorted(groups.items())},
                "presentChosenGroups": present_chosen,
                "skippedPresentGroups": skipped_present,
                "sequences": clip_status,
                "meshNote": mesh_note,
                "unfilledReason": None
                if mesh_role != "unfilled"
                else "upgrade family has no Meshy SmartRig GLB",
            }
        )

    filled = sum(1 for row in units if row["meshRole"] != "unfilled")
    own = sum(1 for row in units if row["meshRole"] == "own_glb")
    placeholders = sum(1 for row in units if row["meshRole"] == "family_placeholder")
    unfilled = [row["labSid"] for row in units if row["meshRole"] == "unfilled"]
    keep_ready = 0
    keep_needed = 0
    for row in units:
        if row["meshRole"] != "own_glb":
            continue
        for seq in row["sequences"]:
            keep_needed += 1
            if seq["gpu"]["matchesKeep"]:
                keep_ready += 1

    return {
        "proofTier": "source/static + filesystem inventory",
        "objective": (
            "physics-dampened CURRENT_CASCADE_KEEP clips for every Meshy SmartRig "
            "unit; same-upgrade-family idle placeholders; Golden Era skinned "
            "preview + adventure-map idle at donor UnitViewConfig scale"
        ),
        "chosenClipCategories": {
            "source": [
                "tools/homm3_silhouette_pose_fit/gpu_cascade_delivery.py CONTRACT_BY_GROUP + SHOOT",
                "UNSHIPPED_DEF_GROUPS / SKIPPED_DEF_GROUPS = turns 7/8, attack up/down 11/13, shoot up/down 14/16",
                "docs/surfaces/custom_unit_skinned_mesh.md crusader ship set",
                "idle_leading_def_sequences: idle-only plus idle-prefixed motion chains",
            ],
            "groups": {str(k): v for k, v in sorted(CONTRACT_SUFFIX_BY_GROUP.items())},
            "skipped": sorted(SKIPPED_DEF_GROUPS | set(UNSHIPPED_DEF_GROUPS)),
            "keep": dict(CURRENT_CASCADE_KEEP),
            "qualityBar": "physics_smooth_enabled cascade keep; good enough for a test run",
        },
        "counts": {
            "catalogUnits": len(catalog),
            "smartrigGlbs": len(glbs),
            "ownGlb": own,
            "familyPlaceholder": placeholders,
            "unfilled": len(unfilled),
            "extraGlbsNotInCatalog": extra_glbs,
            "physicsKeepClipsReady": keep_ready,
            "physicsKeepClipsNeededForOwnGlb": keep_needed,
            "installedCoreViews": len(core_views),
            "labRoot": str(lab_root),
        },
        "unfilledFamilies": sorted(set(missing_family_mesh)),
        "unfilledUnits": unfilled,
        "units": units,
    }


def main() -> int:
    status = build_status()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    counts = status["counts"]
    print(json.dumps({"wrote": str(STATUS_PATH), "counts": counts, "unfilledFamilies": status["unfilledFamilies"], "unfilledUnits": status["unfilledUnits"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
