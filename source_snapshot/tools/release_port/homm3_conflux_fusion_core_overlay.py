"""Core rows for the Conflux Elemental Fusion faction skill (user design 2026-11-15).

Inputs: custom_factions/conflux_fusion/fusion_config.json (the contract the plugin runtime reads) and
custom_factions/conflux_fusion/fusion_units.json (names, squad values, mesh override field and the
signature spec of each of the 105 fused units).

Rows:

- the Elemental Fusion world spell: a clone of the native Necromancer Will row (change_use_necromancy)
  with parameters [mode], no mana cost and no usage limit (usageLimit -1, the native unlimited value); the plugin runtime intercepts the cast and
  opens the fusion picker. Every rank of skill_faction_homm3_conflux grants it (heroMagicAddition);
- the six Advanced/Expert subskills of the skill (SIDs kept for save compatibility);
- 105 fused unit logic/view rows in DB/units/units_*/homm3_conflux/h3_fusion_<host>_<guest>_*.json, then
  37 stage-2 rows h3_fusion_ii_<slug> (fusion_config.json recipes; fusion_units.json stage2): the same stat rule
  applied to the two stage-1 parents, host parent's attack shape, and only the unit's own signature parts as kit.
  They have no dwelling, no upgrade/base links and are never pooled, rewarded or recruited.

Fused unit rules (stats are re-derived from the final parent rows after the balance contract):
HP = sum; damage min/max = round(0.9 x sum); Attack/Defense = higher parent + 1; Initiative/Speed/
movement = the faster parent's; attacks, attack shape and ai = the host's. Kit = both parents' actives
and passives, unless a signature replaces both parents' actives (kind active) or passives (kind passive).
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
FUSION_DIR = REPO_ROOT / "custom_factions" / "conflux_fusion"
CONFIG_PATH = FUSION_DIR / "fusion_config.json"
UNITS_PATH = FUSION_DIR / "fusion_units.json"

FACTION_SID = "homm3_conflux"
SKILL_SID = "skill_faction_homm3_conflux"
SPELL_SID = "homm3_conflux_elemental_fusion"
SPELL_MODE = SPELL_SID
SPELL_PATH = "DB/magics/world_neutral_magics.json"
SPELL_ICON = "neutral_1_magic_units_replace"
SPELL_MANA_COST = 0
SPELL_USAGE_LIMIT = -1  # native unlimited (user 2026-11-15: no once-per-day limit, no mana cost)
NECROMANCY_MAGIC_SID = "change_use_necromancy"
MAGIC_LANG_PATHS = ("Lang/english/texts/magic.json", "Lang/english/texts/magics.json")
MAGIC_LANG_ARGS_PATH = "Lang/args/magic.json"
UNIT_LANG_PATH = "Lang/english/texts/units.json"
ABILITY_LANG_PATH = "Lang/english/texts/unitsAbility.json"
FUSED_UNIT_MARKER = "xHomm3Fusion"
SIGNATURE_ABILITY_KEY = "abilities_sig"
SIGNATURE_PASSIVE_KEY = "passive_sig"

SKILL_NAME = "Elemental Fusion"
SKILL_DESC = (
    "Conflux heroes learn the Elemental Fusion adventure-map spell: permanently merge two elemental stacks in "
    "the hero's army into one stack of a fused elemental, and fuse certain pairs of fused elementals a second time. "
    "Higher skill levels unlock more elemental lines."
)
_RULE_TEXT = (
    "The fused stack keeps 90% of the two stacks' combined strength, and each stack must provide at least a third "
    "of it. Fusion is permanent."
)
RANK_DESCS = (
    f"Grants the Elemental Fusion adventure spell. Fuse Air, Water and Fire Elementals and their upgrades "
    f"(36 fusions). {_RULE_TEXT}",
    f"Elemental Fusion can also fuse Earth Elementals and their upgrades (66 fusions). {_RULE_TEXT}",
    f"Elemental Fusion can also fuse Psychic Elementals and their upgrades (all 105 fusions). {_RULE_TEXT}",
)
IMPLEMENTED = (
    "Elemental Fusion: every rank grants the homm3_conflux_elemental_fusion world spell (Necromancer Will clone, "
    "no mana cost, unlimited uses); Basic unlocks the Air/Water/Fire lines, Advanced adds Earth, Expert adds Psychic "
    "(custom_factions/conflux_fusion/fusion_config.json tierLines). The plugin runtime intercepts the [mode] cast, "
    "opens the fusion picker and replaces the two stacks with floor(0.9 x pooled squadValue / fused squadValue) "
    "creatures of one of 105 generated h3_fusion_* units; 37 recipes (fusion_config.json recipes) fuse two named "
    "fused units again into a stage-2 h3_fusion_ii_* unit by the same rule."
)
SOURCE_DIFFERENCE = (
    "Replaces Elemental Conjury (start-Focus and hero Attack/Spell Power inheritance on elemental Focus abilities). "
    "Fusion has no HoMM3 source; fused units are generated from both parents' final rows and are never recruited."
)

# Advanced/Expert subskill SIDs are kept from Elemental Conjury so saved heroes keep resolving them.
SUBSKILL_IDS = {
    "native_terrain": "sub_skill_faction_homm3_conflux_elemental_conjury_native_terrain",
    "focus_charge": "sub_skill_faction_homm3_conflux_elemental_conjury_focus_charge",
    "fused_defense": "sub_skill_faction_homm3_conflux_elemental_conjury_spell_power",
    "expert_focus_charge": "sub_skill_faction_homm3_conflux_elemental_conjury_expert_focus_charge",
    "pathfinding": "sub_skill_faction_homm3_conflux_elemental_conjury_pathfinding",
    "fused_attack": "sub_skill_faction_homm3_conflux_elemental_conjury_expert_spell_tier",
}
SUBSKILLS_BY_LEVEL = {
    2: (SUBSKILL_IDS["native_terrain"], SUBSKILL_IDS["focus_charge"], SUBSKILL_IDS["fused_defense"]),
    3: (SUBSKILL_IDS["expert_focus_charge"], SUBSKILL_IDS["pathfinding"], SUBSKILL_IDS["fused_attack"]),
}
FUSED_DEFENSE_BONUS = 2
FUSED_ATTACK_BONUS = 2
SUBSKILL_TEXT = {
    "native_terrain": ("Elemental Ground", "Conflux creatures on native terrain deal 10% more damage and take 10% less damage."),
    "focus_charge": ("Planar Reserve", "Your heroes start battles with 1 additional Focus Charge."),
    "fused_defense": ("Stable Bond", f"Fused elementals in this hero's army gain +{FUSED_DEFENSE_BONUS} Defense."),
    "expert_focus_charge": ("Deep Channels", "Your heroes start battles with 1 additional Focus Charge."),
    "pathfinding": ("Elemental Paths", "Your heroes ignore rough-terrain movement penalties on the adventure map."),
    "fused_attack": ("Perfect Fusion", f"Fused elementals in this hero's army gain +{FUSED_ATTACK_BONUS} Attack."),
}

# View passive cards that describe the attack shape; they follow the host (and moveType for the flyer card).
ATTACK_SHAPE_CARDS = frozenset(
    {
        "h3_common_melee_attack_name",
        "h3_common_ranged_attack_name",
        "base_passive_flyer_name",
        "base_passive_melee_attack_no_counter_name",
        "base_passive_noncounter_name",
        "base_passive_strike_swipe_1_name",
    }
)
FLYER_CARD = "base_passive_flyer_name"
# Parent line identity that must not leak onto a fused unit.
STRIP_LOGIC_KEYS = (
    "upgradeSid",
    "baseSid",
    "xHomm3BranchRole",
    "xHomm3SourceMechanic",
    "xHomm3DecisionTest",
    "xHomm3CastleQuality",
    "xHomm3ReleaseQuality",
    "xHomm3BalanceRecommendation20260625",
    "xHomm3ImplementationAudit",
)
STRIP_VIEW_KEYS = STRIP_LOGIC_KEYS
ATTACK_KEYS = ("defaultAttacks", "alternativeAttacks", "counterAttacks")
PENALTY = 0.9


# ---------------------------------------------------------------- data


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_units() -> dict[str, Any]:
    return json.loads(UNITS_PATH.read_text(encoding="utf-8"))


def fused_unit_sids() -> list[str]:
    """Every fused unit: the 105 stage-1 pairs, then the stage-2 recipes."""
    config = load_config()
    return [row["fused"] for row in config["pairs"]] + [row["fused"] for row in config.get("recipes") or []]


def elemental_sids() -> list[str]:
    return [sid for line in load_config()["lines"].values() for sid in line]


def is_fused_unit_row(row: Any) -> bool:
    return isinstance(row, dict) and isinstance(row.get(FUSED_UNIT_MARKER), dict)


def _half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


# ---------------------------------------------------------------- skill, spell, subskills


def faction_skill_levels() -> list[list[dict[str, Any]]]:
    return [[{"type": "heroMagicAddition", "parameters": [SPELL_SID, "false"]}] for _ in range(3)]


def make_subskills(native_receivers_fraction: str = FACTION_SID) -> list[dict[str, Any]]:
    fused = fused_unit_sids()

    def row(key: str, icon: str, bonuses: list[dict[str, Any]]) -> dict[str, Any]:
        sid = SUBSKILL_IDS[key]
        return {"id": sid, "name": f"{sid}_name", "desc": f"{sid}_desc", "icon": icon, "bonuses": bonuses}

    return [
        row(
            "native_terrain",
            "sub_skill_faction_nature_1_icon",
            [
                {"type": "unitStat", "biomeType": "native", "fraction": native_receivers_fraction, "parameters": ["outAllDmgMod", "0.1"]},
                {"type": "unitStat", "biomeType": "native", "fraction": native_receivers_fraction, "parameters": ["inAllDmgMod", "-0.1"]},
            ],
        ),
        row("focus_charge", "skill_faction_homm3_conflux_2", [{"type": "heroStat", "parameters": ["startEnergyLevelsBonus", "1"]}]),
        row("fused_defense", "sub_skill_tactics_4_defence_buff_icon", [{"type": "unitStat", "receivers": fused, "parameters": ["defence", str(FUSED_DEFENSE_BONUS)]}]),
        row("expert_focus_charge", "skill_faction_homm3_conflux_3", [{"type": "heroStat", "parameters": ["startEnergyLevelsBonus", "1"]}]),
        row("pathfinding", "sub_skill_scouting_3_icon", [{"type": "heroStat", "parameters": ["landscapePenaltyPerBonus", "-1.0"]}]),
        row("fused_attack", "sub_skill_tactics_1_offence_buff_icon", [{"type": "unitStat", "receivers": fused, "parameters": ["offence", str(FUSED_ATTACK_BONUS)]}]),
    ]


def subskill_lang_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, sid in SUBSKILL_IDS.items():
        name, desc = SUBSKILL_TEXT[key]
        rows.append({"sid": f"{sid}_name", "text": name})
        rows.append({"sid": f"{sid}_desc", "text": desc})
    return rows


def make_fusion_magic_row(source_rows: list[Any]) -> dict[str, Any]:
    """Clone of the native Necromancer Will world magic; the runtime intercepts its [mode] parameters."""
    base = next((r for r in source_rows if isinstance(r, dict) and r.get("id") == NECROMANCY_MAGIC_SID), None)
    if not isinstance(base, dict):
        raise RuntimeError(f"missing Elemental Fusion magic source {NECROMANCY_MAGIC_SID}")
    row = copy.deepcopy(base)
    row.update(
        {
            "id": SPELL_SID,
            "name": f"{SPELL_SID}_name",
            "icon": SPELL_ICON,
            "description": [f"{SPELL_SID}_description"] * 4,
            "bonusDescriptions": [],
            "upEffectDescription": "",
            "manaCost": [SPELL_MANA_COST] * 4,
            "upgradeCost": [0],
            "rank": 1,
            "school_": "neutral",
            "usedOnMap": True,
            "xHomm3RuntimeHook": (
                "Elemental Fusion reuses the native Necromancer Will world-magic handler; the plugin runtime intercepts "
                "the [mode] parameter row, suppresses the native toggle and opens the fusion picker "
                "(custom_factions/conflux_fusion/fusion_config.json)."
            ),
        }
    )
    world_magic = row.get("worldMagic")
    settings = world_magic.get("magicSettings") if isinstance(world_magic, dict) else None
    if not isinstance(settings, list) or not settings:
        raise RuntimeError(f"malformed Elemental Fusion magic source {NECROMANCY_MAGIC_SID}")
    world_magic["settingPerLevels"] = [0, 0, 0, 0]
    for setting in settings:
        if isinstance(setting, dict):
            setting["mechType"] = NECROMANCY_MAGIC_SID
            setting["parameters"] = [SPELL_MODE]
            setting["usageLimit"] = SPELL_USAGE_LIMIT
            setting["castInfoSid"] = f"{SPELL_SID}_cast"
    return row


def magic_lang_rows() -> list[dict[str, str]]:
    return [
        {"sid": f"{SPELL_SID}_name", "text": "Elemental Fusion"},
        {
            "sid": f"{SPELL_SID}_description",
            "text": (
                "Permanently fuse two elemental stacks in this hero's army into one stack of a fused elemental. "
                "The fused stack keeps 90% of the two stacks' combined strength; each stack must provide at least a "
                "third of it. Elemental Fusion skill levels unlock the lines: Basic Air, Water and Fire; Advanced adds "
                "Earth; Expert adds Psychic. Some pairs of fused elementals can be fused again into a greater "
                "elemental. Fusion cannot be undone."
            ),
        },
        {"sid": f"{SPELL_SID}_cast", "text": "The elementals merge."},
    ]


def merge_fusion_skill_rows_into_overlay(release_zip, output, notes, helpers) -> None:
    """World spell + subskills. helpers: read_overlay_or_release_json, write_json, upsert_array_row,
    dedupe_array_rows_by_id, remove_array_rows_by_id, add_lang_overlay_rows, add_lang_args_overlay_rows,
    stale_subskill_ids."""
    read_doc = helpers["read_overlay_or_release_json"]
    write_json = helpers["write_json"]
    upsert = helpers["upsert_array_row"]
    dedupe = helpers["dedupe_array_rows_by_id"]

    magic_doc = read_doc(release_zip, output, SPELL_PATH)
    if not isinstance(magic_doc, dict) or not isinstance(magic_doc.get("array"), list):
        raise RuntimeError(f"malformed homm3_conflux Elemental Fusion magic target {SPELL_PATH}")
    changed = upsert(magic_doc, make_fusion_magic_row(magic_doc["array"]))
    changed = dedupe(magic_doc) or changed
    if changed:
        output[SPELL_PATH] = write_json(magic_doc)
        notes.append(f"merge homm3_conflux Elemental Fusion world spell into {SPELL_PATH}")

    subskills_name = "DB/heroes_skills/sub_skills/sub_skills.json"
    subskills_doc = read_doc(release_zip, output, subskills_name)
    if not isinstance(subskills_doc, dict) or not isinstance(subskills_doc.get("array"), list):
        raise RuntimeError(f"malformed homm3_conflux Elemental Fusion subskill target {subskills_name}")
    changed = helpers["remove_array_rows_by_id"](subskills_doc, set(helpers.get("stale_subskill_ids") or ()))
    for row in make_subskills():
        changed = upsert(subskills_doc, row) or changed
    changed = dedupe(subskills_doc) or changed
    if changed:
        output[subskills_name] = write_json(subskills_doc)
        notes.append("merge homm3_conflux Elemental Fusion subskills")

    for path in MAGIC_LANG_PATHS:
        helpers["add_lang_overlay_rows"](release_zip, output, path, magic_lang_rows(), notes)
    helpers["add_lang_args_overlay_rows"](
        release_zip, output, MAGIC_LANG_ARGS_PATH, [{"sid": row["sid"], "args": []} for row in magic_lang_rows()], notes
    )


# ---------------------------------------------------------------- unit rows


def _unit_paths(sid: str, faction_sid: str = FACTION_SID) -> tuple[str, str]:
    return (
        f"DB/units/units_logics/{faction_sid}/{sid}_l.json",
        f"DB/units/units_views/{faction_sid}/{sid}_v.json",
    )


class _Rows:
    """Unit row lookup: overlay output first, then the release Core (any faction folder)."""

    def __init__(self, release_zip, output: dict[str, bytes], read_json: Callable[[Any, str], Any]):
        self.release_zip = release_zip
        self.output = output
        self.read_json = read_json
        self._release_names = None

    def _load(self, name: str) -> Any:
        if name in self.output:
            return json.loads(self.output[name].decode("utf-8-sig"))
        return self.read_json(self.release_zip, name)

    def _find(self, sid: str, kind: str) -> str:
        suffix = f"/{sid}_{'l' if kind == 'logics' else 'v'}.json"
        prefix = f"DB/units/units_{kind}/"
        for name in self.output:
            if name.startswith(prefix) and name.endswith(suffix):
                return name
        if self._release_names is None:
            self._release_names = [n for n in self.release_zip.namelist() if n.startswith("DB/units/")]
        for name in self._release_names:
            if name.startswith(prefix) and name.endswith(suffix):
                return name
        raise KeyError(f"no unit {kind} row for {sid}")

    def logic(self, sid: str) -> dict[str, Any]:
        return copy.deepcopy(self._load(self._find(sid, "logics"))["array"][0])

    def view(self, sid: str) -> dict[str, Any]:
        return copy.deepcopy(self._load(self._find(sid, "views"))["array"][0])


def _ref(value: str) -> tuple[str, str, int]:
    sid, kind, index = value.split(":")
    return sid, kind, int(index)


def _lang_texts(release_zip, output, read_doc, path: str) -> dict[str, str]:
    try:
        doc = read_doc(release_zip, output, path)
    except KeyError:
        return {}
    return {
        str(row.get("sid")): str(row.get("text"))
        for row in (doc.get("tokens") or [])
        if isinstance(row, dict) and isinstance(row.get("text"), str)
    }


# Borrowed vanilla ability cards whose english text has {n} placeholders the native formatter fills only from a
# live battle unit (the unit window and the Fusion Glossary show the raw tokens). Each fused unit that carries one
# gets its own description token with the numbers written in. Damage figures come from the fused unit's own stats
# and damage dealer; buff figures are the vanilla buff values the borrowed buff keeps (read 2026-11-15:
# twinkle side buff spellPower +2, aqualotl side buff hero stats -2, aqualotl_debuff_1 speed/initiative -2,
# black_dragon_buff revenge 0 + 30 per creature, qilin_selfbuff maxInDmg 1).
PLACEHOLDER_BUFF_VALUES = {
    "twinkle_ability_3_description": ["2"],
    "aqualotl_ability_6_description": ["2"],
    "aqualotl_ability_5_description": ["2", None],
    "qilin_ability_5_description_new": ["1"],
}

PER_CREATURE_MAGIC_TOKENS = {"star_child_ability_1_description", "black_dragon_ability_2_description"}


def _round_half_up(value: float) -> int:
    return int(value + 0.5)


def _placeholder_values(token: str, logic: dict[str, Any], ability: dict[str, Any] | None, view_card: dict[str, Any]) -> list[str] | None:
    stats = logic.get("stats") or {}
    dealer = (ability or {}).get("damageDealer") or {}
    mult = dealer.get("statDmgMult")
    mult = 1.0 if mult is None else float(mult)
    lo = _round_half_up(float(stats.get("damageMin") or 0) * mult)
    hi = _round_half_up(float(stats.get("damageMax") or 0) * mult)
    pct = str(_round_half_up(mult * 100))
    if token == "gorilla_ability_2_description":
        return [f"{lo}", f"{hi} per creature", pct]
    if token in ("qilin_ability_4_description", "black_dragon_ability_3_description"):
        return [pct, f"{lo}", f"{hi} per creature"]
    if token == "medusa_ability_4_description":
        return [pct, f"{lo}", f"{hi} per creature", str(dealer.get("numTargets") or 1)]
    if token == "star_child_ability_1_description":
        dmg = dealer.get("maxStackDmg") or dealer.get("minStackDmg") or 0
        return [str(dmg), str(dealer.get("numTargets") or 1)]
    if token == "black_dragon_ability_2_description":
        return ["30"]
    values = PLACEHOLDER_BUFF_VALUES.get(token)
    if values is None:
        return None
    out = list(values)
    if token == "aqualotl_ability_5_description":
        buff = dealer.get("buff") or {}
        out[1] = str(buff.get("duration") or 1)
    return out


def _fill_placeholder_texts(fused: str, logic: dict[str, Any], view: dict[str, Any], texts: dict[str, str], lang_rows) -> None:
    logic_by_marker = {}
    for kind in ("abilities", "passives"):
        for row in logic.get(kind) or []:
            if isinstance(row, dict) and row.get("xHomm3AbilityOverride"):
                logic_by_marker[json.dumps(row["xHomm3AbilityOverride"], sort_keys=True)] = row
    for kind in ("abilities", "passives"):
        for index, card in enumerate(view.get(kind) or []):
            if not isinstance(card, dict):
                continue
            token = card.get("description")
            text = texts.get(token) if isinstance(token, str) else None
            if not text or not re.search(r"\{\d+\}", text):
                continue
            ability = None
            marker = card.get("xHomm3AbilityOverride")
            if marker is not None:
                ability = logic_by_marker.get(json.dumps(marker, sort_keys=True))
            if ability is None and index < len(logic.get(kind) or []):
                ability = logic[kind][index]
            values = _placeholder_values(token, logic, ability, card)
            if values is None:
                raise RuntimeError(f"{fused}: no numbers known for placeholder text {token}")
            filled = re.sub(r"\{(\d+)\}", lambda m: values[int(m.group(1))], text)
            if token in PER_CREATURE_MAGIC_TOKENS:
                filled = filled.replace("Magic Damage", "Magic Damage per creature in this stack", 1)
            new_token = f"{fused}_{kind}_{index}_description"
            lang_rows.append({"sid": new_token, "text": filled})
            card["description"] = new_token


def derive_stats(host: dict[str, Any], guest: dict[str, Any]) -> dict[str, Any]:
    """The approved fused stat rule applied to two final parent logic rows."""
    hs, gs = host["stats"], guest["stats"]
    stats = copy.deepcopy(hs)
    stats["hp"] = int(hs["hp"]) + int(gs["hp"])
    stats["damageMin"] = _half_up(PENALTY * (int(hs["damageMin"]) + int(gs["damageMin"])))
    stats["damageMax"] = _half_up(PENALTY * (int(hs["damageMax"]) + int(gs["damageMax"])))
    stats["offence"] = max(int(hs["offence"]), int(gs["offence"])) + 1
    stats["defence"] = max(int(hs["defence"]), int(gs["defence"])) + 1
    faster = guest if (int(gs["speed"]), int(gs["initiative"])) > (int(hs["speed"]), int(hs["initiative"])) else host
    fs = faster["stats"]
    stats["speed"] = int(fs["speed"])
    stats["initiative"] = int(fs["initiative"])
    if fs.get("moveType"):
        stats["moveType"] = fs["moveType"]
    else:
        stats.pop("moveType", None)
    stats["energyPerRound"] = max(int(hs.get("energyPerRound") or 0), int(gs.get("energyPerRound") or 0))
    # No inherited starting Focus (owner 2026-11-16): starting Focus is only a deliberate, carded passive
    # on a named unit, never a family default passed on by fusion.
    stats.pop("startEnergy", None)
    if gs.get("maxOverwatchStrikes") and not hs.get("maxOverwatchStrikes"):
        stats["maxOverwatchStrikes"] = gs["maxOverwatchStrikes"]
    return stats


def _merge_damage_mods(stats: dict[str, Any], guest_stats: dict[str, Any]) -> None:
    for key in ("inDmgMods", "outDmgMods"):
        guest_rows = ((guest_stats.get(key) or {}).get("list")) or []
        if not guest_rows:
            continue
        mods = stats.setdefault(key, {"list": []})
        rows = mods.setdefault("list", [])
        tags = {row.get("t") for row in rows if isinstance(row, dict)}
        for row in guest_rows:
            if isinstance(row, dict) and row.get("t") not in tags:
                rows.append(copy.deepcopy(row))


def _attack_dealers(logic: dict[str, Any]) -> list[dict[str, Any]]:
    dealers = []
    for key in ATTACK_KEYS:
        for attack in logic.get(key) or []:
            dealer = attack.get("damageDealer") if isinstance(attack, dict) else None
            if isinstance(dealer, dict):
                dealers.append(dealer)
    return dealers


def _merge_attack_riders(logic: dict[str, Any], guest: dict[str, Any]) -> None:
    """A guest attack rider (e.g. Frostbite) rides the host's attacks when the host has none."""
    guest_buff = None
    for attack in guest.get("defaultAttacks") or []:
        dealer = attack.get("damageDealer") if isinstance(attack, dict) else None
        if isinstance(dealer, dict) and isinstance(dealer.get("buff"), dict):
            guest_buff = (copy.deepcopy(dealer["buff"]), dealer.get("buffTarget_", "enemy"))
            break
    if guest_buff is None:
        return
    for dealer in _attack_dealers(logic):
        if not isinstance(dealer.get("buff"), dict):
            dealer["buff"] = copy.deepcopy(guest_buff[0])
            dealer["buffTarget_"] = guest_buff[1]


