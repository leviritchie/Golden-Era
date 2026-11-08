#!/usr/bin/env python3
"""Owned skinned units must play the attack clip that matches the attack the game resolves.

Native path (mono UnitDrawer.OnStartAttack, same shape on Golden Era): an attack sets the animator trigger
`attack` and `attackVariant = attackValues[animationIndex]` with attackValues = {0, .2, .4, .6, .8, 1}.
The stock controller every owned-skinned prefab overrides (_Battle_Unit_Anim_ctrl_v2, via
StockEsquireBattle.controller) answers that with "Attack Tree 2", a 1D blend over attackVariant of
14.Attack, 15.Skill_1 .. 19.Skill_5. So the clip a unit plays for an attack is
    slot = SLOTS[view.<attack list>[i].animationIndex]  ->  AnimatorOverrideController[slot]
and nothing else. A view attack with a projectile is a shot and must land on Unit_ShootFront; any other
default/alternative/counter attack is melee and must land on Unit_AttackFront. Abilities follow the same rule
on slots 0/1 (and any projectile ability on any slot). Two attacks of different
kind that share one animationIndex cannot both be right and fail as a data conflict.

Found 2026-09-27: every Castle ranged unit (h3_archer / _upg / _upg_alt) shoots at animationIndex 0, whose
slot 14.Attack is overridden with Unit_AttackFront (Homm3OwnedSkinnedLabBuild.StockMap only uses
ShootFront when a unit has no AttackFront), its melee alternative (index 1) plays 15.Skill_1 =
Unit_Mouseover, and Unit_ShootFront is in the bundle but reachable from no state. Fix: views put the shot
on 1 and melee/counter on 0 (validate_homm3_owned_attack_animation_slots.py) and StockMap maps
15.Skill_1 -> Unit_ShootFront (Unit_AttackFront without a shot clip).

Bundle mode (the only mode): --bundle-dir D --name-prefix P [...]. Views are read from the installed
Core.zip (--core), the bundle -> unit binding from homm3_import.json (--import). Needs UnityPy.
Proof: generated/installed bundle static readback; runtime playback is not claimed.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GE = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
DEFAULT_CORE = GE / "HeroesOldenEra_Data/StreamingAssets/Core.zip"
DEFAULT_IMPORT = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json"
STOCK_BASE = "_Battle_Unit_Anim_ctrl_v2"
SLOTS = ("14.Attack", "15.Skill_1", "16.Skill_2", "17.Skill_3", "18.Skill_4", "19.Skill_5")
SHOOT, MELEE = "Unit_ShootFront", "Unit_AttackFront"
ATTACK_LISTS = ("defaultAttacks", "alternativeAttacks", "counterAttacks")


def load_views(core: Path) -> dict[str, dict]:
    views: dict[str, dict] = {}
    with zipfile.ZipFile(core) as z:
        for name in z.namelist():
            if "/units_views/" not in name or not name.endswith(".json"):
                continue
            doc = json.loads(z.read(name).decode("utf-8-sig"))
            for row in doc.get("array", []) if isinstance(doc, dict) else []:
                if isinstance(row, dict) and row.get("id"):
                    views[row["id"]] = row
    return views


def required_slots(sid: str, view: dict, errors: list[str]) -> dict[str, tuple[str, str]]:
    """slot -> (clip, first attack that asked for it)."""
    need: dict[str, tuple[str, str]] = {}
    for key in ATTACK_LISTS:
        for i, attack in enumerate(view.get(key) or []):
            index = attack.get("animationIndex", 0)
            where = f"{sid} view {key}[{i}] animationIndex={index}"
            if not isinstance(index, int) or not 0 <= index < len(SLOTS):
                errors.append(f"{where}: outside the stock attack tree (0..{len(SLOTS) - 1})")
                continue
            clip = SHOOT if attack.get("projectile") else MELEE
            slot = SLOTS[index]
            prior = need.get(slot)
            if prior and prior[0] != clip:
                errors.append(f"{where}: slot {slot} must play {clip} but {prior[1]} needs {prior[0]} there "
                              f"(data conflict: a shot and a melee attack share one animationIndex)")
                continue
            need.setdefault(slot, (clip, where))
    # Abilities play the same tree. One with a projectile is a shot; a projectile-less ability on the
    # attack/shot slots (0, 1) is a swing (index 1 played Unit_Mouseover before 2026-09-27). Abilities on
    # 2..5 play the stock Mouseover fallback and are not claimed here.
    for i, ability in enumerate(view.get("abilities") or []):
        if not isinstance(ability, dict):
            continue
        index = ability.get("animationIndex", 0)
        where = f"{sid} view abilities[{i}] animationIndex={index}"
        if not ability.get("projectile") and index not in (0, 1):
            continue
        if not isinstance(index, int) or not 0 <= index < len(SLOTS):
            errors.append(f"{where}: outside the stock attack tree (0..{len(SLOTS) - 1})")
            continue
        clip = SHOOT if ability.get("projectile") else MELEE
        slot = SLOTS[index]
        prior = need.get(slot)
        if prior and prior[0] != clip:
            errors.append(f"{where}: slot {slot} must play {clip} but {prior[1]} needs {prior[0]} there")
            continue
        need.setdefault(slot, (clip, where))
    return need


def bundle_overrides(path: Path) -> tuple[dict[str, str], set[str]]:
    import UnityPy  # noqa: PLC0415 - optional dependency, only bundle mode needs it

    env = UnityPy.load(str(path))
    mapping: dict[str, str] = {}
    clips: set[str] = set()
    found = False
    for obj in env.objects:
        kind = obj.type.name
        if kind == "AnimationClip":
            clips.add(obj.read().m_Name)
        elif kind == "AnimatorOverrideController":
            data = obj.read()
            if data.m_Name != "owned_skinned":
                continue
            base = data.m_Controller.read().m_Name if data.m_Controller and data.m_Controller.path_id else None
            if base != STOCK_BASE:
                raise ValueError(f"owned_skinned override is based on {base!r}, not {STOCK_BASE}")
            found = True
            for pair in data.m_Clips:
                if pair.m_OriginalClip and pair.m_OriginalClip.path_id:
                    original = pair.m_OriginalClip.read().m_Name
                    override = pair.m_OverrideClip.read().m_Name if pair.m_OverrideClip and pair.m_OverrideClip.path_id else None
                    mapping[original] = override
    if not found:
        raise ValueError("no owned_skinned AnimatorOverrideController")
    return mapping, clips


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bundle-dir", type=Path, required=True)
    ap.add_argument("--name-prefix", action="append", required=True,
                    help="exact bundle name, or a family prefix ending in '_'")
    ap.add_argument("--core", type=Path, default=DEFAULT_CORE)
    ap.add_argument("--import", dest="import_table", type=Path, default=DEFAULT_IMPORT)
    args = ap.parse_args()

    errors: list[str] = []
    views = load_views(args.core)
    entries = json.loads(args.import_table.read_text(encoding="utf-8-sig"))["entries"]

    def selected(name: str) -> bool:
        return any(name == p or (p.endswith("_") and name.startswith(p)) for p in args.name_prefix)

    bundles = sorted(p for p in args.bundle_dir.iterdir()
                     if p.is_file() and p.suffix == "" and selected(p.name))
    if not bundles:
        print(f"FAIL: no bundle in {args.bundle_dir} matches {args.name_prefix}")
        return 1
    checked = 0
    for path in bundles:
        rows = [e for e in entries if e.get("bundleName") == path.name
                and str(e.get("battlePrefabAssetPath", "")).endswith("/OwnedSkinned/owned_skinned.prefab")]
        sids = sorted({sid for e in rows for sid in e.get("gameUnitSids", [])})
        if not sids:
            continue  # not an owned-skinned battle bundle
        try:
            mapping, clips = bundle_overrides(path)
        except Exception as ex:  # noqa: BLE001 - reported, never swallowed
            errors.append(f"{path.name}: {ex}")
            continue
        for sid in sids:
            view = views.get(sid)
            if view is None:
                errors.append(f"{path.name}: unit {sid} has no units_views row in {args.core.name}")
                continue
            for slot, (clip, where) in required_slots(sid, view, errors).items():
                if clip not in clips:
                    errors.append(f"{path.name}: {where} needs {clip}, which the bundle does not contain")
                elif mapping.get(slot) != clip:
                    errors.append(f"{path.name}: {where} plays {slot} -> {mapping.get(slot)!r}, must be {clip}")
            checked += 1
    if errors:
        print(f"FAIL: owned skinned attack clip contract ({len(errors)} error(s))")
        for e in errors:
            print("  - " + e)
        return 1
    print(f"OK: owned skinned attack clip contract ({checked} unit(s) in {len(bundles)} bundle(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
