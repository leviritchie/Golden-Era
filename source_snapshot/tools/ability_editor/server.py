from __future__ import annotations

import ast
import json
import mimetypes
import re
import zipfile
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
APP_DIR = Path(__file__).resolve().parent
OVERRIDE_DIR = ROOT / "custom_factions" / "ability_overrides"
HERO_OVERRIDE_DIR = ROOT / "custom_factions" / "hero_overrides"
LAW_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"
TEMPLATES_PATH = APP_DIR / "ability_templates.json"
IMAGE_ROOTS = (
    ROOT / "tools" / "reference" / "assetripper_olden_demo_unity" / "ExportedProject" / "Assets" / "Resources" / "icons",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_runtime_assets",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_portraits",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_law_icons",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "BepInEx" / "plugins" / "OfflineUnlockMod" / "homm3_portraits",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "BepInEx" / "plugins" / "OfflineUnlockMod" / "homm3_law_icons",
    ROOT / "faction_icons",
    ROOT / "oldenera_factions",
)
CORE_ZIP_CANDIDATES = (
    Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era")
    / "HeroesOldenEra_Data"
    / "StreamingAssets"
    / "Core.zip",
    ROOT
    / "Heroes of Might and Magic Olden Era - Golden Era"
    / "HeroesOldenEra_Data"
    / "StreamingAssets"
    / "Core.zip",
    ROOT / "Heroes of Might and Magic Olden Era - Golden Era" / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip",
)
LANG_CANDIDATES = (
    Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era")
    / "HeroesOldenEra_Data"
    / "StreamingAssets"
    / "Lang"
    / "english"
    / "texts"
    / "unitsAbility.json",
    Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era")
    / "HeroesOldenEra_Data"
    / "StreamingAssets"
    / "Lang"
    / "english"
    / "texts"
    / "factionLaws.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "heroes.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "heroInfo.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "heroSkills.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "factionLaws.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "unitsAbility.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "magic.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "magic_buff.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "unitsBuff.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOldenEra_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "unitsAbility.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOldenEra_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "heroes.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOldenEra_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "heroInfo.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOldenEra_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "heroSkills.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOldenEra_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "factionLaws.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOldenEra_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "magic.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOldenEra_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "magic_buff.json",
    ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOldenEra_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "unitsBuff.json",
)
CORE_LANG_MEMBERS = (
    "Lang/english/texts/heroes.json",
    "Lang/english/texts/heroInfo.json",
    "Lang/english/texts/heroSkills.json",
    "Lang/english/texts/factionLaws.json",
    "Lang/english/texts/units.json",
    "Lang/english/texts/unitsAbility.json",
    "Lang/english/texts/magic.json",
    "Lang/english/texts/magic_buff.json",
    "Lang/english/texts/unitsBuff.json",
)
RELEASE_OVERLAY_SCRIPT = ROOT / "tools" / "release_port" / "apply_release_core_overlay.py"


def read_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def safe_sid(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value or ""):
        raise ValueError(f"Invalid SID: {value!r}")
    return value


def manifest_units(manifest: dict) -> list[dict]:
    variants = manifest.get("unitVariants") or ["", "_upg", "_upg_alt"]
    units: list[dict] = []
    for line in manifest.get("unitLines") or []:
        if not isinstance(line, dict):
            continue
        base_sid = line.get("baseSid")
        if not isinstance(base_sid, str):
            continue
        names = line.get("names") or []
        variant_sids = line.get("variantSids") if isinstance(line.get("variantSids"), dict) else {}
        for index, suffix in enumerate(variants):
            sid = variant_sids.get(suffix) if isinstance(variant_sids.get(suffix), str) and variant_sids.get(suffix) else base_sid + suffix
            name = names[index] if index < len(names) and isinstance(names[index], str) else sid
            units.append(
                {
                    "sid": sid,
                    "name": name,
                    "tier": line.get("tier"),
                    "variant": suffix or "base",
                    "donorBaseSid": line.get("donorBaseSid"),
                    "donorFactionSid": line.get("donorFactionSid") or manifest.get("identity", {}).get("donorFactionSid"),
                }
            )
    return units


def manifest_heroes(manifest: dict) -> list[dict]:
    heroes = manifest.get("heroes") or {}
    names = heroes.get("names") or []
    count = int(heroes.get("count") or len(names) or 18)
    hero_prefix = heroes.get("heroPrefix") or f"{manifest.get('identity', {}).get('factionSid', 'hero')}_hero_"
    icon_prefix = heroes.get("iconPrefix") or f"hero_{manifest.get('identity', {}).get('factionSid', 'hero')}_"
    result = []
    for index in range(1, count + 1):
        sid = f"{hero_prefix}{index}"
        class_type = "might" if index <= 8 else "magic"
        result.append(
            {
                "sid": sid,
                "index": index,
                "name": names[index - 1] if index <= len(names) and isinstance(names[index - 1], str) else sid,
                "classType": class_type,
                "className": heroes.get("mightClassName") if class_type == "might" else heroes.get("magicClassName"),
                "icon": f"{icon_prefix}{index}",
            }
        )
    return result


def generated_overlay_root(faction_sid: str) -> Path | None:
    candidate = ROOT / "experiments" / faction_sid / "generated_core_overlay"
    if candidate.exists():
        return candidate
    return None


@lru_cache(maxsize=1)
def find_core_zip() -> Path | None:
    for path in CORE_ZIP_CANDIDATES:
        if path.exists():
            return path
    matches = sorted(ROOT.glob("**/HeroesOldenEra_Data/StreamingAssets/Core.zip"))
    return matches[0] if matches else None


def read_core_json(member: str):
    core_zip = find_core_zip()
    if not core_zip:
        return None
    try:
        with zipfile.ZipFile(core_zip) as archive:
            with archive.open(member) as handle:
                return json.loads(handle.read().decode("utf-8-sig"))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile):
        return None


@lru_cache(maxsize=1)
def lang_tokens() -> dict[str, str]:
    tokens: dict[str, str] = {}
    for path in LANG_CANDIDATES:
        if not path.exists():
            continue
        try:
            merge_lang_doc(tokens, read_json(path))
        except Exception:
            continue
    for member in CORE_LANG_MEMBERS:
        try:
            merge_lang_doc(tokens, read_core_json(member))
        except Exception:
            continue
    merge_release_overlay_lang_rows(tokens)
    for path in sorted((ROOT / "experiments").glob("*/generated_core_overlay/Lang/english/texts/unitsAbility.json")):
        try:
            merge_lang_doc(tokens, read_json(path))
        except Exception:
            continue
    for lang_name in ("heroes.json", "heroInfo.json", "heroSkills.json", "factionLaws.json"):
        for path in sorted((ROOT / "experiments").glob(f"*/generated_core_overlay/Lang/english/texts/{lang_name}")):
            try:
                merge_lang_doc(tokens, read_json(path))
            except Exception:
                continue
    return tokens


def merge_lang_doc(tokens: dict[str, str], doc) -> None:
    if isinstance(doc, dict) and isinstance(doc.get("tokens"), list):
        for row in doc["tokens"]:
            if isinstance(row, dict) and isinstance(row.get("sid"), str):
                tokens[row["sid"]] = str(row.get("text") or "")
        return
    if isinstance(doc, dict):
        for key, value in doc.items():
            if isinstance(value, str):
                tokens[key] = value


