"""Core rows for the HoMM3 Stronghold faction skill "Warcry" (replaces the three Warcries hero actions, 2026-11-17).

Warcry is runtime-owned: OfflineUnlockMod/Homm3StrongholdWarcryRuntime.cs runs the attack/ability chain, the
turn-start Attack bonus and every subskill effect except the native-terrain one. The Core rows here are carriers:

- the skill row keeps the proven faction-skill load shape (unitBoolStat ignoreFractionsCount at every rank), so the
  hero gets no Warcries buttons any more;
- the six subskills keep their old SIDs (sub_skill_faction_homm3_stronghold_1..6) and tier slots for save
  compatibility; only Native Drums carries a native bonus;
- the arena skill and arena subskills get the same shape (the generator wrote them; the overlay never did).

The retired generator rows (the three hero abilities, their delta bonuses, side buffs and unit buffs) stay in the
Core untouched: nothing grants them once the skill row stops listing heroBattleAbility bonuses, and the release
overlay's ability-icon rewrite still expects the three ability rows to exist.

Numbers must match Homm3StrongholdWarcryRuntime.cs (KillBonus, RoundInitiative).
"""

from __future__ import annotations

from typing import Any, Callable

FACTION_SID = "homm3_stronghold"
SKILL_SID = "skill_faction_homm3_stronghold"
ARENA_SKILL_SID = "arena_skill_faction_homm3_stronghold"
SUBSKILL_PREFIX = "sub_skill_faction_homm3_stronghold"
ARENA_SUBSKILL_PREFIX = "arena_sub_skill_faction_homm3_stronghold"

SUBSKILL_NATIVE_DRUMS = f"{SUBSKILL_PREFIX}_1"
SUBSKILL_SHAMANS_FURY = f"{SUBSKILL_PREFIX}_2"
SUBSKILL_BATTLE_TEMPO = f"{SUBSKILL_PREFIX}_6"
SUBSKILL_ANSWERING_ROAR = f"{SUBSKILL_PREFIX}_4"
SUBSKILL_BLOOD_RUSH = f"{SUBSKILL_PREFIX}_5"
SUBSKILL_ANCESTRAL_VOICES = f"{SUBSKILL_PREFIX}_3"

# Same tier slots as the retired Warcries subskills (Advanced: 1, 2, 6; Expert: 4, 5, 3).
SUBSKILLS_BY_LEVEL = {
    2: (SUBSKILL_NATIVE_DRUMS, SUBSKILL_SHAMANS_FURY, SUBSKILL_BATTLE_TEMPO),
    3: (SUBSKILL_ANSWERING_ROAR, SUBSKILL_BLOOD_RUSH, SUBSKILL_ANCESTRAL_VOICES),
}

KILL_BONUS = 5
ROUND_INITIATIVE = 2

SKILLS_PATH = "DB/heroes_skills/skills/skills.json"
ARENA_SKILLS_PATH = "DB/heroes_skills/skills/skills_arena.json"
SUBSKILLS_PATH = "DB/heroes_skills/sub_skills/sub_skills.json"
ARENA_SUBSKILLS_PATH = "DB/heroes_skills/sub_skills/sub_skills_arena.json"

SKILL_NAME = "Warcry"
SKILL_DESC = (
    "Each attack or ability used by a friendly stack, one after another, adds 1 to the Warcry counter. Every stack "
    "that attacks in melee joins the Warcry. A Stronghold creature beginning its turn gains Attack for that turn "
    "equal to the counter multiplied by the number of stacks in the Warcry. Moving without attacking, waiting or "
    "defending breaks the Warcry. Ranged attacks raise the counter but do not join the Warcry."
)
RANK_DESCS = [
    "Your army can build a Warcry.",
    "The Warcry Attack bonus is multiplied by 1.5. Unlocks Native Drums, Shaman's Fury and Battle Tempo.",
    "The Warcry Attack bonus is doubled. Unlocks Answering Roar, Blood Rush and Ancestral Voices.",
]
IMPLEMENTED = (
    "Warcry: runtime-owned chain (Homm3StrongholdWarcryRuntime). Attacks and active abilities by friendly stacks keep "
    "the chain and add 1 to the counter; melee attackers become contributors; a Stronghold unit starting its turn gets "
    "counter x contributors x 1/1.5/2 by rank (rounded down) as Attack for the turn; a move, wait or skip breaks it. "
    "The on-screen chain counter is Homm3StrongholdWarcryCounter."
)
SOURCE_DIFFERENCE = (
    "Replaces the three Warcries hero actions (Rallying, Fortune, Tempo Cry). The rank data is the native "
    "unitBoolStat ignoreFractionsCount load shape; the retired hero ability, delta, side-buff and unit-buff rows stay "
    "defined but nothing grants them. Subskills reuse the Warcries subskill SIDs for save compatibility."
)

