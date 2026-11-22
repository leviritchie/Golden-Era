"""Core rows for the HoMM3 Rampart faction skill "Avenger" (avenging strikes rework, 2026-11-19).

Avenger is runtime-owned: OfflineUnlockMod/Homm3RampartAvengerStrikeRuntime.cs runs the avenging strikes and every
subskill effect except the native-terrain one. The Core rows here are carriers:

- the skill row's ranks carry no bonuses (like Inferno Gating), so the hero no longer gets the Avenger mark hero
  action and the army does not ignore the mixed-faction Morale penalty (the old ignoreFractionsCount carrier did);
- the six subskills keep their old SIDs and tier slots (sub_skill_faction_homm3_rampart_avenger_*) for save
  compatibility; only the native-terrain pick carries a native bonus;
- the arena skill and arena subskills get the same shape.

The retired mark rows (hero ability, rank buffs) stay in the Core untouched: nothing grants them once the skill row
stops listing the heroBattleAbility bonus.

Numbers must match Homm3RampartAvengerStrikeRuntime.cs (StrikersByRank, MoveHexesByRank).
"""

from __future__ import annotations

from typing import Any, Callable

FACTION_SID = "homm3_rampart"
SKILL_SID = "skill_faction_homm3_rampart"
ARENA_SKILL_SID = "arena_skill_faction_homm3_rampart"
SUBSKILL_PREFIX = "sub_skill_faction_homm3_rampart_avenger"

SUBSKILL_NATIVE_TERRAIN = f"{SUBSKILL_PREFIX}_weakening_ray"
SUBSKILL_FOCUS = f"{SUBSKILL_PREFIX}_fatal_decay"
SUBSKILL_RETURN = f"{SUBSKILL_PREFIX}_long_mark"
SUBSKILL_RANGED_FIRST = f"{SUBSKILL_PREFIX}_native_terrain"
SUBSKILL_SWIFT_STRIKE = f"{SUBSKILL_PREFIX}_wide_mark"
SUBSKILL_RETALIATION = f"{SUBSKILL_PREFIX}_focus_efficiency"

# Same tier slots as the retired mark subskills (Advanced: weakening_ray, fatal_decay, long_mark;
# Expert: native_terrain, wide_mark, focus_efficiency).
SUBSKILLS_BY_LEVEL = {
    2: (SUBSKILL_NATIVE_TERRAIN, SUBSKILL_FOCUS, SUBSKILL_RETURN),
    3: (SUBSKILL_RANGED_FIRST, SUBSKILL_SWIFT_STRIKE, SUBSKILL_RETALIATION),
}

# Index = rank - 1.
STRIKERS_BY_RANK = (1, 2, 3)
MOVE_HEXES_BY_RANK = (0, 1, 2)
NATIVE_DAMAGE_PERCENT = 10

SUBSKILLS_PATH = "DB/heroes_skills/sub_skills/sub_skills.json"
ARENA_SKILLS_PATH = "DB/heroes_skills/skills/skills_arena.json"
ARENA_SUBSKILLS_PATH = "DB/heroes_skills/sub_skills/sub_skills_arena.json"

SKILL_NAME = "Avenger"
SKILL_DESC = (
    "When an enemy attacks a stack in your army, other friendly stacks answer with avenging strikes: melee attacks "
    "against the attacker. Stacks with the highest Initiative strike first. Avenging strikes do not generate Focus."
)


def _stacks(count: int) -> str:
    return "1 friendly stack" if count == 1 else f"up to {count} friendly stacks"


RANK_DESCS = [
    f"When an enemy attacks your army, {_stacks(STRIKERS_BY_RANK[0])} already next to the attacker makes an avenging strike.",
    f"When an enemy attacks your army, {_stacks(STRIKERS_BY_RANK[1])} within {MOVE_HEXES_BY_RANK[1]} hex of the attacker "
    "move in and make avenging strikes. Unlocks Forest Advantage, Vengeful Focus and Hold the Line.",
    f"When an enemy attacks your army, {_stacks(STRIKERS_BY_RANK[2])} within {MOVE_HEXES_BY_RANK[2]} hexes of the attacker "
    "move in and make avenging strikes. Unlocks Volley of Vengeance, Swift Vengeance and Blood for Blood.",
]
IMPLEMENTED = (
    "Avenger: runtime-owned avenging strikes (Homm3RampartAvengerStrikeRuntime). When an enemy attack step targets a "
    "stack of a Rampart hero's army, up to 1/2/3 other friendly stacks (highest Initiative first) move 0/1/2 hexes and "
    "make a free default attack on the attacker through the native attack builder; the queued steps run after the "
    "attack. Avenging strikes and their retaliations never start another chain. Focus gains during an avenging attack "
    "are refused unless Vengeful Focus is picked."
)
SOURCE_DIFFERENCE = (
    "Replaces the 1-Focus Avenger mark hero action. The ranks carry no native bonuses; the retired hero ability and "
    "mark buff rows stay defined but nothing grants them. Subskills reuse the mark subskill SIDs for save "
    "compatibility."
)