def _merge_dealer(dealer: dict[str, Any], patch: dict[str, Any], drop: list[str] | None = None) -> None:
    for key, value in patch.items():
        if key == "buff" and isinstance(value, dict) and isinstance(dealer.get("buff"), dict):
            dealer["buff"].update(copy.deepcopy(value))
        else:
            dealer[key] = copy.deepcopy(value)
    for key in drop or ():
        dealer.pop(key, None)


def _dedupe_abilities(pairs: list[tuple[dict, dict]], names: dict[str, str]) -> list[tuple[dict, dict]]:
    out: list[tuple[dict, dict]] = []
    seen: set[str] = set()
    for logic, view in pairs:
        token = view.get("name") if isinstance(view, dict) else None
        label = names.get(str(token), str(token)) if token else json.dumps(logic, sort_keys=True)
        if label in seen:
            continue
        seen.add(label)
        out.append((logic, view))
    return out


def _resolve_vanilla_special(release_zip, helpers, sid: str, kind: str, live_index: int) -> tuple[dict, dict]:
    """Signature sources name the release Core's live slot index. A live slot that a donor pin covers
    resolves through the pin (pinned buff sid/values); any other slot resolves live."""
    for (pin_sid, pin_kind, pin_index), pin in (helpers.get("donor_slot_pins") or {}).items():
        if pin_sid == sid and pin_kind == kind and pin.get("liveIndex") == live_index:
            logic_row, view_row, _faction = helpers["resolve_unit_special_from_release"](release_zip, sid, kind, pin_index)
            return logic_row, view_row
    logic_row, view_row, _faction = helpers["resolve_live_unit_special_from_release"](release_zip, sid, kind, live_index)
    return logic_row, view_row


