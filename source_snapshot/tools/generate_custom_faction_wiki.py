#!/usr/bin/env python3
"""Generate starter GitHub-wiki Markdown for custom HoMM3 faction data.

This is intentionally a one-shot documentation helper. It reads the current
live Core.zip and custom_factions manifests, then writes wiki-ready Markdown
under docs/github_wiki/.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CORE_ZIP = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)
OUT_DIR = ROOT / "docs" / "github_wiki"


STAT_NAMES = [
    "hp",
    "offence",
    "defence",
    "damageMin",
    "damageMax",
    "initiative",
    "speed",
    "shots",
]

CITY_SECTIONS = [
    "mains",
    "taverns",
    "markets",
    "artifactMarkets",
    "hires",
    "magicGuilds",
    "banks",
    "walls",
    "intelligences",
    "trainingRanges",
    "graals",
    "manaFountains",
    "unitsConverters",
    "gyms",
    "lyceums",
    "rebirthShrines",
]


def load_json_zip(zf: zipfile.ZipFile, path: str) -> Any:
    return json.loads(zf.read(path).decode("utf-8-sig"))


def token_map(zf: zipfile.ZipFile, name: str) -> dict[str, str]:
    path = f"Lang/english/texts/{name}.json"
    if path not in zf.namelist():
        return {}
    data = load_json_zip(zf, path)
    tokens = data.get("tokens", [])
    if isinstance(tokens, dict):
        return {str(k): str(v) for k, v in tokens.items()}
    return {str(row.get("sid")): str(row.get("text", "")) for row in tokens if row.get("sid")}


def text(tokens: dict[str, str], sid: str | None) -> str:
    if not sid:
        return ""
    return tokens.get(sid, sid)


def slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s or "page"


def cost_list(items: list[dict[str, Any]] | None) -> str:
    if not items:
        return "free"
    return ", ".join(f"{c.get('cost')} {c.get('name')}" for c in items)


def req_list(reqs: list[dict[str, Any]] | None) -> str:
    if not reqs:
        return "none"
    return ", ".join(f"{r.get('sid')} L{r.get('level')}" for r in reqs)


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def bonus_summary(bonus: dict[str, Any]) -> str:
    typ = bonus.get("type") or bonus.get("mech") or bonus.get("t") or "bonus"
    params = bonus.get("parameters")
    if params is None:
        params = {k: v for k, v in bonus.items() if k not in {"type", "mech"}}
    receivers = bonus.get("receivers")
    receiver_text = f" receivers={compact_json(receivers)}" if receivers else ""
    return f"{typ}({compact_json(params)}){receiver_text}"


def bonuses_summary(bonuses: Any) -> str:
    if not bonuses:
        return ""
    if isinstance(bonuses, list):
        return "; ".join(bonus_summary(b) if isinstance(b, dict) else compact_json(b) for b in bonuses)
    return compact_json(bonuses)


def attack_summary(attacks: list[dict[str, Any]]) -> str:
    if not attacks:
        return "none"
    parts: list[str] = []
    for attack in attacks:
        dealer = attack.get("damageDealer", {})
        attack_type = attack.get("attackType_", "attack")
        dmg_type = dealer.get("damageType_", "damage")
        pattern = dealer.get("attackPatternSid", "pattern?")
        mult = dealer.get("statDmgMult", 1)
        trigger_counter = dealer.get("triggerCounter")
        parts.append(f"{attack_type}/{dmg_type}, {pattern}, x{mult}, triggerCounter={trigger_counter}")
    return "; ".join(parts)


def mechanic_summary(value: Any) -> str:
    if not value:
        return "none"
    if isinstance(value, list):
        return "; ".join(mechanic_summary(v) for v in value)
    if isinstance(value, dict):
        if "data" in value and len(value) == 1:
            return mechanic_summary(value["data"])
        keys = []
        for key in ["immunities", "disablers", "targetMechanics", "selfMechanics", "mechanics", "actions"]:
            if value.get(key):
                keys.append(f"{key}={compact_json(value[key])}")
        if keys:
            return "; ".join(keys)
        return compact_json(value)
    return str(value)


def building_effects(row: dict[str, Any]) -> str:
    effects: list[str] = []
    if row.get("bonuses"):
        effects.append(f"bonuses: {bonuses_summary(row['bonuses'])}")
    if row.get("bonusesPerLevel"):
        levels = []
        for idx, level in enumerate(row["bonusesPerLevel"], 1):
            levels.append(f"L{idx} {bonuses_summary(level)}")
        effects.append("bonuses per level: " + " | ".join(levels))
    if row.get("optionalEffectsPerLevel"):
        effects.append("optional effects per level: " + compact_json(row["optionalEffectsPerLevel"]))
    if row.get("unitsHire"):
        hires = []
        units_hire = row["unitsHire"]
        if isinstance(units_hire, dict):
            units_hire = units_hire.get("units", [])
        for h in units_hire:
            if isinstance(h, dict):
                sids = h.get("sids") or h.get("unitSid") or h.get("sid") or "unit?"
                if isinstance(sids, list):
                    sids = ", ".join(sids)
                growth = h.get("weeklyIncrement", h.get("increment", h.get("count", "?")))
                hires.append(f"{sids}: weekly growth {growth}")
            else:
                hires.append(str(h))
        effects.append("recruitment: " + "; ".join(hires))
    if row.get("viewRadius") is not None:
        effects.append(f"town view radius {row['viewRadius']}")
    if row.get("trainingStats"):
        stats = []
        for s in row["trainingStats"]:
            stats.append(f"{s.get('name')} values {compact_json(s.get('values'))}")
        effects.append("training: " + "; ".join(stats))
    if row.get("sideBonuses"):
        effects.append("side bonuses: " + bonuses_summary(row["sideBonuses"]))
    if row.get("cityBonuses"):
        effects.append("city bonuses: " + bonuses_summary(row["cityBonuses"]))
    if row.get("conversionPairs"):
        effects.append("conversion pairs: " + compact_json(row["conversionPairs"]))
    if row.get("rollChances"):
        effects.append("spell roll chances configured")
    if row.get("resArr"):
        effects.append("resource action: " + compact_json(row["resArr"]))
    if row.get("levelStep") is not None:
        effects.append(f"level step {row['levelStep']}")
    if row.get("extraChargePurchase") is not None:
        effects.append(
            "artifact market charges: "
            f"buy x{row.get('extraChargePurchase')}, sell x{row.get('extraChargeSell')}, "
            f"rarity counts {compact_json(row.get('itemsCountPerRarity'))}"
        )
    return "<br>".join(effects) if effects else "Native section behavior only; no explicit bonus payload."


def table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        clean = [str(cell).replace("\n", "<br>").replace("|", "\\|") for cell in row]
        out.append("| " + " | ".join(clean) + " |")
    return "\n".join(out)


def collect_unit_rows(zf: zipfile.ZipFile, faction_sid: str) -> list[dict[str, Any]]:
    prefix = f"DB/units/units_logics/{faction_sid}/"
    rows: list[dict[str, Any]] = []
    for name in sorted(zf.namelist()):
        if name.startswith(prefix) and name.endswith(".json"):
            rows.extend(load_json_zip(zf, name).get("array", []))
    return sorted(rows, key=lambda u: (u.get("tier", 99), str(u.get("id"))))


def format_squad(squad: list[dict[str, Any]] | None) -> str:
    if not squad:
        return "none"
    return ", ".join(f"{row.get('sid')} {row.get('min')}-{row.get('max')}" for row in squad)


def collect_heroes(faction_sid: str) -> list[tuple[str, dict[str, Any]]]:
    path = ROOT / "custom_factions" / "hero_overrides" / f"{faction_sid}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    heroes = data.get("heroOverrides", {})
    return sorted(heroes.items(), key=lambda kv: kv[0])


def render_faction_page(
    zf: zipfile.ZipFile,
    manifest: dict[str, Any],
    all_tokens: dict[str, str],
) -> tuple[str, str]:
    identity = manifest["identity"]
    faction_sid = identity["factionSid"]
    display = manifest.get("runtime", {}).get("displayName") or text(all_tokens, identity.get("displayNameToken")) or faction_sid
    city = load_json_zip(zf, manifest["coreOverlay"]["cityLogic"])["array"][0]
    laws = load_json_zip(zf, manifest["coreOverlay"]["lawsTable"])["array"]
    units = collect_unit_rows(zf, faction_sid)
    heroes = collect_heroes(faction_sid)

    lines: list[str] = [
        f"# {display}",
        "",
        f"Generated from live Core.zip on {date.today().isoformat()}.",
        "",
        "## Identity",
        "",
        table(
            ["Field", "Current value"],
            [
                ["Faction SID", faction_sid],
                ["City SID", identity.get("citySid", "")],
                ["Donor faction/city", f"{identity.get('donorFactionSid', '')} / {identity.get('donorCitySid', '')}"],
                ["Native biome", identity.get("nativeBiome", "")],
                ["Runtime biome", str(manifest.get("releaseScaffold", {}).get("biome", ""))],
                ["Faction skill", manifest.get("skillsAndLaws", {}).get("factionSkillSid", "")],
                ["Law prefix", manifest.get("skillsAndLaws", {}).get("lawPrefix", "")],
                ["Map billboard height", str(manifest.get("runtime", {}).get("cityMapBillboardHeight", ""))],
            ],
        ),
        "",
        "## Runtime Contract",
        "",
        "- Custom-to-donor source: `" + str(manifest.get("runtime", {}).get("customToDonorSource", "")) + "`.",
        "- Reverse donor lookup: `" + str(manifest.get("runtime", {}).get("reverseDonorLookup", "")) + "`.",
        "- Global donor reverse lookup allowed: `" + str(manifest.get("runtime", {}).get("allowGlobalDonorReverseLookup", "")) + "`.",
        "- Direct city map object: `" + str(manifest.get("coreOverlay", {}).get("directCityMapObject", "")) + "`.",
        "- Direct dwelling prefix: `" + str(manifest.get("coreOverlay", {}).get("directDwellingPrefix", "")) + "`.",
    ]
    donor_prefixes = manifest.get("runtime", {}).get("dwellingDonorPrefixes") or []
    if donor_prefixes:
        lines.append("- Donor dwelling prefixes resolved only by exact/contextual payload: `" + "`, `".join(donor_prefixes) + "`.")
    if manifest.get("validation", {}).get("allowedDebt"):
        lines.extend(["", "## Known Debt / Warnings", ""])
        lines.extend(f"- {item}" for item in manifest["validation"]["allowedDebt"])

    if heroes:
        lines.extend(["", "## Heroes", ""])
        hero_rows = []
        for hero_sid, hero in heroes:
            spec = hero.get("specialization") or {}
            spec_effects = bonuses_summary(spec.get("bonuses"))
            hero_rows.append(
                [
                    f"`{hero_sid}`",
                    hero.get("nameText", ""),
                    hero.get("className", hero.get("classType", "")),
                    format_squad(hero.get("startSquad")),
                    format_squad(hero.get("startSquadAlt")),
                    "; ".join(
                        f"{skill.get('sid')} L{skill.get('skillLevel')}" for skill in hero.get("startSkills", [])
                    ),
                    spec.get("nameText", ""),
                    spec.get("descriptionText", ""),
                    spec_effects or "none",
                ]
            )
        lines.append(
            table(
                [
                    "Hero SID",
                    "Name",
                    "Class",
                    "Start squad",
                    "Alt squad",
                    "Start skills",
                    "Specialization",
                    "Specialization text",
                    "Specialization mechanics",
                ],
                hero_rows,
            )
        )

    lines.extend(["", "## Unit Lines", ""])
    unit_line_rows = []
    names_by_id = {u.get("id"): text(all_tokens, f"{u.get('id')}_name") for u in units}
    for line in manifest.get("unitLines", []):
        variants = []
        for suffix in manifest.get("unitVariants", ["", "_upg", "_upg_alt"]):
            sid = f"{line.get('baseSid')}{suffix}"
            variants.append(f"`{sid}` {names_by_id.get(sid, '')}".strip())
        unit_line_rows.append([
            str(line.get("tier", "")),
            line.get("baseSid", ""),
            line.get("donorBaseSid", ""),
            "<br>".join(variants),
        ])
    lines.append(table(["Tier", "Base SID", "Donor base", "Current variants"], unit_line_rows))

    lines.extend(["", "## Units", ""])
    unit_rows = []
    for u in units:
        stats = u.get("stats", {})
        stat_text = ", ".join(f"{k}={stats.get(k)}" for k in STAT_NAMES if stats.get(k) is not None)
        mods = []
        for key in ["inDmgMods", "outDmgMods"]:
            if stats.get(key, {}).get("list"):
                mods.append(f"{key}={compact_json(stats[key]['list'])}")
        if mods:
            stat_text += "; " + "; ".join(mods)
        unit_rows.append([
            str(u.get("tier", "")),
            f"`{u.get('id')}`<br>{text(all_tokens, str(u.get('id')) + '_name')}",
            cost_list(u.get("unitCost", {}).get("costResArray")),
            f"squadValue={u.get('squadValue')}, expBonus={u.get('expBonus')}, ai={u.get('ai')}",
            stat_text,
            attack_summary(u.get("defaultAttacks", [])),
            attack_summary(u.get("alternativeAttacks", [])),
            mechanic_summary(u.get("passives", [])),
            mechanic_summary(u.get("abilities", [])),
            str(u.get("upgradeSid", "")),
        ])
    lines.append(
        table(
            [
                "Tier",
                "Unit",
                "Cost",
                "Values",
                "Stats",
                "Default attack",
                "Alt attack",
                "Passives",
                "Abilities",
                "Upgrade",
            ],
            unit_rows,
        )
    )

    lines.extend(["", "## Buildings", ""])
    building_rows = []
    for section in CITY_SECTIONS:
        for row in city.get(section, []) or []:
            names = row.get("names") or []
            descs = row.get("descriptions") or []
            params = row.get("parametersPerLevel") or []
            level_bits = []
            for idx, params_row in enumerate(params, 1):
                level_bits.append(
                    f"L{idx}: cost {cost_list(params_row.get('costs'))}; req {req_list(params_row.get('prevBuildings'))}"
                )
            name_text = "<br>".join(text(all_tokens, n) for n in names)
            desc_text = "<br>".join(text(all_tokens, d) for d in descs)
            building_rows.append([
                section,
                f"`{row.get('sid')}`",
                name_text,
                desc_text,
                "<br>".join(level_bits),
                building_effects(row),
            ])
    lines.append(table(["Section", "SID", "Name", "Current text", "Construction", "Current mechanics"], building_rows))

    lines.extend(["", "## Laws", ""])
    law_rows = []
    for law in laws:
        level_bits = []
        for idx, level in enumerate(law.get("parametersPerLevel") or [], 1):
            level_bits.append(f"L{idx}: cost {level.get('cost')}; {bonuses_summary(level.get('bonuses'))}")
        law_rows.append([
            f"`{law.get('id')}`",
            text(all_tokens, law.get("name")),
            text(all_tokens, law.get("desc")),
            "<br>".join(level_bits),
        ])
    lines.append(table(["SID", "Name", "Current text", "Current mechanics by level"], law_rows))

    return display, "\n".join(lines) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(CORE_ZIP) as zf:
        all_tokens: dict[str, str] = {}
        for token_file in [
            "cities",
            "units",
            "unitsAbility",
            "factionLaws",
            "heroSkills",
            "fractions",
            "heroes",
            "heroInfo",
        ]:
            all_tokens.update(token_map(zf, token_file))

        pages: list[tuple[str, str, str]] = []
        overview_rows: list[list[str]] = []
        for manifest_path in sorted((ROOT / "custom_factions").glob("homm3_*.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            display, body = render_faction_page(zf, manifest, all_tokens)
            page_name = f"Custom-Faction-{slug(display.replace(' (HoMM3)', ''))}.md"
            (OUT_DIR / page_name).write_text(body, encoding="utf-8", newline="\n")
            pages.append((display, page_name, manifest["identity"]["factionSid"]))
            overview_rows.append(
                [
                    f"[{display}]({page_name[:-3]})",
                    manifest["identity"]["factionSid"],
                    manifest["identity"].get("nativeBiome", ""),
                    manifest["identity"].get("donorFactionSid", ""),
                    manifest.get("skillsAndLaws", {}).get("factionSkillSid", ""),
                    str(len(manifest.get("unitLines", []))),
                ]
            )

        home = [
            "# Custom Faction Wiki",
            "",
            f"Starter wiki generated on {date.today().isoformat()} from the live Steam Core.zip and `custom_factions/*.json` manifests.",
            "",
            "This wiki documents current implemented data, not design intent. It keeps raw SIDs visible because the custom faction pipeline depends on stable identifiers and exact donor-routing contracts.",
            "",
            "## Pages",
            "",
            "- [Custom Faction Overview](Custom-Faction-Overview)",
            "- [Custom Faction Attribute Reference](Custom-Faction-Attribute-Reference)",
        ]
        home.extend(f"- [{display}]({page[:-3]})" for display, page, _ in pages)
        (OUT_DIR / "Home.md").write_text("\n".join(home) + "\n", encoding="utf-8", newline="\n")

        overview = [
            "# Custom Faction Overview",
            "",
            "These are the currently registered custom factions in the live Core data.",
            "",
            table(["Faction", "Faction SID", "Native biome", "Donor faction", "Faction skill SID", "Unit lines"], overview_rows),
            "",
            "## Shared Implementation Rules",
            "",
            "- Custom factions use manifest-owned custom-to-donor mapping. Do not enable broad reverse lookup from donor SIDs; resolve donor map objects from exact live payloads or known contextual state.",
            "- Buildings are functional by section-specific fields, not only by a generic `bonuses` array. Check `unitsHire`, `viewRadius`, `trainingStats`, `sideBonuses`, `cityBonuses`, `conversionPairs`, artifact-market charge fields, and section name before declaring a row inert.",
            "- Player-facing text should describe only shipped behavior. Avoid water, ship, teleport, war-machine, or school-purchase claims unless the corresponding native or traced runtime path exists.",
            "- Unit view donor meshes are scaffolding. Current unit behavior is defined by logic rows, attacks, abilities, passives, and the runtime HoMM3 import hooks.",
        ]
        (OUT_DIR / "Custom-Faction-Overview.md").write_text(
            "\n".join(overview) + "\n", encoding="utf-8", newline="\n"
        )

        attr = [
            "# Custom Faction Attribute Reference",
            "",
            "This page explains how to read the faction pages and what each documented attribute currently means.",
            "",
            "## Identity Attributes",
            "",
            "- `Faction SID` is the Core faction id used by unit, hero, law, city, and runtime registry rows.",
            "- `City SID` is the custom city object logic id.",
            "- `Donor faction/city` is the native scaffold used for Core shape, UI routes, or scene compatibility. It is not a license to globally alias donor rows.",
            "- `Native biome` and runtime biome identify the faction terrain assignment. Custom biomes require both Core rows and runtime renderer registration.",
            "- `Faction skill` is the hero skill SID assigned by hero overrides and law/skill icon routing.",
            "- `Law prefix` owns the faction law ids in `DB/fractions_laws`.",
            "",
            "## Unit Attributes",
            "",
            "- `Cost`, `squadValue`, `expBonus`, `ai`, and combat stats come directly from live unit logic JSON.",
            "- `Default attack` and `Alt attack` summarize the live attack payloads: attack kind, damage type, attack pattern, damage multiplier, and whether the attack triggers counters.",
            "- `Passives` and `Abilities` are compact JSON summaries of implemented live mechanics. Empty means no explicit payload exists in the unit row.",
            "- `Upgrade` is the current `upgradeSid`. Standard upgrade chains are gameplay data; do not remove them to hide UI problems.",
            "",
            "## Hero Attributes",
            "",
            "- Hero rows come from `custom_factions/hero_overrides/<faction>.json`.",
            "- `Start squad`, `Alt squad`, `Start skills`, and specialization payloads are current manifest-owned gameplay data used by the release overlay.",
            "- Specialization text and mechanics are both shown because text can drift from payloads during generator work.",
            "",
            "## Building Attributes",
            "",
            "- `Section` is the city JSON section that supplies native behavior. This matters as much as the row SID.",
            "- `Construction` lists level costs and prerequisites from `parametersPerLevel`.",
            "- `Current mechanics` is generated from live payload fields such as `bonuses`, `bonusesPerLevel`, `unitsHire`, `viewRadius`, `trainingStats`, `sideBonuses`, `cityBonuses`, `conversionPairs`, `rollChances`, and artifact-market charge settings.",
            "- Rows that show native section behavior only may still work through the native section handler. Verify the section and row-specific fields before changing behavior.",
            "",
            "## Law Attributes",
            "",
            "- Laws are listed exactly as live `fractions_laws_table_homm3_*` rows.",
            "- Each level shows current law cost and raw bonus payload. Text placeholders such as `{0}` are retained when the live localization keeps them.",
            "",
            "## Documentation Boundary",
            "",
            "These pages describe the live data state. They do not prove every runtime hook surface, animation, or UI presentation path works; use runtime notes and agent references for those surfaces.",
        ]
        (OUT_DIR / "Custom-Faction-Attribute-Reference.md").write_text(
            "\n".join(attr) + "\n", encoding="utf-8", newline="\n"
        )

        sidebar = ["# Custom Factions", "", "- [Home](Home)", "- [Overview](Custom-Faction-Overview)", "- [Attribute Reference](Custom-Faction-Attribute-Reference)"]
        sidebar.extend(f"- [{display}]({page[:-3]})" for display, page, _ in pages)
        (OUT_DIR / "_Sidebar.md").write_text("\n".join(sidebar) + "\n", encoding="utf-8", newline="\n")

    print(f"Wrote {len(list(OUT_DIR.glob('*.md')))} wiki pages to {OUT_DIR}")


if __name__ == "__main__":
    main()