def merge_release_overlay_lang_rows(tokens: dict[str, str]) -> None:
    if not RELEASE_OVERLAY_SCRIPT.exists():
        return
    try:
        tree = ast.parse(RELEASE_OVERLAY_SCRIPT.read_text(encoding="utf-8"))
    except Exception:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.List):
            continue
        rows = []
        for item in node.elts:
            if not isinstance(item, ast.Dict):
                rows = []
                break
            keys = [key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else None for key in item.keys]
            if "sid" not in keys or "text" not in keys:
                rows = []
                break
            try:
                row = ast.literal_eval(item)
            except Exception:
                rows = []
                break
            rows.append(row)
        if rows:
            merge_lang_doc(tokens, {"tokens": rows})


def localize(value, tokens: dict[str, str]) -> str:
    if isinstance(value, str):
        return tokens.get(value, value)
    return ""


def resolved_description_key(name_key, desc_key, tokens: dict[str, str]) -> str:
    if isinstance(desc_key, str) and desc_key:
        if not desc_key.startswith("h3_") or desc_key in tokens:
            return desc_key
    if not isinstance(name_key, str) or not name_key.startswith("h3_"):
        return desc_key if isinstance(desc_key, str) else ""
    candidates = []
    if name_key.endswith("_name"):
        candidates.append(name_key[:-5] + "_description")
    candidates.append(name_key.replace("_ability_name", "_ability_description"))
    candidates.append(name_key.replace("_passive_name", "_passive_description"))
    for candidate in candidates:
        if candidate in tokens:
            return candidate
    return desc_key if isinstance(desc_key, str) else (candidates[0] if candidates else "")


def first_array_item(path: Path):
    if not path.exists():
        return None
    try:
        doc = read_json(path)
    except Exception:
        return None
    rows = doc.get("array") if isinstance(doc, dict) else None
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def first_array_item_doc(doc):
    if not isinstance(doc, dict):
        return None
    rows = doc.get("array") if isinstance(doc, dict) else None
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def read_unit_item(faction_sid: str, unit_sid: str, kind: str) -> tuple[dict | None, str | None]:
    root = generated_overlay_root(faction_sid)
    subdir = "units_logics" if kind == "logic" else "units_views"
    suffix = "_l.json" if kind == "logic" else "_v.json"
    member = f"DB/units/{subdir}/{faction_sid}/{unit_sid}{suffix}"
    if root:
        item = first_array_item(root / member)
        if isinstance(item, dict):
            return item, f"generated:{root.relative_to(ROOT).as_posix()}/{member}"
    item = first_array_item_doc(read_core_json(member))
    if isinstance(item, dict):
        return item, f"core:{member}"
    return None, None


def current_unit_data(faction_sid: str, unit_sid: str) -> dict:
    logic, logic_source = read_unit_item(faction_sid, unit_sid, "logic")
    view, view_source = read_unit_item(faction_sid, unit_sid, "view")
    tokens = lang_tokens()
    return {
        "sources": {"logic": logic_source, "view": view_source},
        "summary": current_specials(logic, view, tokens),
        "logic": {
            "abilities": logic.get("abilities", []) if isinstance(logic, dict) else [],
            "passives": logic.get("passives", []) if isinstance(logic, dict) else [],
            "defaultAttacks": logic.get("defaultAttacks", []) if isinstance(logic, dict) else [],
            "alternativeAttacks": logic.get("alternativeAttacks", []) if isinstance(logic, dict) else [],
            "counterAttacks": logic.get("counterAttacks", []) if isinstance(logic, dict) else [],
            "xHomm3ReleaseQuality": logic.get("xHomm3ReleaseQuality") if isinstance(logic, dict) else None,
            "xHomm3ImplementedMechanics": logic.get("xHomm3ImplementedMechanics") if isinstance(logic, dict) else None,
        },
        "view": {
            "abilities": view.get("abilities", []) if isinstance(view, dict) else [],
            "passives": view.get("passives", []) if isinstance(view, dict) else [],
            "defaultAttacks": view.get("defaultAttacks", []) if isinstance(view, dict) else [],
            "alternativeAttacks": view.get("alternativeAttacks", []) if isinstance(view, dict) else [],
            "counterAttacks": view.get("counterAttacks", []) if isinstance(view, dict) else [],
        },
    }


def manifest_for_faction(faction_sid: str) -> dict | None:
    path = ROOT / "custom_factions" / f"{safe_sid(faction_sid)}.json"
    if path.exists():
        return read_json(path)
    return None


def read_hero_item(faction_sid: str, hero_sid: str) -> tuple[dict | None, str | None]:
    member = f"DB/heroes/{faction_sid}/{hero_sid}.json"
    root = generated_overlay_root(faction_sid)
    if root:
        item = first_array_item(root / member)
        if isinstance(item, dict):
            return item, f"generated:{root.relative_to(ROOT).as_posix()}/{member}"
    item = first_array_item_doc(read_core_json(member))
    if isinstance(item, dict):
        return item, f"core:{member}"
    return None, None


def read_specialization_rows(faction_sid: str) -> tuple[list[dict], str | None]:
    manifest = manifest_for_faction(faction_sid)
    member = ((manifest or {}).get("coreOverlay") or {}).get("heroSpecializations")
    if not isinstance(member, str):
        member = f"DB/heroes_specializations/specializations_{faction_sid}.json"
    root = generated_overlay_root(faction_sid)
    if root and (root / member).exists():
        try:
            doc = read_json(root / member)
            rows = doc.get("array") if isinstance(doc, dict) else None
            return [row for row in rows or [] if isinstance(row, dict)], f"generated:{root.relative_to(ROOT).as_posix()}/{member}"
        except Exception:
            pass
    doc = read_core_json(member)
    rows = doc.get("array") if isinstance(doc, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)], f"core:{member}" if rows is not None else None


def read_law_rows(faction_sid: str) -> tuple[list[dict], str | None, str | None]:
    manifest = manifest_for_faction(faction_sid)
    member = ((manifest or {}).get("coreOverlay") or {}).get("lawsTable")
    if not isinstance(member, str):
        member = f"DB/fractions_laws/fractions_laws_table_{faction_sid}.json"
    root = generated_overlay_root(faction_sid)
    generated_error = None
    if root and (root / member).exists():
        try:
            doc = read_json(root / member)
            rows = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(rows, list):
                raise ValueError("law table JSON has no array list")
            return [row for row in rows if isinstance(row, dict)], f"generated:{root.relative_to(ROOT).as_posix()}/{member}", None
        except Exception as exc:
            generated_error = f"failed to read generated law table {root.relative_to(ROOT).as_posix()}/{member}: {exc}"
    doc = read_core_json(member)
    rows = doc.get("array") if isinstance(doc, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)], f"core:{member}" if rows is not None else None, generated_error