def _signature_marker(fused: str, signature: dict[str, Any], key: str) -> dict[str, Any]:
    marker = {"key": key, "fusionSignature": signature.get("effect")}
    if signature.get("source"):
        marker["sourceUnitSpecial"] = signature["source"]
    if signature.get("spellEffectKey"):
        marker["sourceSpellEffectKey"] = signature["spellEffectKey"]
    return marker


def _build_signature_active(fused, signature, rows: _Rows, release_zip, helpers, lang_rows) -> tuple[dict, dict]:
    override_text_token = helpers["override_text_token"]
    marker = _signature_marker(fused, signature, SIGNATURE_ABILITY_KEY)
    envelope = signature.get("envelope") or {}
    build = signature["build"]
    if build == "unit_special":
        sid, kind, index = _ref(signature["source"])
        if sid.startswith("h3_"):
            logic_row = copy.deepcopy(rows.logic(sid)[kind][index])
            view_row = copy.deepcopy(rows.view(sid)[kind][index])
        else:
            logic_row, view_row = _resolve_vanilla_special(release_zip, helpers, sid, kind, index)
        logic_row["xHomm3AbilityOverride"] = marker
        view_row["xHomm3AbilityOverride"] = marker
        helpers["apply_ability_envelope_overrides"](logic_row, view_row, envelope)
        if isinstance(signature.get("dealerPatch"), dict):
            dealer = logic_row.setdefault("damageDealer", {})
            _merge_dealer(dealer, signature["dealerPatch"], signature.get("dealerDrop"))
        if not signature.get("useSourceText"):
            name_token = override_text_token(fused, None, signature.get("nameText"), f"{SIGNATURE_ABILITY_KEY}_name", lang_rows)
            desc_token = override_text_token(
                fused, None, signature.get("descriptionText"), f"{SIGNATURE_ABILITY_KEY}_description", lang_rows
            )
            if name_token:
                view_row["name"] = name_token
            if desc_token:
                view_row["description"] = desc_token
        return logic_row, view_row
    if build == "spell_effect":
        selection = {
            "effectKey": signature["spellEffectKey"],
            "cooldown": envelope.get("cooldown"),
            "energyLevel": envelope.get("energyLevel"),
            "rank": envelope.get("rank"),
            "turnBehavior": envelope.get("turnBehavior"),
        }
        if envelope.get("charges") is not None:
            selection["charges"] = envelope["charges"]
        if signature.get("buffDuration") is not None:
            selection["effectDuration"] = signature["buffDuration"]
        display = {"nameText": signature.get("nameText"), "descriptionText": signature.get("descriptionText")}
        logic_row, view_row = helpers["build_spell_effect_rows"](
            release_zip, fused, "abilities", None, None, selection, display, marker, lang_rows
        )
        dealer = logic_row.setdefault("damageDealer", {})
        _merge_dealer(dealer, signature.get("dealerPatch") or {}, signature.get("dealerDrop"))
        return logic_row, view_row
    raise RuntimeError(f"{fused}: unsupported active signature build {build!r}")


