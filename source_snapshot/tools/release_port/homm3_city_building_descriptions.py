"""Derived OE descriptions for every HoMM3 city building level, in all 16 OE locales.

Owner of the tooltip text (``descriptions`` / ``narrativeDescriptions`` lang rows) of
every ``homm3_*_city`` building. The text is computed from the building's final
generated config row (section, bonuses, hire lines, native fields), in vanilla OE
wording, with literal numbers (custom keys get no ``{0}`` substitution from
``BhTooltipBuilding``). Names stay with the per-faction tables in
``apply_release_core_overlay.py``.

Each description is a list of sentences ``(template id, arguments)``; English renders
here, the 15 other locales render from ``homm3_city_building_description_locales.py``
(own machine translations, or the vanilla locale row for a sentence vanilla OE already
has).

Producer: ``apply_release_core_overlay.apply_homm3_city_building_descriptions`` (English,
before multilingual sync) and ``apply_homm3_city_building_description_locales`` (all
other locales, after sync).
Gate: ``tools/release_port/validate_homm3_city_building_descriptions_contract.py``.
Doc: ``docs/homm3_city_building_descriptions.md``.

Fail closed: a section, graal type or bonus type this module does not know raises,
so a new mechanic cannot ship with stale or invented text. Bonus types the section does
not apply in game (flat ``cityUnitsIncrement`` or ``heroStat`` on a bank, anything on
``myceliumRoots``) raise too.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import homm3_city_building_description_locales as L

RESOURCE_NAMES = {
    "gold": "Gold",
    "wood": "Wood",
    "ore": "Ore",
    "mercury": "Mercury",
    "crystals": "Crystals",
    "gemstones": "Gems",
    "dust": "Alchemical Dust",
}

HERO_STAT_NAMES = {
    "offence": "Attack",
    "defence": "Defense",
    "spellPower": "Spell Power",
    "intelligence": "Knowledge",
    "moral": "Morale",
    "luck": "Luck",
}

# Sections whose rows are city building configs (BuildingsData lists).
BUILDING_SECTIONS = (
    "mains",
    "taverns",
    "markets",
    "hires",
    "magicGuilds",
    "banks",
    "manaFountains",
    "intelligences",
    "graals",
    "unitsConverters",
    "trainingRanges",
    "rebirthShrines",
    "heroBonusBanks",
    "cityBonusBanks",
    "myceliumRoots",
    "portalSummonings",
    "artifactChangers",
    "artifactMarkets",
    "walls",
)

# Bonus types each bonus section really applies (see apply_release_core_overlay
# NATIVE_CITY_BUILDING_BONUS_TYPES for the evidence).
NATIVE_SECTION_BONUS_TYPES = {
    "banks": frozenset({"sideRes", "cityUnitsIncrementPer"}),
    "cityBonusBanks": frozenset({"sideRes", "cityUnitsIncrementPer"}),
    "heroBonusBanks": frozenset({"heroStat", "heroExp"}),
}

# Text that names a mechanic or entity OE does not have (war machines, HoMM3-only
# buildings/rules) or that is generic filler instead of an effect. Checked
# case-insensitively against every English name and description of every homm3 city.
FORBIDDEN_DESCRIPTION_PATTERNS = (
    r"\bballista",
    r"\bcannons?\b",
    r"\bammo(?:\s|-)?cart",
    r"first aid",
    r"war machine",
    r"\bcatapult",
    r"\bshipyard",
    r"\bbuild(?:s)? (?:a )?ships?\b",
    r"\bcapitol\b",
    r"when supported",
    r"special (?:town )?building",
    r"administrative center",
    r"support building",
    r"visiting hero services",
    r"horde building",
    r"grail building",
    r"\btreasury\b",
    r"\bhomm3\b",
    r"\bhota\b",
    r"\bvcmi\b",
    r"\bsubstitut",
    r"\bplaceholder\b",
    r"\btodo\b",
    r"\btbd\b",
)
FORBIDDEN_NAME_PATTERNS = tuple(
    p for p in FORBIDDEN_DESCRIPTION_PATTERNS if p not in (r"\bcapitol\b",)
)
# Rampart's artifact market is the HoMM3 'Treasury' by name; only Blacksmith rows may not
# carry the word (user decision 2026-10-01).
FORBIDDEN_NAME_PATTERNS = tuple(p for p in FORBIDDEN_NAME_PATTERNS if p != r"\btreasury\b")

_INVARIANT_PLURAL_WORDS = {"yeti", "argali", "vermin", "dead", "olgoi-khorkhoi", "efreet"}
_IRREGULAR_PLURAL_WORDS = {
    "elf": "Elves",
    "dwarf": "Dwarves",
    "efreeti": "Efreet",
    "cyclops": "Cyclopes",
    "monarch": "Monarchs",
    "pegasus": "Pegasi",
    "cerberus": "Cerberi",
    "colossus": "Colossi",
}


def plural_unit_name(name: str) -> str:
    """English plural of a creature display name (last word inflected)."""
    head, _, last = name.rpartition(" ")
    low = last.lower()
    if low in _INVARIANT_PLURAL_WORDS:
        plural = last
    elif low in _IRREGULAR_PLURAL_WORDS:
        plural = _IRREGULAR_PLURAL_WORDS[low]
    elif low.endswith("man") and low not in ("shaman", "talisman"):
        plural = last[:-3] + "men"
    elif low.endswith(("s", "x", "z", "ch", "sh")):
        plural = last + "es"
    elif low.endswith("y") and len(low) > 1 and low[-2] not in "aeiou":
        plural = last[:-1] + "ies"
    else:
        plural = last + "s"
    return f"{head} {plural}" if head else plural


def join_and(items: list[str]) -> str:
    if not items:
        raise ValueError("join_and: empty list")
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _num(value: Any) -> float:
    return float(str(value))


def fmt_number(value: Any) -> str:
    number = _num(value)
    return str(int(number)) if number == int(number) else f"{number:g}"


def fmt_percent(value: Any) -> str:
    return fmt_number(round(_num(value) * 100, 6))


def _bonus_type_params(bonus: dict[str, Any]) -> tuple[str, list[Any]]:
    btype = bonus.get("type")
    params = bonus.get("parameters")
    if not isinstance(btype, str) or not isinstance(params, list):
        raise ValueError(f"malformed bonus {bonus!r}")
    return btype, params


def _resource(sid: Any) -> str:
    if sid not in RESOURCE_NAMES:
        raise ValueError(f"unknown resource {sid!r}")
    return str(sid)


def _hero_stat(sid: Any) -> str:
    if sid not in HERO_STAT_NAMES:
        raise ValueError(f"unknown hero stat {sid!r}")
    return str(sid)


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sentence:
    """One tooltip sentence: template id plus its arguments.

    ``nums`` are already formatted numbers; ``units`` unit sids; ``res`` / ``stats``
    (sid, formatted amount) pairs; ``vanilla`` positional values for a vanilla row.
    """

    tid: str
    nums: tuple[tuple[str, str], ...] = ()
    units: tuple[str, ...] = ()
    res: tuple[tuple[str, str], ...] = ()
    stats: tuple[tuple[str, str], ...] = ()
    vanilla: tuple[str, ...] = ()

    def num(self, key: str) -> str:
        return dict(self.nums)[key]


@dataclass
class CityContext:
    """Per-city lookups the derivation needs (unit display names, dwelling growth)."""

    city_item: dict[str, Any]
    _weekly: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for row in self.city_item.get("hires") or []:
            if not isinstance(row, dict):
                continue
            for line in ((row.get("unitsHire") or {}).get("units") or []):
                if isinstance(line, dict) and line.get("sids"):
                    self._weekly[str(line["sids"][0])] = int(line.get("weeklyIncrement") or 0)

    def weekly(self, base_sid: str) -> int:
        if base_sid not in self._weekly:
            raise ValueError(f"growth key {base_sid!r} is not the first sid of a hire line")
        return self._weekly[base_sid]


def _check_native(section: str, bonuses: list[dict[str, Any]]) -> dict[str, list[list[Any]]]:
    allowed = NATIVE_SECTION_BONUS_TYPES[section]
    grouped: dict[str, list[list[Any]]] = {}
    for bonus in bonuses:
        btype, params = _bonus_type_params(bonus)
        if btype not in allowed:
            raise ValueError(f"{section} bonus {btype!r} is not applied by the game (allowed {sorted(allowed)})")
        grouped.setdefault(btype, []).append(params)
    if not grouped:
        raise ValueError(f"{section} row without bonuses")
    return grouped


def flat_growth_for_percent(weekly: int, pct: Any) -> int:
    """Flat units/week a per-dwelling percent adds on its own (native int truncation)."""
    return int(math.floor(weekly * _num(pct) + 1e-9))


def _bank_sentences(section: str, row: dict[str, Any], ctx: CityContext) -> list[Sentence]:
    grouped = _check_native(section, row.get("bonuses") or [])
    out: list[Sentence] = []
    if "sideRes" in grouped:
        out.append(Sentence("res_daily", res=tuple((_resource(p[0]), fmt_number(p[1])) for p in grouped["sideRes"])))
    per_unit: dict[str, list[str]] = {}
    for key, pct in ((p[0], p[1]) for p in grouped.get("cityUnitsIncrementPer", [])):
        if key == "all":
            out.append(Sentence("city_pct", nums=(("p", fmt_percent(pct)),)))
            continue
        flat = flat_growth_for_percent(ctx.weekly(str(key)), pct)
        if flat <= 0:
            raise ValueError(f"growth percent {pct} on {key} adds no unit")
        per_unit.setdefault(str(flat), []).append(str(key))
    for amount, keys in per_unit.items():
        out.append(Sentence("growth_city", nums=(("n", amount),), units=tuple(keys)))
    return out


def _hero_bonus_bank_sentences(row: dict[str, Any]) -> list[Sentence]:
    grouped = _check_native("heroBonusBanks", row.get("bonuses") or [])
    out: list[Sentence] = []
    if "heroStat" in grouped:
        out.append(Sentence("hero_stats", stats=tuple((_hero_stat(p[0]), fmt_number(p[1])) for p in grouped["heroStat"])))
    if "heroExp" in grouped:
        out.append(Sentence("hero_exp"))
    return out


def _graal_sentences(row: dict[str, Any]) -> list[Sentence]:
    graal_type = row.get("graalType")
    side = row.get("sideBonuses") or []
    city = row.get("cityBonuses") or []
    city_pct = None
    reveal = False
    for bonus in city:
        btype, params = _bonus_type_params(bonus)
        if btype == "cityUnitsIncrementPer" and params[0] == "all":
            city_pct = fmt_percent(params[1])
        elif btype == "cityRadiusView":
            reveal = _num(params[0]) >= 999
            if not reveal:
                raise ValueError(f"graal cityRadiusView {params[0]!r} is not a full reveal")
        else:
            raise ValueError(f"unsupported graal city bonus {btype!r}")
    if city_pct is None:
        raise ValueError(f"graal {row.get('sid')} without city growth percent")
    tail = Sentence("graal_tail", nums=(("p", city_pct),))
    if graal_type == "HumanGraal":
        res = {}
        for bonus in side:
            btype, params = _bonus_type_params(bonus)
            if btype != "sideResHumGraal":
                raise ValueError(f"unsupported HumanGraal side bonus {btype!r}")
            res[params[0]] = fmt_number(params[1])
        others = {k: v for k, v in res.items() if k != "gold"}
        if "gold" not in res or set(others) != {"wood", "ore", "gemstones", "crystals", "mercury"} or len(set(others.values())) != 1:
            raise ValueError(f"HumanGraal resource set not in vanilla shape: {res}")
        each = next(iter(others.values()))
        return [Sentence("graal_human", nums=(("g", res["gold"]), ("e", each)), vanilla=(res["gold"], each)), tail]
    if graal_type == "NatureGraal":
        if len(side) != 1:
            raise ValueError("NatureGraal expects one side bonus")
        btype, params = _bonus_type_params(side[0])
        if btype != "cityUnitsIncrement" or params[0] != "all":
            raise ValueError(f"unsupported NatureGraal side bonus {btype!r}")
        n = fmt_number(params[1])
        return [Sentence("graal_nature", nums=(("n", n),), vanilla=(n,)), tail]
    if graal_type == "DungeonGraal":
        if side or not reveal:
            raise ValueError("DungeonGraal expects a full reveal and no side bonuses")
        return [Sentence("graal_dungeon"), tail]
    if graal_type in ("DemonGraal", "UndeadGraal"):
        stats: dict[str, str] = {}
        for bonus in side:
            btype, params = _bonus_type_params(bonus)
            if btype not in ("unitStat", "heroStat") or bonus.get("receiverAllegiance") != "ally":
                raise ValueError(f"unsupported {graal_type} side bonus {btype!r}")
            stats.setdefault(params[0], params[1])
        if graal_type == "DemonGraal":
            if set(stats) != {"offence", "crit"}:
                raise ValueError(f"DemonGraal stats {stats}")
            return [
                Sentence("graal_demon", nums=(("a", fmt_number(stats["offence"])), ("c", fmt_percent(stats["crit"])))),
                tail,
            ]
        if set(stats) != {"defence", "anticrit"}:
            raise ValueError(f"UndeadGraal stats {stats}")
        d, a = fmt_number(stats["defence"]), fmt_percent(stats["anticrit"])
        return [Sentence("graal_undead", nums=(("d", d), ("a", a), ("p", city_pct)), vanilla=(d, a, city_pct))]
    raise ValueError(f"unsupported graalType {graal_type!r}")


def _level_bonuses(row: dict[str, Any], level_index: int) -> list[dict[str, Any]]:
    per_level = row.get("bonusesPerLevel")
    if not isinstance(per_level, list) or level_index >= len(per_level):
        raise ValueError(f"{row.get('sid')}: missing bonusesPerLevel[{level_index}]")
    bonuses = per_level[level_index].get("bonuses") if isinstance(per_level[level_index], dict) else None
    if not isinstance(bonuses, list):
        raise ValueError(f"{row.get('sid')}: bonusesPerLevel[{level_index}] has no bonuses")
    return bonuses


def _upgrade_tier(row: dict[str, Any], level_index: int) -> int:
    """1-based count of levels up to this one that offer optional effects (0 = none here)."""
    levels = row.get("optionalEffectsPerLevel") or []
    if level_index >= len(levels) or not (levels[level_index] or {}).get("effects"):
        return 0
    return sum(1 for entry in levels[: level_index + 1] if (entry or {}).get("effects"))


def _main_sentences(row: dict[str, Any], level_index: int) -> list[Sentence]:
    values: dict[str, str] = {}
    for bonus in _level_bonuses(row, level_index):
        btype, params = _bonus_type_params(bonus)
        if btype == "sideRes" and params[0] == "gold":
            values["g"] = fmt_number(params[1])
        elif btype == "citySideExp":
            values["l"] = fmt_number(params[0])
        elif btype == "astrologyExp":
            values["a"] = fmt_number(params[0])
        else:
            raise ValueError(f"unsupported main bonus {btype!r}")
    if set(values) != {"g", "l", "a"}:
        raise ValueError(f"main building level {level_index + 1} bonuses {values}")
    out = [Sentence("main", nums=tuple(sorted(values.items())))]
    tier = _upgrade_tier(row, level_index)
    if tier:
        out.append(Sentence("main_upgrade", nums=(("t", str(tier)),)))
    return out


def _wall_sentences(row: dict[str, Any], level_index: int, level_count: int) -> list[Sentence]:
    if level_count != 3:
        raise ValueError(f"walls with {level_count} levels have no vanilla text shape")
    pct = None
    for bonus in _level_bonuses(row, level_index):
        btype, params = _bonus_type_params(bonus)
        if btype != "cityUnitsIncrementPer" or params[0] != "all":
            raise ValueError(f"unsupported wall bonus {btype!r}")
        pct = fmt_percent(params[1])
    tier = _upgrade_tier(row, level_index)
    if tier != level_index + 1:
        raise ValueError(f"wall level {level_index + 1} offers defensive upgrade tier {tier}")
    if level_index == 0:
        out = [Sentence("wall_1")]
        if pct not in (None, "0"):
            out.append(Sentence("city_pct", nums=(("p", pct),)))
        return out
    if pct in (None, "0"):
        raise ValueError(f"wall level {level_index + 1} without a growth percent has no vanilla text shape")
    return [Sentence(f"wall_{level_index + 1}", nums=(("p", pct),), vanilla=(pct,))]


def _hire_sentences(row: dict[str, Any], level_index: int) -> list[Sentence]:
    units = ((row.get("unitsHire") or {}).get("units")) or []
    if not units:
        raise ValueError(f"{row.get('sid')}: hire row without units")
    chosen: list[str] = []
    for line in units:
        sids = line.get("sids") or []
        if len(sids) < 2:
            raise ValueError(f"{row.get('sid')}: hire line {sids} has no upgrade")
        chosen.extend([sids[0]] if level_index == 0 else list(sids[1:]))
    return [Sentence("hire", units=tuple(str(s) for s in chosen))]


def _converter_sentences(row: dict[str, Any]) -> list[Sentence]:
    pairs = row.get("conversionPairs") or []
    if not pairs:
        raise ValueError(f"{row.get('sid')}: units converter without conversionPairs")
    ordered = sorted((int(p["tier"]), str(p["sid"])) for p in pairs)
    banned = set(row.get("bannedUnits") or [])
    missing = [sid for _, sid in ordered if sid not in banned]
    if missing:
        raise ValueError(f"{row.get('sid')}: conversion targets {missing} are not banned, so they convert into themselves")
    return [Sentence("converter", units=tuple(sid for _, sid in ordered))]


def derive_building_sentences(
    section: str, row: dict[str, Any], level_index: int, level_count: int, ctx: CityContext
) -> list[Sentence]:
    if section == "mains":
        return _main_sentences(row, level_index)
    if section == "taverns":
        return [Sentence("tavern")]
    if section == "markets":
        return [Sentence("market")]
    if section == "artifactMarkets":
        return [Sentence("artifact_market")]
    if section == "hires":
        return _hire_sentences(row, level_index)
    if section == "magicGuilds":
        tier = str(level_index + 1)
        return [Sentence("mg_one" if tier == "1" else "mg_range", nums=(("t", tier),))]
    if section == "walls":
        return _wall_sentences(row, level_index, level_count)
    if section in ("banks", "cityBonusBanks"):
        return _bank_sentences(section, row, ctx)
    if section == "heroBonusBanks":
        return _hero_bonus_bank_sentences(row)
    if section == "myceliumRoots":
        if row.get("bonuses"):
            raise ValueError(f"{row.get('sid')}: myceliumRoots has no bonuses field in game; its bonuses do nothing")
        return [Sentence("mycelium")]
    if section == "graals":
        return _graal_sentences(row)
    if section == "intelligences":
        radius = row.get("viewRadius")
        if not isinstance(radius, (int, float)) or radius <= 0:
            raise ValueError(f"{row.get('sid')}: intelligence row without viewRadius")
        r = fmt_number(radius)
        return [Sentence("intelligence", nums=(("r", r),), vanilla=(r,))]
    if section == "trainingRanges":
        return [Sentence("training")]
    if section == "rebirthShrines":
        return [Sentence("rebirth")]
    if section == "manaFountains":
        return [Sentence("mana")]
    if section == "unitsConverters":
        return _converter_sentences(row)
    if section == "artifactChangers":
        return [Sentence("artifact_changer")]
    raise ValueError(f"no derived description for section {section!r} ({row.get('sid')})")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_ENGLISH_FIXED = {
    "tavern": "Allows the hiring of new heroes.",
    "market": "Allows resources to be traded.",
    "artifact_market": "Allows artifacts to be traded.",
    "mycelium": "Allows a hero to travel to any city of their choice under your control.",
    "training": (
        "Allows a selected hero to spend a day learning. They will be unavailable until the next day and "
        "receive a permanent increase to an attribute of their choice."
    ),
    "rebirth": (
        "Allows to revert a hero to level one once. The hero receives a permanent bonus to their attributes "
        "that depends on their level at the moment of the ritual."
    ),
    "mana": "Immediately restores all mana to any visiting hero.",
    "artifact_changer": "Allows enchanting of magic scrolls so that they grant spells of maximum level.",
    "hero_exp": "Levels up any visiting hero once.",
    "wall_1": "Provides walls during sieges. Allows the builder to pick one level-1 defensive upgrade.",
    "graal_dungeon": "Completely removes the fog of war.",
}


def _render_english(s: Sentence, unit_name: Callable[[str], str]) -> str:
    if s.tid in _ENGLISH_FIXED:
        return _ENGLISH_FIXED[s.tid]
    n = dict(s.nums)
    if s.tid == "res_daily":
        return f"Produces {join_and([f'{amount} {RESOURCE_NAMES[res]}' for res, amount in s.res])} daily."
    if s.tid == "growth_city":
        names = join_and([plural_unit_name(unit_name(u)) for u in s.units])
        return f"Increases the weekly growth of {names} by {n['n']} in this city."
    if s.tid == "city_pct":
        return f"City dwellings produce +{n['p']}% units."
    if s.tid == "graal_tail":
        return f"This city's dwellings produce +{n['p']}% units."
    if s.tid == "hero_stats":
        return f"Grants {join_and([f'+{amount} {HERO_STAT_NAMES[stat]}' for stat, amount in s.stats])} to any visiting hero."
    if s.tid == "main":
        if len({n["g"], n["l"], n["a"]}) == 1:
            return f"Grants the kingdom {n['g']} Gold, Law points, and Astrology points daily."
        return f"Grants the kingdom {n['g']} Gold, {n['l']} Law points, and {n['a']} Astrology points daily."
    if s.tid == "main_upgrade":
        return f"Allows the owner to pick one level-{n['t']} economy upgrade."
    if s.tid == "hire":
        return f"Allows the recruitment of {join_and([plural_unit_name(unit_name(u)) for u in s.units])}."
    if s.tid in ("mg_one", "mg_range"):
        t = n["t"]
        known = "tier-1" if t == "1" else f"tier-1–{t}"
        return (
            f"Unlocks random tier-{t} spells in the Magic Observatory and the ability to spend dust to upgrade "
            f"tier-{t} spells or unlock additional ones. When heroes visit the city, all unlocked {known} spells "
            "are added to their Spellbook."
        )
    if s.tid == "wall_2":
        return (
            "Adds two towers to the battlements that shoot at attackers during sieges. "
            f"Allows the builder to pick one level-2 defensive upgrade. City dwellings produce +{n['p']}% units."
        )
    if s.tid == "wall_3":
        return (
            "Adds one more grand tower to the battlements that shoots at attackers during sieges and spikes by the walls. "
            f"Allows the builder to pick one level-3 defensive upgrade. City dwellings produce +{n['p']}% units."
        )
    if s.tid == "intelligence":
        return f"Removes the fog of war within {n['r']} squares around the city."
    if s.tid == "graal_human":
        return f"The owner's cities produce {n['g']} Gold and {n['e']} of each other resource daily."
    if s.tid == "graal_nature":
        return f"+{n['n']} to all creature growth in all your cities."
    if s.tid == "graal_demon":
        return f"All friendly creatures gain +{n['a']} Attack in battle. +{n['c']}% Lucky Strike Damage, including from hero spells."
    if s.tid == "graal_undead":
        return (
            f"All friendly creatures gain +{n['d']} Defense and take −{n['a']}% Lucky Strike Damage in battle "
            f"(including from spells). This city's dwellings produce +{n['p']}% units."
        )
    if s.tid == "converter":
        names = join_and([plural_unit_name(unit_name(u)) for u in s.units])
        return f"Allows sacrificing of other creatures to turn them into units of the same tier: {names}."
    raise ValueError(f"no English rendering for sentence {s.tid!r}")


def _fill_vanilla(template: str, values: tuple[str, ...], key: str) -> str:
    out = template
    for index, value in enumerate(values):
        token = "{" + str(index) + "}"
        if token not in out:
            raise ValueError(f"vanilla row {key} has no {token}")
        out = out.replace(token, value)
    if re.search(r"\{\d+\}", out):
        raise ValueError(f"vanilla row {key} has more placeholders than values: {template!r}")
    return out


def _render_locale(
    lang: str,
    s: Sentence,
    unit_name: Callable[[str], str],
    vanilla_text: Callable[[str], str],
) -> str:
    key = L.VANILLA_SENTENCE_KEYS.get(s.tid)
    if key is not None:
        return _fill_vanilla(vanilla_text(key), s.vanilla, key)
    if s.tid not in L.TEMPLATES:
        raise ValueError(f"no {lang} template for sentence {s.tid!r}")
    template = L.TEMPLATES[s.tid][lang]
    sep = L.LIST_SEPARATOR[lang]
    values = dict(s.nums)
    if s.units:
        values["units"] = sep.join(unit_name(u) for u in s.units)
    if s.res:
        values["res"] = sep.join(
            L.RESOURCE_ITEM[lang].format(n=amount, name=L.RESOURCE_NAMES[lang][res]) for res, amount in s.res
        )
    if s.stats:
        values["stats"] = sep.join(
            L.STAT_ITEM[lang].format(n=amount, name=L.HERO_STAT_NAMES[lang][stat]) for stat, amount in s.stats
        )
    return template.format(**values)


def render_sentences(
    lang: str,
    sentences: list[Sentence],
    unit_name: Callable[[str], str],
    vanilla_text: Callable[[str], str] | None = None,
) -> str:
    """Render one description. ``unit_name`` / ``vanilla_text`` read that locale's Lang rows."""
    if lang == "english":
        return " ".join(_render_english(s, unit_name) for s in sentences)
    if lang not in L.LOCALES:
        raise ValueError(f"unknown locale {lang!r}")
    if vanilla_text is None:
        raise ValueError(f"{lang}: vanilla_text lookup required")
    return L.SENTENCE_SEPARATOR[lang].join(_render_locale(lang, s, unit_name, vanilla_text) for s in sentences)


