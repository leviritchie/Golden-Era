#!/usr/bin/env python3
"""Generate HoMM3 custom unit ability catalog markdown + JSON for the web UI."""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

FACTION_ORDER = [
    "homm3_castle",
    "homm3_rampart",
    "homm3_tower",
    "homm3_inferno",
    "homm3_necropolis",
    "homm3_dungeon",
    "homm3_stronghold",
    "homm3_fortress",
    "homm3_conflux",
    "homm3_cove",
    "homm3_factory",
    "homm3_bulwark",
]

FACTION_LABELS = {
    "homm3_castle": "Castle",
    "homm3_rampart": "Rampart",
    "homm3_tower": "Tower",
    "homm3_inferno": "Inferno",
    "homm3_necropolis": "Necropolis",
    "homm3_dungeon": "Dungeon",
    "homm3_stronghold": "Stronghold",
    "homm3_fortress": "Fortress",
    "homm3_conflux": "Conflux",
    "homm3_cove": "Cove",
    "homm3_factory": "Factory",
    "homm3_bulwark": "Bulwark",
}

COMMON_GENERIC = {
    "h3_common_melee_attack_name",
    "h3_common_ranged_attack_name",
    "h3_common_flying_name",
    "h3_common_no_melee_penalty_name",
    "h3_common_no_enemy_retaliation_name",
}

DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)