def _apply_signature_passive(fused, signature, logic, view, rows: _Rows, helpers, lang_rows) -> None:
    override_text_token = helpers["override_text_token"]
    passives = logic.setdefault("passives", [])
    for ref in signature.get("logicPassives") or []:
        sid, _kind, index = _ref(ref)
        row = copy.deepcopy(rows.logic(sid)["passives"][index])
        patch = signature.get("logicPassiveDealerPatch")
        if isinstance(patch, dict):
            for action in row.get("actions") or []:
                if isinstance(action, dict) and isinstance(action.get("damageDealer"), dict):
                    _merge_dealer(action["damageDealer"], patch)
        passives.append(row)
    if signature.get("attackBuff"):
        sid, kind, index = _ref(signature["attackBuff"])
        donor = rows.logic(sid)[kind][index]["damageDealer"]
        for dealer in _attack_dealers(logic):
            dealer["buff"] = copy.deepcopy(donor["buff"])
            dealer["buffTarget_"] = donor.get("buffTarget_", "enemy")
    if signature.get("attackMechanics"):
        sid, kind, index = _ref(signature["attackMechanics"])
        donor = rows.logic(sid)[kind][index]["damageDealer"]
        for attack in logic.get("defaultAttacks") or []:
            if isinstance(attack.get("damageDealer"), dict):
                attack["damageDealer"]["targetMechanics"] = copy.deepcopy(donor.get("targetMechanics") or [])
    for key, value in (signature.get("logicFields") or {}).items():
        logic[key] = copy.deepcopy(value)
    # Fields set on every default attack row (e.g. returnToStartAfterAttack for strike-and-return).
    for attack in logic.get("defaultAttacks") or []:
        if isinstance(attack, dict):
            for key, value in (signature.get("attackFields") or {}).items():
                attack[key] = copy.deepcopy(value)
    for key, value in (signature.get("stats") or {}).items():
        logic["stats"][key] = copy.deepcopy(value)
    cards = view.setdefault("passives", [])
    for position, ref in enumerate(signature.get("cards") or []):
        sid, _kind, index = _ref(ref)
        card = copy.deepcopy(rows.view(sid)["passives"][index])
        suffix = SIGNATURE_PASSIVE_KEY if position == 0 else f"{SIGNATURE_PASSIVE_KEY}_{position}"
        name_token = override_text_token(fused, None, signature.get("nameText"), f"{suffix}_name", lang_rows)
        desc_token = override_text_token(fused, None, signature.get("descriptionText"), f"{suffix}_description", lang_rows)
        if name_token:
            card["name"] = name_token
        if desc_token:
            card["description"] = desc_token
        cards.append(card)


