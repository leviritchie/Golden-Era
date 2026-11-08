"""Mirror custom English localization rows into every supported release locale.

This is intentionally release-overlay tooling rather than a one-off Core.zip
patch. It preserves existing localized rows, reuses the game's own translation
memory for exact English text matches, and drafts translations for missing or
still-English custom HoMM3 rows.
"""

from __future__ import annotations

import re
import sys
import zipfile
import json
from pathlib import Path
from typing import Any, Callable

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from homm3_campaign_hub_sid_order import (  # noqa: E402
    PLAY_ORDER_HUB_SIDS as HOMM3_CAMPAIGN_PLAY_ORDER,
)

# Profiles list sorts alphabetically by hub SID; play-order SIDs are zero-padded.
HOMM3_CAMPAIGN_HUB_SIDS: frozenset[str] = frozenset(HOMM3_CAMPAIGN_PLAY_ORDER)

TEXT_FILES = (
    "artifacts.json",
    "campaign.json",
    "cinematic.json",
    "cities.json",
    "customMaps.json",
    "dialogues.json",
    "factionLaws.json",
    "fractions.json",
    "heroInfo.json",
    "heroes.json",
    "heroSkills.json",
    "magic.json",
    "magic_buff.json",
    "mapObjects.json",
    "menu.json",
    "tutorial.json",
    "ui.json",
    "units.json",
    "unitsAbility.json",
    "unitsBuff.json",
    "unsorted.json",
)

CUSTOM_SID_RE = re.compile(r"(?i)(homm3|^h3_|Homm3)")
CUSTOM_UNIT_VIEW_RE = re.compile(r"^DB/units/units_views/(?:homm3_[^/]+|neutral)/h3_[^/]+_v\.json$")
UNIT_ABILITY_CARD_SLOTS = ("abilities", "passives", "alternativeAttacks", "defaultAttacks", "counterAttacks")
# Campaign PlayVideo softsubs: StreamingAssets/video/*.mp4.json SIDs resolve via
# LocKit cinematic.json tokens. Scrubbing these produces LOC:homm3_*_video_N.
CAMPAIGN_VIDEO_SOFTSUB_SID_RE = re.compile(
    r"(?i)^homm3_(?:roe|absod)_.+_video_\d+$"
)
CANONICAL_CUSTOM_TEXT_FILES = {
    "campaign.json",
    "cities.json",
    "factionLaws.json",
    "fractions.json",
    "heroInfo.json",
    "heroes.json",
    "heroSkills.json",
    "magic_buff.json",
    "mapObjects.json",
    "units.json",
    "unitsAbility.json",
    "unitsBuff.json",
}
PLACEHOLDER_RE = re.compile(r"\{\d+\}")
SUBSTANTIVE_ENGLISH_RE = re.compile(
    r"[.!?:;]|"
    r"\b(?:attack|damage|recruit|spell|hero|enemy|friendly|city|town|"
    r"creature|unit|basic|advanced|expert|command|specialist|upg\.)\b",
    re.IGNORECASE,
)
PHRASEBOOK_DIR = Path(__file__).with_name("localization_phrasebooks")
_PHRASEBOOK_EXACT: dict[str, dict[str, str]] | None = None
_PHRASEBOOK_TEMPLATES: list[tuple[re.Pattern[str], dict[str, str]]] | None = None