SUBSKILL_TEXT = {
    SUBSKILL_NATIVE_TERRAIN: ("Forest Advantage", f"Rampart creatures on native terrain deal {NATIVE_DAMAGE_PERCENT}% more damage."),
    SUBSKILL_FOCUS: ("Vengeful Focus", "Avenging strikes generate Focus."),
    SUBSKILL_RETURN: ("Hold the Line", "Stacks that move to make an avenging strike return to their starting position afterwards."),
    SUBSKILL_RANGED_FIRST: (
        "Volley of Vengeance",
        "Ranged stacks can make the first avenging strike of each chain, shooting from where they stand.",
    ),
    SUBSKILL_SWIFT_STRIKE: ("Swift Vengeance", "Avenging strikes have Swift Strike: they do not provoke retaliation."),
    SUBSKILL_RETALIATION: (
        "Blood for Blood",
        "Enemy retaliations against your stacks also trigger avenging strikes, except retaliations against avenging strikes.",
    ),
}
SUBSKILL_ORDER = (
    SUBSKILL_NATIVE_TERRAIN,
    SUBSKILL_FOCUS,
    SUBSKILL_RETURN,
    SUBSKILL_RANGED_FIRST,
    SUBSKILL_SWIFT_STRIKE,
    SUBSKILL_RETALIATION,
)
AVENGER_ICON = "sub_skill_faction_homm3_rampart_avenger_mark"
SUBSKILL_ICONS = {
    SUBSKILL_NATIVE_TERRAIN: "sub_skill_faction_nature_1_icon",
    SUBSKILL_FOCUS: "magic_fatal_decay_effect_icon",
    SUBSKILL_RETURN: AVENGER_ICON,
    SUBSKILL_RANGED_FIRST: "magic_shorten_shadow_effect_icon",
    SUBSKILL_SWIFT_STRIKE: AVENGER_ICON,
    SUBSKILL_RETALIATION: AVENGER_ICON,
}


def faction_skill_levels() -> list[list[dict[str, Any]]]:
    """Runtime-owned: the ranks carry no bonuses (empty ranks load fine, as Inferno Gating shows since 2026-11-14).

    The runtime reads the rank from the hero's skill list, not from these bonuses.
    """
    return [[], [], []]


def _arena(sid: str) -> str:
    return "arena_" + sid


def make_subskills(arena: bool = False) -> list[dict[str, Any]]:
    rows = []
    for sid in SUBSKILL_ORDER:
        bonuses: list[dict[str, Any]] = []
        if sid == SUBSKILL_NATIVE_TERRAIN:
            bonuses = [
                {
                    "type": "unitStat",
                    "biomeType": "native",
                    "fraction": FACTION_SID,
                    "parameters": ["outAllDmgMod", str(NATIVE_DAMAGE_PERCENT / 100)],
                }
            ]
        rows.append(
            {
                "id": _arena(sid) if arena else sid,
                # arena rows reuse the main name/desc tokens
                "name": f"{sid}_name",
                "desc": f"{sid}_desc",
                "icon": SUBSKILL_ICONS[sid],
                "bonuses": bonuses,
            }
        )
    return rows


def make_arena_skill_row() -> dict[str, Any]:
    return {
        "id": ARENA_SKILL_SID,
        "name": f"{SKILL_SID}_name",
        "desc": f"{SKILL_SID}_desc",
        "skillType": "Faction",
        "parametersPerLevel": [
            {
                "icon": SKILL_SID if index == 1 else f"{SKILL_SID}_{index}",
                "name": f"{SKILL_SID}_name_{index}",
                "desc": f"{SKILL_SID}_desc_{index}",
                "bonuses": bonuses,
                "subSkills": [_arena(sid) for sid in SUBSKILLS_BY_LEVEL.get(index, ())],
            }
            for index, bonuses in enumerate(faction_skill_levels(), start=1)
        ],
        "xHomm3ImplementedMechanics": IMPLEMENTED,
    }


def subskill_lang_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for sid in SUBSKILL_ORDER:
        name, desc = SUBSKILL_TEXT[sid]
        rows.append({"sid": f"{sid}_name", "text": name})
        rows.append({"sid": f"{sid}_desc", "text": desc})
    return rows


def locale_refresh_sid(sid: str) -> bool:
    """English heroSkills tokens that replace stale translations until the rework is translated."""
    return (
        sid.startswith(f"{SUBSKILL_PREFIX}_")
        or sid.startswith(f"{SKILL_SID}_name")
        or sid.startswith(f"{SKILL_SID}_desc")
    ) and not sid.startswith(f"{SKILL_SID}_ability")


def merge_rampart_avenger_arena_into_overlay(
    *,
    read_doc: Callable[[str], Any],
    write_doc: Callable[[str, Any], None],
    upsert_array_row: Callable[[dict[str, Any], dict[str, Any]], bool],
    dedupe_array_rows_by_id: Callable[[dict[str, Any]], bool],
    notes: list[str],
) -> None:
    """Merge the Avenger arena rows. The main skill and subskill rows come from the release overlay's rampart branch.

    Fail closed: the runtime reads the arena subskill SIDs too, so a missing target document is an error.
    """

    def edit(path: str, label: str, upserts: list[dict[str, Any]]) -> None:
        doc = read_doc(path)
        if not isinstance(doc, dict) or not isinstance(doc.get("array"), list):
            raise RuntimeError(f"malformed homm3_rampart Avenger target {path}")
        changed = False
        for row in upserts:
            changed = upsert_array_row(doc, row) or changed
        changed = dedupe_array_rows_by_id(doc) or changed
        if changed:
            write_doc(path, doc)
            notes.append(f"merge homm3_rampart Avenger {label}")

    edit(ARENA_SUBSKILLS_PATH, "arena subskills", make_subskills(arena=True))
    edit(ARENA_SKILLS_PATH, "arena faction skill", [make_arena_skill_row()])