def _merge_helper_rows(release_zip, output, notes, helpers, signature, fused) -> None:
    for helper in signature.get("helperRows") or []:
        path, row = helper["path"], helper["row"]
        doc = helpers["read_overlay_or_release_json"](release_zip, output, path)
        if not isinstance(doc, dict) or not isinstance(doc.get("array"), list):
            raise RuntimeError(f"{fused}: malformed signature helper target {path}")
        if helpers["upsert_array_row"](doc, copy.deepcopy(row)):
            output[path] = helpers["write_json"](doc)
            notes.append(f"merge Conflux fusion signature helper {row.get('id')} into {path}")


def build_fused_unit(fused, entry, rows: _Rows, release_zip, output, notes, helpers, lang_rows, ability_names):
    host_sid, guest_sid = entry["host"], entry["guest"]
    host_logic, guest_logic = rows.logic(host_sid), rows.logic(guest_sid)
    host_view, guest_view = rows.view(host_sid), rows.view(guest_sid)
    signature = entry.get("signature") or None
    if signature and signature.get("build") == "fallback":
        signature_kind = None
    else:
        signature_kind = signature.get("kind") if signature else None

    logic = copy.deepcopy(host_logic)
    for key in STRIP_LOGIC_KEYS:
        logic.pop(key, None)
    logic["id"] = fused
    logic["fraction"] = FACTION_SID
    logic["squadValue"] = int(entry["squadValue"])
    logic["tier"] = max(int(host_logic.get("tier") or 0), int(guest_logic.get("tier") or 0))
    logic["expBonus"] = max(int(host_logic.get("expBonus") or 0), int(guest_logic.get("expBonus") or 0))
    gold = 0
    for parent in (host_logic, guest_logic):
        for res in ((parent.get("unitCost") or {}).get("costResArray") or []):
            if isinstance(res, dict) and res.get("name") == "gold":
                gold += int(res.get("cost") or 0)
    logic["unitCost"] = {"costResArray": [{"name": "gold", "cost": gold}]}
    logic["stats"] = derive_stats(host_logic, guest_logic)
    logic["leaveCorpse"] = False

    # Passives (logic rows, attack riders, damage modifiers) and actives.
    if signature_kind == "passive":
        logic["passives"] = []
        for dealer in _attack_dealers(logic):
            dealer.pop("buff", None)
            dealer.pop("buffTarget_", None)
        for key in ("inDmgMods", "outDmgMods"):
            logic["stats"][key] = {"list": []}
    else:
        passives = logic.setdefault("passives", [])
        known = {json.dumps(p, sort_keys=True) for p in passives}
        for row in guest_logic.get("passives") or []:
            if json.dumps(row, sort_keys=True) not in known:
                passives.append(copy.deepcopy(row))
        _merge_attack_riders(logic, guest_logic)
        _merge_damage_mods(logic["stats"], guest_logic["stats"])

    view = copy.deepcopy(host_view)
    for key in STRIP_VIEW_KEYS:
        view.pop(key, None)
    view["id"] = fused
    mesh = entry.get("mesh")
    if isinstance(mesh, dict):
        for key in ("mesh", "mapMesh"):
            if mesh.get(key):
                view[key] = mesh[key]

    # View passive cards: host attack-shape cards; non-shape cards of both parents unless replaced.
    host_cards = [c for c in host_view.get("passives") or [] if isinstance(c, dict)]
    guest_cards = [c for c in guest_view.get("passives") or [] if isinstance(c, dict)]
    cards = [copy.deepcopy(c) for c in host_cards if c.get("name") in ATTACK_SHAPE_CARDS and c.get("name") != FLYER_CARD]
    if logic["stats"].get("moveType") == "fly":
        flyer = next((c for c in host_cards + guest_cards if c.get("name") == FLYER_CARD), None)
        cards.append(copy.deepcopy(flyer) if flyer else {"name": "base_passive_flyer_name", "description": "base_passive_flyer_description"})
    if signature_kind != "passive":
        names = {c.get("name") for c in cards}
        for card in host_cards + guest_cards:
            if card.get("name") in ATTACK_SHAPE_CARDS or card.get("name") in names:
                continue
            names.add(card.get("name"))
            cards.append(copy.deepcopy(card))
    view["passives"] = cards

    # Actives: host abilities then guest abilities (views index-aligned), or the signature alone.
    if signature_kind == "active":
        abilities = [_build_signature_active(fused, signature, rows, release_zip, helpers, lang_rows)]
    else:
        abilities = []
        for parent_logic, parent_view in ((host_logic, host_view), (guest_logic, guest_view)):
            logic_slots = parent_logic.get("abilities") or []
            view_slots = parent_view.get("abilities") or []
            for index, ability in enumerate(logic_slots):
                card = view_slots[index] if index < len(view_slots) else {}
                abilities.append((copy.deepcopy(ability), copy.deepcopy(card)))
        abilities = _dedupe_abilities(abilities, ability_names)
    logic["abilities"] = [a for a, _ in abilities]
    view["abilities"] = [v for _, v in abilities]

    if signature_kind == "passive":
        _apply_signature_passive(fused, signature, logic, view, rows, helpers, lang_rows)
    if signature and signature.get("helperRows"):
        _merge_helper_rows(release_zip, output, notes, helpers, signature, fused)

    marker = {
        "name": entry["name"],
        "host": host_sid,
        "guest": guest_sid,
        "poolEligible": False,
        "recruitable": False,
        "meshSource": host_sid if not isinstance(mesh, dict) else "fusion_units.json mesh",
        "signature": (signature or {}).get("effect"),
        "signatureBuild": (signature or {}).get("build"),
        "source": "custom_factions/conflux_fusion/fusion_units.json",
    }
    logic[FUSED_UNIT_MARKER] = marker
    view[FUSED_UNIT_MARKER] = marker
    # Same card-icon pass the manifest units get (donor cards carry no icon field of their own).
    if helpers.get("ensure_unit_view_card_icons"):
        helpers["ensure_unit_view_card_icons"](view)
    if helpers.get("dedupe_unit_view_card_rows"):
        helpers["dedupe_unit_view_card_rows"](view)
    return logic, view