FALLBACK_TERMS: dict[str, dict[str, str]] = {
    "BRportugese": {
        "Attack": "Ataque",
        "Defense": "Defesa",
        "Initiative": "Iniciativa",
        "Luck": "Sorte",
        "Morale": "Moral",
        "Damage": "Dano",
        "Health": "Vida",
        "Speed": "Velocidade",
        "Basic": "Basico",
        "Advanced": "Avancado",
        "Expert": "Especialista",
        "Command": "Comando",
        "army": "exercito",
        "creature": "criatura",
        "creatures": "criaturas",
        "friendly": "aliado",
        "enemy": "inimigo",
        "hero": "heroi",
        "town": "cidade",
        "city": "cidade",
        "building": "edificio",
        "spell": "feitico",
        "magic": "magia",
    },
    "czech": {
        "Attack": "Utok",
        "Defense": "Obrana",
        "Initiative": "Iniciativa",
        "Luck": "Stesti",
        "Morale": "Morale",
        "Damage": "Poskozeni",
        "Health": "Zdravi",
        "Speed": "Rychlost",
        "Basic": "Zakladni",
        "Advanced": "Pokrocila",
        "Expert": "Experti",
        "Command": "Veleni",
        "army": "armada",
        "creature": "tvor",
        "creatures": "tvorove",
        "friendly": "spojenecky",
        "enemy": "nepratelsky",
        "hero": "hrdina",
        "town": "mesto",
        "city": "mesto",
        "building": "budova",
        "spell": "kouzlo",
        "magic": "magie",
    },
    "french": {
        "Attack": "Attaque",
        "Defense": "Defense",
        "Initiative": "Initiative",
        "Luck": "Chance",
        "Morale": "Moral",
        "Damage": "Degats",
        "Health": "Sante",
        "Speed": "Vitesse",
        "Basic": "Base",
        "Advanced": "Avance",
        "Expert": "Expert",
        "Command": "Commandement",
        "army": "armee",
        "creature": "creature",
        "creatures": "creatures",
        "friendly": "allie",
        "enemy": "ennemi",
        "hero": "heros",
        "town": "ville",
        "city": "cite",
        "building": "batiment",
        "spell": "sort",
        "magic": "magie",
    },
    "german": {
        "Attack": "Angriff",
        "Defense": "Verteidigung",
        "Initiative": "Initiative",
        "Luck": "Gluck",
        "Morale": "Moral",
        "Damage": "Schaden",
        "Health": "Gesundheit",
        "Speed": "Geschwindigkeit",
        "Basic": "Einfach",
        "Advanced": "Fortgeschritten",
        "Expert": "Experte",
        "Command": "Befehl",
        "army": "Armee",
        "creature": "Kreatur",
        "creatures": "Kreaturen",
        "friendly": "verbundet",
        "enemy": "feindlich",
        "hero": "Held",
        "town": "Stadt",
        "city": "Stadt",
        "building": "Gebaude",
        "spell": "Zauber",
        "magic": "Magie",
    },
    "hungarian": {
        "Attack": "Tamadas",
        "Defense": "Vedelem",
        "Initiative": "Kezdemenyezes",
        "Luck": "Szerencse",
        "Morale": "Moral",
        "Damage": "Sebzes",
        "Health": "Eletero",
        "Speed": "Sebesseg",
        "Basic": "Alap",
        "Advanced": "Halado",
        "Expert": "Mester",
        "Command": "Parancs",
        "army": "sereg",
        "creature": "leny",
        "creatures": "lenyek",
        "friendly": "barati",
        "enemy": "ellenseges",
        "hero": "hos",
        "town": "varos",
        "city": "varos",
        "building": "epulet",
        "spell": "varazslat",
        "magic": "magia",
    },
    "italian": {
        "Attack": "Attacco",
        "Defense": "Difesa",
        "Initiative": "Iniziativa",
        "Luck": "Fortuna",
        "Morale": "Morale",
        "Damage": "Danni",
        "Health": "Salute",
        "Speed": "Velocita",
        "Basic": "Base",
        "Advanced": "Avanzato",
        "Expert": "Esperto",
        "Command": "Comando",
        "army": "esercito",
        "creature": "creatura",
        "creatures": "creature",
        "friendly": "alleato",
        "enemy": "nemico",
        "hero": "eroe",
        "town": "citta",
        "city": "citta",
        "building": "edificio",
        "spell": "incantesimo",
        "magic": "magia",
    },
    "japanese": {
        "Attack": "攻撃",
        "Defense": "防御",
        "Initiative": "イニシアチブ",
        "Luck": "幸運",
        "Morale": "士気",
        "Damage": "ダメージ",
        "Health": "体力",
        "Speed": "速度",
        "Basic": "基本",
        "Advanced": "上級",
        "Expert": "達人",
        "Command": "指揮",
        "army": "軍勢",
        "creature": "クリーチャー",
        "creatures": "クリーチャー",
        "friendly": "味方",
        "enemy": "敵",
        "hero": "ヒーロー",
        "town": "町",
        "city": "都市",
        "building": "建物",
        "spell": "呪文",
        "magic": "魔法",
    },
    "korean": {
        "Attack": "공격",
        "Defense": "방어",
        "Initiative": "주도권",
        "Luck": "행운",
        "Morale": "사기",
        "Damage": "피해",
        "Health": "체력",
        "Speed": "속도",
        "Basic": "기본",
        "Advanced": "고급",
        "Expert": "전문",
        "Command": "지휘",
        "army": "군대",
        "creature": "생명체",
        "creatures": "생명체",
        "friendly": "아군",
        "enemy": "적",
        "hero": "영웅",
        "town": "마을",
        "city": "도시",
        "building": "건물",
        "spell": "주문",
        "magic": "마법",
    },
    "polish": {
        "Attack": "Atak",
        "Defense": "Obrona",
        "Initiative": "Inicjatywa",
        "Luck": "Szczescie",
        "Morale": "Morale",
        "Damage": "Obrazenia",
        "Health": "Zdrowie",
        "Speed": "Szybkosc",
        "Basic": "Podstawowy",
        "Advanced": "Zaawansowany",
        "Expert": "Ekspert",
        "Command": "Dowodzenie",
        "army": "armia",
        "creature": "stworzenie",
        "creatures": "stworzenia",
        "friendly": "sojuszniczy",
        "enemy": "wrogi",
        "hero": "bohater",
        "town": "miasto",
        "city": "miasto",
        "building": "budynek",
        "spell": "zaklecie",
        "magic": "magia",
    },
    "russian": {
        "Attack": "Атака",
        "Defense": "Защита",
        "Initiative": "Инициатива",
        "Luck": "Удача",
        "Morale": "Боевой дух",
        "Damage": "Урон",
        "Health": "Здоровье",
        "Speed": "Скорость",
        "Basic": "Базовый",
        "Advanced": "Продвинутый",
        "Expert": "Эксперт",
        "Command": "Командование",
        "army": "армия",
        "creature": "существо",
        "creatures": "существа",
        "friendly": "союзный",
        "enemy": "вражеский",
        "hero": "герой",
        "town": "город",
        "city": "город",
        "building": "здание",
        "spell": "заклинание",
        "magic": "магия",
    },
    "spanish": {
        "Attack": "Ataque",
        "Defense": "Defensa",
        "Initiative": "Iniciativa",
        "Luck": "Suerte",
        "Morale": "Moral",
        "Damage": "Dano",
        "Health": "Salud",
        "Speed": "Velocidad",
        "Basic": "Basico",
        "Advanced": "Avanzado",
        "Expert": "Experto",
        "Command": "Mando",
        "army": "ejercito",
        "creature": "criatura",
        "creatures": "criaturas",
        "friendly": "aliado",
        "enemy": "enemigo",
        "hero": "heroe",
        "town": "pueblo",
        "city": "ciudad",
        "building": "edificio",
        "spell": "hechizo",
        "magic": "magia",
    },
    "turkish": {
        "Attack": "Saldiri",
        "Defense": "Savunma",
        "Initiative": "Inisiyatif",
        "Luck": "Sans",
        "Morale": "Moral",
        "Damage": "Hasar",
        "Health": "Saglik",
        "Speed": "Hiz",
        "Basic": "Temel",
        "Advanced": "Gelismis",
        "Expert": "Uzman",
        "Command": "Komuta",
        "army": "ordu",
        "creature": "yaratik",
        "creatures": "yaratiklar",
        "friendly": "dost",
        "enemy": "dusman",
        "hero": "kahraman",
        "town": "kasaba",
        "city": "sehir",
        "building": "bina",
        "spell": "buyu",
        "magic": "sihir",
    },
    "ukrainian": {
        "Attack": "Атака",
        "Defense": "Захист",
        "Initiative": "Ініціатива",
        "Luck": "Удача",
        "Morale": "Бойовий дух",
        "Damage": "Шкода",
        "Health": "Здоров'я",
        "Speed": "Швидкість",
        "Basic": "Базовий",
        "Advanced": "Просунутий",
        "Expert": "Експерт",
        "Command": "Командування",
        "army": "армія",
        "creature": "істота",
        "creatures": "істоти",
        "friendly": "союзний",
        "enemy": "ворожий",
        "hero": "герой",
        "town": "місто",
        "city": "місто",
        "building": "будівля",
        "spell": "закляття",
        "magic": "магія",
    },
    "zhCN": {
        "Attack": "攻击",
        "Defense": "防御",
        "Initiative": "主动性",
        "Luck": "幸运",
        "Morale": "士气",
        "Damage": "伤害",
        "Health": "生命值",
        "Speed": "速度",
        "Basic": "基础",
        "Advanced": "高级",
        "Expert": "专家",
        "Command": "指挥",
        "army": "军队",
        "creature": "生物",
        "creatures": "生物",
        "friendly": "友方",
        "enemy": "敌方",
        "hero": "英雄",
        "town": "城镇",
        "city": "城市",
        "building": "建筑",
        "spell": "法术",
        "magic": "魔法",
    },
    "zhTW": {
        "Attack": "攻擊",
        "Defense": "防禦",
        "Initiative": "主動性",
        "Luck": "幸運",
        "Morale": "士氣",
        "Damage": "傷害",
        "Health": "生命值",
        "Speed": "速度",
        "Basic": "基礎",
        "Advanced": "進階",
        "Expert": "專家",
        "Command": "指揮",
        "army": "軍隊",
        "creature": "生物",
        "creatures": "生物",
        "friendly": "友方",
        "enemy": "敵方",
        "hero": "英雄",
        "town": "城鎮",
        "city": "城市",
        "building": "建築",
        "spell": "法術",
        "magic": "魔法",
    },
}