SUBSKILL_TEXT = {
    SUBSKILL_NATIVE_DRUMS: ("Native Drums", "Stronghold creatures on native terrain deal 10% more damage."),
    SUBSKILL_SHAMANS_FURY: ("Shaman's Fury", "The Warcry Attack bonus is also added to the hero's Spell Power."),
    SUBSKILL_BATTLE_TEMPO: (
        "Battle Tempo",
        f"Stronghold creatures that start a round with the Warcry active gain +{ROUND_INITIATIVE} Initiative for that round.",
    ),
    SUBSKILL_ANSWERING_ROAR: ("Answering Roar", "A friendly stack that retaliates joins the Warcry."),
    SUBSKILL_BLOOD_RUSH: ("Blood Rush", f"Destroying an enemy stack adds {KILL_BONUS} to the Warcry Attack bonus until the Warcry breaks."),
    SUBSKILL_ANCESTRAL_VOICES: (
        "Ancestral Voices",
        "Allied stacks that die keep contributing to the Warcry for the rest of the battle, even after it breaks.",
    ),
}
SUBSKILL_ICONS = {
    SUBSKILL_NATIVE_DRUMS: "sub_skill_faction_dungeon_1_icon",
    SUBSKILL_SHAMANS_FURY: "sub_skill_faction_dungeon_2_icon",
    SUBSKILL_ANCESTRAL_VOICES: "sub_skill_faction_dungeon_3_icon",
    SUBSKILL_ANSWERING_ROAR: "sub_skill_faction_dungeon_4_icon",
    SUBSKILL_BLOOD_RUSH: "sub_skill_faction_dungeon_5_icon",
    SUBSKILL_BATTLE_TEMPO: "sub_skill_faction_dungeon_6_icon",
}


def faction_skill_levels() -> list[list[dict[str, Any]]]:
    """Runtime-owned load shape: every rank carries only the harmless native carrier bonus."""
    return [[{"type": "unitBoolStat", "parameters": ["ignoreFractionsCount", "true"]}] for _ in range(3)]


def _arena(sid: str) -> str:
    return "arena_" + sid


def make_subskills(arena: bool = False) -> list[dict[str, Any]]:
    rows = []
    for sid in sorted(SUBSKILL_TEXT):
        bonuses: list[dict[str, Any]] = []
        if sid == SUBSKILL_NATIVE_DRUMS:
            bonuses = [{"type": "unitStat", "biomeType": "native", "fraction": FACTION_SID, "parameters": ["outAllDmgMod", "0.1"]}]
        rows.append(
            {
                "id": _arena(sid) if arena else sid,
                # arena rows reuse the main name/desc tokens, as the generator always did
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
    for sid in sorted(SUBSKILL_TEXT, key=lambda s: int(s.rsplit("_", 1)[1])):
        name, desc = SUBSKILL_TEXT[sid]
        rows.append({"sid": f"{sid}_name", "text": name})
        rows.append({"sid": f"{sid}_desc", "text": desc})
    return rows


def merge_stronghold_warcry_into_overlay(
    *,
    read_doc: Callable[[str], Any],
    write_doc: Callable[[str, Any], None],
    upsert_array_row: Callable[[dict[str, Any], dict[str, Any]], bool],
    dedupe_array_rows_by_id: Callable[[dict[str, Any]], bool],
    notes: list[str],
) -> None:
    """Merge the Warcry subskills and arena rows. The main skill row comes from make_specialized_generic_skill_row.

    Fail closed: the runtime reads these subskill SIDs, so a missing target document is an error.
    """

    def edit(path: str, label: str, upserts: list[dict[str, Any]]) -> None:
        doc = read_doc(path)
        if not isinstance(doc, dict) or not isinstance(doc.get("array"), list):
            raise RuntimeError(f"malformed homm3_stronghold Warcry target {path}")
        changed = False
        for row in upserts:
            changed = upsert_array_row(doc, row) or changed
        changed = dedupe_array_rows_by_id(doc) or changed
        if changed:
            write_doc(path, doc)
            notes.append(f"merge homm3_stronghold Warcry {label}")

    edit(SUBSKILLS_PATH, "subskills", make_subskills())
    edit(ARENA_SUBSKILLS_PATH, "arena subskills", make_subskills(arena=True))
    edit(ARENA_SKILLS_PATH, "arena faction skill", [make_arena_skill_row()])