def iter_fraction_rows(faction_sid: str):
    manifest = manifest_for_faction(faction_sid)
    member = ((manifest or {}).get("coreOverlay") or {}).get("factionJson")
    if not isinstance(member, str):
        member = f"DB/fractions/{faction_sid}.json"
    root = generated_overlay_root(faction_sid)
    if root and (root / member).exists():
        try:
            row = first_array_item(root / member)
            if not isinstance(row, dict):
                raise ValueError("faction JSON has no array item")
            yield row, f"generated:{root.relative_to(ROOT).as_posix()}/{member}", None
        except Exception as exc:
            yield None, None, f"failed to read generated faction JSON {root.relative_to(ROOT).as_posix()}/{member}: {exc}"
    row = first_array_item_doc(read_core_json(member))
    if isinstance(row, dict):
        yield row, f"core:{member}", None


def build_law_tree_index(faction_row: dict | None) -> dict[str, dict]:
    lines = faction_row.get("fractionLawsLines") if isinstance(faction_row, dict) else None
    if not isinstance(lines, list):
        return {}
    index: dict[str, dict] = {}
    for line_index, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            continue
        groups = line.get("groups") if isinstance(line.get("groups"), list) else []
        count_to_unlock = line.get("countToUnlock")
        for group_index, group in enumerate(groups, start=1):
            laws = group.get("laws") if isinstance(group, dict) and isinstance(group.get("laws"), list) else []
            for slot_index, law_id in enumerate(laws, start=1):
                if not isinstance(law_id, str) or law_id in index:
                    continue
                index[law_id] = {
                    "unlockPoints": count_to_unlock,
                    "lineIndex": line_index,
                    "groupIndex": group_index,
                    "slotIndex": slot_index,
                }
    return index


def law_tree_index(faction_sid: str, law_ids: set[str] | None = None) -> tuple[dict[str, dict], str | None, str | None]:
    best_tree: dict[str, dict] = {}
    best_source = None
    warnings = []
    best_score = -1
    for faction_row, source, warning in iter_fraction_rows(faction_sid):
        if warning:
            warnings.append(warning)
        tree = build_law_tree_index(faction_row)
        score = len(set(tree).intersection(law_ids or set(tree)))
        if score > best_score:
            best_tree = tree
            best_source = source
            best_score = score
    if law_ids and best_tree and best_score <= 0:
        warnings.append(f"faction law tree {best_source or 'unknown source'} has no matching current law ids")
    return best_tree, best_source, " / ".join(warnings) if warnings else None


def describe_law_bonus(bonus: dict) -> str:
    if not isinstance(bonus, dict):
        return "Malformed bonus row."
    bonus_type = str(bonus.get("type") or "")
    params = bonus.get("parameters") if isinstance(bonus.get("parameters"), list) else []
    receivers = bonus.get("receivers") if isinstance(bonus.get("receivers"), list) else []
    allegiance = bonus.get("receiverAllegiance")
    biome = bonus.get("biomeType")
    prefix = "Enemy " if allegiance == "enemy" else ("Native-terrain " if biome == "native" else "")
    if bonus_type == "sideRes" and len(params) >= 2:
        return f"Daily {params[0]} income changes by {params[1]}."
    if bonus_type == "sideOneTimeAddRes" and len(params) >= 2:
        return f"One-time grant: {params[1]} {params[0]}."
    if bonus_type == "sideObjectViewRadius" and params:
        return f"Object view radius changes by {params[0]}."
    if bonus_type == "sideStat" and params:
        return "Side stat change: " + ", ".join(str(item) for item in params) + "."
    if bonus_type in {"heroStat", "heroStatBattle"} and len(params) >= 2:
        scope = "battle hero stat" if bonus_type == "heroStatBattle" else "hero stat"
        return f"{scope} {params[0]} changes by {params[-1]}."
    if bonus_type == "cityUnitsIncrement" and len(params) >= 2:
        return f"Weekly growth for {params[0]} changes by {params[1]}."
    if bonus_type == "constructionDiscount":
        return "Construction discount: " + ", ".join(str(item) for item in params) + "."
    if bonus_type == "constructionDailyLimit" and params:
        return f"Additional daily construction limit: {params[0]}."
    if bonus_type == "unitHiringDiscount":
        return "Creature hiring discount: " + ", ".join(str(item) for item in params) + "."
    if bonus_type == "astrologyExp" and params:
        return f"Daily Astrology points: {params[0]}."
    if bonus_type == "battleSubskillBonus":
        return "Adds battle subskill bonus: " + ", ".join(str(item) for item in params) + "."
    if bonus_type == "unitStat" and params:
        target = f"{len(receivers)} listed unit(s)" if receivers else "all matching units"
        if params[0] == "modifierSet" and len(params) >= 4:
            return f"{prefix}{target} {params[1]} modifier {params[2]} changes by {params[3]}."
        return f"{prefix}{target} stat {params[0]} changes by {params[-1]}."
    return bonus_type + (": " + ", ".join(str(item) for item in params) if params else "")


def current_law_data(faction_sid: str) -> dict:
    rows, source, warning = read_law_rows(faction_sid)
    law_ids = {str(row.get("id")) for row in rows if isinstance(row.get("id"), str)}
    tree, faction_source, faction_warning = law_tree_index(faction_sid, law_ids)
    tokens = lang_tokens()
    laws = []
    for index, row in enumerate(rows, start=1):
        levels = row.get("parametersPerLevel") if isinstance(row.get("parametersPerLevel"), list) else []
        summarized_levels = []
        for level_index, level in enumerate(levels, start=1):
            bonuses = level.get("bonuses") if isinstance(level, dict) and isinstance(level.get("bonuses"), list) else []
            summarized_levels.append(
                {
                    "index": level_index,
                    "cost": level.get("cost") if isinstance(level, dict) else None,
                    "bonuses": bonuses,
                    "bonusDescriptions": [describe_law_bonus(bonus) for bonus in bonuses],
                }
            )
        laws.append(
            {
                "id": str(row.get("id") or f"{faction_sid}_law_{index}"),
                "index": index,
                "name": localize(row.get("name"), tokens) or str(row.get("name") or ""),
                "description": localize(row.get("desc"), tokens) or str(row.get("desc") or ""),
                "icon": str(row.get("icon") or ""),
                "nameToken": str(row.get("name") or ""),
                "descriptionToken": str(row.get("desc") or ""),
                "parametersPerLevel": levels,
                "levels": summarized_levels,
                "tree": tree.get(str(row.get("id") or f"{faction_sid}_law_{index}"), {}),
                "raw": row,
            }
        )
    warnings = [item for item in (warning, faction_warning) if item]
    return {"sources": {"laws": source, "faction": faction_source}, "warnings": warnings, "laws": laws}


def current_hero_data(faction_sid: str, hero_sid: str) -> dict:
    hero, hero_source = read_hero_item(faction_sid, hero_sid)
    specs, spec_source = read_specialization_rows(faction_sid)
    tokens = lang_tokens()
    spec_id = hero.get("specialization") if isinstance(hero, dict) else None
    spec = next((row for row in specs if row.get("id") == spec_id), None)
    return {
        "sources": {"hero": hero_source, "specializations": spec_source},
        "summary": {
            "sid": hero_sid,
            "name": localize(hero.get("name"), tokens) if isinstance(hero, dict) else hero_sid,
            "description": localize(hero.get("description"), tokens) if isinstance(hero, dict) else "",
            "icon": hero.get("icon") if isinstance(hero, dict) else "",
            "classType": hero.get("classType") if isinstance(hero, dict) else "",
            "className": hero.get("className") if isinstance(hero, dict) else "",
            "specialization": spec_id or "",
            "specializationName": localize(spec.get("name"), tokens) if isinstance(spec, dict) else "",
            "specializationDescription": localize(spec.get("desc"), tokens) if isinstance(spec, dict) else "",
            "specializationIcon": spec.get("icon") if isinstance(spec, dict) else "",
            "startSquad": hero.get("startSquad", []) if isinstance(hero, dict) else [],
            "startSquadAlt": hero.get("startSquadAlt", []) if isinstance(hero, dict) else [],
            "startSkills": hero.get("startSkills", []) if isinstance(hero, dict) else [],
        },
        "hero": hero or {},
        "specialization": spec or {},
    }