def derive_building_description(
    section: str,
    row: dict[str, Any],
    level_index: int,
    level_count: int,
    unit_name: Callable[[str], str],
    city_item: dict[str, Any] | None = None,
) -> str:
    ctx = CityContext(city_item or {})
    return render_sentences("english", derive_building_sentences(section, row, level_index, level_count, ctx), unit_name)


def iter_city_building_levels(city_item: dict[str, Any]):
    """Yield (section, row, level_index, level_count) for every building level of a city row."""
    for section in BUILDING_SECTIONS:
        rows = city_item.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("names"), list):
                continue
            level_count = len(row["names"])
            for level_index in range(level_count):
                yield section, row, level_index, level_count
    unknown = [
        key
        for key, value in city_item.items()
        if key not in BUILDING_SECTIONS
        and isinstance(value, list)
        and value
        and isinstance(value[0], dict)
        and "names" in value[0]
    ]
    if unknown:
        raise ValueError(f"{city_item.get('id')}: building sections without a description rule: {unknown}")


def derive_city_description_sentences(city_item: dict[str, Any]) -> dict[str, list[Sentence]]:
    """Map each description and narrativeDescription lang key of a city row to its sentences."""
    ctx = CityContext(city_item)
    out: dict[str, list[Sentence]] = {}
    for section, row, level_index, level_count in iter_city_building_levels(city_item):
        sentences = derive_building_sentences(section, row, level_index, level_count, ctx)
        for field_name in ("descriptions", "narrativeDescriptions"):
            keys = row.get(field_name)
            if not isinstance(keys, list) or len(keys) != level_count or not isinstance(keys[level_index], str):
                raise ValueError(f"{city_item.get('id')}:{row.get('sid')}: {field_name} does not cover level {level_index + 1}")
            key = keys[level_index]
            if key in out and out[key] != sentences:
                raise ValueError(f"{city_item.get('id')}: lang key {key} shared by levels with different effects")
            out[key] = sentences
    return out


