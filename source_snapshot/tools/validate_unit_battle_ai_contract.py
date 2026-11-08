#!/usr/bin/env python3
"""Every unit logic's `ai` must resolve to a battle-AI params row in the same Core.

The game builds the lookup id as `<unit.ai>_<difficulty>` and reads it from
`DB/ai_battle/**`. A missing row logs `[Config Error] Config with id "<ai>_normal"
was not found` and then throws a NullReferenceException inside the battle AI
(`dyt.baxb(Unit, BattleAiParams, ...)`). On an AI-vs-neutral auto battle that
exception aborts the AI side's turn and softlocks the game (playtest 2026-09-29,
`h3_sharpshooter` with `ai: archer_type`).

Difficulties are derived from the Core's own `default_<difficulty>` rows, so the
gate follows the shipped data rather than a hard-coded list.

Only the base `<ai>_<difficulty>` id is checked; that is the lookup proven by the
playtest log. Derived variants (`_def`, `_alt`) are not asserted here.

Second rule, the vanilla invariant (0 exceptions in the release Core): a unit whose
defaultAttacks shoot has a range_type* ai and every other unit a melee_type*/reach_type*
ai. h3_* rows used to inherit ai from their donor, so Factory halflings/gunslingers ran
melee AI and HoMM3 angels/rocs ran ranged AI (owner: assign_homm3_battle_ai_types in
tools/release_port/apply_release_core_overlay.py).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

AI_BATTLE_PREFIX = "DB/ai_battle/"
UNIT_LOGIC_PREFIX = "DB/units/units_logics/"
_ID_RE = re.compile(r'"id"\s*:\s*"([^"]+)"')


def _read_json(zf: zipfile.ZipFile, name: str) -> object:
    return json.loads(zf.read(name).decode("utf-8-sig"))


def battle_ai_ids(zf: zipfile.ZipFile) -> set[str]:
    ids: set[str] = set()
    for name in zf.namelist():
        if not name.startswith(AI_BATTLE_PREFIX) or not name.endswith(".json"):
            continue
        # ai_battle files carry tab-aligned JSON with trailing commas in places;
        # read ids textually so a lenient game parser is not second-guessed here.
        ids.update(_ID_RE.findall(zf.read(name).decode("utf-8-sig", "replace")))
    return ids


def validate_unit_battle_ai_in_core(core_zip: Path) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(core_zip) as zf:
        ai_ids = battle_ai_ids(zf)
        difficulties = sorted(i[len("default_"):] for i in ai_ids if i.startswith("default_"))
        if not difficulties:
            return [f"{core_zip}: no DB/ai_battle default_<difficulty> rows found; cannot resolve unit ai ids"]
        checked = 0
        for name in sorted(zf.namelist()):
            if not name.startswith(UNIT_LOGIC_PREFIX) or not name.endswith(".json"):
                continue
            try:
                doc = _read_json(zf, name)
            except ValueError as ex:
                errors.append(f"{name}: unit logic is not valid JSON ({ex})")
                continue
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or "ai" not in row:
                    continue
                checked += 1
                ai = row.get("ai")
                uid = row.get("id")
                if not isinstance(ai, str) or not ai:
                    errors.append(f"{name}:{uid}: ai must be a non-empty string, got {ai!r}")
                    continue
                attacks = row.get("defaultAttacks")
                shoots = isinstance(attacks, list) and any(
                    isinstance(a, dict) and a.get("attackType_") == "shoot" for a in attacks
                )
                if shoots != ai.startswith("range_type"):
                    errors.append(
                        f"{name}:{uid}: ai {ai!r} does not match its defaultAttacks "
                        f"({'shoot needs range_type*' if shoots else 'melee needs melee_type*/reach_type*'})"
                    )
                missing = [f"{ai}_{d}" for d in difficulties if f"{ai}_{d}" not in ai_ids]
                if missing:
                    errors.append(
                        f"{name}:{uid}: ai {ai!r} has no DB/ai_battle row for {', '.join(missing)} "
                        "(battle AI throws NullReferenceException; AI auto-battles softlock)"
                    )
        if checked == 0:
            errors.append(f"{core_zip}: no unit logic rows with an ai field found")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core", type=Path, required=True, help="Built or installed Core.zip")
    args = parser.parse_args(argv)
    if not args.core.is_file():
        print(f"ERROR: Core.zip not found: {args.core}")
        return 1
    errors = validate_unit_battle_ai_in_core(args.core)
    for err in errors:
        print(f"ERROR: {err}")
    if errors:
        print(f"unit battle-ai contract failed: {len(errors)} error(s)")
        return 1
    print("unit battle-ai contract OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