def add_conflux_fusion_units(release_zip, output, notes, helpers) -> None:
    """Phase A (after every parent kit is final, before multilingual sync): build the 105 fused rows.
    helpers: read_json, read_overlay_or_release_json, write_json, upsert_array_row, add_lang_overlay_rows,
    override_text_token, apply_ability_envelope_overrides, resolve_unit_special_from_release,
    build_spell_effect_rows."""
    config = load_config()
    units = load_units()["units"]
    pairs = config["pairs"]
    if len(pairs) != 105 or set(units) != {p["fused"] for p in pairs}:
        raise RuntimeError("Conflux fusion data: fusion_config.json pairs and fusion_units.json units must list the same 105 units")
    rows = _Rows(release_zip, output, helpers["read_json"])
    ability_names = _lang_texts(release_zip, output, helpers["read_overlay_or_release_json"], ABILITY_LANG_PATH)
    ability_lang_rows: list[dict[str, str]] = []
    unit_lang_rows: list[dict[str, str]] = []
    write_json = helpers["write_json"]
    for pair in pairs:
        fused = pair["fused"]
        entry = units[fused]
        if entry["host"] != pair["host"] or entry["guest"] != pair["guest"] or entry["name"] != pair["name"]:
            raise RuntimeError(f"Conflux fusion data mismatch for {fused}")
        logic, view = build_fused_unit(fused, entry, rows, release_zip, output, notes, helpers, ability_lang_rows, ability_names)
        _fill_placeholder_texts(fused, logic, view, ability_names, ability_lang_rows)
        logic_name, view_name = _unit_paths(fused)
        output[logic_name] = write_json({"array": [logic]})
        output[view_name] = write_json({"array": [view]})
        host_name = entry["name"]
        unit_lang_rows.append({"sid": f"{fused}_name", "text": host_name})
        unit_lang_rows.append(
            {
                "sid": f"{fused}_narrativeDescription",
                "text": f"{host_name} is a fused elemental, born when two Conflux elemental stacks merge.",
            }
        )
    helpers["add_lang_overlay_rows"](release_zip, output, UNIT_LANG_PATH, unit_lang_rows, notes)
    if ability_lang_rows:
        helpers["add_lang_overlay_rows"](release_zip, output, ABILITY_LANG_PATH, ability_lang_rows, notes)
    signatures = sum(1 for u in units.values() if (u.get("signature") or {}).get("build") not in (None, "fallback"))
    notes.append(f"add {len(pairs)} Conflux Elemental Fusion unit rows ({signatures} signatures)")
    add_conflux_fusion_stage2_units(release_zip, output, notes, helpers, rows, ability_names)