def _read_overlay_or_zip(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    name: str,
    read_json: Callable[[zipfile.ZipFile, str], Any],
) -> Any:
    if name in output:
        return json.loads(output[name].decode("utf-8-sig"))
    return read_json(release_zip, name)


def _lang_dirs(release_zip: zipfile.ZipFile) -> list[str]:
    langs = {
        entry.filename.split("/")[1]
        for entry in release_zip.infolist()
        if entry.filename.startswith("Lang/") and "/texts/" in entry.filename
    }
    return sorted(lang for lang in langs if lang != "english")


def _tokens_by_sid(doc: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(doc, dict):
        return {}
    rows = doc.get("tokens")
    if not isinstance(rows, list):
        return {}
    return {str(row.get("sid")): row for row in rows if isinstance(row, dict) and row.get("sid")}


def custom_unit_ability_view_sids(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
) -> frozenset[str]:
    """Collect custom text SIDs consumed by pending custom unit view cards."""
    members = {
        name for name in release_zip.namelist() if CUSTOM_UNIT_VIEW_RE.fullmatch(name)
    } | {
        name for name in output if CUSTOM_UNIT_VIEW_RE.fullmatch(name)
    }
    refs: set[str] = set()
    for member in sorted(members):
        try:
            raw = output[member] if member in output else release_zip.read(member)
            doc = json.loads(raw.decode("utf-8-sig"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as ex:
            raise ValueError(f"cannot read custom unit view for localization ownership: {member}: {ex}") from ex
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            rows = [doc] if isinstance(doc, dict) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for slot in UNIT_ABILITY_CARD_SLOTS:
                cards = row.get(slot)
                if not isinstance(cards, list):
                    continue
                for card in cards:
                    if not isinstance(card, dict):
                        continue
                    for field in ("name", "description"):
                        values = card.get(field)
                        if isinstance(values, str):
                            values = (values,)
                        if isinstance(values, (list, tuple)):
                            refs.update(
                                value for value in values
                                if isinstance(value, str) and CUSTOM_SID_RE.search(value)
                            )
    return frozenset(refs)


def canonical_custom_text_files_for_sid(
    sid: str,
    unit_ability_sids: frozenset[str] | set[str] | None = None,
) -> set[str]:
    """Return text files where a custom HoMM3 localization SID is allowed.

    This prevents stale release archives from turning one English custom row
    into fake coverage in every Lang text file during multilingual sync.
    """
    if not CUSTOM_SID_RE.search(sid):
        return set()
    if unit_ability_sids is not None and sid in unit_ability_sids:
        return {"unitsAbility.json"}

    if sid.startswith("fraction_law_homm3_"):
        return {"factionLaws.json"}
    if sid.startswith("barracks_homm3_"):
        return {"mapObjects.json"}
    # Land-on external dwellings are clone SIDs; keep them mapObjects-only so
    # multilingual scrub does not treat them as faction/city identity tokens.
    if sid.startswith("homm3_landon_barracks_"):
        return {"mapObjects.json"}
    if sid.startswith("Homm3") and "_Build_" in sid:
        return {"cities.json"}
    if sid.startswith(("sub_class_homm3_", "sub_skill_faction_homm3_", "might_homm3_", "magic_homm3_")):
        return {"heroSkills.json"}
    if sid.startswith("skill_faction_homm3_"):
        if "_effect" in sid:
            return {"magic_buff.json"}
        return {"heroSkills.json"}

    if sid.startswith("homm3_") and "_hero_" in sid:
        if sid.endswith("_specialization"):
            return {"heroes.json"}
        if sid.endswith("_name") or re.fullmatch(r"homm3_[a-z]+_hero_\d+", sid):
            return {"heroes.json", "heroInfo.json"}
        return {"heroInfo.json"}

    # Adventure-map hero buffs (DB/heroes_buffs) read their name/description from mapObjects;
    # without this the generic "_buff" rule below scrubs e.g. homm3_fortress_trophies_buff_name.
    if sid.startswith(("homm3_fortress_trophies_", "homm3_dungeon_captives_")):
        return {"mapObjects.json"}

    if sid.startswith("homm3_") and ("_warcry_" in sid or "_effect" in sid or "_buff" in sid or "_debuff" in sid):
        return {"magic_buff.json", "unitsBuff.json"}

    # Custom-law combat markers live in magic_buff / unitsBuff (overlay
    # CUSTOM_LAW_VISUAL_MARKER_LANG_PATHS). Without this, multilingual scrub drops them.
    if sid.startswith("homm3_law_marker_"):
        return {"magic_buff.json", "unitsBuff.json"}

    # Battle buff tooltip SIDs (name_/desc) for Factory Split Assembly / Bulwark Runes /
    # Frostbound Skies. Combat UI reads magic_buff + unitsBuff; heroSkills also carries
    # the same rows for skill-panel reuse. Without this, multilingual scrub treats them
    # as fraction tokens and can drop the combat catalogs.
    if sid.startswith("homm3_") and (
        "_split_assembly_" in sid
        or "_rune_level_" in sid
        or "_frostbound_skies_" in sid
    ):
        return {"magic_buff.json", "unitsBuff.json", "heroSkills.json"}

    if sid.startswith("h3_"):
        if any(
            part in sid
            for part in (
                "_ability",
                "_abilities_",
                "_attack",
                "_passive",
                "_active",
                "_stunning_blow",
                "_root_bind",
                "_thunderbolt",
                "_mana_transfer",
                "_death_stare",
            )
        ):
            return {"unitsAbility.json"}
        if any(part in sid for part in ("_buff", "_debuff", "_effect")):
            return {"unitsBuff.json", "magic_buff.json"}
        return {"units.json"}

    # BhCampaign.Init LocKit key is "campaign_" + hubSid. Mission pin titles use
    # "<missionConfigId>_title" / "_description". These must stay in campaign.json
    # tokens; scrubbing them as noncanonical produces player-visible LOC: labels.
    # Hub SIDs use zero-padded play-order names (homm3_01_…–homm3_20_…).
    if sid.startswith("campaign_homm3_") or sid in HOMM3_CAMPAIGN_HUB_SIDS:
        return {"campaign.json"}
    if sid.endswith("_title") and sid[: -len("_title")] in HOMM3_CAMPAIGN_HUB_SIDS:
        return {"campaign.json"}
    if sid.endswith(("_title", "_description")) and sid.startswith(
        ("homm3_roe_", "homm3_ab_", "homm3_sod_")
    ):
        return {"campaign.json"}

    # Softsub SIDs must be classified before the broad homm3_roe_ → customMaps
    # and homm3_ → fractions rules, or multilingual scrub strips cinematic tokens.
    if CAMPAIGN_VIDEO_SOFTSUB_SID_RE.match(sid):
        return {"cinematic.json"}

    # Campaign quest-log SIDs (parent title + checklist bullets). These are not
    # homm3_-prefixed; without this rule multilingual sync leaves them English-only
    # or drops them as noncanonical.
    if re.fullmatch(
        r"[a-z0-9_]+_(?:intro|main_goal|main_goal_desc|main_goal_obj_\d+)",
        sid,
        flags=re.IGNORECASE,
    ):
        return {"customMaps.json"}

    if sid.startswith("homm3_roe_") or sid.startswith("homecoming_"):
        return {"customMaps.json"}

    if sid.startswith("homm3_"):
        # Faction/city identity tokens are intentionally present in more than
        # one player-facing surface depending on the native UI route.
        return {"fractions.json", "cities.json", "mapObjects.json"}

    return set()


def _custom_row_belongs_in_file(
    sid: str,
    file_name: str,
    unit_ability_sids: frozenset[str] | set[str] | None = None,
) -> bool:
    allowed = canonical_custom_text_files_for_sid(sid, unit_ability_sids)
    return bool(allowed) and file_name in allowed


def _remove_noncanonical_custom_rows(
    doc: Any,
    file_name: str,
    unit_ability_sids: frozenset[str] | set[str] | None = None,
) -> int:
    if not isinstance(doc, dict):
        return 0
    tokens = doc.get("tokens")
    if not isinstance(tokens, list):
        return 0
    kept: list[Any] = []
    removed = 0
    for row in tokens:
        sid = str(row.get("sid")) if isinstance(row, dict) and row.get("sid") else ""
        if sid and CUSTOM_SID_RE.search(sid) and not _custom_row_belongs_in_file(sid, file_name, unit_ability_sids):
            removed += 1
            continue
        kept.append(row)
    if removed:
        doc["tokens"] = kept
    return removed


def _translation_memory(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    lang: str,
    read_json: Callable[[zipfile.ZipFile, str], Any],
) -> dict[str, str]:
    memory: dict[str, str] = {}
    for file_name in TEXT_FILES:
        english_name = f"Lang/english/texts/{file_name}"
        localized_name = f"Lang/{lang}/texts/{file_name}"
        try:
            english = _read_overlay_or_zip(release_zip, output, english_name, read_json)
            localized = _read_overlay_or_zip(release_zip, output, localized_name, read_json)
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        localized_by_sid = _tokens_by_sid(localized)
        for sid, english_row in _tokens_by_sid(english).items():
            english_text = english_row.get("text")
            localized_row = localized_by_sid.get(sid)
            localized_text = localized_row.get("text") if localized_row else None
            if (
                isinstance(english_text, str)
                and isinstance(localized_text, str)
                and localized_text
                and localized_text != english_text
            ):
                memory.setdefault(english_text, localized_text)
    return memory


def _same_placeholders(source: str, translated: str) -> bool:
    return sorted(PLACEHOLDER_RE.findall(source)) == sorted(PLACEHOLDER_RE.findall(translated))


def _template_pattern(template: str) -> re.Pattern[str]:
    parts: list[str] = []
    cursor = 0
    seen: set[str] = set()
    for match in re.finditer(r"\{(\d+)\}", template):
        placeholder = match.group(1)
        parts.append(re.escape(template[cursor : match.start()]))
        if placeholder in seen:
            parts.append(f"(?P=p{placeholder})")
        else:
            parts.append(f"(?P<p{placeholder}>.+?)")
            seen.add(placeholder)
        cursor = match.end()
    parts.append(re.escape(template[cursor:]))
    return re.compile("^" + "".join(parts) + "$")


def _render_template(template: str, match: re.Match[str]) -> str:
    result = template
    for name, value in match.groupdict().items():
        if name.startswith("p"):
            result = result.replace("{" + name[1:] + "}", value)
    return result


def _load_phrasebooks() -> tuple[dict[str, dict[str, str]], list[tuple[re.Pattern[str], dict[str, str]]]]:
    global _PHRASEBOOK_EXACT, _PHRASEBOOK_TEMPLATES
    if _PHRASEBOOK_EXACT is not None and _PHRASEBOOK_TEMPLATES is not None:
        return _PHRASEBOOK_EXACT, _PHRASEBOOK_TEMPLATES

    exact: dict[str, dict[str, str]] = {}
    templates: list[tuple[re.Pattern[str], dict[str, str]]] = []
    if PHRASEBOOK_DIR.is_dir():
        for path in sorted(PHRASEBOOK_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            entries = data.get("entries")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                english = entry.get("english")
                translations = entry.get("translations")
                if not isinstance(english, str) or not isinstance(translations, dict):
                    continue
                clean = {
                    str(lang): str(value)
                    for lang, value in translations.items()
                    if isinstance(value, str) and value != english
                }
                if not clean:
                    continue
                match_type = entry.get("matchType")
                if match_type == "template" or (match_type is None and re.search(r"\{\d+\}", english)):
                    templates.append((_template_pattern(english), clean))
                else:
                    exact.setdefault(english, {}).update(clean)

    _PHRASEBOOK_EXACT = exact
    _PHRASEBOOK_TEMPLATES = templates
    return exact, templates


def _phrasebook_translate(lang: str, text: str) -> str | None:
    exact, templates = _load_phrasebooks()
    translation = exact.get(text, {}).get(lang)
    if translation:
        return translation
    for pattern, translations in templates:
        match = pattern.fullmatch(text)
        if not match:
            continue
        template = translations.get(lang)
        if template:
            return _render_template(template, match)
    return None


def _phrasebook_can_translate(lang: str, text: str) -> bool:
    exact, templates = _load_phrasebooks()
    if exact.get(text, {}).get(lang):
        return True
    return any(pattern.fullmatch(text) and translations.get(lang) for pattern, translations in templates)


def _needs_localization(lang: str, text: str) -> bool:
    return _phrasebook_can_translate(lang, text) or len(text) > 32 or bool(SUBSTANTIVE_ENGLISH_RE.search(text))


def _short_label_translate(lang: str, text: str) -> str | None:
    exact = {
        "Town Hall": {
            "BRportugese": "Prefeitura",
            "czech": "Radnice",
            "french": "Hotel de ville",
            "german": "Rathaus",
            "hungarian": "Varoshaza",
            "italian": "Municipio",
            "japanese": "町役場",
            "korean": "마을 회관",
            "polish": "Ratusz",
            "russian": "Ратуша",
            "spanish": "Ayuntamiento",
            "turkish": "Belediye Binasi",
            "ukrainian": "Ратуша",
            "zhCN": "议事厅",
            "zhTW": "議事廳",
        },
        "City Hall": {
            "BRportugese": "Camara Municipal",
            "czech": "Mestska radnice",
            "french": "Hotel de cite",
            "german": "Stadthalle",
            "hungarian": "Nagyvaroshaza",
            "italian": "Municipio cittadino",
            "japanese": "市庁舎",
            "korean": "도시 회관",
            "polish": "Magistrat",
            "russian": "Городская ратуша",
            "spanish": "Concejo",
            "turkish": "Sehir Meclisi",
            "ukrainian": "Міська ратуша",
            "zhCN": "市政厅",
            "zhTW": "市政廳",
        },
        "Ranged Attack": {
            "BRportugese": "Ataque a distancia",
            "czech": "Utok na dalku",
            "french": "Attaque a distance",
            "german": "Fernangriff",
            "hungarian": "Tavolsagi tamadas",
            "italian": "Attacco a distanza",
            "japanese": "遠隔攻撃",
            "korean": "원거리 공격",
            "polish": "Atak dystansowy",
            "russian": "Дальняя атака",
            "spanish": "Ataque a distancia",
            "turkish": "Menzilli saldiri",
            "ukrainian": "Дальня атака",
            "zhCN": "远程攻击",
            "zhTW": "遠程攻擊",
        },
        "Double Attack": {
            "BRportugese": "Ataque duplo",
            "czech": "Dvojity utok",
            "french": "Double attaque",
            "german": "Doppelangriff",
            "hungarian": "Kettos tamadas",
            "italian": "Doppio attacco",
            "japanese": "二回攻撃",
            "korean": "이중 공격",
            "polish": "Podwojny atak",
            "russian": "Двойная атака",
            "spanish": "Ataque doble",
            "turkish": "Cift saldiri",
            "ukrainian": "Подвійна атака",
            "zhCN": "双重攻击",
            "zhTW": "雙重攻擊",
        },
    }
    return exact.get(text, {}).get(lang)


def _term(lang: str, value: str) -> str:
    return FALLBACK_TERMS.get(lang, {}).get(value, value)


def _glossary_replace(lang: str, text: str) -> str:
    terms = FALLBACK_TERMS.get(lang, {})
    result = text
    for source in sorted(terms, key=len, reverse=True):
        result = re.sub(rf"\b{re.escape(source)}\b", terms[source], result)
    return result


def _draft_translate(lang: str, text: str, memory: dict[str, str]) -> str:
    phrasebook = _phrasebook_translate(lang, text)
    if phrasebook:
        return phrasebook

    if text in memory and _same_placeholders(text, memory[text]):
        return memory[text]

    short_label = _short_label_translate(lang, text)
    if short_label:
        return short_label

    tower_label = re.fullmatch(r"Tower (.+)\.", text)
    if tower_label:
        label = _glossary_replace(lang, tower_label.group(1))
        return {
            "BRportugese": f"Edificio da Torre: {label}.",
            "czech": f"Budova Veze: {label}.",
            "french": f"Batiment de la Tour : {label}.",
            "german": f"Turm-Gebaude: {label}.",
            "hungarian": f"Torony-epulet: {label}.",
            "italian": f"Edificio della Torre: {label}.",
            "japanese": f"タワーの施設：{label}。",
            "korean": f"타워 건물: {label}.",
            "polish": f"Budynek Wiezy: {label}.",
            "russian": f"Здание Башни: {label}.",
            "spanish": f"Edificio de Torre: {label}.",
            "turkish": f"Kule binasi: {label}.",
            "ukrainian": f"Споруда Вежі: {label}.",
            "zhCN": f"塔楼建筑：{label}。",
            "zhTW": f"塔樓建築：{label}。",
        }.get(lang, text)

    tower_narrative = re.fullmatch(r"A Tower (.+)\.", text)
    if tower_narrative:
        label = _glossary_replace(lang, tower_narrative.group(1))
        return {
            "BRportugese": f"Um edificio da Torre: {label}.",
            "czech": f"Budova Veze: {label}.",
            "french": f"Un batiment de la Tour : {label}.",
            "german": f"Ein Turm-Gebaude: {label}.",
            "hungarian": f"Egy toronybeli epulet: {label}.",
            "italian": f"Un edificio della Torre: {label}.",
            "japanese": f"タワーの施設：{label}。",
            "korean": f"타워 건물: {label}.",
            "polish": f"Budynek Wiezy: {label}.",
            "russian": f"Здание Башни: {label}.",
            "spanish": f"Un edificio de Torre: {label}.",
            "turkish": f"Bir Kule binasi: {label}.",
            "ukrainian": f"Споруда Вежі: {label}.",
            "zhCN": f"塔楼建筑：{label}。",
            "zhTW": f"塔樓建築：{label}。",
        }.get(lang, text)

    # Preserve short proper names if no in-game translation memory knows them.
    if len(text) <= 32 and not re.search(r"[.!?:;]", text):
        return _glossary_replace(lang, text)

    exact = {
        "Allows resource trading.": {
            "BRportugese": "Permite negociar recursos.",
            "czech": "Umoznuje obchodovani se surovinami.",
            "french": "Permet le commerce des ressources.",
            "german": "Ermoglicht den Handel mit Ressourcen.",
            "hungarian": "Lehetove teszi az eroforrasok kereskedelmet.",
            "italian": "Consente lo scambio di risorse.",
            "japanese": "資源の取引を可能にする。",
            "korean": "자원 거래를 허용합니다.",
            "polish": "Umozliwia handel zasobami.",
            "russian": "Позволяет торговать ресурсами.",
            "spanish": "Permite comerciar recursos.",
            "turkish": "Kaynak ticaretine izin verir.",
            "ukrainian": "Дозволяє торгувати ресурсами.",
            "zhCN": "允许交易资源。",
            "zhTW": "允許交易資源。",
        },
        "Flying movement.": {
            "BRportugese": "Movimento voador.",
            "czech": "Letajici pohyb.",
            "french": "Deplacement volant.",
            "german": "Fliegende Bewegung.",
            "hungarian": "Repulo mozgas.",
            "italian": "Movimento volante.",
            "japanese": "飛行移動。",
            "korean": "비행 이동.",
            "polish": "Ruch latajacy.",
            "russian": "Летающее передвижение.",
            "spanish": "Movimiento volador.",
            "turkish": "Ucan hareket.",
            "ukrainian": "Летючий рух.",
            "zhCN": "飞行移动。",
            "zhTW": "飛行移動。",
        },
        "Strikes twice when performing melee attacks.": {
            "BRportugese": "Golpeia duas vezes ao realizar ataques corpo a corpo.",
            "czech": "Pri boji zblizka utoci dvakrat.",
            "french": "Frappe deux fois lors des attaques de melee.",
            "german": "Schlagt bei Nahkampfangriffen zweimal zu.",
            "hungarian": "Ketszer csap le kozelharci tamadasnal.",
            "italian": "Colpisce due volte negli attacchi in mischia.",
            "japanese": "近接攻撃時に2回攻撃する。",
            "korean": "근접 공격 시 두 번 공격합니다.",
            "polish": "Uderza dwa razy podczas atakow w zwarciu.",
            "russian": "Наносит два удара при атаках в ближнем бою.",
            "spanish": "Golpea dos veces al realizar ataques cuerpo a cuerpo.",
            "turkish": "Yakin dovus saldirilarinda iki kez vurur.",
            "ukrainian": "Завдає два удари під час атак у ближньому бою.",
            "zhCN": "进行近战攻击时攻击两次。",
            "zhTW": "進行近戰攻擊時攻擊兩次。",
        },
        "A heavy ranged attack.": {
            "BRportugese": "Um poderoso ataque a distancia.",
            "czech": "Tezky utok na dalku.",
            "french": "Une puissante attaque a distance.",
            "german": "Ein schwerer Fernangriff.",
            "hungarian": "Eros tavolsagi tamadas.",
            "italian": "Un potente attacco a distanza.",
            "japanese": "強力な遠隔攻撃。",
            "korean": "강력한 원거리 공격입니다.",
            "polish": "Ciezki atak dystansowy.",
            "russian": "Мощная дальняя атака.",
            "spanish": "Un potente ataque a distancia.",
            "turkish": "Agir bir menzilli saldiri.",
            "ukrainian": "Потужна дальня атака.",
            "zhCN": "一次强力的远程攻击。",
            "zhTW": "一次強力的遠程攻擊。",
        },
    }
    if text in exact:
        return exact[text].get(lang, text)

    spell_level = re.fullmatch(r"Allows visiting heroes to learn level (\d+) spells\.", text)
    if spell_level:
        level = spell_level.group(1)
        return {
            "BRportugese": f"Permite que herois visitantes aprendam feiticos de nivel {level}.",
            "czech": f"Umoznuje hostujicim hrdinum naucit se kouzla {level}. urovne.",
            "french": f"Permet aux heros en visite d'apprendre des sorts de niveau {level}.",
            "german": f"Ermoglicht besuchenden Helden, Zauber der Stufe {level} zu lernen.",
            "hungarian": f"Lehetove teszi a latogato hosoknek {level}. szintu varazslatok megtanulasat.",
            "italian": f"Consente agli eroi in visita di imparare incantesimi di livello {level}.",
            "japanese": f"訪問中の英雄がレベル{level}の呪文を習得できる。",
            "korean": f"방문 영웅이 {level}레벨 주문을 배울 수 있습니다.",
            "polish": f"Pozwala odwiedzajacym bohaterom uczyc sie zaklec poziomu {level}.",
            "russian": f"Позволяет посещающим героям изучать заклинания {level}-го уровня.",
            "spanish": f"Permite a los heroes visitantes aprender hechizos de nivel {level}.",
            "turkish": f"Ziyaret eden kahramanlarin {level}. seviye buyuleri ogrenmesini saglar.",
            "ukrainian": f"Дозволяє героям-відвідувачам вивчати закляття {level}-го рівня.",
            "zhCN": f"允许来访英雄学习{level}级法术。",
            "zhTW": f"允許來訪英雄學習{level}級法術。",
        }.get(lang, text)

    buy = re.fullmatch(r"Allows visiting heroes to buy (.+)\.", text)
    if buy:
        item = _glossary_replace(lang, buy.group(1))
        return {
            "BRportugese": f"Permite que herois visitantes comprem {item}.",
            "czech": f"Umoznuje hostujicim hrdinum koupit {item}.",
            "french": f"Permet aux heros en visite d'acheter {item}.",
            "german": f"Ermoglicht besuchenden Helden, {item} zu kaufen.",
            "hungarian": f"Lehetove teszi a latogato hosoknek {item} vasarlasat.",
            "italian": f"Consente agli eroi in visita di acquistare {item}.",
            "japanese": f"訪問中の英雄が{item}を購入できる。",
            "korean": f"방문 영웅이 {item}을 구매할 수 있습니다.",
            "polish": f"Pozwala odwiedzajacym bohaterom kupic {item}.",
            "russian": f"Позволяет посещающим героям купить {item}.",
            "spanish": f"Permite a los heroes visitantes comprar {item}.",
            "turkish": f"Ziyaret eden kahramanlarin {item} satin almasini saglar.",
            "ukrainian": f"Дозволяє героям-відвідувачам купувати {item}.",
            "zhCN": f"允许来访英雄购买{item}。",
            "zhTW": f"允許來訪英雄購買{item}。",
        }.get(lang, text)

    recruit = re.fullmatch(r"The (Upg\. )?(.+) allows you to recruit (.+)\.", text)
    if recruit:
        upgraded = bool(recruit.group(1))
        building = _glossary_replace(lang, recruit.group(2))
        unit = _glossary_replace(lang, recruit.group(3))
        return {
            "BRportugese": f"O {'edificio aprimorado' if upgraded else 'edificio'} {building} permite recrutar {unit}.",
            "czech": f"{'Vylepsena budova' if upgraded else 'Budova'} {building} umoznuje najimat {unit}.",
            "french": f"Le {'batiment ameliore' if upgraded else 'batiment'} {building} permet de recruter {unit}.",
            "german": f"Das {'verbesserte Gebaude' if upgraded else 'Gebaude'} {building} ermoglicht die Rekrutierung von {unit}.",
            "hungarian": f"A(z) {'fejlesztett ' if upgraded else ''}{building} lehetove teszi {unit} toborzasat.",
            "italian": f"L'edificio {'migliorato ' if upgraded else ''}{building} consente di reclutare {unit}.",
            "japanese": f"{'改良された' if upgraded else ''}{building}で{unit}を雇用できる。",
            "korean": f"{'개선된 ' if upgraded else ''}{building}에서 {unit}을 모집할 수 있습니다.",
            "polish": f"{'Ulepszony budynek' if upgraded else 'Budynek'} {building} pozwala rekrutowac {unit}.",
            "russian": f"{'Улучшенное строение' if upgraded else 'Строение'} {building} позволяет нанимать {unit}.",
            "spanish": f"El {'edificio mejorado' if upgraded else 'edificio'} {building} permite reclutar {unit}.",
            "turkish": f"{'Gelismis ' if upgraded else ''}{building} {unit} alinmasina izin verir.",
            "ukrainian": f"{'Поліпшена споруда' if upgraded else 'Споруда'} {building} дозволяє наймати {unit}.",
            "zhCN": f"{'升级后的' if upgraded else ''}{building}允许招募{unit}。",
            "zhTW": f"{'升級後的' if upgraded else ''}{building}允許招募{unit}。",
        }.get(lang, text)

    allows = re.fullmatch(r"Allows recruitment of (.+)\.", text)
    if allows:
        subject = _glossary_replace(lang, allows.group(1))
        return {
            "BRportugese": f"Permite recrutar {subject}.",
            "czech": f"Umoznuje najimat {subject}.",
            "french": f"Permet de recruter {subject}.",
            "german": f"Ermoglicht die Rekrutierung von {subject}.",
            "hungarian": f"Lehetove teszi {subject} toborzasat.",
            "italian": f"Consente il reclutamento di {subject}.",
            "japanese": f"{subject}の雇用を可能にする。",
            "korean": f"{subject} 모집을 허용합니다.",
            "polish": f"Umozliwia rekrutacje: {subject}.",
            "russian": f"Позволяет нанимать {subject}.",
            "spanish": f"Permite reclutar {subject}.",
            "turkish": f"{subject} alinmasina izin verir.",
            "ukrainian": f"Дозволяє наймати {subject}.",
            "zhCN": f"允许招募{subject}。",
            "zhTW": f"允許招募{subject}。",
        }.get(lang, text)

    command = re.fullmatch(r"(.+) Command (\d+)", text)
    if command:
        faction = _glossary_replace(lang, command.group(1))
        number = command.group(2)
        return {
            "BRportugese": f"Comando {faction} {number}",
            "czech": f"{faction}: Veleni {number}",
            "french": f"Commandement {faction} {number}",
            "german": f"{faction}-Befehl {number}",
            "hungarian": f"{faction} parancs {number}",
            "italian": f"Comando {faction} {number}",
            "japanese": f"{faction}指揮 {number}",
            "korean": f"{faction} 지휘 {number}",
            "polish": f"Dowodzenie {faction} {number}",
            "russian": f"Командование {faction} {number}",
            "spanish": f"Mando {faction} {number}",
            "turkish": f"{faction} Komuta {number}",
            "ukrainian": f"Командування {faction} {number}",
            "zhCN": f"{faction}指挥 {number}",
            "zhTW": f"{faction}指揮 {number}",
        }.get(lang, text)

    skill_rank = re.fullmatch(r"(Basic|Advanced|Expert) (.+)", text)
    if skill_rank:
        return f"{_term(lang, skill_rank.group(1))} {_glossary_replace(lang, skill_rank.group(2))}"

    specialist = re.fullmatch(r"(.+) Specialist", text)
    if specialist:
        subject = _glossary_replace(lang, specialist.group(1))
        return {
            "BRportugese": f"Especialista em {subject}",
            "czech": f"Specialista na {subject}",
            "french": f"Specialiste de {subject}",
            "german": f"{subject}-Spezialist",
            "hungarian": f"{subject} specialista",
            "italian": f"Specialista di {subject}",
            "japanese": f"{subject}の専門家",
            "korean": f"{subject} 전문가",
            "polish": f"Specjalista od {subject}",
            "russian": f"Специалист по {subject}",
            "spanish": f"Especialista en {subject}",
            "turkish": f"{subject} Uzmani",
            "ukrainian": f"Спеціаліст з {subject}",
            "zhCN": f"{subject}专家",
            "zhTW": f"{subject}專家",
        }.get(lang, text)

    served = re.fullmatch(r"(.+) serves the HoMM3 (.+) army\.", text)
    if served:
        unit = _glossary_replace(lang, served.group(1))
        faction = _glossary_replace(lang, served.group(2))
        return {
            "BRportugese": f"{unit} serve ao exercito HoMM3 {faction}.",
            "czech": f"{unit} slouzi armade HoMM3 {faction}.",
            "french": f"{unit} sert dans l'armee HoMM3 {faction}.",
            "german": f"{unit} dient der HoMM3-Armee {faction}.",
            "hungarian": f"{unit} a HoMM3 {faction} seregben szolgal.",
            "italian": f"{unit} serve l'esercito HoMM3 {faction}.",
            "japanese": f"{unit}はHoMM3 {faction}軍に仕える。",
            "korean": f"{unit}은 HoMM3 {faction} 군대에 속합니다.",
            "polish": f"{unit} sluzy w armii HoMM3 {faction}.",
            "russian": f"{unit} служит в армии HoMM3 {faction}.",
            "spanish": f"{unit} sirve al ejercito HoMM3 {faction}.",
            "turkish": f"{unit}, HoMM3 {faction} ordusuna hizmet eder.",
            "ukrainian": f"{unit} служить в армії HoMM3 {faction}.",
            "zhCN": f"{unit}为HoMM3 {faction}军队效力。",
            "zhTW": f"{unit}為HoMM3 {faction}軍隊效力。",
        }.get(lang, text)

    dwelling = re.fullmatch(r"An external dwelling that provides (.+) recruits for (.+) \(HoMM3\) armies\.", text)
    if dwelling:
        unit = _glossary_replace(lang, dwelling.group(1))
        faction = _glossary_replace(lang, dwelling.group(2))
        return {
            "BRportugese": f"Uma moradia externa que fornece recrutas {unit} para exercitos {faction} (HoMM3).",
            "czech": f"Venkovni obydli poskytujici jednotky {unit} pro armady {faction} (HoMM3).",
            "french": f"Une demeure externe qui fournit des recrues {unit} aux armees {faction} (HoMM3).",
            "german": f"Eine externe Behausung, die {unit}-Rekruten fur {faction}-Armeen (HoMM3) liefert.",
            "hungarian": f"Kulso lakohely, amely {unit} ujoncokat ad a(z) {faction} (HoMM3) seregeknek.",
            "italian": f"Una dimora esterna che fornisce reclute {unit} agli eserciti {faction} (HoMM3).",
            "japanese": f"{faction}（HoMM3）軍に{unit}の新兵を提供する外部住居。",
            "korean": f"{faction}(HoMM3) 군대에 {unit} 신병을 제공하는 외부 거주지입니다.",
            "polish": f"Zewnetrzne siedlisko zapewniajace rekrutow {unit} dla armii {faction} (HoMM3).",
            "russian": f"Внешнее жилище, предоставляющее рекрутов {unit} для армий {faction} (HoMM3).",
            "spanish": f"Una morada externa que proporciona reclutas {unit} para los ejercitos {faction} (HoMM3).",
            "turkish": f"{faction} (HoMM3) ordulari icin {unit} askerleri saglayan harici mesken.",
            "ukrainian": f"Зовнішнє житло, що надає рекрутів {unit} для армій {faction} (HoMM3).",
            "zhCN": f"为{faction}（HoMM3）军队提供{unit}新兵的外部巢穴。",
            "zhTW": f"為{faction}（HoMM3）軍隊提供{unit}新兵的外部巢穴。",
        }.get(lang, text)

    produces_daily = re.fullmatch(r"Produces (.+) per day for (?:the )?(.+)\.", text)
    if produces_daily:
        resource = _glossary_replace(lang, produces_daily.group(1))
        faction = _glossary_replace(lang, produces_daily.group(2))
        return {
            "BRportugese": f"Produz {resource} por dia para {faction}.",
            "czech": f"Produkuje {resource} denne pro {faction}.",
            "french": f"Produit {resource} par jour pour {faction}.",
            "german": f"Produziert {resource} pro Tag fur {faction}.",
            "hungarian": f"Naponta {resource} termel a(z) {faction} szamara.",
            "italian": f"Produce {resource} al giorno per {faction}.",
            "japanese": f"{faction}に毎日{resource}を産出する。",
            "korean": f"{faction}에 매일 {resource}을 생산합니다.",
            "polish": f"Produkuje {resource} dziennie dla {faction}.",
            "russian": f"Производит {resource} в день для {faction}.",
            "spanish": f"Produce {resource} al dia para {faction}.",
            "turkish": f"{faction} icin gunde {resource} uretir.",
            "ukrainian": f"Виробляє {resource} на день для {faction}.",
            "zhCN": f"每天为{faction}生产{resource}。",
            "zhTW": f"每天為{faction}生產{resource}。",
        }.get(lang, text)

    growth = re.fullmatch(r"Increases (.+) growth(?: by (.+))?(?: per week)?\.", text)
    if growth:
        subject = _glossary_replace(lang, growth.group(1))
        amount = growth.group(2)
        return {
            "BRportugese": f"Aumenta o crescimento de {subject}{' em ' + amount if amount else ''} por semana.",
            "czech": f"Zvysuje tydenni rust {subject}{' o ' + amount if amount else ''}.",
            "french": f"Augmente la croissance de {subject}{' de ' + amount if amount else ''} par semaine.",
            "german": f"Erhoht das wochentliche Wachstum von {subject}{' um ' + amount if amount else ''}.",
            "hungarian": f"Noveli {subject} heti novekedeset{' ' + amount + ' ertekkel' if amount else ''}.",
            "italian": f"Aumenta la crescita settimanale di {subject}{' di ' + amount if amount else ''}.",
            "japanese": f"{subject}の週間成長量を{amount or ''}増加させる。",
            "korean": f"{subject}의 주간 성장을{(' ' + amount + '만큼') if amount else ''} 증가시킵니다.",
            "polish": f"Zwieksza tygodniowy przyrost {subject}{' o ' + amount if amount else ''}.",
            "russian": f"Увеличивает недельный прирост {subject}{' на ' + amount if amount else ''}.",
            "spanish": f"Aumenta el crecimiento semanal de {subject}{' en ' + amount if amount else ''}.",
            "turkish": f"{subject} haftalik buyumesini{(' ' + amount + ' kadar') if amount else ''} artirir.",
            "ukrainian": f"Збільшує щотижневий приріст {subject}{' на ' + amount if amount else ''}.",
            "zhCN": f"使{subject}每周产量增加{amount or ''}。",
            "zhTW": f"使{subject}每週產量增加{amount or ''}。",
        }.get(lang, text)

    # Last pass: use translated game terms while leaving proper names, HoMM3,
    # HotA, VCMI, SIDs, and exact numeric placeholders intact.
    translated = _glossary_replace(lang, text)
    return translated if translated != text else text


def _translated_row(lang: str, row: dict[str, Any], memory: dict[str, str]) -> dict[str, Any]:
    translated = dict(row)
    text = translated.get("text")
    if isinstance(text, str):
        candidate = _draft_translate(lang, text, memory)
        if not _same_placeholders(text, candidate):
            candidate = text
        translated["text"] = candidate
    return translated


def sync_multilingual_custom_lang_rows(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
    read_json: Callable[[zipfile.ZipFile, str], Any],
    write_json: Callable[[Any], bytes],
    upsert_lang_rows: Callable[[dict[str, Any], list[dict[str, Any]]], bool],
) -> None:
    langs = _lang_dirs(release_zip)
    try:
        unit_ability_sids = custom_unit_ability_view_sids(release_zip, output)
    except ValueError as ex:
        raise RuntimeError(str(ex)) from ex
    inserted_total = 0
    reused_total = 0
    drafted_total = 0
    scrubbed_total = 0

    for file_name in TEXT_FILES:
        english_name = f"Lang/english/texts/{file_name}"
        try:
            english_doc = _read_overlay_or_zip(release_zip, output, english_name, read_json)
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        removed = _remove_noncanonical_custom_rows(english_doc, file_name, unit_ability_sids)
        if removed:
            output[english_name] = write_json(english_doc)
            scrubbed_total += removed
            notes.append(f"scrub noncanonical custom Lang rows {english_name} ({removed})")

    for lang in langs:
        memory = _translation_memory(release_zip, output, lang, read_json)
        for file_name in TEXT_FILES:
            english_name = f"Lang/english/texts/{file_name}"
            localized_name = f"Lang/{lang}/texts/{file_name}"
            try:
                english_doc = _read_overlay_or_zip(release_zip, output, english_name, read_json)
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            english_rows = [
                row
                for sid, row in _tokens_by_sid(english_doc).items()
                if _custom_row_belongs_in_file(sid, file_name, unit_ability_sids) and isinstance(row.get("text"), str)
            ]

            try:
                localized_doc = _read_overlay_or_zip(release_zip, output, localized_name, read_json)
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
                localized_doc = {"tokens": []}
            if not isinstance(localized_doc, dict):
                localized_doc = {"tokens": []}
            removed = _remove_noncanonical_custom_rows(localized_doc, file_name, unit_ability_sids)
            if removed:
                scrubbed_total += removed
            existing = _tokens_by_sid(localized_doc)

            missing: list[dict[str, Any]] = []
            for row in english_rows:
                sid = str(row["sid"])
                if sid in existing:
                    english_text = row.get("text")
                    localized_text = existing[sid].get("text")
                    phrasebook_translation = (
                        _phrasebook_translate(lang, english_text)
                        if isinstance(english_text, str)
                        else None
                    )
                    needs_placeholder_repair = (
                        isinstance(english_text, str)
                        and isinstance(localized_text, str)
                        and not _same_placeholders(english_text, localized_text)
                    )
                    needs_same_as_english_repair = (
                        isinstance(english_text, str)
                        and isinstance(localized_text, str)
                        and localized_text == english_text
                        and _needs_localization(lang, english_text)
                    )
                    needs_phrasebook_refresh = (
                        isinstance(phrasebook_translation, str)
                        and isinstance(localized_text, str)
                        and localized_text != phrasebook_translation
                    )
                    if not (needs_placeholder_repair or needs_same_as_english_repair or needs_phrasebook_refresh):
                        continue
                translated = _translated_row(lang, row, memory)
                if translated.get("text") in memory.values():
                    reused_total += 1
                elif translated.get("text") != row.get("text"):
                    drafted_total += 1
                missing.append(translated)

            if (missing and upsert_lang_rows(localized_doc, missing)) or removed:
                output[localized_name] = write_json(localized_doc)
                inserted_total += len(missing)
                action = "merge multilingual custom Lang rows"
                if removed and not missing:
                    action = "scrub noncanonical custom Lang rows"
                elif removed:
                    action = "merge/scrub multilingual custom Lang rows"
                notes.append(f"{action} {localized_name} ({len(missing)} upsert, {removed} scrub)")

    if inserted_total or scrubbed_total:
        notes.append(
            "sync multilingual custom Lang rows "
            f"inserted={inserted_total} translation_memory={reused_total} "
            f"drafted={drafted_total} scrubbed={scrubbed_total}"
        )