UNIT_SPECIAL_SLOT_KINDS = ("abilities", "passives", "alternativeAttacks")


def current_specials(logic: dict | None, view: dict | None, tokens: dict[str, str]) -> list[dict]:
    specials = []
    for slot_kind in UNIT_SPECIAL_SLOT_KINDS:
        logic_rows = logic.get(slot_kind, []) if isinstance(logic, dict) and isinstance(logic.get(slot_kind), list) else []
        view_rows = view.get(slot_kind, []) if isinstance(view, dict) and isinstance(view.get(slot_kind), list) else []
        for index, view_row in enumerate(view_rows):
            if not isinstance(view_row, dict):
                continue
            name_key = view_row.get("name")
            desc_key = resolved_description_key(name_key, view_row.get("description"), tokens)
            logic_row = logic_rows[index] if index < len(logic_rows) and isinstance(logic_rows[index], dict) else None
            mechanics = []
            if isinstance(logic_row, dict):
                for node in walk_json(logic_row):
                    mech = node.get("mech") if isinstance(node, dict) else None
                    if isinstance(mech, str) and mech not in mechanics:
                        mechanics.append(mech)
            specials.append(
                {
                    "key": f"{slot_kind}:{index}",
                    "slotKind": slot_kind,
                    "index": index,
                    "nameKey": name_key if isinstance(name_key, str) else "",
                    "descriptionKey": desc_key if isinstance(desc_key, str) else "",
                    "nameText": localize(name_key, tokens),
                    "descriptionText": localize(desc_key, tokens) if desc_key else "",
                    "abilityType": localize(view_row.get("abilityType"), tokens),
                    "view": view_row,
                    "logic": logic_row,
                    "mechanics": mechanics,
                }
            )
    return specials


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def add_effect(effects: dict[str, dict], *, kind: str, key: str, label: str, source: str, payload=None, tags=None):
    if not key:
        return
    effect_id = f"{kind}:{key}"
    entry = effects.setdefault(
        effect_id,
        {
            "id": effect_id,
            "kind": kind,
            "key": key,
            "label": label or key,
            "sources": [],
            "tags": sorted(set(tags or [])),
            "payload": payload,
        },
    )
    if source not in entry["sources"]:
        entry["sources"].append(source)
    if tags:
        entry["tags"] = sorted(set(entry.get("tags") or []) | set(tags))
    if payload is not None and entry.get("payload") is None:
        entry["payload"] = payload


def collect_effects_from_item(effects: dict[str, dict], item: dict, source: str, tokens: dict[str, str]) -> None:
    for node in walk_json(item):
        mech = node.get("mech")
        values = node.get("values")
        if isinstance(mech, str):
            add_effect(effects, kind="mechanic", key=mech, label=mech, source=source, payload=node, tags=["logic"])
            if isinstance(values, list) and values and isinstance(values[0], str):
                add_effect(effects, kind="mechanic-value", key=f"{mech}:{values[0]}", label=f"{mech} / {values[0]}", source=source, payload=node, tags=["logic"])
        buff_sid = node.get("buffSid")
        buff_node = node.get("buff")
        if not isinstance(buff_sid, str) and isinstance(buff_node, str):
            buff_sid = buff_node
        if not isinstance(buff_sid, str) and isinstance(buff_node, dict):
            sid = buff_node.get("sid")
            if isinstance(sid, str):
                buff_sid = sid
        if isinstance(buff_sid, str):
            add_effect(effects, kind="buff", key=buff_sid, label=buff_sid, source=source, payload=node, tags=["buff"])
        projectile = node.get("projectile")
        if isinstance(projectile, str) and projectile:
            add_effect(effects, kind="projectile", key=projectile, label=projectile, source=source, payload=node, tags=["projectile"])
        icon = node.get("icon")
        if isinstance(icon, str) and icon:
            add_effect(effects, kind="icon", key=icon, label=localize(icon, tokens), source=source, payload=node, tags=["icon"])
        ability_type = node.get("abilityType")
        if isinstance(ability_type, str) and ability_type:
            add_effect(effects, kind="ability-type", key=ability_type, label=localize(ability_type, tokens), source=source, payload=node, tags=["view"])
        name_key = node.get("name")
        desc_key = node.get("description")
        if isinstance(name_key, str) or isinstance(desc_key, str):
            key = name_key or desc_key
            add_effect(
                effects,
                kind="localized-ability",
                key=key,
                label=localize(name_key, tokens) or key,
                source=source,
                payload=node,
                tags=["localized", localize(desc_key, tokens)],
            )


def unit_special_label(view_row: dict, slot_kind: str, tokens: dict[str, str]) -> str:
    name = localize(view_row.get("name"), tokens)
    ability_type = localize(view_row.get("abilityType"), tokens)
    if ability_type and name and ability_type != view_row.get("abilityType"):
        return f"{ability_type}: {name}"
    if name:
        return name
    return slot_kind


def collect_unit_special_effects(
    effects: dict[str, dict],
    logic: dict,
    view: dict,
    source: str,
    tokens: dict[str, str],
) -> None:
    source_unit_sid = str(view.get("id") or logic.get("id") or "")
    for slot_kind in UNIT_SPECIAL_SLOT_KINDS:
        logic_rows = logic.get(slot_kind, []) if isinstance(logic.get(slot_kind), list) else []
        view_rows = view.get(slot_kind, []) if isinstance(view.get(slot_kind), list) else []
        for index, view_row in enumerate(view_rows):
            if not isinstance(view_row, dict):
                continue
            logic_row = logic_rows[index] if index < len(logic_rows) and isinstance(logic_rows[index], dict) else None
            key = f"{source_unit_sid}:{slot_kind}:{index}"
            desc_key = resolved_description_key(view_row.get("name"), view_row.get("description"), tokens)
            tags = [
                "unit-special",
                slot_kind,
                localize(desc_key, tokens) if desc_key else "",
            ]
            payload = {
                "sourceUnitSid": source_unit_sid,
                "slotKind": slot_kind,
                "index": index,
                "nameKey": view_row.get("name") if isinstance(view_row.get("name"), str) else "",
                "descriptionKey": desc_key if isinstance(desc_key, str) else "",
                "logic": logic_row,
                "view": view_row,
            }
            add_effect(
                effects,
                kind="unit-special",
                key=key,
                label=unit_special_label(view_row, slot_kind, tokens),
                source=source,
                payload=payload,
                tags=[tag for tag in tags if tag],
            )


