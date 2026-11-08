#!/usr/bin/env python3
"""Readback gate: HoMM3 unit views put the shot on animation slot 1 and melee on slot 0.

Native UnitDrawer.OnStartAttack plays "Attack Tree 2" with attackVariant = {0,.2,.4,.6,.8,1}[animationIndex],
i.e. animationIndex 0 -> 14.Attack, 1 -> 15.Skill_1, 2..5 -> 16.Skill_2..19.Skill_5. The owned skinned lab
build maps 14.Attack -> Unit_AttackFront and 15.Skill_1 -> Unit_ShootFront (Unit_AttackFront when the unit has
no shot clip). Views therefore follow the vanilla shooter convention (crossbowman, lightweaver, aqualotl,
arbitrator: default shot on 1, melee alternative and counter on 0):

  * every attack or ability that carries a projectile uses animationIndex 1;
  * every default/alternative/counter attack without a projectile uses animationIndex 0;
  * a unit that shoots never puts a projectile-less ability on index 1 (that slot is its shot).

apply_release_core_overlay.py assigns the slots (assign_homm3_attack_animation_slots) and runs this gate on the
candidate Core.zip and again on the updated release Core.zip. Static/generated-artifact proof only.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

DEFAULT_CORE = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/"
                    "HeroesOldenEra_Data/StreamingAssets/Core.zip")
VIEW_PREFIX = "DB/units/units_views/"
UNIT_PREFIX = "h3_"
ATTACK_LISTS = ("defaultAttacks", "alternativeAttacks", "counterAttacks")
MELEE_SLOT, SHOT_SLOT = 0, 1


def attacks(value) -> list[dict]:
    if isinstance(value, list):
        return [a for a in value if isinstance(a, dict)]
    return [value] if isinstance(value, dict) else []


def row_errors(row: dict) -> list[str]:
    sid = row.get("id", "?")
    errors = []
    shoots = any(a.get("projectile") for k in (*ATTACK_LISTS, "abilities") for a in attacks(row.get(k)))
    for key in ATTACK_LISTS:
        for i, a in enumerate(attacks(row.get(key))):
            want = SHOT_SLOT if a.get("projectile") else MELEE_SLOT
            if a.get("animationIndex", 0) != want:
                errors.append(f"{sid}: {key}[{i}] animationIndex {a.get('animationIndex', 0)} != {want}"
                              f" ({'shot' if want == SHOT_SLOT else 'melee'})")
    for i, a in enumerate(attacks(row.get("abilities"))):
        idx = a.get("animationIndex", 0)
        if a.get("projectile") and idx != SHOT_SLOT:
            errors.append(f"{sid}: abilities[{i}] carries a projectile on animationIndex {idx} != {SHOT_SLOT}")
        elif shoots and not a.get("projectile") and idx == SHOT_SLOT:
            errors.append(f"{sid}: abilities[{i}] has no projectile but sits on the shot slot {SHOT_SLOT}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--core", type=Path, default=DEFAULT_CORE)
    args = ap.parse_args()
    errors, checked = [], 0
    with zipfile.ZipFile(args.core) as z:
        for name in z.namelist():
            if not (name.startswith(VIEW_PREFIX) and name.endswith("_v.json")):
                continue
            if not Path(name).name.startswith(UNIT_PREFIX):
                continue
            doc = json.loads(z.read(name).decode("utf-8-sig"))
            for row in doc.get("array") or []:
                if isinstance(row, dict) and str(row.get("id", "")).startswith(UNIT_PREFIX):
                    checked += 1
                    errors.extend(row_errors(row))
    if checked == 0:
        errors.append(f"no {UNIT_PREFIX}* units_views rows in {args.core}")
    for e in errors:
        print("ERROR: " + e)
    print(f"{'FAIL' if errors else 'OK'}: {checked} {UNIT_PREFIX}* view row(s), {len(errors)} error(s) in {args.core}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
