import json
import re
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MOD_DIR = ROOT / "vcmi" / "Mods" / "tears-of-ashan"
CONTENT_ZIP = MOD_DIR / "content.zip"
OUT = ROOT / "docs" / "homm3_tears_of_ashan_creature_specs.md"

FACTION_ORDER = [
    "castle",
    "rampart",
    "tower",
    "inferno",
    "necropolis",
    "dungeon",
    "stronghold",
    "fortress",
    "conflux",
    "cove",
]

SKIP_CREATURE_FILES = {
    "castle.json",
    "rampart.json",
    "tower.json",
    "inferno.json",
    "necropolis.json",
    "dungeon.json",
    "stronghold.json",
    "fortress.json",
    "conflux.json",
    "cove.json",
    "rebalance.json",
}


def md(text):
    return str(text).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")


def creature_name(data):
    name = data.get("name", {})
    if isinstance(name, dict):
        return name.get("singular") or name.get("plural") or ""
    return str(name)


def damage(data):
    dmg = data.get("damage", {})
    if isinstance(dmg, dict):
        return f"{dmg.get('min', '')}-{dmg.get('max', '')}"
    return str(dmg)


def cost(data):
    c = data.get("cost", {})
    if not isinstance(c, dict) or not c:
        return ""
    return ", ".join(f"{k} {v}" for k, v in sorted(c.items()))


def ability_summary(abilities):
    if not isinstance(abilities, dict) or not abilities:
        return "none"
    parts = []
    for key, spec in abilities.items():
        if not isinstance(spec, dict):
            parts.append(f"{key}: {spec}")
            continue
        detail = [spec.get("type", "")]
        for field in ("subtype", "val", "addInfo", "valueType", "propagator", "propagationUpdater"):
            if field in spec:
                detail.append(f"{field}={spec[field]}")
        if "description" in spec:
            desc = re.sub(r"\s+", " ", str(spec["description"]).strip())
            detail.append(f'desc="{desc}"')
        parts.append(f"{key}: " + ", ".join(x for x in detail if x))
    return "; ".join(parts)


def spell_refs(abilities):
    refs = []
    if not isinstance(abilities, dict):
        return refs
    for spec in abilities.values():
        if isinstance(spec, dict) and spec.get("type") == "SPELLCASTER" and spec.get("subtype"):
            refs.append(str(spec["subtype"]))
    return refs


def spell_summary(spell_id, spell):
    levels = spell.get("levels", {}) if isinstance(spell, dict) else {}
    descriptions = []
    if isinstance(levels, dict):
        for level in ("none", "basic", "advanced", "expert"):
            desc = levels.get(level, {}).get("description") if isinstance(levels.get(level), dict) else None
            if desc:
                descriptions.append(f"{level}: {re.sub(r'\\s+', ' ', str(desc).strip())}")
    fields = []
    for field in ("type", "targetType", "level", "power"):
        if field in spell:
            fields.append(f"{field}={spell[field]}")
    if descriptions:
        fields.append("; ".join(descriptions))
    return "; ".join(fields)


def load_json_from_zip(z, name):
    text = z.read(name).decode("utf-8-sig")
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    return json.loads(text)


def sort_key(item):
    path, creature_id, data = item
    return (
        FACTION_ORDER.index(data.get("faction", "zzz"))
        if data.get("faction") in FACTION_ORDER
        else 999,
        data.get("level", 99),
        path,
        creature_id,
    )


def main():
    mod = json.loads((MOD_DIR / "mod.json").read_text(encoding="utf-8"))
    creatures = []
    spells = {}
    with zipfile.ZipFile(CONTENT_ZIP) as z:
        for name in z.namelist():
            if name.startswith("config/spells/") and name.endswith(".json"):
                data = load_json_from_zip(z, name)
                for spell_id, spell in data.items():
                    spells[spell_id] = spell

        for name in z.namelist():
            if not name.startswith("config/creatures/") or not name.endswith(".json"):
                continue
            file_name = name.rsplit("/", 1)[1]
            if file_name in SKIP_CREATURE_FILES:
                continue
            data = load_json_from_zip(z, name)
            for creature_id, creature in data.items():
                if isinstance(creature, dict) and creature.get("faction") in FACTION_ORDER:
                    creatures.append((name, creature_id, creature))

    by_faction = {f: [] for f in FACTION_ORDER}
    used_spell_refs = set()
    for item in sorted(creatures, key=sort_key):
        _, _, creature = item
        by_faction[creature["faction"]].append(item)
        used_spell_refs.update(spell_refs(creature.get("abilities")))

    lines = [
        "# Tears of Ashan Creature Specs",
        "",
        "Generated from local VCMI source `vcmi/Mods/tears-of-ashan/content.zip`.",
        f"ToA manifest version: `{mod.get('version', 'unknown')}`.",
        "",
        "Use this as the canonical source for `_upg_alt` creature stats and ability targets in future HoMM3 faction ports. Do not treat the older faction-plan alternate-upgrade text as implementation-ready when it conflicts with this mined data.",
        "",
        "VCMI ability names are source identifiers, not Olden Era implementation names. Port them by preserving behavior first, then mapping to OE-native data or a traced hook. Probability-based effects should become explicit OE focus-point abilities when the faction-plan README requires that conversion.",
        "",
    ]

    for faction in FACTION_ORDER:
        rows = by_faction[faction]
        lines.extend([f"## {faction.title()}", ""])
        lines.append("| Source | VCMI id | Name | Lvl | A/D | Dmg | HP | Spd | Growth | Shots | Cost | Upgrades | Abilities |")
        lines.append("| --- | --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |")
        for path, creature_id, data in rows:
            rowsrc = path.replace("config/creatures/", "")
            ad = f"{data.get('attack', '')}/{data.get('defense', '')}"
            shots = data.get("shots", "")
            upgrades = ", ".join(data.get("upgrades", [])) if isinstance(data.get("upgrades"), list) else ""
            lines.append(
                "| "
                + " | ".join(
                    md(x)
                    for x in [
                        rowsrc,
                        creature_id,
                        creature_name(data),
                        data.get("level", ""),
                        ad,
                        damage(data),
                        data.get("hitPoints", ""),
                        data.get("speed", ""),
                        data.get("growth", ""),
                        shots,
                        cost(data),
                        upgrades,
                        ability_summary(data.get("abilities")),
                    ]
                )
                + " |"
            )
        lines.append("")

    if used_spell_refs:
        lines.extend(["## Referenced Creature Ability Spells", ""])
        lines.append("| Spell id | Summary |")
        lines.append("| --- | --- |")
        for spell_id in sorted(used_spell_refs):
            lines.append(f"| {md(spell_id)} | {md(spell_summary(spell_id, spells.get(spell_id, {})))} |")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} with {len(creatures)} creatures and {len(used_spell_refs)} spell refs.")


if __name__ == "__main__":
    main()