def collect_spell_effects_from_doc(effects: dict[str, dict], doc: dict, source: str, tokens: dict[str, str]) -> None:
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        spell_sid = row.get("id")
        battle_magic = row.get("battleMagic")
        dealers = battle_magic.get("magicDealers") if isinstance(battle_magic, dict) else None
        if not isinstance(spell_sid, str) or not isinstance(dealers, list):
            continue
        dealer_indexes = battle_magic.get("dealersPerLevels")
        if not isinstance(dealer_indexes, list) or not dealer_indexes:
            dealer_indexes = list(range(len(dealers)))
        name = localize(row.get("name"), tokens) or spell_sid
        descriptions = row.get("description")
        spell_rank = row.get("rank")
        school = row.get("school_")
        for level, dealer_index in enumerate(dealer_indexes, start=1):
            if not isinstance(dealer_index, int) or dealer_index < 0 or dealer_index >= len(dealers):
                continue
            dealer = dealers[dealer_index]
            if not isinstance(dealer, dict):
                continue
            buff = dealer.get("buff")
            buff_sid = buff.get("sid") if isinstance(buff, dict) else ""
            duration = buff.get("duration") if isinstance(buff, dict) else None
            desc_key = ""
            if isinstance(descriptions, list) and descriptions:
                desc_candidate = descriptions[min(level - 1, len(descriptions) - 1)]
                if isinstance(desc_candidate, str):
                    desc_key = desc_candidate
            elif isinstance(row.get("description"), str):
                desc_key = row["description"]
            tags = [
                "spell-effect",
                str(school or ""),
                f"tier {spell_rank}" if spell_rank else "",
                f"level {level}",
                localize(desc_key, tokens) if desc_key else "",
                f"buff {buff_sid}" if buff_sid else "",
            ]
            payload = {
                "spellSid": spell_sid,
                "spellTier": spell_rank,
                "spellLevel": level,
                "dealerIndex": dealer_index,
                "buffSid": buff_sid,
                "duration": duration,
                "nameKey": row.get("name") if isinstance(row.get("name"), str) else "",
                "descriptionKey": desc_key,
                "icon": row.get("icon") if isinstance(row.get("icon"), str) else "",
                "school": school if isinstance(school, str) else "",
                "dealer": dealer,
            }
            add_effect(
                effects,
                kind="spell-effect",
                key=f"{spell_sid}:level:{level}",
                label=f"{name} L{level}",
                source=source,
                payload=payload,
                tags=[tag for tag in tags if tag],
            )


def collect_buffs_from_doc(effects: dict[str, dict], doc: dict, source: str, tokens: dict[str, str]) -> None:
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        buff_sid = row.get("id")
        if not isinstance(buff_sid, str):
            continue
        name = localize(row.get("name_"), tokens) or buff_sid
        description = localize(row.get("description_"), tokens)
        tags = ["buff", description, *(str(tag) for tag in row.get("tags", []) if isinstance(tag, str))]
        add_effect(effects, kind="buff", key=buff_sid, label=name, source=source, payload=row, tags=[tag for tag in tags if tag])


HERO_STAT_KEYS = ("offence", "defence", "spellPower", "intelligence", "luck", "moral", "viewRadius")


def hero_skill_catalog() -> dict:
    tokens = lang_tokens()
    skills = []
    for member in ("DB/heroes_skills/skills/skills.json", "DB/heroes_skills/skills/skills_arena.json"):
        doc = read_core_json(member)
        for row in (doc.get("array") if isinstance(doc, dict) else []) or []:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                continue
            skills.append(
                {
                    "sid": row["id"],
                    "label": localize(row.get("name"), tokens) or row["id"],
                    "description": localize(row.get("desc"), tokens),
                    "icon": row.get("icon") or "",
                    "source": f"core:{member}",
                }
            )
    return {"skills": sorted(skills, key=lambda item: (item["label"], item["sid"]))}


def hero_specialization_catalog() -> dict:
    tokens = lang_tokens()
    specs = []
    seen = set()
    core_zip = find_core_zip()
    if core_zip:
        try:
            with zipfile.ZipFile(core_zip) as archive:
                members = [name for name in archive.namelist() if name.startswith("DB/heroes_specializations/") and name.endswith(".json")]
                for member in members:
                    doc = json.loads(archive.read(member).decode("utf-8-sig"))
                    for row in (doc.get("array") if isinstance(doc, dict) else []) or []:
                        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in seen:
                            continue
                        seen.add(row["id"])
                        specs.append(
                            {
                                "sid": row["id"],
                                "label": localize(row.get("name"), tokens) or row["id"],
                                "description": localize(row.get("desc"), tokens),
                                "icon": row.get("icon") or "",
                                "bonuses": row.get("bonuses") if isinstance(row.get("bonuses"), list) else [],
                                "source": f"core:{member}",
                            }
                        )
        except Exception:
            pass
    templates = []
    for stat in HERO_STAT_KEYS:
        templates.append(
            {
                "id": f"heroStat:{stat}",
                "label": f"{stat} per level",
                "summary": f"Adds {stat} through a native heroStat specialization bonus.",
                "bonus": {"type": "heroStat", "parameters": [stat, "0"], "upgrade": {"increment": 1, "levelStep": 5}},
            }
        )
    return {"specializations": sorted(specs, key=lambda item: (item["label"], item["sid"])), "bonusTemplates": templates}


