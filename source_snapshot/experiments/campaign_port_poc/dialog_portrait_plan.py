"""Plan Olden Era dialog slides with portraits from unchanged HoMM3 event text.

Does not rewrite dialogue. Splits existing quoted multi-speaker text into OE-style
slides and attaches single-speaker avatars when a portrait key is known.

Portrait sources:
- Custom HoMM3 heroes (icons/dialogue/dialogue_hero_homm3_*)
- Vanilla OE dialogue icons already in Resources
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
HOMM3_MANIFEST = (
    REPO
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_hero_portraits_upscaled"
    / "manifest.json"
)
HUB_INDEX = REPO / "scenarios" / "ab_sod_campaigns" / "hub_index.v1.json"
QUOTED_CREATURES = (
    REPO / "artifacts" / "unit_portrait_touchup_pilot" / "campaign_quoted_creatures.json"
)
SPEAKER_OVERRIDES = Path(__file__).resolve().parent / "dialog_speaker_overrides.v1.json"
HOMM3_UNIT_DIALOG_PREFIX = "icons/dialogue/dialogue_unit_"


QUOTE_RE = re.compile(r'"([^"]*)"|“([^”]*)”')
_SPEECH_VERBS = (
    r"says?|said|shouts?|shouted|snarls?|snarled|asks?|asked|replies?|replied|"
    r"whispers?|yells?|yelled|growls?|growled|demands?|demanded|continues?|continued|"
    r"adds?|added|cries|cried|exclaims?|exclaimed|explains?|explained|sighs?|sighed|"
    r"grunts?|grunted|corrects?|corrected|groans?|groaned|answers?|answered|"
    r"laughs?|laughed|laughing|hollers?|hollered|hollering|"
    r"sings?|sang|sung|singing|complains?|complained|complaining|"
    r"announces?|announced|declares?|declared"
)
SPEAKER_CUE_RE = re.compile(
    rf"(?P<who>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){{0,3}})\s+"
    rf"(?:{_SPEECH_VERBS})\b",
    re.M,
)
# Player is speaking only for explicit speech/act verbs — not narration like "You are…".
# Keep intervening text tight: "You shout" / "You begin complaining" / "You pull … and shout".
YOU_CUE_RE = re.compile(
    rf"\byou\s+(?:(?:just|then|also|now|simply|kindly|quickly|finally|slowly|politely)\s+)*"
    rf"(?:begin\s+(?:to\s+)?|start\s+(?:to\s+)?)?(?:{_SPEECH_VERBS})\b"
    rf"|"
    rf"\byou\s+(?:pull|take|draw|grab|pick)\b[^.\"“]{{0,48}}?\b(?:and\s+)?(?:{_SPEECH_VERBS})\b",
    re.I,
)
# HoMM3 often attributes after the quote: `"Hello," says Sandro`
SAYS_AFTER_RE = re.compile(
    r"^\s*says?\s+(?P<who>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\b"
)
# Allow "says;" / "says," immediately before the opening quote.
SAYS_BEFORE_RE = re.compile(
    r"(?P<who>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\s+says?\s*[,;:]?\s*$"
)
I_AM_RE = re.compile(
    r"\bI,\s+(?P<name>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,2})\b"
)
# Trailing speech / song cue just before a quote (NPC roles, not proper names).
ROLE_SPEECH_TAIL_RE = re.compile(
    rf"(?:{_SPEECH_VERBS}|delivers?(?:\s+you)?(?:\s+the\s+news)?|"
    r"outburst of song|begin(?:s|ning)?\s+singing|line up[^.\"“]{{0,40}}singing|"
    r"with slurred words|sales pitch)\s*[,;:.…]?\s*$",
    re.I,
)

# Generic NPC / role → dialog icon (vanilla OE key or injected dialogue_unit_h3_*).
# Ambiguous roles (native/fellow/messenger) may be remapped per-mission from quoted
# creature context — see _resolve_ambiguous_role.
VANILLA_ROLE_ICONS: dict[str, str | None] = {
    "peasant": "icons/dialogue/dialogue_unit_peasant",
    "peasants": "icons/dialogue/dialogue_unit_peasant",
    "messenger": "icons/dialogue/dialogue_unit_peasant",
    "merchant": "icons/dialogue/dialogue_unit_peasant",
    "merchants": "icons/dialogue/dialogue_unit_peasant",
    "native": None,  # resolved from mission creature context when possible
    "natives": None,
    "fellow": None,
    "fool": "icons/dialogue/dialogue_unit_peasant",
    "woman": "icons/dialogue/dialogue_unit_peasant",
    "advisor": "icons/dialogue/dialogue_unit_peasant",
    "advisors": "icons/dialogue/dialogue_unit_peasant",
    "counselor": "icons/dialogue/dialogue_unit_peasant",
    "counselors": "icons/dialogue/dialogue_unit_peasant",
    # Defaults prefer HoMM3 unit art; factionRoleUnits remaps further per campaign.
    "scout": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_archer",
    "scouts": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_archer",
    "guard": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_pikeman_upg",
    "guards": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_pikeman_upg",
    "captain": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_swordsman_upg",
    "troop": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_swordsman",
    "troops": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_swordsman",
    "mercenary": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_swordsman",
    "mercenaries": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_swordsman",
    "assassin": "icons/dialogue/dialogue_unit_assassin",
    "lich": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_lich",
    "skeleton": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_skeleton",
    "skeletons": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_skeleton",
    "vampire": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_vampire_upg",
    "vampires": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_vampire_upg",
    "druid": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_dendroid_guard",
    "dendroid": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_dendroid_guard",
    "ent": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_dendroid_soldier",
    "elf": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_wood_elf",
    "tracker": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_wood_elf",
    "pixie": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_pixie",
    "medusa": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_medusa",
    "troglodyte": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_troglodyte",
    "sentinel": "icons/dialogue/dialogue_unit_sentinel",
    "inquisitor": "icons/dialogue/dialogue_unit_inquisitor",
    "crossbowman": "icons/dialogue/dialogue_unit_crossbowman",
    "builder": "icons/dialogue/dialogue_unique_builder",
    "goblin": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_goblin",
    "goblins": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_goblin",
    "hobgoblin": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_goblin_upg",
    "hobgoblins": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_goblin_upg",
    "orc": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_orc",
    "orcs": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_orc",
    "cyclops": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_cyclops",
    "cyclop": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_cyclops",
    "troll": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_troll",
    "trolls": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_troll",
    "mummy": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_mummy",
    "mummies": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_mummy",
    "halfling": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_halfling",
    "halflings": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_halfling",
    "sharpshooter": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_sharpshooter",
    "sharpshooters": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_sharpshooter",
    "zombie": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_walking_dead",
    "zombies": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_walking_dead",
    "monk": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_monk",
    "monks": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_monk",
    "pit fiend": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_pit_fiend",
    "pit fiends": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_pit_fiend",
    "centaur": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_centaur",
    "centaurs": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_centaur",
    "swordsman": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_swordsman",
    "swordsmen": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_swordsman",
    "lizardman": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_lizardman",
    "lizardmen": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_lizardman",
    "gnoll": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_gnoll",
    "gnolls": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_gnoll",
    "spy": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_vampire",
    "spies": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_vampire",
    "lieutenant": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_swordsman_upg",
    "lieutenants": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_swordsman_upg",
    "sentry": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_pikeman",
    "runner": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_archer",
    "leprechaun": f"{HOMM3_UNIT_DIALOG_PREFIX}h3_halfling",
    "maiden": "icons/dialogue/dialogue_unit_peasant",
    "maidens": "icons/dialogue/dialogue_unit_peasant",
    "shipwright": "icons/dialogue/dialogue_unit_peasant",
    "keeper": "icons/dialogue/dialogue_unit_peasant",
}
# Ambiguous civilian/tribal labels remapped from mission quoted-creature context.
_AMBIGUOUS_CONTEXT_ROLES = frozenset({"native", "natives", "fellow", "messenger"})
# Prefer these unit SIDs when remapping "natives"/tribal leaders in a mission.
_TRIBAL_CONTEXT_UNIT_PRIORITY = (
    "h3_goblin",
    "h3_goblin_upg",
    "h3_orc",
    "h3_orc_upg",
    "h3_gnoll",
    "h3_lizardman",
    "h3_lizardman_upg",
    "h3_troglodyte",
)
_ROLE_ALT = "|".join(
    sorted((re.escape(k) for k in VANILLA_ROLE_ICONS), key=len, reverse=True)
)
ROLE_MENTION_RE = re.compile(rf"\b(?P<who>{_ROLE_ALT})\b", re.I)
ROLE_PREP_ROLE_RE = re.compile(
    rf"\b(?:from|of|with)\s+the\s+(?:{_ROLE_ALT})\b",
    re.I,
)

# Text-name aliases → HoMM3 portrait display names in the manifest.
NAME_ALIASES: dict[str, str] = {
    "gurnis": "Gurnisson",
    "crag hack": "Crag Hack",
    "mister hack": "Crag Hack",
    "mr. hack": "Crag Hack",
    "mr hack": "Crag Hack",
    "queen catherine": "Catherine",
    "catherine ironfist": "Catherine",
    "catherine gryphonheart": "Catherine",
    "king roland": "Roland",
    "haart lich": "Haart Lich",
    "lord haart lich": "Haart Lich",
    "mutare the dragon": "Mutare Drake",
    "duke boragus": "Boragus",
}

# Letter / attributed-speech cues immediately before a quote.
LETTER_FROM_RE = re.compile(
    r"(?:from|message\s+from|letter\s+from|note\s+from|scroll\s+from|"
    r"orders?\s+from|reply\s+from|word\s+from)\s+"
    r"(?P<who>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})"
    r"(?:\s*[-–—:,]|\s+sends?\b|\s*$)",
    re.I | re.M,
)
SIGNED_BY_RE = re.compile(
    r"(?:--|—|–|signed[,:]?)\s*(?P<who>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\s*\.?$",
    re.I | re.M,
)
SENDS_MESSAGE_RE = re.compile(
    r"(?P<who>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\s+"
    r"sends?\s+(?:you\s+)?(?:a\s+|another\s+)?(?:message|letter|note|scroll)\b",
    re.I,
)


@dataclass
class SpeakerRef:
    label: str
    icon: str | None
    source: str  # homm3_hero | vanilla_role | player | unresolved
    hero_sid: str | None = None


@dataclass
class PlannedSlide:
    text: str
    speaker_label: str
    icon: str | None
    title_position: int = 1
    avatars: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DialogPortraitPlan:
    dialog_sid: str
    mission_id: str
    mode: str  # single | multi | none
    slides: list[PlannedSlide]
    required_homm3_icons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_NAME_TO_SID: dict[str, str] | None = None
_MISSION_PLAYER: dict[str, str] | None = None
_MISSION_QUOTED_UNITS: dict[str, list[str]] | None = None
_UNIT_DISPLAY_NAMES: dict[str, str] | None = None
_SPEAKER_OVERRIDE_DATA: dict[str, Any] | None = None
_MISSION_FACTION: dict[str, str] | None = None


def _load_speaker_overrides() -> dict[str, Any]:
    global _SPEAKER_OVERRIDE_DATA
    if _SPEAKER_OVERRIDE_DATA is not None:
        return _SPEAKER_OVERRIDE_DATA
    if not SPEAKER_OVERRIDES.is_file():
        _SPEAKER_OVERRIDE_DATA = {}
        return _SPEAKER_OVERRIDE_DATA
    data = json.loads(SPEAKER_OVERRIDES.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"speaker overrides must be an object: {SPEAKER_OVERRIDES}")
    _SPEAKER_OVERRIDE_DATA = data
    return _SPEAKER_OVERRIDE_DATA


def _load_mission_faction_map() -> dict[str, str]:
    """mission_id -> hub factionTag (castle/rampart/...)."""
    global _MISSION_FACTION
    if _MISSION_FACTION is not None:
        return _MISSION_FACTION
    out: dict[str, str] = {}
    if HUB_INDEX.is_file():
        data = json.loads(HUB_INDEX.read_text(encoding="utf-8"))
        for hub in data.get("hubs") or []:
            if not isinstance(hub, dict):
                continue
            tag = str(hub.get("factionTag") or "").strip().lower()
            if not tag:
                continue
            for mission in hub.get("missions") or []:
                out[str(mission)] = tag
    # RoE Castle continuity hubs not listed in AB/SoD hub_index.
    for mission in (
        "homecoming",
        "guardian_angels",
        "griffin_cliff",
        "steadwick_liberation",
    ):
        out.setdefault(mission, "castle")
    for mission in ("deal_with_the_devil", "a_devilish_plan", "groundbreaking"):
        out.setdefault(mission, "dungeon")
    for mission in (
        "season_of_harvest",
        "corporeal_punishment",
        "from_day_to_night",
        "poison_fit_for_a_king",
    ):
        out.setdefault(mission, "necropolis")
    for mission in ("safe_passage", "united_front", "for_king_and_country", "a_gryphons_heart"):
        out.setdefault(mission, "castle")
    for mission in ("neutral_affairs", "tunnels_and_troglodytes", "neutral_1a", "neutral_1b", "neutral_1c"):
        out.setdefault(mission, "castle")
    for mission in ("independence", "the_road_home", "the_grail", "to_build_a_tunnel", "kreegan_alliance", "with_blinders_on", "steadwicks_fall"):
        out.setdefault(mission, "castle")
    # Curated per-mission faction wins over hub packaging (AB/Final multi-hero hubs).
    overrides = _load_speaker_overrides().get("missionFactions") or {}
    if isinstance(overrides, dict):
        for mission_id, faction in overrides.items():
            tag = str(faction or "").strip().lower()
            if tag:
                out[str(mission_id)] = tag
    _MISSION_FACTION = out
    return out


def speaker_ref_from_override(spec: dict[str, Any] | None) -> SpeakerRef | None:
    """Build a SpeakerRef from a curated override row."""
    if not isinstance(spec, dict):
        return None
    kind = str(spec.get("kind") or "").strip().lower()
    label = str(spec.get("label") or "").strip()
    if kind == "none":
        return SpeakerRef(label="", icon=None, source="unresolved")
    if kind == "hero":
        sid = str(spec.get("sid") or "").strip()
        if not sid:
            return None
        return SpeakerRef(
            label=label or hero_sid_display_name(sid),
            icon=hero_sid_to_dialog_icon(sid),
            source="homm3_hero",
            hero_sid=sid,
        )
    if kind == "unit":
        sid = str(spec.get("sid") or "").strip()
        if not sid.startswith("h3_"):
            return None
        return SpeakerRef(
            label=label or unit_sid_display_name(sid),
            icon=unit_sid_to_dialog_icon(sid),
            source="vanilla_role",
        )
    if kind == "vanilla":
        icon = str(spec.get("icon") or "").strip() or None
        return SpeakerRef(
            label=label or "Speaker",
            icon=icon,
            source="vanilla_role",
        )
    return None


def dialog_override_spec(dialog_sid: str) -> dict[str, Any] | None:
    data = _load_speaker_overrides()
    dialogs = data.get("dialogs") or {}
    if not isinstance(dialogs, dict):
        return None
    row = dialogs.get(str(dialog_sid or ""))
    return row if isinstance(row, dict) else None


def npc_alias_ref(raw_name: str) -> SpeakerRef | None:
    data = _load_speaker_overrides()
    aliases = data.get("npcAliases") or {}
    if not isinstance(aliases, dict):
        return None
    key = str(raw_name or "").strip().lower()
    if key in aliases and isinstance(aliases[key], dict):
        return speaker_ref_from_override(aliases[key])
    # Try dropping honorifics.
    for prefix in ("king ", "queen ", "lord ", "duke ", "general ", "sir ", "house "):
        if key.startswith(prefix):
            leaf = key[len(prefix) :]
            if leaf in aliases and isinstance(aliases[leaf], dict):
                return speaker_ref_from_override(aliases[leaf])
    return None


def faction_role_unit_sid(role: str, *, mission_id: str | None) -> str | None:
    data = _load_speaker_overrides()
    roles_by_faction = data.get("factionRoleUnits") or {}
    if not isinstance(roles_by_faction, dict):
        return None
    faction = _load_mission_faction_map().get(str(mission_id or ""), "")
    if not faction:
        return None
    table = roles_by_faction.get(faction) or {}
    if not isinstance(table, dict):
        return None
    sid = table.get(str(role or "").strip().lower())
    return str(sid).strip() if sid else None


def _apply_mission_protagonist_overrides(out: dict[str, str]) -> None:
    data = _load_speaker_overrides()
    overrides = data.get("missionProtagonists") or {}
    if not isinstance(overrides, dict):
        return
    for mission_id, hero_sid in overrides.items():
        sid = str(hero_sid or "").strip()
        if sid:
            out[str(mission_id)] = sid


def unit_sid_to_dialog_icon(unit_sid: str) -> str:
    """h3_goblin -> icons/dialogue/dialogue_unit_h3_goblin"""
    sid = str(unit_sid or "").strip()
    if not sid.startswith("h3_"):
        raise ValueError(f"expected h3_* unit sid; got {unit_sid!r}")
    return f"{HOMM3_UNIT_DIALOG_PREFIX}{sid}"


def unit_sid_display_name(unit_sid: str) -> str:
    names = _load_unit_display_names()
    sid = str(unit_sid or "").strip()
    if sid in names:
        return names[sid]
    # h3_goblin_upg -> Goblin Upg fallback; prefer explicit role labels at call site.
    leaf = sid[len("h3_") :].replace("_", " ").strip()
    return leaf.title() if leaf else sid


def _load_unit_display_names() -> dict[str, str]:
    global _UNIT_DISPLAY_NAMES
    if _UNIT_DISPLAY_NAMES is not None:
        return _UNIT_DISPLAY_NAMES
    out: dict[str, str] = {
        "h3_goblin": "Goblin",
        "h3_goblin_upg": "Hobgoblin",
        "h3_orc": "Orc",
        "h3_orc_upg": "Orc",
        "h3_cyclops": "Cyclops",
        "h3_troll": "Troll",
        "h3_mummy": "Mummy",
        "h3_halfling": "Halfling",
        "h3_sharpshooter": "Sharpshooter",
    }
    if QUOTED_CREATURES.is_file():
        data = json.loads(QUOTED_CREATURES.read_text(encoding="utf-8"))
        for row in data.get("creatures") or []:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("sid") or "").strip()
            name = str(row.get("name") or "").strip()
            if sid and name and sid not in out:
                out[sid] = name
    _UNIT_DISPLAY_NAMES = out
    return out


def _load_mission_quoted_units() -> dict[str, list[str]]:
    global _MISSION_QUOTED_UNITS
    if _MISSION_QUOTED_UNITS is not None:
        return _MISSION_QUOTED_UNITS
    out: dict[str, list[str]] = {}
    if QUOTED_CREATURES.is_file():
        data = json.loads(QUOTED_CREATURES.read_text(encoding="utf-8"))
        for row in data.get("creatures") or []:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("sid") or "").strip()
            if not sid:
                continue
            for mission in row.get("missions") or []:
                mid = str(mission or "").strip()
                if not mid:
                    continue
                out.setdefault(mid, [])
                if sid not in out[mid]:
                    out[mid].append(sid)
    _MISSION_QUOTED_UNITS = out
    return out


def mission_context_unit_sid(mission_id: str) -> str | None:
    """Best tribal/creature speaker SID for ambiguous native/fellow roles."""
    units = _load_mission_quoted_units().get(str(mission_id or ""), [])
    if not units:
        return None
    for preferred in _TRIBAL_CONTEXT_UNIT_PRIORITY:
        if preferred in units:
            return preferred
    return units[0]


def _resolve_ambiguous_role(role: str, *, mission_id: str | None) -> SpeakerRef | None:
    key = str(role or "").strip().lower()
    if key not in _AMBIGUOUS_CONTEXT_ROLES:
        return None
    unit_sid = mission_context_unit_sid(str(mission_id or ""))
    if unit_sid is None:
        # No mission creature context — messenger/peasant fallback; natives stay unlabeled.
        if key == "messenger":
            return SpeakerRef(
                label="Messenger",
                icon="icons/dialogue/dialogue_unit_peasant",
                source="vanilla_role",
            )
        return SpeakerRef(label=key.title(), icon=None, source="vanilla_role")
    label = {
        "native": unit_sid_display_name(unit_sid),
        "natives": unit_sid_display_name(unit_sid),
        "fellow": unit_sid_display_name(unit_sid),
        "messenger": "Messenger",
    }.get(key, unit_sid_display_name(unit_sid))
    return SpeakerRef(
        label=label,
        icon=unit_sid_to_dialog_icon(unit_sid),
        source="vanilla_role",
    )


def _load_homm3_name_map() -> dict[str, str]:
    global _NAME_TO_SID
    if _NAME_TO_SID is not None:
        return _NAME_TO_SID
    data = json.loads(HOMM3_MANIFEST.read_text(encoding="utf-8"))
    entries = data.get("entries") or {}
    out: dict[str, str] = {}
    for sid, row in entries.items():
        name = str((row or {}).get("name") or "").strip()
        if name:
            out[name.lower()] = sid
    # Aliases that point at real names
    for alias, canon in NAME_ALIASES.items():
        sid = out.get(canon.lower())
        if sid:
            out[alias.lower()] = sid
    _NAME_TO_SID = out
    return out


def _load_mission_player_map() -> dict[str, str]:
    global _MISSION_PLAYER
    if _MISSION_PLAYER is not None:
        return _MISSION_PLAYER
    data = json.loads(HUB_INDEX.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for hub in data.get("hubs") or []:
        hero = str(hub.get("heroSid") or "").strip()
        if not hero:
            continue
        for mission in hub.get("missions") or []:
            out[str(mission)] = hero
    # Continuity installer hubs are authoritative for RoE + AB/SoD campaignHeroSid,
    # including missions absent from ab_sod hub_index (e.g. homecoming).
    installer = REPO / "tools" / "install_roe_castle_continuity_weave.py"
    if installer.is_file():
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "install_roe_castle_continuity_weave", installer
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load continuity installer for dialog protagonists: {installer}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        hubs = getattr(mod, "HUB_CONFIGS", None)
        if not isinstance(hubs, dict) or not hubs:
            raise RuntimeError(f"{installer} missing HUB_CONFIGS")
        for hub in hubs.values():
            if not isinstance(hub, dict):
                continue
            hero = str(hub.get("campaignHeroSid") or "").strip()
            if not hero:
                continue
            for row in hub.get("mapInstalls") or []:
                if not isinstance(row, dict):
                    continue
                overlay = Path(str(row.get("coreOverlay") or ""))
                parts = overlay.parts
                if "raw_translation_map" not in parts:
                    continue
                mission_id = parts[parts.index("raw_translation_map") - 1]
                if mission_id == "homecoming_poc":
                    mission_id = "homecoming"
                out[str(mission_id)] = hero
    _apply_mission_protagonist_overrides(out)
    _MISSION_PLAYER = out
    return out


def mission_protagonist_icon(mission_id: str) -> tuple[str, str] | None:
    """Return (display_name, dialog_icon) for the campaign protagonist, if known."""
    player_sid = _load_mission_player_map().get(str(mission_id or ""))
    if not player_sid:
        return None
    return hero_sid_display_name(player_sid), hero_sid_to_dialog_icon(player_sid)


def _is_custom_dialog_icon(icon: str | None) -> bool:
    if not icon:
        return False
    return "dialogue_hero_homm3_" in icon or icon.startswith(HOMM3_UNIT_DIALOG_PREFIX + "h3_")


def hero_sid_to_dialog_icon(hero_sid: str) -> str:
    """homm3_stronghold_hero_2 -> icons/dialogue/dialogue_hero_homm3_stronghold_2"""
    sid = str(hero_sid or "").strip()
    if not sid.startswith("homm3_") or "_hero_" not in sid:
        raise ValueError(f"expected homm3_<faction>_hero_N sid; got {hero_sid!r}")
    rest = sid[len("homm3_") :]
    faction, _, num = rest.partition("_hero_")
    if not faction or not num:
        raise ValueError(f"cannot parse hero sid for dialog icon: {hero_sid!r}")
    return f"icons/dialogue/dialogue_hero_homm3_{faction}_{num}"


def hero_sid_display_name(hero_sid: str) -> str:
    names = {v: k for k, v in _load_homm3_name_map().items()}
    # prefer canonical casing from manifest values
    data = json.loads(HOMM3_MANIFEST.read_text(encoding="utf-8"))
    row = (data.get("entries") or {}).get(hero_sid) or {}
    name = str(row.get("name") or "").strip()
    return name or hero_sid


def resolve_named_speaker(raw_name: str, *, mission_id: str | None = None) -> SpeakerRef:
    name = str(raw_name or "").strip()
    if not name:
        return SpeakerRef(label="Unknown", icon=None, source="unresolved")
    key = name.lower()
    if key in ("you", "player"):
        player_sid = _load_mission_player_map().get(str(mission_id or ""))
        if player_sid:
            return SpeakerRef(
                label=hero_sid_display_name(player_sid),
                icon=hero_sid_to_dialog_icon(player_sid),
                source="player",
                hero_sid=player_sid,
            )
        return SpeakerRef(label="You", icon=None, source="unresolved")

    # Curated NPC aliases (Lucifer→devil, Tralossk→lizardman, Xex→demon, …).
    alias = npc_alias_ref(name)
    if alias is not None:
        return alias

    homm3 = _load_homm3_name_map()
    if key in homm3:
        sid = homm3[key]
        return SpeakerRef(
            label=hero_sid_display_name(sid),
            icon=hero_sid_to_dialog_icon(sid),
            source="homm3_hero",
            hero_sid=sid,
        )

    # Role keywords inside longer labels ("stout dwarf" won't match; "The Lich" will)
    for role, icon in VANILLA_ROLE_ICONS.items():
        if key == role or key.endswith(" " + role) or key.startswith(role + " "):
            if role in _AMBIGUOUS_CONTEXT_ROLES:
                ambiguous = _resolve_ambiguous_role(role, mission_id=mission_id)
                if ambiguous is not None:
                    if name and name[0].isupper() and ambiguous.label:
                        # Keep explicit capitalized cue text when useful ("Messenger").
                        if role == "messenger":
                            return ambiguous
                    return ambiguous
            # Prefer campaign-faction unit portraits when every unit art is available.
            faction_unit = faction_role_unit_sid(role, mission_id=mission_id)
            if faction_unit:
                label = name if name and name[0].isupper() else unit_sid_display_name(faction_unit)
                if role in ("goblin", "goblins"):
                    label = "Goblin" if role == "goblin" else "Goblins"
                elif role in ("hobgoblin", "hobgoblins"):
                    label = "Hobgoblin" if role == "hobgoblin" else "Hobgoblins"
                elif role in ("scout", "scouts", "guard", "guards", "troop", "troops",
                              "advisor", "advisors", "messenger", "mercenary", "mercenaries",
                              "captain"):
                    label = role.title()
                return SpeakerRef(
                    label=label,
                    icon=unit_sid_to_dialog_icon(faction_unit),
                    source="vanilla_role",
                )
            label = name if name and name[0].isupper() else role.title()
            if role in ("goblin", "goblins"):
                label = "Goblin" if role == "goblin" else "Goblins"
            elif role in ("hobgoblin", "hobgoblins"):
                label = "Hobgoblin" if role == "hobgoblin" else "Hobgoblins"
            return SpeakerRef(label=label, icon=icon, source="vanilla_role")

    return SpeakerRef(label=name, icon=None, source="unresolved")


def _role_speaker_in_span(span: str, *, mission_id: str | None = None) -> SpeakerRef | None:
    """Best NPC role noun in span, if that role is in VANILLA_ROLE_ICONS."""
    matches = list(ROLE_MENTION_RE.finditer(span or ""))
    if not matches:
        return None
    # Prefer the grammatical subject: drop "from/of/with the <role>" qualifiers.
    cleaned = ROLE_PREP_ROLE_RE.sub(" ", span or "")
    cleaned_matches = list(ROLE_MENTION_RE.finditer(cleaned))
    who = (cleaned_matches[-1] if cleaned_matches else matches[-1]).group("who")
    return resolve_named_speaker(who, mission_id=mission_id)


def _quote_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for m in QUOTE_RE.finditer(text):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        if body is None or len(body.strip()) < 2:
            continue
        spans.append((m.start(), m.end(), body))
    return spans


def _speaker_for_quote(
    text: str,
    quote_start: int,
    quote_end: int,
    quote_body: str,
    *,
    mission_id: str,
    known_speakers: list[SpeakerRef],
    quote_index: int,
    previous: SpeakerRef | None = None,
    previous_quote_end: int | None = None,
) -> SpeakerRef:
    before = text[max(0, quote_start - 160) : quote_start]
    after = text[quote_end : min(len(text), quote_end + 80)]
    intervening_start = previous_quote_end if previous_quote_end is not None else max(0, quote_start - 160)
    intervening = text[intervening_start:quote_start]

    # `"...", says Sandro`
    m_after = SAYS_AFTER_RE.match(after)
    if m_after:
        return resolve_named_speaker(m_after.group("who"), mission_id=mission_id)

    # `Sandro says "..."` (name immediately before quote)
    m_before_says = SAYS_BEFORE_RE.search(before)
    if m_before_says:
        return resolve_named_speaker(m_before_says.group("who"), mission_id=mission_id)

    # Letter / attributed speech: "From Catherine:", "message from Jeddite", "Boragus sends a message"
    m_letter = LETTER_FROM_RE.search(before)
    if m_letter and m_letter.end() >= len(before) - 48:
        return resolve_named_speaker(m_letter.group("who"), mission_id=mission_id)
    m_sends = SENDS_MESSAGE_RE.search(before)
    if m_sends and m_sends.end() >= len(before) - 64:
        return resolve_named_speaker(m_sends.group("who"), mission_id=mission_id)
    m_signed = SIGNED_BY_RE.search(after) or SIGNED_BY_RE.search(
        text[quote_end : min(len(text), quote_end + 120)]
    )
    if m_signed:
        return resolve_named_speaker(m_signed.group("who"), mission_id=mission_id)

    you = YOU_CUE_RE.search(before)
    if you and you.end() >= len(before) - 40:
        return resolve_named_speaker("you", mission_id=mission_id)
    you_after = YOU_CUE_RE.match(re.sub(r"^[,\s]+", "", after))
    if you_after:
        return resolve_named_speaker("you", mission_id=mission_id)

    cues = list(SPEAKER_CUE_RE.finditer(before))
    if cues:
        who = cues[-1].group("who")
        if who.lower() not in {"the", "a", "an", "as", "he", "she", "it", "this", "that", "then"}:
            return resolve_named_speaker(who, mission_id=mission_id)

    # "the jolly old fellow … says;" / "goblins … begin singing"
    if ROLE_SPEECH_TAIL_RE.search(before):
        m_tail = ROLE_SPEECH_TAIL_RE.search(before)
        assert m_tail is not None
        window = before[max(0, m_tail.start() - 120) : m_tail.start()]
        role = _role_speaker_in_span(window, mission_id=mission_id) or _role_speaker_in_span(
            before, mission_id=mission_id
        )
        if role is not None:
            return role

    iam = I_AM_RE.search(quote_body)
    if iam:
        return resolve_named_speaker(iam.group("name"), mission_id=mission_id)

    # Narration between quotes often re-introduces the next speaker ("Sandro's eyes narrow.")
    # Ignore possessives like "Sandro's hands" — those are not speaking cues.
    # Do NOT treat second-person narration ("You are confronted…") as the speaker.
    mentioned: list[tuple[int, SpeakerRef]] = []
    for speaker in known_speakers:
        if not speaker.icon and speaker.source != "vanilla_role":
            continue
        for m in re.finditer(re.escape(speaker.label), intervening, re.I):
            if intervening[m.end() : m.end() + 2].startswith("'s") or intervening[
                m.end() : m.end() + 1
            ] == "’":
                continue
            mentioned.append((m.start(), speaker))
        first = speaker.label.split()[0]
        if len(first) >= 4:
            for m in re.finditer(rf"\b{re.escape(first)}\b", intervening, re.I):
                if intervening[m.end() : m.end() + 2].startswith("'s") or intervening[
                    m.end() : m.end() + 1
                ] in ("'", "’"):
                    # Sandro's / Name'
                    tail = intervening[m.end() : m.end() + 3]
                    if tail.startswith("'s") or tail.startswith("’s"):
                        continue
                mentioned.append((m.start(), speaker))
    for m in YOU_CUE_RE.finditer(intervening):
        player = resolve_named_speaker("you", mission_id=mission_id)
        if player.icon:
            mentioned.append((m.start(), player))
    role_in_intervening = _role_speaker_in_span(intervening, mission_id=mission_id)
    if role_in_intervening is not None and ROLE_SPEECH_TAIL_RE.search(intervening):
        # Prefer the role nearest the quote when narration names an NPC group.
        mentioned.append((len(intervening), role_in_intervening))
    if mentioned:
        mentioned.sort(key=lambda item: item[0])
        return mentioned[-1][1]

    # Last resort for song/shout quotes: role noun anywhere in the local before-span.
    role = _role_speaker_in_span(before, mission_id=mission_id)
    if role is not None and re.search(
        r"\b(?:sing|song|holler|yell|shout|say|said|surround|confront)\b",
        before,
        re.I,
    ):
        return role

    # Otherwise alternate between the two known voices when available.
    resolvable = [s for s in known_speakers if s.icon]
    if previous is not None and previous.icon and len(resolvable) == 2:
        for s in resolvable:
            if s.icon != previous.icon:
                return s
    if len(resolvable) == 2:
        return resolvable[quote_index % 2]
    if previous is not None and previous.icon:
        return previous
    if len(resolvable) == 1:
        return resolvable[0]
    return SpeakerRef(label="Unknown", icon=None, source="unresolved")


def _discover_known_speakers(text: str, mission_id: str) -> list[SpeakerRef]:
    found: dict[str, SpeakerRef] = {}
    for m in SPEAKER_CUE_RE.finditer(text):
        who = m.group("who")
        ref = resolve_named_speaker(who, mission_id=mission_id)
        if ref.icon or ref.source == "vanilla_role":
            found[ref.label.lower()] = ref
    for m in re.finditer(
        rf"\bsays?\s+(?P<who>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){{0,3}})\b",
        text,
    ):
        ref = resolve_named_speaker(m.group("who"), mission_id=mission_id)
        if ref.icon or ref.source == "vanilla_role":
            found[ref.label.lower()] = ref
    for m in ROLE_MENTION_RE.finditer(text):
        ref = resolve_named_speaker(m.group("who"), mission_id=mission_id)
        if ref.source == "vanilla_role":
            found[ref.label.lower()] = ref
    if YOU_CUE_RE.search(text):
        ref = resolve_named_speaker("you", mission_id=mission_id)
        if ref.icon:
            found[ref.label.lower()] = ref
    for m in I_AM_RE.finditer(text):
        ref = resolve_named_speaker(m.group("name"), mission_id=mission_id)
        if ref.icon or ref.source == "vanilla_role":
            found[ref.label.lower()] = ref
    return list(found.values())


def _avatar(
    icon: str,
    *,
    position: int,
    foreground: bool,
) -> dict[str, Any]:
    return {
        "position": position,
        "icon": icon,
        "isForeground": "true" if foreground else "false",
        "animations": ["zoomIn" if foreground else "zoomOut"],
    }


def _pair_avatars(
    active: SpeakerRef,
    partner: SpeakerRef | None,
    *,
    left_icon: str | None,
    right_icon: str | None,
) -> tuple[list[dict[str, Any]], int, str | None, str | None]:
    """Build OE two-portrait row; remember left/right icons across slides."""
    if not active.icon:
        return [], 3, left_icon, right_icon
    if partner is None or not partner.icon or partner.icon == active.icon:
        return [_avatar(active.icon, position=1, foreground=True)], 1, active.icon, right_icon

    if left_icon is None:
        left_icon = active.icon
        right_icon = partner.icon
    elif active.icon not in (left_icon, right_icon):
        left_icon = active.icon
        right_icon = partner.icon
    elif partner.icon not in (left_icon, right_icon):
        if active.icon == left_icon:
            right_icon = partner.icon
        else:
            left_icon = partner.icon

    avatars = [
        _avatar(left_icon, position=1, foreground=active.icon == left_icon),
        _avatar(right_icon, position=5, foreground=active.icon == right_icon),
    ]
    title_pos = 1 if active.icon == left_icon else 2
    return avatars, title_pos, left_icon, right_icon


def _plan_from_quote_overrides(
    *,
    dialog_sid: str,
    mission_id: str,
    body: str,
    spans: list[tuple[int, int, str]],
    quote_specs: list[Any],
    notes: list[str],
) -> DialogPortraitPlan:
    """Partition body by quotes and attach curated speakers per quote index."""
    boundaries = [0] + [spans[i][0] for i in range(1, len(spans))] + [len(body)]
    resolved: list[tuple[str, SpeakerRef]] = []
    for i, (_start, _end, _qbody) in enumerate(spans):
        chunk = body[boundaries[i] : boundaries[i + 1]]
        spec = quote_specs[i] if i < len(quote_specs) else quote_specs[-1]
        speaker = speaker_ref_from_override(spec if isinstance(spec, dict) else None)
        if speaker is None or not speaker.icon:
            speaker = SpeakerRef(label="Unknown", icon=None, source="unresolved")
            notes.append(f"curated quote {i} missing icon")
        resolved.append((chunk, speaker))

    speaking_icons = {s.icon for _, s in resolved if s.icon}
    left_icon: str | None = None
    right_icon: str | None = None
    slides: list[PlannedSlide] = []
    required: set[str] = set()
    for chunk, speaker in resolved:
        partner = None
        if speaker.icon and len(speaking_icons) >= 2:
            for _, other in resolved:
                if other.icon and other.icon != speaker.icon:
                    partner = other
                    break
        avatars, title_pos, left_icon, right_icon = _pair_avatars(
            speaker, partner, left_icon=left_icon, right_icon=right_icon
        )
        if _is_custom_dialog_icon(speaker.icon):
            required.add(speaker.icon)
        if partner and _is_custom_dialog_icon(partner.icon):
            required.add(partner.icon)
        slides.append(
            PlannedSlide(
                text=chunk,
                speaker_label=(
                    speaker.label
                    if speaker.icon or speaker.source == "vanilla_role"
                    else ""
                ),
                icon=speaker.icon,
                title_position=title_pos,
                avatars=avatars,
            )
        )
    joined = "".join(s.text for s in slides)
    if joined != body:
        notes.append("curated quote partition mismatch; falling back")
        return _portraitless(dialog_sid, mission_id, body, None, notes)
    resolvable = sum(1 for s in slides if s.icon)
    if resolvable == 0:
        return _portraitless(dialog_sid, mission_id, body, None, notes)
    # Single curated voice across many scare/quote spans: one slide, full body.
    if len(speaking_icons) == 1 and len(quote_specs) == 1:
        speaker = next(s for s in slides if s.icon)
        return DialogPortraitPlan(
            dialog_sid=dialog_sid,
            mission_id=mission_id,
            mode="single",
            slides=[
                PlannedSlide(
                    text=body,
                    speaker_label=speaker.speaker_label,
                    icon=speaker.icon,
                    title_position=1,
                    avatars=[_avatar(speaker.icon, position=1, foreground=True)],
                )
            ],
            required_homm3_icons=sorted(required),
            notes=notes,
        )
    mode = "multi" if len(speaking_icons) >= 2 else "single"
    return DialogPortraitPlan(
        dialog_sid=dialog_sid,
        mission_id=mission_id,
        mode=mode,
        slides=slides,
        required_homm3_icons=sorted(required),
        notes=notes,
    )


def plan_dialog_portraits(
    *,
    dialog_sid: str,
    mission_id: str,
    text: str,
    existing_avatars: list[dict[str, Any]] | None = None,
    existing_title: str | None = None,
) -> DialogPortraitPlan:
    """Plan slides for one dialog body. Preserves full original text across slides."""
    body = str(text or "")
    notes: list[str] = []
    if not body.strip():
        return DialogPortraitPlan(dialog_sid, mission_id, "none", [], notes=["empty text"])

    # Honor pre-bound colocated avatar (e.g. Gurnisson EVENT) as single-speaker default.
    preexisting = existing_avatars if isinstance(existing_avatars, list) else []
    preexisting_icon = None
    if preexisting and isinstance(preexisting[0], dict):
        preexisting_icon = str(preexisting[0].get("icon") or "").strip() or None

    spans = _quote_spans(body)
    override = dialog_override_spec(dialog_sid)

    # Explicit curated none (scare-quotes / non-speech).
    if override and str(override.get("kind") or "").lower() == "none":
        return _portraitless(
            dialog_sid, mission_id, body, existing_title, notes + ["curated none"]
        )

    # Per-quote curated speakers (multi or single).
    quote_specs = override.get("quoteSpeakers") if isinstance(override, dict) else None
    if isinstance(quote_specs, list) and spans and len(quote_specs) > 0:
        return _plan_from_quote_overrides(
            dialog_sid=dialog_sid,
            mission_id=mission_id,
            body=body,
            spans=spans,
            quote_specs=quote_specs,
            notes=notes + ["curated quoteSpeakers"],
        )

    # Whole-dialog curated single speaker.
    if isinstance(override, dict) and override.get("kind") and "quoteSpeakers" not in override:
        curated = speaker_ref_from_override(override)
        if curated is not None and curated.icon:
            required = [curated.icon] if _is_custom_dialog_icon(curated.icon) else []
            return DialogPortraitPlan(
                dialog_sid=dialog_sid,
                mission_id=mission_id,
                mode="single",
                slides=[
                    PlannedSlide(
                        text=body,
                        speaker_label=curated.label,
                        icon=curated.icon,
                        title_position=1,
                        avatars=[_avatar(curated.icon, position=1, foreground=True)],
                    )
                ],
                required_homm3_icons=required,
                notes=notes + ["curated dialog speaker"],
            )

    known = _discover_known_speakers(body, mission_id)

    if len(spans) >= 2:
        required: set[str] = set()
        prev_speaker: SpeakerRef | None = None
        prev_quote_end: int | None = None
        # Non-overlapping partition: [0, q1_start), [q1_start, q2_start), ..., [qN_start, EOF)
        boundaries = [0] + [spans[i][0] for i in range(1, len(spans))] + [len(body)]
        resolved: list[tuple[str, SpeakerRef]] = []
        for i, (start, end, qbody) in enumerate(spans):
            chunk = body[boundaries[i] : boundaries[i + 1]]
            speaker = _speaker_for_quote(
                body,
                start,
                end,
                qbody,
                mission_id=mission_id,
                known_speakers=known,
                quote_index=i,
                previous=prev_speaker,
                previous_quote_end=prev_quote_end,
            )
            if speaker.icon:
                prev_speaker = speaker
            prev_quote_end = end
            if not speaker.icon:
                notes.append(f"unresolved speaker on quote {i}: {speaker.label!r}")
            resolved.append((chunk, speaker))

        # Only dual-portrait against speakers who actually have a quote turn.
        speaking_icons = {s.icon for _, s in resolved if s.icon}
        left_icon: str | None = None
        right_icon: str | None = None
        slides: list[PlannedSlide] = []
        for chunk, speaker in resolved:
            partner = None
            if speaker.icon and len(speaking_icons) >= 2:
                for _, other in resolved:
                    if other.icon and other.icon != speaker.icon:
                        partner = other
                        break
            avatars, title_pos, left_icon, right_icon = _pair_avatars(
                speaker, partner, left_icon=left_icon, right_icon=right_icon
            )
            if _is_custom_dialog_icon(speaker.icon):
                required.add(speaker.icon)
            if partner and _is_custom_dialog_icon(partner.icon):
                required.add(partner.icon)
            slides.append(
                PlannedSlide(
                    text=chunk,
                    speaker_label=(
                        speaker.label
                        if speaker.icon or speaker.source == "vanilla_role"
                        else ""
                    ),
                    icon=speaker.icon,
                    title_position=title_pos,
                    avatars=avatars,
                )
            )
        joined = "".join(s.text for s in slides)
        if joined != body:
            notes.append("partition mismatch; falling back to single slide")
            return _single_fallback(
                dialog_sid, mission_id, body, preexisting_icon, existing_title, notes
            )
        resolvable_slides = sum(1 for s in slides if s.icon)
        if resolvable_slides == 0:
            return _single_fallback(
                dialog_sid, mission_id, body, preexisting_icon, existing_title, notes
            )
        mode = "multi" if resolvable_slides >= 2 else "single"
        return DialogPortraitPlan(
            dialog_sid=dialog_sid,
            mission_id=mission_id,
            mode=mode,
            slides=slides,
            required_homm3_icons=sorted(required),
            notes=notes,
        )

    # Single-quote or no-quote
    if len(spans) == 1:
        start, end, qbody = spans[0]
        speaker = _speaker_for_quote(
            body,
            start,
            end,
            qbody,
            mission_id=mission_id,
            known_speakers=known,
            quote_index=0,
        )
        if not speaker.icon and preexisting_icon:
            speaker = SpeakerRef(
                label=str(existing_title or "Speaker"),
                icon=preexisting_icon,
                source="homm3_hero",
            )
        if speaker.icon:
            required = []
            if _is_custom_dialog_icon(speaker.icon):
                required.append(speaker.icon)
            return DialogPortraitPlan(
                dialog_sid=dialog_sid,
                mission_id=mission_id,
                mode="single",
                slides=[
                    PlannedSlide(
                        text=body,
                        speaker_label=speaker.label,
                        icon=speaker.icon,
                        title_position=1,
                        avatars=[_avatar(speaker.icon, position=1, foreground=True)],
                    )
                ],
                required_homm3_icons=required,
                notes=notes,
            )
        if speaker.source == "vanilla_role":
            notes.append(f"role speaker {speaker.label!r} has no dialogue icon")
            return DialogPortraitPlan(
                dialog_sid=dialog_sid,
                mission_id=mission_id,
                mode="none",
                slides=[
                    PlannedSlide(
                        text=body,
                        speaker_label=speaker.label,
                        icon=None,
                    )
                ],
                notes=notes,
            )

    if preexisting_icon:
        return DialogPortraitPlan(
            dialog_sid=dialog_sid,
            mission_id=mission_id,
            mode="single",
            slides=[
                PlannedSlide(
                    text=body,
                    speaker_label=str(existing_title or "Speaker"),
                    icon=preexisting_icon,
                    title_position=1,
                    avatars=[_avatar(preexisting_icon, position=1, foreground=True)],
                )
            ],
            required_homm3_icons=(
                [preexisting_icon] if _is_custom_dialog_icon(preexisting_icon) else []
            ),
            notes=notes,
        )

    return _portraitless(
        dialog_sid, mission_id, body, existing_title, notes + ["no portrait match"]
    )


def _portraitless(
    dialog_sid: str,
    mission_id: str,
    body: str,
    existing_title: str | None,
    notes: list[str],
) -> DialogPortraitPlan:
    """Narration / unresolved speech stays portrait-less (never protagonist by default)."""
    del existing_title  # never reuse mission/day titles as speaker names
    return DialogPortraitPlan(
        dialog_sid=dialog_sid,
        mission_id=mission_id,
        mode="none",
        slides=[
            PlannedSlide(
                text=body,
                speaker_label="",
                icon=None,
            )
        ],
        notes=notes + ["left portraitless; no resolvable speaker"],
    )


def _single_fallback(
    dialog_sid: str,
    mission_id: str,
    body: str,
    preexisting_icon: str | None,
    existing_title: str | None,
    notes: list[str],
) -> DialogPortraitPlan:
    if preexisting_icon:
        return DialogPortraitPlan(
            dialog_sid=dialog_sid,
            mission_id=mission_id,
            mode="single",
            slides=[
                PlannedSlide(
                    text=body,
                    speaker_label=str(existing_title or "Speaker"),
                    icon=preexisting_icon,
                    title_position=1,
                    avatars=[_avatar(preexisting_icon, position=1, foreground=True)],
                )
            ],
            required_homm3_icons=(
                [preexisting_icon]
                if (
                    "dialogue_hero_homm3_" in preexisting_icon
                    or preexisting_icon.startswith(HOMM3_UNIT_DIALOG_PREFIX + "h3_")
                )
                else []
            ),
            notes=notes,
        )
    return _portraitless(dialog_sid, mission_id, body, existing_title, notes)


def apply_plan_to_dialog_entry(entry: dict[str, Any], plan: DialogPortraitPlan) -> dict[str, Any]:
    """Attach plan fields onto a core_dialog_entries_from_alignment entry."""
    out = dict(entry)
    if plan.mode == "none" or not plan.slides:
        # Clear leftover mission/day/protagonist titles; keep role label when known.
        slide = plan.slides[0] if plan.slides else None
        out["title"] = (slide.speaker_label if slide else "") or ""
        out.pop("avatars", None)
        out.pop("titlePosition", None)
        out.pop("slides", None)
        return out
    if plan.mode == "single":
        # Prefer the first slide that actually carries avatars. Multi-quote plans can
        # be classified single when only one speaker resolved; slide 0 may be empty.
        slide = next((s for s in plan.slides if s.avatars), plan.slides[0])
        if slide.avatars:
            out["avatars"] = slide.avatars
            out["title"] = slide.speaker_label or ""
            out["titlePosition"] = slide.title_position
            # Keep full original body for single-portrait emit (not just quote chunk).
            out["text"] = "".join(s.text for s in plan.slides) if len(plan.slides) > 1 else slide.text
        else:
            out["title"] = slide.speaker_label or ""
            out.pop("avatars", None)
        return out
    # multi
    out["slides"] = [
        {
            "text": s.text,
            "title": s.speaker_label or "",
            "titlePosition": s.title_position,
            "avatars": s.avatars,
        }
        for s in plan.slides
    ]
    # Keep legacy text as full body for any consumer still reading entry["text"]
    out["text"] = "".join(s.text for s in plan.slides)
    # Avoid leaving a stale single-title from the entry seed (mission name / Day N).
    out["title"] = out["slides"][0]["title"] if out["slides"] else ""
    return out