def build_stage2_unit(fused, entry, rows: _Rows, release_zip, output, notes, helpers, lang_rows):
    """A second fusion of two stage-1 fused rows (user 2026-11-15). Same stat rule as stage 1, applied to the two fused
    parents; attack shape from the host parent; the kit is the unit's own signature parts only (no parent abilities)."""
    host_sid, guest_sid = entry["host"], entry["guest"]
    host_logic, guest_logic = rows.logic(host_sid), rows.logic(guest_sid)
    host_view, guest_view = rows.view(host_sid), rows.view(guest_sid)
    logic = copy.deepcopy(host_logic)
    logic.pop(FUSED_UNIT_MARKER, None)
    logic["id"] = fused
    logic["squadValue"] = int(entry["squadValue"])
    logic["tier"] = max(int(host_logic.get("tier") or 0), int(guest_logic.get("tier") or 0))
    logic["expBonus"] = max(int(host_logic.get("expBonus") or 0), int(guest_logic.get("expBonus") or 0))
    gold = 0
    for parent in (host_logic, guest_logic):
        for res in ((parent.get("unitCost") or {}).get("costResArray") or []):
            if isinstance(res, dict) and res.get("name") == "gold":
                gold += int(res.get("cost") or 0)
    logic["unitCost"] = {"costResArray": [{"name": "gold", "cost": gold}]}
    logic["stats"] = derive_stats(host_logic, guest_logic)
    for key in ("inDmgMods", "outDmgMods"):
        logic["stats"][key] = {"list": []}
    logic["passives"] = []
    logic["abilities"] = []
    for dealer in _attack_dealers(logic):
        dealer.pop("buff", None)
        dealer.pop("buffTarget_", None)

    view = copy.deepcopy(host_view)
    view.pop(FUSED_UNIT_MARKER, None)
    view["id"] = fused
    mesh = entry.get("mesh")
    if isinstance(mesh, dict):
        for key in ("mesh", "mapMesh"):
            if mesh.get(key):
                view[key] = mesh[key]
    host_cards = [c for c in host_view.get("passives") or [] if isinstance(c, dict)]
    guest_cards = [c for c in guest_view.get("passives") or [] if isinstance(c, dict)]
    cards = [copy.deepcopy(c) for c in host_cards if c.get("name") in ATTACK_SHAPE_CARDS and c.get("name") != FLYER_CARD]
    if logic["stats"].get("moveType") == "fly":
        flyer = next((c for c in host_cards + guest_cards if c.get("name") == FLYER_CARD), None)
        cards.append(copy.deepcopy(flyer) if flyer else {"name": "base_passive_flyer_name", "description": "base_passive_flyer_description"})
    view["passives"] = cards
    view["abilities"] = []

    built = []
    for signature in entry.get("signatures") or []:
        if signature.get("build") == "fallback":
            continue
        if signature["kind"] == "active":
            ability, card = _build_signature_active(fused, signature, rows, release_zip, helpers, lang_rows)
            logic["abilities"].append(ability)
            view["abilities"].append(card)
        else:
            _apply_signature_passive(fused, signature, logic, view, rows, helpers, lang_rows)
        if signature.get("helperRows"):
            _merge_helper_rows(release_zip, output, notes, helpers, signature, fused)
        built.append(signature.get("effect"))
    if not built:
        raise RuntimeError(f"{fused}: stage-2 fusion has no buildable signature")

    marker = {
        "name": entry["name"],
        "stage": 2,
        "parents": [entry["a"], entry["b"]],
        "host": host_sid,
        "guest": guest_sid,
        "poolEligible": False,
        "recruitable": False,
        "meshSource": "fusion_units.json mesh" if isinstance(mesh, dict) else host_sid,
        "signature": " + ".join(built),
        "source": "custom_factions/conflux_fusion/fusion_units.json stage2",
    }
    logic[FUSED_UNIT_MARKER] = marker
    view[FUSED_UNIT_MARKER] = marker
    if helpers.get("ensure_unit_view_card_icons"):
        helpers["ensure_unit_view_card_icons"](view)
    if helpers.get("dedupe_unit_view_card_rows"):
        helpers["dedupe_unit_view_card_rows"](view)
    return logic, view


