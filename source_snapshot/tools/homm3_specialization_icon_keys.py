"""Icon-key mapping for HoMM3 non-creature hero specializations."""

from __future__ import annotations

# Olden Era resolves these through native skill/spell sprite keys at runtime.
SPECIALIZATION_ICON_BY_KIND: dict[str, str] = {
    "archery": "skill_assault",
    "armorer": "skill_protection",
    "artillery": "skill_siege",
    "ballista": "skill_battlemage",
    "crystal": "skill_economy",
    "eagleEye": "skill_scouting",
    "estates": "skill_economy",
    "firstAid": "day_1_magic_healing_water",
    "fortune": "skill_luck",
    "gem": "skill_economy",
    "gold": "skill_economy",
    "intelligence": "skill_wisdom",
    "learning": "skill_wisdom",
    "logistics": "skill_logistic",
    "mercury": "skill_economy",
    "mysticism": "skill_wisdom",
    "navigation": "skill_logistic",
    "necromancy": "night_3_magic_enlarge_shadow",
    "offence": "skill_assault",
    "offense": "skill_assault",
    "pathfinding": "skill_logistic_2",
    "resistance": "skill_protection",
    "scouting": "skill_scouting",
    "slayer": "skill_assault",
    "sorcery": "skill_sorcery",
    "speed": "skill_logistic",
    "stone": "skill_economy",
    "sulfur": "skill_economy",
    "tactics": "skill_tactics",
    "leadership": "skill_leadership",
}


def specialization_icon_key_for_kind(kind: str, *, fallback: str = "skill_trainer") -> str:
    if not isinstance(kind, str) or not kind.strip():
        return fallback
    return SPECIALIZATION_ICON_BY_KIND.get(kind.strip(), fallback)
