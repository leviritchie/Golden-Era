#!/usr/bin/env python3
"""HoMM3 battle unit SFX must follow the animator states the units actually play.

Combat creature SFX is clip-gated (Homm3LabClipAudioDriver -> Homm3LabBattleAudioPlayer): on each animator state
change the driver turns the entered state into an audio slot ("14.Attack", "20.Damage", "21.Death", "01.Walk",
"22.Idle", "27.Victory") through Homm3LabClipAudioStates. Billboard controllers name their states after the slots.
Owned skinned prefabs override the stock battle controller _Battle_Unit_Anim_ctrl_v2, whose states are
"Attack Tree 2", "damage 0", "DYING.die 0", "move 0", ...

Found 2026-10-01 ("units seem to be missing audio"): the driver listed only the billboard state names, so every
owned skinned unit fell through to the dominant clip's name. "Unit_AttackFront" and "Unit_Death" still matched, but
damage ("Unit_Hitted"), walk/fly ("Unit_Move"), shots ("Unit_ShootFront") and victory ("Unit_Defence") were silent.

Source mode (always): the driver's StockStateSlots table must map exactly REQUIRED_STOCK below, and its
BillboardStateSlots must keep the billboard slots.
Bundle mode (--bundle-dir D [--name-prefix P ...], needs UnityPy): every owned skinned bundle (an
AnimatorOverrideController over _Battle_Unit_Anim_ctrl_v2) must carry every state path the table lists, so a
renamed stock state fails here instead of going silent in game.
Proof: source/static and generated/installed bundle readback; runtime playback is not claimed.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3LabClipAudioDriver.cs"
STOCK_BASE = "_Battle_Unit_Anim_ctrl_v2"

REQUIRED_STOCK = {
    "Base Layer.Attack Tree 2": "14.Attack",
    "Base Layer.Move Ability.moveAttack": "14.Attack",
    "Base Layer.damage 0": "20.Damage",
    "Base Layer.DYING.die 0": "21.Death",
    "Base Layer.move 0": "01.Walk",
    "Base Layer.Move Ability.moveAbility": "01.Walk",
    "Base Layer.FLYING.fly 0": "01.Walk",
    "Base Layer.Flying Ability.flyAbility": "01.Walk",
    "Base Layer.idle": "22.Idle",
    "Base Layer.rareIdle 0": "22.Idle",
    "Base Layer.Victory": "27.Victory",
}
REQUIRED_BILLBOARD = {
    "14.Attack": "14.Attack",
    "15.Skill_1": "14.Attack",
    "20.Damage": "20.Damage",
    "21.Death": "21.Death",
    "01.Walk": "01.Walk",
    "22.Idle": "22.Idle",
}
PAIR = re.compile(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')


def read_table(text: str, name: str, errors: list[str]) -> dict[str, str]:
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*\{(.*?)\};", text, re.S)
    if not m:
        errors.append(f"{DRIVER.name}: table {name} not found")
        return {}
    table: dict[str, str] = {}
    for state, slot in PAIR.findall(m.group(1)):
        if state in table:
            errors.append(f"{name}: state '{state}' listed twice")
        table[state] = slot
    return table


def check_source(errors: list[str]) -> dict[str, str]:
    if not DRIVER.exists():
        errors.append(f"missing {DRIVER}")
        return {}
    text = DRIVER.read_text(encoding="utf-8")
    stock = read_table(text, "StockStateSlots", errors)
    billboard = read_table(text, "BillboardStateSlots", errors)
    for label, want, got in (("StockStateSlots", REQUIRED_STOCK, stock), ("BillboardStateSlots", REQUIRED_BILLBOARD, billboard)):
        for state, slot in want.items():
            if got.get(state) != slot:
                errors.append(f"{label}: '{state}' must map to '{slot}' (got {got.get(state)!r})")
        for state in got.keys() - want.keys():
            errors.append(f"{label}: unpinned state '{state}' -> '{got[state]}' (add it to this validator with its reason)")
    if "TryPickSlot(stateInfo" not in text:
        errors.append(f"{DRIVER.name}: the driver no longer resolves the slot through Homm3LabClipAudioStates.TryPickSlot")
    return stock


def check_bundles(bundle_dir: Path, prefixes: list[str], stock: dict[str, str], errors: list[str]) -> int:
    try:
        import UnityPy  # type: ignore
    except ImportError:
        errors.append("bundle mode needs UnityPy (pip install UnityPy)")
        return 0
    checked = 0
    files = sorted(p for p in bundle_dir.iterdir()
                   if p.is_file() and p.suffix == "" and p.name.startswith("custom_units_")
                   and (not prefixes or any(p.name.startswith(x) for x in prefixes)))
    for path in files:
        env = UnityPy.load(str(path))
        has_owned = False
        paths: set[str] | None = None
        for obj in env.objects:
            kind = obj.type.name
            if kind == "AnimatorOverrideController":
                has_owned = True
            elif kind == "AnimatorController":
                tree = obj.read_typetree()
                if tree.get("m_Name") == STOCK_BASE:
                    paths = {v for _, v in tree.get("m_TOS", [])}
        if not has_owned:
            continue
        if paths is None:
            continue  # an override over another base is not the stock battle lane
        checked += 1
        for state in stock:
            if state not in paths:
                errors.append(f"{path.name}: stock controller has no state '{state}' (driver slot {stock[state]})")
    return checked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bundle-dir", type=Path)
    ap.add_argument("--name-prefix", action="append", default=[])
    args = ap.parse_args()
    errors: list[str] = []
    stock = check_source(errors)
    checked = 0
    if args.bundle_dir is not None and not errors:
        if not args.bundle_dir.is_dir():
            errors.append(f"missing bundle dir {args.bundle_dir}")
        else:
            checked = check_bundles(args.bundle_dir, args.name_prefix, stock, errors)
            if checked == 0 and not errors:
                errors.append(f"no owned skinned bundle over {STOCK_BASE} under {args.bundle_dir}")
    if errors:
        print("validate_homm3_lab_clip_audio_driver_contract: FAIL")
        for e in errors:
            print("  - " + e)
        return 1
    tail = f", {checked} owned skinned bundle(s) carry every stock state" if args.bundle_dir else ""
    print(f"validate_homm3_lab_clip_audio_driver_contract: OK ({len(stock)} stock states{tail})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