def derive_city_description_rows(
    city_item: dict[str, Any], unit_name: Callable[[str], str]
) -> dict[str, str]:
    """English text for each description and narrativeDescription lang key of a city row."""
    return {
        key: render_sentences("english", sentences, unit_name)
        for key, sentences in derive_city_description_sentences(city_item).items()
    }


def text_problems(text: Any, key: str, *, kind: str) -> list[str]:
    """Static checks on English text shared by producer and validator."""
    if not isinstance(text, str) or not text.strip():
        return [f"{key}: missing or empty {kind}"]
    problems: list[str] = []
    if text.strip() == key or re.fullmatch(r"[A-Za-z0-9_]+", text.strip()) and "_" in text:
        problems.append(f"{key}: {kind} is a raw key {text!r}")
    if "{" in text or "}" in text:
        problems.append(f"{key}: {kind} has an unfilled placeholder {text!r}")
    patterns = FORBIDDEN_DESCRIPTION_PATTERNS if kind == "description" else FORBIDDEN_NAME_PATTERNS
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            problems.append(f"{key}: {kind} names a mechanic/entity absent from OE or filler ({pattern}): {text!r}")
    return problems


def locale_text_problems(lang: str, text: Any, english: Any, key: str) -> list[str]:
    """Checks on one locale row of a derived key: present, localized, no forbidden term."""
    if not isinstance(text, str) or not text.strip():
        return [f"{lang} {key}: missing or empty"]
    problems: list[str] = []
    if isinstance(english, str) and text.strip() == english.strip():
        problems.append(f"{lang} {key}: English fallback {text!r}")
    if re.search(r"\{\d*\}", text):
        problems.append(f"{lang} {key}: unfilled placeholder {text!r}")
    for pattern in L.COMMON_FORBIDDEN + L.FORBIDDEN_PATTERNS[lang] + FORBIDDEN_DESCRIPTION_PATTERNS[:7]:
        if re.search(pattern, text, re.IGNORECASE):
            problems.append(f"{lang} {key}: war-machine/HoMM3/filler term ({pattern}): {text!r}")
    for pattern in L.FILLER_MARKERS:
        if re.search(pattern, text):
            problems.append(f"{lang} {key}: filler marker ({pattern}): {text!r}")
    return problems