def add_conflux_fusion_stage2_units(release_zip, output, notes, helpers, rows: _Rows, ability_names) -> None:
    """Stage-2 rows, built after the stage-1 rows exist in the overlay output (their parents)."""
    recipes = load_config().get("recipes") or []
    stage2 = load_units().get("stage2") or {}
    if set(stage2) != {r["fused"] for r in recipes}:
        raise RuntimeError("Conflux fusion data: fusion_config.json recipes and fusion_units.json stage2 must list the same units")
    if not recipes:
        return
    write_json = helpers["write_json"]
    rows = _Rows(release_zip, output, helpers["read_json"])
    ability_lang_rows: list[dict[str, str]] = []
    unit_lang_rows: list[dict[str, str]] = []
    for recipe in recipes:
        fused = recipe["fused"]
        entry = stage2[fused]
        for key in ("a", "b", "host", "guest", "name"):
            if entry.get(key) != recipe.get(key):
                raise RuntimeError(f"Conflux stage-2 fusion data mismatch for {fused} ({key})")
        logic, view = build_stage2_unit(fused, entry, rows, release_zip, output, notes, helpers, ability_lang_rows)
        _fill_placeholder_texts(fused, logic, view, ability_names, ability_lang_rows)
        logic_name, view_name = _unit_paths(fused)
        output[logic_name] = write_json({"array": [logic]})
        output[view_name] = write_json({"array": [view]})
        unit_lang_rows.append({"sid": f"{fused}_name", "text": entry["name"]})
        unit_lang_rows.append(
            {
                "sid": f"{fused}_narrativeDescription",
                "text": entry.get("narrative")
                or f"{entry['name']} is a second-stage fused elemental, born when two fused Conflux elementals merge.",
            }
        )
    helpers["add_lang_overlay_rows"](release_zip, output, UNIT_LANG_PATH, unit_lang_rows, notes)
    if ability_lang_rows:
        helpers["add_lang_overlay_rows"](release_zip, output, ABILITY_LANG_PATH, ability_lang_rows, notes)
    notes.append(f"add {len(recipes)} Conflux stage-2 fusion unit rows")


def finalize_conflux_fusion_units(release_zip, output, notes, helpers) -> None:
    """Phase B (after the balance contract): rebuild every fused row from the final parent rows (stats and
    kits: the contract still changes parent stats, squad values and some passives).
    Phase A already wrote the same lang tokens before multilingual sync; rebuilding re-upserts identical text."""
    add_conflux_fusion_units(release_zip, output, notes, helpers)
    notes.append("rebuild Conflux fusion unit rows from final parent rows")
    align_fused_card_icons(release_zip, output, notes, helpers)


def _norm_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(re.sub(r"<[^>]+>", "", value).split()).lower()


def align_fused_card_icons(release_zip, output, notes, helpers) -> None:
    """A fused card that shows the same text as another unit's card uses that card's icon when the other
    units agree on one (tools/validate_homm3_unit_ability_redesign_contract.py semantic icon rule)."""
    read_json = helpers["read_json"]

    def load(name: str) -> Any:
        if name in output:
            return json.loads(output[name].decode("utf-8-sig"))
        return read_json(release_zip, name)

    names = set(release_zip.namelist()) | set(output)
    texts: dict[str, str] = {}
    for name in sorted(names):
        if name.startswith("Lang/english/texts/") and name.endswith(".json"):
            doc = load(name)
            for section in ("tokens", "array"):
                for row in (doc.get(section) if isinstance(doc, dict) else None) or []:
                    if isinstance(row, dict) and isinstance(row.get("sid"), str) and isinstance(row.get("text"), str):
                        texts[row["sid"]] = row["text"]

    def keys(card: dict[str, Any], bucket: str) -> tuple[tuple, tuple]:
        name_text = _norm_text(texts.get(card.get("name"), card.get("name")))
        desc_text = _norm_text(texts.get(card.get("description"), card.get("description")))
        return (bucket, name_text, desc_text), (bucket, name_text)

    exact: dict[tuple, set[str]] = {}
    by_name: dict[tuple, set[str]] = {}
    fused_views: list[str] = []
    for name in sorted(names):
        if not (name.startswith("DB/units/units_views/") and name.endswith("_v.json")):
            continue
        if "/h3_fusion_" in name:
            fused_views.append(name)
            continue
        doc = load(name)
        item = doc["array"][0] if isinstance(doc, dict) and isinstance(doc.get("array"), list) and doc["array"] else doc
        if not isinstance(item, dict):
            continue
        for bucket in ("abilities", "passives", "defaultAttacks", "alternativeAttacks", "counterAttacks"):
            for card in item.get(bucket) or []:
                if isinstance(card, dict) and card.get("icon"):
                    exact_key, name_key = keys(card, bucket)
                    exact.setdefault(exact_key, set()).add(card["icon"])
                    by_name.setdefault(name_key, set()).add(card["icon"])
    changed = 0
    for name in fused_views:
        doc = load(name)
        item = doc["array"][0]
        dirty = False
        for bucket in ("abilities", "passives", "defaultAttacks", "alternativeAttacks", "counterAttacks"):
            for card in item.get(bucket) or []:
                if not isinstance(card, dict):
                    continue
                exact_key, name_key = keys(card, bucket)
                icons = exact.get(exact_key) or set()
                if len(icons) != 1:
                    icons = by_name.get(name_key) or set()
                if len(icons) == 1:
                    icon = next(iter(icons))
                    if card.get("icon") != icon:
                        card["icon"] = icon
                        dirty = True
                        changed += 1
        if dirty:
            output[name] = helpers["write_json"](doc)
    notes.append(f"align {changed} Conflux fusion card icon(s) with matching unit cards")
