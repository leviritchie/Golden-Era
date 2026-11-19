#!/usr/bin/env python3
"""Build the Cove buried-treasure catalog the plugin reads at runtime.

Usage: python tools/cove_treasure/build_treasure_catalog.py <Core.zip> <out.tsv>
Rows: "A<TAB>item sid<TAB>goodsValue" for every non-special artifact with a goods value, and
"U<TAB>unit sid<TAB>squadValue<TAB>tier" for the nonliving whitelist of the design doc (section 3.4), including the
_upg and _upg_alt variants that exist in that Core. A and U rows end with the English display name, and
"N<TAB>resource sid<TAB>name" rows name the resources, so the treasure popup never shows an internal id. Re-run after a Core change that adds artifacts or re-prices units.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

NONLIVING = [
    # undead (vanilla)
    "skeleton", "flicker", "pet", "graverobber", "lich", "avatar_of_war", "vampire",
    # Necropolis (HoMM3)
    "h3_skeleton", "h3_walking_dead", "h3_wight", "h3_vampire", "h3_lich", "h3_black_knight", "h3_bone_dragon",
    # constructs
    "h3_gargoyle", "h3_golem", "h3_automaton", "h3_sentinel_automaton", "h3_dreadnought", "h3_juggernaut",
    "animated_armor", "h3_steel_golem", "mech_guard", "sentinel",
    # elementals
    "h3_air_elemental", "h3_water_elemental", "h3_fire_elemental", "h3_earth_elemental", "h3_psychic_elemental",
    # other
    "h3_mummy", "mummy", "kitten_skeleton",
]
RESOURCES = ["gold", "wood", "ore", "mercury", "crystals", "gemstones", "dust"]
ALLOWED = {base + suffix for base in NONLIVING for suffix in ("", "_upg", "_upg_alt")}


def load(z: zipfile.ZipFile, name: str):
    return json.loads(z.read(name).decode("utf-8-sig"))


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    core, out = Path(sys.argv[1]), Path(sys.argv[2])
    artifacts: dict[str, int] = {}
    units: dict[str, tuple[int, int]] = {}
    names: dict[str, str] = {}
    with zipfile.ZipFile(core) as z:
        tokens: dict[str, str] = {}
        for lang in ("artifacts", "units", "unitsAbility", "ui"):
            for token in load(z, f"Lang/english/texts/{lang}.json").get("tokens", []):
                if isinstance(token, dict) and token.get("sid") and token.get("text"):
                    tokens.setdefault(token["sid"], " ".join(str(token["text"]).split()))

        def name_of(sid: str, name_sid: str | None = None) -> None:
            # Vanilla items use their id as the name token; everything else uses "<id>_name".
            for key in (name_sid, f"{sid}_name", sid):
                if key and key in tokens:
                    names[sid] = tokens[key]
                    return

        for sid in RESOURCES:
            name_of(sid)
        for name in z.namelist():
            if name.startswith("DB/items/items/") and name.endswith(".json"):
                for row in load(z, name).get("array", []):
                    if (isinstance(row, dict) and row.get("id") and row.get("goodsValue") and not row.get("isSpecialItem")
                            and not row["id"].startswith("campaign_")):
                        artifacts[row["id"]] = int(row["goodsValue"])
                        name_of(row["id"], row.get("name"))
                continue
            match = re.search(r"DB/units/units_logics/.*/([^/]+)_l\.json$", name)
            if match and match.group(1) in ALLOWED:
                data = load(z, name)
                row = data["array"][0] if isinstance(data, dict) and "array" in data else data
                if isinstance(row, dict) and row.get("squadValue"):
                    units[match.group(1)] = (int(row["squadValue"]), int(row.get("tier", 1)))
                    name_of(match.group(1))
    unnamed = sorted(sid for sid in [*artifacts, *units, *RESOURCES] if sid not in names)
    lines = [f"A\t{sid}\t{value}\t{names.get(sid, '')}" for sid, value in sorted(artifacts.items())]
    lines += [f"U\t{sid}\t{value}\t{tier}\t{names.get(sid, '')}" for sid, (value, tier) in sorted(units.items())]
    lines += [f"N\t{sid}\t{names[sid]}" for sid in RESOURCES if sid in names]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    missing = sorted(base for base in NONLIVING if base not in units)
    print(f"{out}: {len(artifacts)} artifacts, {len(units)} units; whitelist bases not in this Core: {missing or 'none'}")
    print(f"without an English name ({len(unnamed)}): {unnamed or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