def iter_core_unit_members(prefix: str):
    core_zip = find_core_zip()
    if not core_zip:
        return
    try:
        with zipfile.ZipFile(core_zip) as archive:
            for name in archive.namelist():
                if name.startswith(prefix) and name.endswith(".json"):
                    try:
                        yield name, json.loads(archive.read(name).decode("utf-8-sig"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
    except zipfile.BadZipFile:
        return


def effect_catalog() -> dict:
    effects: dict[str, dict] = {}
    tokens = lang_tokens()
    core_docs: dict[str, dict] = {}
    for prefix in ("DB/units/units_logics/", "DB/units/units_views/"):
        for member, doc in iter_core_unit_members(prefix) or []:
            if "/homm3_" in member:
                continue
            core_docs[member] = doc
            item = first_array_item_doc(doc)
            if isinstance(item, dict):
                collect_effects_from_item(effects, item, f"core:{member}", tokens)
    for logic_member, logic_doc in core_docs.items():
        if not logic_member.startswith("DB/units/units_logics/") or not logic_member.endswith("_l.json"):
            continue
        view_member = logic_member.replace("DB/units/units_logics/", "DB/units/units_views/", 1).removesuffix("_l.json") + "_v.json"
        logic_item = first_array_item_doc(logic_doc)
        view_item = first_array_item_doc(core_docs.get(view_member))
        if isinstance(logic_item, dict) and isinstance(view_item, dict):
            collect_unit_special_effects(effects, logic_item, view_item, f"core:{logic_member} | core:{view_member}", tokens)
    for root in sorted((ROOT / "experiments").glob("*/generated_core_overlay")):
        logic_paths = list((root / "DB" / "units" / "units_logics").glob("*/*.json"))
        view_paths = list((root / "DB" / "units" / "units_views").glob("*/*.json"))
        for path in logic_paths + view_paths:
            item = first_array_item(path)
            if isinstance(item, dict):
                collect_effects_from_item(effects, item, f"generated:{path.relative_to(ROOT).as_posix()}", tokens)
        for logic_path in logic_paths:
            if not logic_path.name.endswith("_l.json"):
                continue
            view_path = root / logic_path.relative_to(root).as_posix().replace("DB/units/units_logics/", "DB/units/units_views/", 1).removesuffix("_l.json")
            view_path = Path(str(view_path) + "_v.json")
            logic_item = first_array_item(logic_path)
            view_item = first_array_item(view_path)
            if isinstance(logic_item, dict) and isinstance(view_item, dict):
                source = f"generated:{logic_path.relative_to(ROOT).as_posix()} | generated:{view_path.relative_to(ROOT).as_posix()}"
                collect_unit_special_effects(effects, logic_item, view_item, source, tokens)
    for prefix, collector in (("DB/magics/", collect_spell_effects_from_doc), ("DB/buffs/", collect_buffs_from_doc)):
        for member, doc in iter_core_unit_members(prefix) or []:
            collector(effects, doc, f"core:{member}", tokens)
    return {
        "coreZip": str(find_core_zip()) if find_core_zip() else None,
        "effects": sorted(effects.values(), key=lambda item: (item["kind"], item["key"])),
    }


def relative_repo_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_runtime_icon_key(key: str) -> bool:
    key = key.strip()
    if not key:
        return False
    if "@" in key or "/" in key or "\\" in key:
        return False
    lowered = key.lower()
    if lowered.endswith("_name") or lowered.endswith("_description"):
        return False
    return re.fullmatch(r"[A-Za-z0-9_.-]+", key) is not None


def icon_catalog() -> dict:
    icons = []
    seen: set[str] = set()
    seen_keys: set[str] = set()
    warnings: list[str] = []
    priority_groups = {
        "current_law_icons": -2,
        "fraction_laws": -1,
        "homm3_law_icons": -1,
        "homm3_portraits": -1,
        "hero_magics": 0,
        "buffs": 1,
        "abilities": 2,
        "artifacts": 3,
        "skills": 4,
    }
    for root in IMAGE_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.png")):
            try:
                rel = relative_repo_path(path)
            except ValueError:
                continue
            lower = rel.lower()
            score = 0
            for token in ("icon", "ability", "skill", "buff", "spell", "magic", "effect", "portrait", "faction", "building"):
                if token in lower:
                    score += 1
            if root.name == "homm3_portraits":
                score += 3
            if score == 0 and "00_00.png" not in lower:
                continue
            if rel in seen:
                continue
            seen.add(rel)
            key = path.stem
            parent = path.parent.name
            if parent and re.fullmatch(r"[A-Za-z0-9_.-]+", parent):
                key = parent if key == "00_00" else key
            relative_group = path.parent.relative_to(root).as_posix() if path.parent != root else root.name
            runtime_safe = is_runtime_icon_key(key)
            icons.append(
                {
                    "key": key,
                    "label": path.stem,
                    "path": rel,
                    "url": "/asset/" + quote(rel),
                    "group": relative_group,
                    "score": score,
                    "runtimeSafe": runtime_safe,
                }
            )
            if runtime_safe:
                seen_keys.add(key)
    for manifest in load_manifests():
        faction_sid = manifest["factionSid"]
        try:
            law_data = current_law_data(faction_sid)
        except Exception as exc:
            warnings.append(f"failed to index current law icons for {faction_sid}: {exc}")
            continue
        for law in law_data.get("laws", []):
            key = str(law.get("icon") or "").strip()
            if not is_runtime_icon_key(key) or key in seen_keys:
                continue
            icons.append(
                {
                    "key": key,
                    "label": key,
                    "path": "",
                    "url": "",
                    "group": "current_law_icons",
                    "score": 3,
                    "runtimeSafe": True,
                }
            )
            seen_keys.add(key)
    icons.sort(
        key=lambda item: (
            priority_groups.get(item["group"], 50),
            not item["runtimeSafe"],
            -item["score"],
            item["path"],
        )
    )
    return {"icons": icons[:20000], "roots": [str(path) for path in IMAGE_ROOTS if path.exists()], "warnings": warnings}


def load_manifests() -> list[dict]:
    manifests: list[dict] = []
    for path in sorted((ROOT / "custom_factions").glob("homm3_*.json")):
        manifest = read_json(path)
        identity = manifest.get("identity") or {}
        faction_sid = identity.get("factionSid")
        if not faction_sid:
            continue
        manifests.append(
            {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "factionSid": faction_sid,
                "displayName": manifest.get("runtime", {}).get("displayName") or faction_sid,
                "citySid": identity.get("citySid"),
                "nativeBiome": identity.get("nativeBiome"),
                "units": manifest_units(manifest),
                "heroes": manifest_heroes(manifest),
            }
        )
    return manifests


def override_path(faction_sid: str) -> Path:
    return OVERRIDE_DIR / f"{safe_sid(faction_sid)}.json"


def load_overrides(faction_sid: str) -> dict:
    path = override_path(faction_sid)
    if path.exists():
        return read_json(path)
    return {"schemaVersion": 1, "factionSid": faction_sid, "unitOverrides": {}}


def hero_override_path(faction_sid: str) -> Path:
    return HERO_OVERRIDE_DIR / f"{safe_sid(faction_sid)}.json"


def load_hero_overrides(faction_sid: str) -> dict:
    path = hero_override_path(faction_sid)
    if path.exists():
        return read_json(path)
    return {"schemaVersion": 1, "factionSid": faction_sid, "heroOverrides": {}}


def law_override_path(faction_sid: str) -> Path:
    return LAW_OVERRIDE_DIR / f"{safe_sid(faction_sid)}.json"


def load_law_overrides(faction_sid: str) -> dict:
    path = law_override_path(faction_sid)
    if path.exists():
        return read_json(path)
    return {"schemaVersion": 1, "factionSid": faction_sid, "lawOverrides": {}}


def validate_override_payload(payload: dict) -> dict:
    faction_sid = safe_sid(str(payload.get("factionSid") or ""))
    overrides = payload.get("unitOverrides")
    if not isinstance(overrides, dict):
        raise ValueError("unitOverrides must be an object")
    normalized = {"schemaVersion": 1, "factionSid": faction_sid, "unitOverrides": {}}
    for unit_sid, entry in overrides.items():
        unit_sid = safe_sid(str(unit_sid))
        if not isinstance(entry, dict):
            raise ValueError(f"{unit_sid}: override must be an object")
        abilities = entry.get("abilities", [])
        if not isinstance(abilities, list):
            raise ValueError(f"{unit_sid}: abilities must be a list")
        clean_abilities = []
        for index, ability in enumerate(abilities):
            if not isinstance(ability, dict):
                raise ValueError(f"{unit_sid}: ability {index} must be an object")
            template_id = str(ability.get("templateId") or "").strip()
            if not template_id:
                raise ValueError(f"{unit_sid}: ability {index} missing templateId")
            fields = ability.get("fields") or {}
            if not isinstance(fields, dict):
                raise ValueError(f"{unit_sid}: ability {index} fields must be an object")
            buff_sid = fields.get("buffSid")
            if isinstance(buff_sid, str) and (buff_sid.endswith("_name") or buff_sid.endswith("_description")):
                raise ValueError(f"{unit_sid}: ability {index} buffSid must be a buff/mechanic SID, not localization token {buff_sid}")
            turn_behavior = fields.get("turnBehavior")
            if turn_behavior not in (None, "", "ends", "free"):
                raise ValueError(f"{unit_sid}: ability {index} turnBehavior must be Ends turn or Does not end turn")
            clean_abilities.append(
                {
                    "id": str(ability.get("id") or f"{unit_sid}_{index + 1}"),
                    "templateId": template_id,
                    "enabled": bool(ability.get("enabled", True)),
                    "fields": fields,
                    "notes": str(ability.get("notes") or ""),
                }
            )
        normalized["unitOverrides"][unit_sid] = {
            "abilities": clean_abilities,
            "existingSpecials": clean_existing_specials(unit_sid, entry.get("existingSpecials", [])),
            "replaceExistingAbilities": bool(entry.get("replaceExistingAbilities", False)),
            "replaceExistingPassives": bool(entry.get("replaceExistingPassives", False)),
        }
    return normalized


ALLOWED_LAW_BONUS_TYPES = {
    "astrologyExp",
    "battleSubskillBonus",
    "cityUnitsIncrement",
    "constructionDailyLimit",
    "constructionDiscount",
    "heroStat",
    "heroStatBattle",
    "sideOneTimeAddRes",
    "sideObjectViewRadius",
    "sideRes",
    "sideStat",
    "unitHiringDiscount",
    "unitStat",
}


def clean_law_levels(law_key: str, levels) -> list[dict]:
    if levels in (None, ""):
        return []
    if not isinstance(levels, list):
        raise ValueError(f"{law_key}: parametersPerLevel must be a list")
    clean_levels = []
    for level_index, level in enumerate(levels):
        if not isinstance(level, dict):
            raise ValueError(f"{law_key}: level {level_index + 1} must be an object")
        clean_level = dict(level)
        clean_level["cost"] = int(level.get("cost") or 0)
        bonuses = level.get("bonuses")
        if not isinstance(bonuses, list):
            raise ValueError(f"{law_key}: level {level_index + 1} bonuses must be a list")
        clean_bonuses = []
        for bonus_index, bonus in enumerate(bonuses):
            if not isinstance(bonus, dict):
                raise ValueError(f"{law_key}: level {level_index + 1} bonus {bonus_index + 1} must be an object")
            bonus_type = str(bonus.get("type") or "").strip()
            if bonus_type not in ALLOWED_LAW_BONUS_TYPES:
                raise ValueError(f"{law_key}: level {level_index + 1} bonus {bonus_index + 1} has unsupported type {bonus_type!r}")
            clean_bonus = dict(bonus)
            clean_bonus["type"] = bonus_type
            if "parameters" in clean_bonus and not isinstance(clean_bonus["parameters"], list):
                raise ValueError(f"{law_key}: level {level_index + 1} bonus {bonus_index + 1} parameters must be a list")
            if "receivers" in clean_bonus and not isinstance(clean_bonus["receivers"], list):
                raise ValueError(f"{law_key}: level {level_index + 1} bonus {bonus_index + 1} receivers must be a list")
            clean_bonuses.append(clean_bonus)
        clean_level["bonuses"] = clean_bonuses
        clean_levels.append(clean_level)
    return clean_levels


def validate_law_override_payload(payload: dict) -> dict:
    faction_sid = safe_sid(str(payload.get("factionSid") or ""))
    overrides = payload.get("lawOverrides")
    if not isinstance(overrides, dict):
        raise ValueError("lawOverrides must be an object")
    normalized = {"schemaVersion": 1, "factionSid": faction_sid, "lawOverrides": {}}
    for law_key, entry in overrides.items():
        law_key = safe_sid(str(law_key))
        if not isinstance(entry, dict):
            raise ValueError(f"{law_key}: override must be an object")
        clean_entry = dict(entry)
        clean_entry.update(
            {
                "enabled": bool(entry.get("enabled", True)),
                "nameText": str(entry.get("nameText") or ""),
                "descriptionText": str(entry.get("descriptionText") or ""),
                "iconKey": str(entry.get("iconKey") or ""),
                "notes": str(entry.get("notes") or ""),
            }
        )
        if "parametersPerLevel" in entry:
            clean_entry["parametersPerLevel"] = clean_law_levels(law_key, entry.get("parametersPerLevel"))
        normalized["lawOverrides"][law_key] = clean_entry
    return normalized


def clean_existing_specials(unit_sid: str, specials) -> list[dict]:
    if specials in (None, ""):
        return []
    if not isinstance(specials, list):
        raise ValueError(f"{unit_sid}: existingSpecials must be a list")
    clean = []
    for index, special in enumerate(specials):
        if not isinstance(special, dict):
            raise ValueError(f"{unit_sid}: existingSpecials {index} must be an object")
        slot_kind = str(special.get("slotKind") or "")
        if slot_kind not in UNIT_SPECIAL_SLOT_KINDS:
            raise ValueError(
                f"{unit_sid}: existingSpecials {index} slotKind must be one of {', '.join(UNIT_SPECIAL_SLOT_KINDS)}"
            )
        turn_behavior = str(special.get("turnBehavior") or "").strip()
        if turn_behavior not in {"", "ends", "free"}:
            raise ValueError(f"{unit_sid}: existingSpecials {index} turnBehavior must be Ends turn or Does not end turn")
        clean.append(
            {
                "key": f"{slot_kind}:{int(special.get('index') or 0)}",
                "slotKind": slot_kind,
                "index": int(special.get("index") or 0),
                "enabled": bool(special.get("enabled", True)),
                "nameKey": str(special.get("nameKey") or ""),
                "descriptionKey": str(special.get("descriptionKey") or ""),
                "nameText": str(special.get("nameText") or ""),
                "descriptionText": str(special.get("descriptionText") or ""),
                "iconKey": str(special.get("iconKey") or ""),
                "abilityType": str(special.get("abilityType") or ""),
                "animationIndex": int(special.get("animationIndex") or 0),
                "turnBehavior": turn_behavior,
                "energyLevel": int(special.get("energyLevel") or 0),
                "cooldown": int(special.get("cooldown") or 0),
                "rank": int(special.get("rank") or 1),
                "charges": int(special["charges"]) if str(special.get("charges") or "").strip() else "",
                "effectKey": str(special.get("effectKey") or ""),
                "effectKind": str(special.get("effectKind") or ""),
                "effectLabel": str(special.get("effectLabel") or ""),
                "effectPayload": special.get("effectPayload") if isinstance(special.get("effectPayload"), dict) else {},
                "notes": str(special.get("notes") or ""),
            }
        )
    return clean


def clean_squad_rows(hero_sid: str, rows, field: str) -> list[dict]:
    if rows in (None, ""):
        return []
    if not isinstance(rows, list):
        raise ValueError(f"{hero_sid}: {field} must be a list")
    clean = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{hero_sid}: {field} {index} must be an object")
        sid = safe_sid(str(row.get("sid") or ""))
        clean.append({"sid": sid, "min": int(row.get("min") or 1), "max": int(row.get("max") or row.get("min") or 1)})
    return clean


def clean_skill_rows(hero_sid: str, rows) -> list[dict]:
    if rows in (None, ""):
        return []
    if not isinstance(rows, list):
        raise ValueError(f"{hero_sid}: startSkills must be a list")
    clean = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{hero_sid}: startSkills {index} must be an object")
        sid = safe_sid(str(row.get("sid") or ""))
        if sid.startswith("skill_faction_"):
            raise ValueError(
                f"{hero_sid}: startSkills must omit faction skill {sid!r}; Core overlay prepends it"
            )
        level = int(row.get("skillLevel") or 1)
        if level != 1:
            raise ValueError(
                f"{hero_sid}: startSkills {index} must be Basic (skillLevel 1); "
                f"Advanced/Expert reads as a third starting skill, got skillLevel={level}"
            )
        clean.append({"sid": sid, "skillLevel": 1})
    if len(clean) > 1:
        raise ValueError(
            f"{hero_sid}: startSkills must contain at most one HoMM3 secondary; Core prepends the faction skill"
        )
    return clean


def validate_hero_override_payload(payload: dict) -> dict:
    faction_sid = safe_sid(str(payload.get("factionSid") or ""))
    overrides = payload.get("heroOverrides")
    if not isinstance(overrides, dict):
        raise ValueError("heroOverrides must be an object")
    normalized = {"schemaVersion": 1, "factionSid": faction_sid, "heroOverrides": {}}
    for hero_sid, entry in overrides.items():
        hero_sid = safe_sid(str(hero_sid))
        if not isinstance(entry, dict):
            raise ValueError(f"{hero_sid}: override must be an object")
        spec = entry.get("specialization") if isinstance(entry.get("specialization"), dict) else {}
        bonuses = spec.get("bonuses") if isinstance(spec.get("bonuses"), list) else []
        clean_bonuses = []
        for index, bonus in enumerate(bonuses):
            if not isinstance(bonus, dict):
                raise ValueError(f"{hero_sid}: specialization bonus {index} must be an object")
            bonus_type = str(bonus.get("type") or "")
            if bonus_type != "heroStat":
                raise ValueError(f"{hero_sid}: specialization bonus {index} only supports heroStat in this editor")
            stat = str(bonus.get("stat") or "")
            if stat not in HERO_STAT_KEYS:
                raise ValueError(f"{hero_sid}: specialization bonus {index} has unsupported stat {stat}")
            clean_bonuses.append(
                {
                    "type": "heroStat",
                    "stat": stat,
                    "base": int(bonus.get("base") or 0),
                    "increment": int(bonus.get("increment") or 1),
                    "levelStep": int(bonus.get("levelStep") or 5),
                }
            )
        normalized["heroOverrides"][hero_sid] = {
            "enabled": bool(entry.get("enabled", True)),
            "nameText": str(entry.get("nameText") or ""),
            "descriptionText": str(entry.get("descriptionText") or ""),
            "mottoText": str(entry.get("mottoText") or ""),
            "iconKey": str(entry.get("iconKey") or ""),
            "classType": str(entry.get("classType") or ""),
            "className": str(entry.get("className") or ""),
            "startSquad": clean_squad_rows(hero_sid, entry.get("startSquad"), "startSquad"),
            "startSquadAlt": clean_squad_rows(hero_sid, entry.get("startSquadAlt"), "startSquadAlt"),
            "startSkills": clean_skill_rows(hero_sid, entry.get("startSkills")),
            "specialization": {
                "mode": str(spec.get("mode") or "custom"),
                "sourceSpecId": str(spec.get("sourceSpecId") or ""),
                "nameText": str(spec.get("nameText") or ""),
                "descriptionText": str(spec.get("descriptionText") or ""),
                "iconKey": str(spec.get("iconKey") or ""),
                "bonuses": clean_bonuses,
            },
            "notes": str(entry.get("notes") or ""),
        }
    return normalized


class Handler(BaseHTTPRequestHandler):
    server_version = "Homm3AbilityEditor/0.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/state":
                self.send_json({"manifests": load_manifests(), "templates": read_json(TEMPLATES_PATH)["templates"]})
                return
            if parsed.path == "/api/overrides":
                faction_sid = safe_sid(parse_qs(parsed.query).get("factionSid", [""])[0])
                self.send_json(load_overrides(faction_sid))
                return
            if parsed.path == "/api/hero_overrides":
                faction_sid = safe_sid(parse_qs(parsed.query).get("factionSid", [""])[0])
                self.send_json(load_hero_overrides(faction_sid))
                return
            if parsed.path == "/api/law_overrides":
                faction_sid = safe_sid(parse_qs(parsed.query).get("factionSid", [""])[0])
                self.send_json(load_law_overrides(faction_sid))
                return
            if parsed.path == "/api/unit":
                query = parse_qs(parsed.query)
                faction_sid = safe_sid(query.get("factionSid", [""])[0])
                unit_sid = safe_sid(query.get("unitSid", [""])[0])
                self.send_json(current_unit_data(faction_sid, unit_sid))
                return
            if parsed.path == "/api/hero":
                query = parse_qs(parsed.query)
                faction_sid = safe_sid(query.get("factionSid", [""])[0])
                hero_sid = safe_sid(query.get("heroSid", [""])[0])
                self.send_json(current_hero_data(faction_sid, hero_sid))
                return
            if parsed.path == "/api/laws":
                faction_sid = safe_sid(parse_qs(parsed.query).get("factionSid", [""])[0])
                self.send_json(current_law_data(faction_sid))
                return
            if parsed.path == "/api/effects":
                self.send_json(effect_catalog())
                return
            if parsed.path == "/api/hero_skills":
                self.send_json(hero_skill_catalog())
                return
            if parsed.path == "/api/hero_specializations":
                self.send_json(hero_specialization_catalog())
                return
            if parsed.path == "/api/icons":
                self.send_json(icon_catalog())
                return
            if parsed.path.startswith("/asset/"):
                self.send_asset(unquote(parsed.path.removeprefix("/asset/")))
                return
            self.send_static(parsed.path)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path not in {"/api/overrides", "/api/hero_overrides", "/api/law_overrides"}:
                self.send_json({"error": "Unknown endpoint"}, status=404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if parsed.path == "/api/hero_overrides":
                normalized = validate_hero_override_payload(payload)
                path = hero_override_path(normalized["factionSid"])
            elif parsed.path == "/api/law_overrides":
                normalized = validate_law_override_payload(payload)
                path = law_override_path(normalized["factionSid"])
            else:
                normalized = validate_override_payload(payload)
                path = override_path(normalized["factionSid"])
            write_json(path, normalized)
            self.send_json({"ok": True, "path": str(path.relative_to(ROOT)).replace("\\", "/")})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def send_static(self, request_path: str):
        if request_path in {"", "/"}:
            request_path = "/index.html"
        relative = request_path.lstrip("/")
        path = (APP_DIR / "static" / relative).resolve()
        static_root = (APP_DIR / "static").resolve()
        if static_root not in path.parents and path != static_root:
            self.send_error(403)
            return
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_asset(self, relative_path: str):
        path = (ROOT / relative_path).resolve()
        allowed = False
        for root in IMAGE_ROOTS:
            resolved_root = root.resolve()
            if path == resolved_root or resolved_root in path.parents:
                allowed = True
                break
        if not allowed or not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value, status: int = 200):
        body = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the HoMM3 custom unit ability editor.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Ability editor running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