def load_lang_map(z: zipfile.ZipFile, member: str) -> dict[str, str]:
    try:
        doc = json.loads(z.read(member).decode("utf-8-sig"))
    except KeyError:
        return {}
    out: dict[str, str] = {}

    def ingest_rows(rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if isinstance(row, dict) and "sid" in row:
                out[str(row["sid"])] = str(row.get("text") or "")

    if isinstance(doc, dict):
        for list_key in ("tokens", "entries", "array"):
            if list_key in doc:
                ingest_rows(doc.get(list_key))
        if out:
            return out
        for key, value in doc.items():
            if isinstance(value, str):
                out[str(key)] = value
            elif isinstance(value, dict) and "text" in value:
                out[str(key)] = str(value.get("text") or "")
        return out
    if isinstance(doc, list):
        ingest_rows(doc)
    return out


def unwrap(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get("array"), list) and raw["array"]:
        first = raw["array"][0]
        return first if isinstance(first, dict) else {}
    return raw if isinstance(raw, dict) else {}


def fmt_cost(unit_cost: Any) -> str:
    if not isinstance(unit_cost, dict):
        return "n/a"
    parts: list[str] = []
    cost_res = unit_cost.get("costResArray")
    if isinstance(cost_res, list):
        for row in cost_res:
            if not isinstance(row, dict):
                continue
            name = row.get("name") or row.get("sid") or "resource"
            cost = row.get("cost")
            if cost in (0, 0.0, None, ""):
                continue
            parts.append(f"{cost} {name}")
    for key in sorted(unit_cost.keys()):
        if key == "costResArray":
            continue
        value = unit_cost[key]
        if value in (0, 0.0, None, ""):
            continue
        if isinstance(value, (int, float, str)):
            parts.append(f"{value} {key}")
    return ", ".join(parts) if parts else "free/none"


def parse_cost_parts(unit_cost: Any) -> list[dict[str, Any]]:
    if not isinstance(unit_cost, dict):
        return []
    parts: list[dict[str, Any]] = []
    cost_res = unit_cost.get("costResArray")
    if isinstance(cost_res, list):
        for row in cost_res:
            if not isinstance(row, dict):
                continue
            name = row.get("name") or row.get("sid") or "resource"
            cost = row.get("cost")
            if cost in (0, 0.0, None, ""):
                continue
            parts.append({"resource": str(name), "amount": cost})
    return parts


def humanize_key(key: str) -> str:
    text = key
    for suffix in ("_name", "_description", "_Name", "_Description"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    text = text.replace("h3_", "").replace("_", " ").strip()
    return text.title() if text else key


def resolve_label(txt_fn, key: Any, fallback: str = "") -> str:
    resolved = txt_fn(key)
    if resolved:
        return resolved
    if fallback:
        return fallback
    if key:
        return humanize_key(str(key))
    return ""


def summarize_logic_ability(ability: dict[str, Any]) -> dict[str, Any]:
    dealer = ability.get("damageDealer") or {}
    if not isinstance(dealer, dict):
        dealer = {}
    buff = dealer.get("buff")
    buff_sid = buff.get("sid") if isinstance(buff, dict) else None
    data = ability.get("data") if isinstance(ability.get("data"), dict) else {}
    tags = dealer.get("tags") or []
    return {
        "energy": ability.get("energyLevel"),
        "cd": ability.get("cd") if "cd" in ability else ability.get("cooldown"),
        "rank": ability.get("rank"),
        "attackType": ability.get("attackType_") or ability.get("attackType"),
        "dontUseEnergy": bool(ability.get("dontUseEnergy")),
        "charges": ability.get("charges"),
        "tags": list(tags) if isinstance(tags, list) else [],
        "damageType": dealer.get("damageType_"),
        "pattern": dealer.get("attackPatternSid"),
        "statDmgMult": dealer.get("statDmgMult"),
        "buffSid": buff_sid,
        "sequence": data.get("sequenceEffect") if isinstance(data, dict) else None,
    }


def summarize_passive_logic(passive: dict[str, Any]) -> str:
    data = passive.get("data") if isinstance(passive.get("data"), dict) else passive
    bits: list[str] = []
    if not isinstance(data, dict):
        return ""
    if "sequenceEffect" in data:
        bits.append(f"sequence={data['sequenceEffect']}")
    for key, value in data.items():
        if key == "sequenceEffect":
            continue
        if isinstance(value, (str, int, float, bool)):
            bits.append(f"{key}={value}")
        elif isinstance(value, list) and value and all(
            isinstance(item, (str, int, float, bool)) for item in value[:5]
        ):
            bits.append(f"{key}={value}")
        if len(bits) >= 8:
            break
    return "; ".join(bits)


def load_ability_overrides(repo: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    ovr_dir = repo / "custom_factions" / "ability_overrides"
    if not ovr_dir.is_dir():
        return out
    for path in sorted(ovr_dir.glob("homm3_*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for sid, unit in (doc.get("unitOverrides") or {}).items():
            if isinstance(unit, dict):
                out[str(sid)] = unit
    return out


def cost_bits_from_summary(summary: dict[str, Any]) -> list[str]:
    bits: list[str] = []
    if summary.get("dontUseEnergy"):
        bits.append("Focus: none (dontUseEnergy)")
    elif summary.get("energy") is not None:
        bits.append(f"Focus: {summary['energy']}")
    else:
        bits.append("Focus: unspecified")
    if summary.get("cd") is not None:
        bits.append(f"Cooldown: {summary['cd']}")
    if summary.get("rank") is not None:
        bits.append(f"Rank: {summary['rank']}")
    if summary.get("charges") not in (None, "", []):
        bits.append(f"Charges: {summary['charges']}")
    if summary.get("attackType"):
        bits.append(f"Attack type: {summary['attackType']}")
    return bits


def logic_bits_from_summary(summary: dict[str, Any]) -> list[str]:
    bits: list[str] = []
    if summary.get("buffSid"):
        bits.append(f"buff `{summary['buffSid']}`")
    if summary.get("damageType"):
        bits.append(f"damageType `{summary['damageType']}`")
    if summary.get("statDmgMult") not in (None, 1, 1.0):
        bits.append(f"statDmgMult `{summary['statDmgMult']}`")
    if summary.get("pattern"):
        bits.append(f"pattern `{summary['pattern']}`")
    if summary.get("tags"):
        bits.append("tags " + ", ".join(str(tag) for tag in summary["tags"][:8]))
    return bits


def collect_catalog(repo: Path, core_path: Path) -> tuple[dict[str, Any], dict[str, int]]:
    override_by_sid = load_ability_overrides(repo)
    stats = {"units": 0, "missing_desc": 0, "factions": 0}

    with zipfile.ZipFile(core_path) as zf:
        names = zf.namelist()
        ability_lang = load_lang_map(zf, "Lang/english/texts/unitsAbility.json")
        unit_lang = load_lang_map(zf, "Lang/english/texts/units.json")
        for extra in (
            "Lang/english/texts/unitNames.json",
            "Lang/english/texts/unitsNames.json",
        ):
            unit_lang.update(load_lang_map(zf, extra))

        logic_files = [
            name
            for name in names
            if name.startswith("DB/units/units_logics/homm3_") and name.endswith("_l.json")
        ]
        view_files = {
            name.split("/")[-1].replace("_v.json", ""): name
            for name in names
            if name.startswith("DB/units/units_views/homm3_") and name.endswith("_v.json")
        }

        def txt(key: Any) -> str:
            if not key:
                return ""
            token = str(key)
            for table in (ability_lang, unit_lang):
                value = table.get(token)
                if value and value.strip():
                    return value.strip()
            return ""

        def unit_display_name(sid: str) -> str:
            for key in (f"{sid}_name", sid, f"{sid}_Name"):
                value = txt(key)
                if value:
                    return value
            return humanize_key(sid)

        def override_special(sid: str, slot_kind: str, index: int) -> dict[str, Any] | None:
            override = override_by_sid.get(sid) or {}
            for special in override.get("existingSpecials") or []:
                if not special.get("enabled"):
                    continue
                if special.get("slotKind") == slot_kind and special.get("index") == index:
                    return special
            return None

        by_faction: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for logic_path in sorted(logic_files):
            faction = logic_path.split("/")[3]
            sid = logic_path.split("/")[-1].replace("_l.json", "")
            logic = unwrap(json.loads(zf.read(logic_path)))
            view_path = view_files.get(sid)
            view = unwrap(json.loads(zf.read(view_path))) if view_path else {}
            by_faction[faction].append((sid, logic, view))

        faction_keys = FACTION_ORDER + sorted(set(by_faction) - set(FACTION_ORDER))
        unit_records: list[dict[str, Any]] = []
        faction_summaries: list[dict[str, Any]] = []

        for faction in faction_keys:
            rows = by_faction.get(faction, [])
            if not rows:
                continue

            def sort_key(item: tuple[str, dict[str, Any], dict[str, Any]]) -> tuple[int, str]:
                sid, logic, _view = item
                tier = logic.get("tier")
                try:
                    tier_i = int(tier)  # type: ignore[arg-type]
                except Exception:
                    tier_i = 99
                return (tier_i, sid)

            with_actives = 0
            with_passives = 0
            for sid, logic, view in sorted(rows, key=sort_key):
                view_abilities = view.get("abilities") or []
                logic_abilities = logic.get("abilities") or []
                view_passives = view.get("passives") or []
                logic_passives = logic.get("passives") or []
                view_alts = view.get("alternativeAttacks") or []
                logic_alts = logic.get("alternativeAttacks") or []
                if view_abilities or logic_abilities:
                    with_actives += 1
                if view_passives or logic_passives:
                    with_passives += 1

                try:
                    tier_i = int(logic.get("tier"))  # type: ignore[arg-type]
                except Exception:
                    tier_i = 99

                actives: list[dict[str, Any]] = []
                count = max(len(view_abilities), len(logic_abilities))
                for index in range(count):
                    view_row = view_abilities[index] if index < len(view_abilities) else {}
                    logic_row = logic_abilities[index] if index < len(logic_abilities) else {}
                    if not isinstance(view_row, dict):
                        view_row = {}
                    if not isinstance(logic_row, dict):
                        logic_row = {}
                    name_key = view_row.get("name")
                    desc_key = view_row.get("description")
                    special = override_special(sid, "abilities", index)
                    ability_name = resolve_label(
                        txt,
                        name_key,
                        fallback=str((special or {}).get("nameText") or ""),
                    ) or f"Ability {index}"
                    ability_desc = txt(desc_key) or str(
                        (special or {}).get("descriptionText") or ""
                    )
                    if desc_key and not ability_desc:
                        stats["missing_desc"] += 1
                    summary = summarize_logic_ability(logic_row)
                    intended = None
                    if special:
                        intended_name = special.get("nameText") or ""
                        intended_desc = special.get("descriptionText") or ""
                        live_name = txt(name_key)
                        live_desc = txt(desc_key)
                        differs = (intended_name and intended_name != live_name) or (
                            intended_desc and intended_desc != live_desc
                        )
                        if differs:
                            intended = {
                                "name": intended_name,
                                "description": intended_desc,
                                "energy": special.get("energyLevel"),
                                "cooldown": special.get("cooldown"),
                            }
                    actives.append(
                        {
                            "name": ability_name,
                            "description": ability_desc,
                            "focus": summary.get("energy"),
                            "cooldown": summary.get("cd"),
                            "rank": summary.get("rank"),
                            "charges": summary.get("charges"),
                            "attackType": summary.get("attackType"),
                            "dontUseEnergy": summary.get("dontUseEnergy"),
                            "costLabel": "; ".join(cost_bits_from_summary(summary)),
                            "logicLabel": "; ".join(logic_bits_from_summary(summary)),
                            "buffSid": summary.get("buffSid"),
                            "tags": summary.get("tags") or [],
                            "intended": intended,
                            "icon": view_row.get("icon") or "",
                        }
                    )

                passives: list[dict[str, Any]] = []
                count = max(len(view_passives), len(logic_passives))
                for index in range(count):
                    view_row = view_passives[index] if index < len(view_passives) else {}
                    logic_row = logic_passives[index] if index < len(logic_passives) else {}
                    if not isinstance(view_row, dict):
                        view_row = {}
                    if not isinstance(logic_row, dict):
                        logic_row = {}
                    name_key = view_row.get("name")
                    desc_key = view_row.get("description")
                    special = override_special(sid, "passives", index)
                    passive_name = resolve_label(
                        txt,
                        name_key,
                        fallback=str((special or {}).get("nameText") or ""),
                    ) or f"Passive {index}"
                    passive_desc = txt(desc_key) or str(
                        (special or {}).get("descriptionText") or ""
                    )
                    if desc_key and not passive_desc:
                        stats["missing_desc"] += 1
                    logic_sum = summarize_passive_logic(logic_row)
                    is_generic = bool(name_key in COMMON_GENERIC) if name_key else False
                    passives.append(
                        {
                            "name": passive_name,
                            "description": passive_desc,
                            "generic": is_generic,
                            "logicLabel": logic_sum,
                            "icon": view_row.get("icon") or "",
                        }
                    )

                alts: list[dict[str, Any]] = []
                count = max(len(view_alts), len(logic_alts))
                for index in range(count):
                    view_row = view_alts[index] if index < len(view_alts) else {}
                    if not isinstance(view_row, dict):
                        view_row = {}
                    name_key = view_row.get("name")
                    desc_key = view_row.get("description")
                    alts.append(
                        {
                            "name": resolve_label(txt, name_key) or f"Alt attack {index}",
                            "description": txt(desc_key),
                            "info": view_row.get("infoDescription") or "",
                            "icon": view_row.get("icon") or "",
                        }
                    )

                default_notes: list[str] = []
                defaults = logic.get("defaultAttacks") or []
                if defaults and isinstance(defaults[0], dict):
                    dealer = defaults[0].get("damageDealer") or {}
                    if isinstance(dealer, dict):
                        tags = dealer.get("tags") or []
                        extra_tags = [
                            tag
                            for tag in tags
                            if tag
                            not in (
                                "melee_attack",
                                "shoot_attack",
                                "normal_damage",
                                "basic_attack",
                            )
                        ]
                        if extra_tags:
                            default_notes.append("tags=" + ",".join(str(tag) for tag in tags))
                        for key in ("shootRange", "shootThreshold", "shootRedCount", "shootDmgBuff"):
                            if key in dealer:
                                default_notes.append(f"{key}={dealer[key]}")
                        buff = dealer.get("buff")
                        if isinstance(buff, dict) and buff.get("sid"):
                            default_notes.append(f"on-hit buff `{buff['sid']}`")
                        target_mechanics = dealer.get("targetMechanics") or []
                        if target_mechanics:
                            default_notes.append(f"targetMechanics={target_mechanics}")

                unit_records.append(
                    {
                        "sid": sid,
                        "name": unit_display_name(sid),
                        "factionSid": faction,
                        "factionLabel": FACTION_LABELS.get(
                            faction, faction.replace("homm3_", "").title()
                        ),
                        "tier": tier_i,
                        "hireCost": fmt_cost(logic.get("unitCost") or {}),
                        "hireCostParts": parse_cost_parts(logic.get("unitCost") or {}),
                        "branch": logic.get("xHomm3BranchRole")
                        or view.get("xHomm3BranchRole")
                        or "",
                        "sourceMechanic": logic.get("xHomm3SourceMechanic")
                        or view.get("xHomm3SourceMechanic")
                        or "",
                        "portrait": f"/portraits/{sid}.png",
                        "actives": actives,
                        "passives": passives,
                        "altAttacks": alts,
                        "defaultAttackNotes": default_notes,
                        "hasActives": bool(actives),
                        "hasIdentityPassives": any(not p.get("generic") for p in passives),
                        "activeCount": len(actives),
                        "passiveCount": len(passives),
                    }
                )

            faction_summaries.append(
                {
                    "sid": faction,
                    "label": FACTION_LABELS.get(faction, faction.replace("homm3_", "").title()),
                    "unitCount": len(rows),
                    "withActives": with_actives,
                    "withPassives": with_passives,
                }
            )
            stats["factions"] += 1
            stats["units"] += len(rows)

    catalog = {
        "schemaVersion": 1,
        "generated": date.today().isoformat(),
        "source": "Golden Era Core.zip installed payload readback",
        "proofTier": [
            "installed payload readback for names, descriptions, Focus costs, cooldowns, hire costs"
        ],
        "notProven": ["runtime behavior for every listed mechanic"],
        "factions": faction_summaries,
        "units": unit_records,
        "stats": {
            "units": stats["units"],
            "factions": stats["factions"],
            "withActives": sum(1 for unit in unit_records if unit["hasActives"]),
            "withPassives": sum(1 for unit in unit_records if unit["passiveCount"] > 0),
            "missingDesc": stats["missing_desc"],
        },
    }
    return catalog, stats


def render_markdown(catalog: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# HoMM3 Custom Unit Ability Catalog")
    lines.append("")
    lines.append(
        "Status: generated from the active Golden Era `Core.zip` unit logic/view rows "
        "and English `unitsAbility.json` / `units.json` localization."
    )
    lines.append("")
    lines.append(
        "Proof tier: **installed payload readback** for names, descriptions, Focus costs, "
        "cooldowns, and hire costs present in Core. This is not a claim that every listed "
        "mechanic is runtime-behavior proven."
    )
    lines.append("")
    lines.append(f"Generated: {catalog.get('generated')}.")
    lines.append("")
    lines.append("Browse UI:")
    lines.append("")
    lines.append("```powershell")
    lines.append("$env:PYTHONUTF8 = '1'")
    lines.append("python tools/unit_ability_catalog/server.py")
    lines.append("```")
    lines.append("")
    lines.append("Regenerate markdown + JSON with:")
    lines.append("")
    lines.append("```powershell")
    lines.append("$env:PYTHONUTF8 = '1'")
    lines.append("python tools/generate_homm3_custom_unit_ability_catalog.py")
    lines.append("```")
    lines.append("")
    lines.append("## How to read this catalog")
    lines.append("")
    lines.append(
        "- **Active**: action-bar ability from the unit `abilities` bucket. Cost is Focus "
        "(`energyLevel`) unless marked no-energy. Cooldown is `cd` in rounds."
    )
    lines.append(
        "- **Passive**: card-visible row from the unit `passives` bucket. Passives have no Focus cost."
    )
    lines.append(
        "- **Alt attack**: alternate attack mode (usually melee for shooters). These are "
        "no-energy attack modes, not Focus actives."
    )
    lines.append(
        "- **Hire cost**: town recruitment `unitCost` from logic, not the ability Focus cost."
    )
    lines.append(
        "- **Intended (override)**: when `custom_factions/ability_overrides` has an enabled "
        "special whose editor text differs from live Core localization, that intended wording "
        "is shown under the live Core text."
    )
    lines.append(
        "- When a live localization key is missing, the catalog falls back to ability-override "
        "editor text, then a humanized key label."
    )
    lines.append(
        "- Common generic cards such as Melee Attack / Ranged Attack are listed briefly; "
        "unique identity abilities are listed in full."
    )
    lines.append("")
    lines.append("Related docs (not replacements for this catalog):")
    lines.append("")
    lines.append("- Per-faction HotA source specs: `docs/homm3_faction_plans/`")
    lines.append("- Mechanics debt / exact-behavior audit: `docs/homm3_custom_unit_mechanics_trace.md`")
    lines.append("- Ability override editor notes: `docs/ability_editor_agent_notes.md`")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Faction | Units | With actives | With passives |")
    lines.append("| --- | ---: | ---: | ---: |")
    for faction in catalog.get("factions") or []:
        lines.append(
            f"| `{faction['sid']}` | {faction['unitCount']} | "
            f"{faction['withActives']} | {faction['withPassives']} |"
        )
    stats = catalog.get("stats") or {}
    lines.append(
        f"| **Total** | **{stats.get('units', 0)}** | "
        f"**{stats.get('withActives', 0)}** | **{stats.get('withPassives', 0)}** |"
    )
    lines.append("")

    units_by_faction: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in catalog.get("units") or []:
        units_by_faction[str(unit["factionSid"])].append(unit)

    for faction in catalog.get("factions") or []:
        faction_sid = faction["sid"]
        lines.append(f"## {faction_sid}")
        lines.append("")
        for unit in units_by_faction.get(faction_sid, []):
            lines.append(f"### {unit['name']} (`{unit['sid']}`)")
            lines.append("")
            meta = [f"Tier {unit['tier']}", f"Hire cost: {unit['hireCost']}"]
            if unit.get("branch"):
                meta.append(f"Branch: {unit['branch']}")
            if unit.get("sourceMechanic"):
                meta.append(f"Source mechanic: `{unit['sourceMechanic']}`")
            lines.append("- " + " | ".join(meta))
            lines.append("")

            actives = unit.get("actives") or []
            if actives:
                lines.append("**Actives**")
                lines.append("")
                for active in actives:
                    lines.append(f"- **{active['name']}** — {active.get('costLabel') or ''}")
                    if active.get("description"):
                        lines.append(f"  - Effect: {active['description']}")
                    else:
                        lines.append(
                            "  - Effect: *(no English unitsAbility text; see logic tags below)*"
                        )
                    if active.get("logicLabel"):
                        lines.append(f"  - Logic: {active['logicLabel']}")
                    intended = active.get("intended")
                    if intended:
                        lines.append(
                            f"  - Intended (override): **{intended.get('name') or ''}** — "
                            f"{intended.get('description') or ''}".rstrip(" —")
                        )
                        intended_cost: list[str] = []
                        if intended.get("energy") not in (None, ""):
                            intended_cost.append(f"Focus {intended.get('energy')}")
                        if intended.get("cooldown") not in (None, ""):
                            intended_cost.append(f"CD {intended.get('cooldown')}")
                        if intended_cost:
                            lines.append(f"  - Intended cost: {', '.join(intended_cost)}")
                lines.append("")
            else:
                lines.append("**Actives:** none")
                lines.append("")

            passives = unit.get("passives") or []
            if passives:
                lines.append("**Passives**")
                lines.append("")
                for passive in passives:
                    if passive.get("generic") and not passive.get("logicLabel"):
                        lines.append(
                            f"- **{passive['name']}** — "
                            f"{passive.get('description') or '(generic attack/mobility card)'}"
                        )
                    else:
                        lines.append(f"- **{passive['name']}** — Cost: none (passive)")
                        if passive.get("description"):
                            lines.append(f"  - Effect: {passive['description']}")
                        else:
                            lines.append("  - Effect: *(no English unitsAbility text)*")
                        if passive.get("logicLabel"):
                            lines.append(f"  - Logic: {passive['logicLabel']}")
                lines.append("")
            else:
                lines.append("**Passives:** none beyond basic attack presentation (if any)")
                lines.append("")

            alts = unit.get("altAttacks") or []
            if alts:
                lines.append("**Alternate attacks**")
                lines.append("")
                for alt in alts:
                    cost = "Focus: none"
                    if alt.get("info"):
                        cost += f" (`{alt['info']}`)"
                    lines.append(f"- **{alt['name']}** — {cost}")
                    if alt.get("description"):
                        lines.append(f"  - Effect: {alt['description']}")
                lines.append("")

            notes = unit.get("defaultAttackNotes") or []
            if notes:
                lines.append("**Default attack notes:** " + "; ".join(notes))
                lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root",
    )
    parser.add_argument(
        "--core-zip",
        type=Path,
        default=DEFAULT_CORE,
        help="Path to active Golden Era Core.zip",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output markdown path",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Output JSON path for the web UI",
    )
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    output = (args.output or (repo / "docs" / "homm3_custom_unit_ability_catalog.md")).resolve()
    json_output = (
        args.json_output
        or (repo / "tools" / "unit_ability_catalog" / "static" / "catalog.json")
    ).resolve()
    if not args.core_zip.is_file():
        raise SystemExit(f"Core.zip not found: {args.core_zip}")

    catalog, stats = collect_catalog(repo, args.core_zip)
    text = render_markdown(catalog)
    output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    json_output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Wrote {json_output}")
    print(
        f"units={stats['units']} factions={stats['factions']} "
        f"missing_desc={stats['missing_desc']} md_bytes={output.stat().st_size} "
        f"json_bytes={json_output.stat().st_size}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
